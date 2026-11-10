"""Small-data checks for W03 registration, first purchases and monthly repeat.

Expectations come from original CSV and customer material 03/05. This script
does not read generated model SQL. Run next to check_base16/check_orders24.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import check_base16 as base
import check_orders24 as financial


FIRST = ["first_buyer_count", "first_order_sales_cents", "first_order_count", "repeat_order_count"]
MONTHLY = ["monthly_buyer_count", "monthly_repeat_buyer_count", "monthly_repeat_rate"]
UNITS = {m: "count" for m in FIRST + MONTHLY + ["new_member_count"]}
UNITS.update(first_order_sales_cents="cents", monthly_repeat_rate="ratio")


def next_month(day):
    return date(day.year + (day.month == 12), 1 if day.month == 12 else day.month + 1, 1)


class Oracle:
    def __init__(self, data):
        self.orders = base.read_csv(data / "orders.csv")
        members = base.read_csv(data / "members.csv")
        stores = base.read_csv(data / "stores.csv")
        self.members = {m["member_id"]: m for m in members}
        self.stores = {s["store_id"]: s for s in stores}
        if len({o["order_id"] for o in self.orders}) != len(self.orders) or len(self.members) != len(members):
            raise ValueError("DUPLICATE_RAW_KEY")
        self.valid = [o for o in self.orders if o["status"] == "paid"
                      and int(o["paid_cents"]) > int(o["refund_cents"])]
        self.valid_ids = {o["order_id"] for o in self.valid}
        first_by_member = {}
        for order in sorted(self.valid, key=lambda o: (o["ordered_at"], o["order_id"])):
            first_by_member.setdefault(order["member_id"], order["order_id"])
        self.first_ids = set(first_by_member.values())

    def first(self, intent):
        groups = defaultdict(list)
        if not intent["group_by"]:
            groups[()] = []
        for row in self.orders:
            if not intent["start"] <= row["ordered_at"] < intent["end"]:
                continue
            matched = True
            for f in intent["filters"]:
                if f["op"] != "eq":
                    raise ValueError("UNSUPPORTED_ORACLE_FILTER")
                if base.dimension(row, f["field"], self.members, self.stores) != f["value"]:
                    matched = False
            if matched:
                key = tuple(base.dimension(row, d, self.members, self.stores) for d in intent["group_by"])
                groups[key].append(row)
        result = {}
        for key, rows in groups.items():
            first = [o for o in rows if o["order_id"] in self.first_ids]
            result[key] = {
                "first_buyer_count": len({o["member_id"] for o in first}),
                "first_order_sales_cents": sum(int(o["paid_cents"]) - int(o["refund_cents"]) for o in first),
                "first_order_count": len(first),
                "repeat_order_count": sum(o["order_id"] in self.valid_ids and o["order_id"] not in self.first_ids for o in rows),
            }
        return result

    def registration(self, intent):
        counts = Counter()
        if not intent["group_by"]:
            counts[()] = 0
        for member in self.members.values():
            if intent["start"] <= member["registered_at"] < intent["end"]:
                values = {"home_store": member["home_store_id"], "member__tier": member["tier"]}
                counts[tuple(values[d] for d in intent["group_by"])] += 1
        return {key: {"new_member_count": count} for key, count in counts.items()}

    def monthly(self, intent):
        if intent["filters"] or set(intent["group_by"]) - {"metric_time__month"}:
            raise ValueError("INVALID_MONTHLY_ORACLE_REQUEST")
        months = {}
        start, end = date.fromisoformat(intent["start"]), date.fromisoformat(intent["end"])
        if start.day != 1 or end.day != 1:
            raise ValueError("MONTHLY_REQUEST_NOT_WHOLE_MONTHS")
        current = start
        while current < end:
            months[current.isoformat()] = Counter()
            current = next_month(current)
        if not intent["group_by"] and len(months) != 1:
            raise ValueError("MULTI_MONTH_REQUEST_REQUIRES_GROUPING")
        for row in self.valid:
            if intent["start"] <= row["ordered_at"] < intent["end"]:
                months[row["ordered_at"][:7] + "-01"][row["member_id"]] += 1
        result = {}
        for month, members in months.items():
            buyers = len(members)
            repeat = sum(n >= 2 for n in members.values())
            result[(month,) if intent["group_by"] else ()] = {
                "monthly_buyer_count": buyers,
                "monthly_repeat_buyer_count": repeat,
                "monthly_repeat_rate": None if buyers == 0 else str(Decimal(repeat) / Decimal(buyers)),
            }
        return result


def group_key(row, dimensions):
    values = []
    for dimension in dimensions:
        value = row[dimension]
        if dimension == "metric_time__month":
            parsed = datetime.fromisoformat(str(value))
            if parsed.day != 1 or any((parsed.hour, parsed.minute, parsed.second, parsed.microsecond)):
                raise ValueError("INVALID_MONTH_GROUP: " + str(value))
            value = parsed.date().isoformat()
        values.append(str(value))
    return tuple(values)


def compare(actual, expected, intent, expected_status="ok"):
    if actual.get("status") != expected_status:
        return [{"kind": "status_mismatch", "expected": expected_status, "actual": actual}]
    if expected_status != "ok":
        return []
    errors = []
    if actual.get("intent") != intent:
        errors.append({"kind": "intent_mismatch"})
    columns = actual.get("columns", [])
    wanted = intent["group_by"] + intent["metrics"]
    if len(columns) != len(set(columns)) or set(columns) != set(wanted):
        return errors + [{"kind": "columns_mismatch", "expected": wanted, "actual": columns}]
    got = {}
    for values in actual.get("rows", []):
        if len(values) != len(columns):
            errors.append({"kind": "row_width_mismatch"})
            continue
        row = dict(zip(columns, values))
        try:
            key = group_key(row, intent["group_by"])
        except (ValueError, TypeError) as error:
            errors.append({"kind": "invalid_group", "reason": str(error)})
            continue
        if key in got:
            errors.append({"kind": "duplicate_group", "group": key})
        got[key] = row
    for key in sorted(set(expected) | set(got)):
        if key not in expected or key not in got:
            errors.append({"kind": "group_mismatch", "group": key,
                           "expected": key in expected, "actual": key in got})
            continue
        for metric in intent["metrics"]:
            a, e = got[key][metric], expected[key][metric]
            matches = financial.equal(metric, a, e) if metric == "monthly_repeat_rate" else base.numeric_equal(a, e)
            if not matches:
                errors.append({"kind": "value_mismatch", "group": key, "metric_id": metric,
                               "expected": e, "actual": a})
    for metric in intent["metrics"]:
        if actual.get("units", {}).get(metric) != UNITS[metric]:
            errors.append({"kind": "unit_mismatch", "metric_id": metric,
                           "expected": UNITS[metric], "actual": actual.get("units", {}).get(metric)})
    return errors


def make_cases(oracle, coverage):
    cases = []
    def add(name, family, metrics, start, end, groups=None, filters=None, status="ok"):
        cases.append({"id": name, "family": family, "expected_status": status,
                      "intent": {"metrics": metrics, "start": start, "end": end,
                                 "group_by": groups or [], "filters": filters or []}})
    for name, start, end in (("aug", "2026-08-01", "2026-09-01"),
                              ("jul", "2026-07-01", "2026-08-01"),
                              ("coverage", *coverage),
                              ("aug_first_half", "2026-08-01", "2026-08-16")):
        add("first_" + name, "first", FIRST, start, end)
    add("first_aug_store", "first", FIRST, "2026-08-01", "2026-09-01", ["store"])
    add("first_aug_home_store", "first", FIRST, "2026-08-01", "2026-09-01", ["home_store"])
    add("first_aug_filtered_store", "first", FIRST, "2026-08-01", "2026-09-01",
        filters=[{"field": "store", "op": "eq", "value": "S01"}])
    add("registration_aug", "registration", ["new_member_count"], "2026-08-01", "2026-09-01")
    add("registration_coverage", "registration", ["new_member_count"], *coverage)
    add("registration_home_store", "registration", ["new_member_count"], *coverage, ["home_store"])
    add("registration_tier", "registration", ["new_member_count"], *coverage, ["member__tier"])
    add("monthly_aug", "monthly", MONTHLY, "2026-08-01", "2026-09-01")
    add("monthly_jul", "monthly", MONTHLY, "2026-07-01", "2026-08-01")
    add("monthly_jul_aug", "monthly", MONTHLY, "2026-07-01", "2026-09-01", ["metric_time__month"])
    occupied = {o["ordered_at"][:7] for o in oracle.valid}
    month, end = date.fromisoformat(coverage[0]), date.fromisoformat(coverage[1])
    while month < end and month.strftime("%Y-%m") in occupied:
        month = next_month(month)
    if month >= end:
        raise ValueError("NO_EMPTY_MONTH_IN_SMALL_DATASET")
    add("monthly_empty", "monthly", MONTHLY, month.isoformat(), next_month(month).isoformat())
    add("reject_partial_month", "monthly", MONTHLY, "2026-08-02", "2026-09-01", status="unsupported")
    add("reject_monthly_day_group", "monthly", MONTHLY, "2026-08-01", "2026-09-01", ["metric_time__day"], status="unsupported")
    add("reject_monthly_store_group", "monthly", MONTHLY, "2026-08-01", "2026-09-01", ["store"], status="unsupported")
    add("reject_monthly_store_filter", "monthly", MONTHLY, "2026-08-01", "2026-09-01",
        filters=[{"field": "store", "op": "eq", "value": "S01"}], status="unsupported")
    add("reject_multimonth_total", "monthly", MONTHLY, "2026-07-01", "2026-09-01", status="unsupported")
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--data", default=Path("materials/data/small"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = base.read_json(args.data / "manifest.json")
    dataset = base.read_json(args.project / "dataset.json")
    for name, expected_hash in manifest["sha256"].items():
        actual_hash = hashlib.sha256((args.data / name).read_bytes()).hexdigest()
        if actual_hash != expected_hash or dataset["sha256"].get(name) != actual_hash:
            raise ValueError("RAW_DATA_OR_PROJECT_HASH_MISMATCH: " + name)
    if any(dataset[k] != manifest[k] for k in ("id", "coverage")):
        raise ValueError("DATASET_SCOPE_MISMATCH")
    dataset_hash = hashlib.sha256(json.dumps(
        {k: v for k, v in dataset.items() if k != "library_sha256"}, sort_keys=True).encode()).hexdigest()
    oracle = Oracle(args.data)
    cases = make_cases(oracle, manifest["coverage"])
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "kind": "incremental_member8_csv_check",
        "expected_basis": "Customer materials 03/05; original CSV; first valid orders determined before filtering",
        "project": str(args.project.resolve()), "data_version": dataset["id"],
        "data_sha256": dataset_hash, "catalog_sha256": dataset["library_sha256"],
        "source_sha256": manifest["sha256"],
        "script_sha256": {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                          for p in (__file__, base.__file__, financial.__file__)},
        "comparison_policy": {"counts_and_cents": "exact", "null": "strict",
                              "month_keys": "first-of-month ISO date or midnight timestamp",
                              "ratio_abs_tolerance": str(financial.ABS_TOL),
                              "ratio_rel_tolerance": str(financial.REL_TOL)}, "cases": [],
    }
    for case in cases:
        folder = args.output / case["id"]
        folder.mkdir()
        intent = case["intent"]
        expected = getattr(oracle, case["family"])(intent) if case["expected_status"] == "ok" else {}
        base.save(folder / "query.json", intent)
        base.save(folder / "expected.json", {"status": case["expected_status"],
                  "groups": [{"group": list(k), "metrics": v} for k, v in sorted(expected.items())]})
        print("RUN " + case["id"], flush=True)
        command = [sys.executable, "tools/w03.py", "query", "--project", str(args.project),
                   "--input", str(folder / "query.json"), "--output", str(folder / "actual.json")]
        try:
            run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=240)
            (folder / "query.log").write_text(run.stdout + run.stderr, encoding="utf-8")
            result = base.read_json(folder / "actual.json") if (folder / "actual.json").exists() else {}
            errors = compare(result, expected, intent, case["expected_status"])
            if run.returncode:
                errors.append({"kind": "query_process_failed", "returncode": run.returncode})
            if result.get("status") == "ok":
                for key, value in (("data_sha256", dataset_hash), ("catalog_sha256", dataset["library_sha256"])):
                    if result.get(key) != value:
                        errors.append({"kind": "result_version_mismatch", "field": key})
        except (subprocess.TimeoutExpired, ValueError, OSError) as error:
            errors = [{"kind": "execution_error", "reason": str(error)}]
        item = {"id": case["id"], "expected_status": case["expected_status"],
                "passed": not errors, "checked_metrics": intent["metrics"], "errors": errors}
        base.save(folder / "comparison.json", item)
        report["cases"].append(item)
        report["passed"] = all(c["passed"] for c in report["cases"])
        report["complete"] = len(report["cases"]) == len(cases)
        base.save(args.output / "report.json", report)
        print(("PASS " if item["passed"] else "FAIL ") + case["id"], flush=True)
    print(json.dumps({"passed": report["passed"],
                      "cases_passed": sum(c["passed"] for c in report["cases"]),
                      "cases_total": len(cases), "metrics": len(UNITS),
                      "report": str(args.output / "report.json")}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
