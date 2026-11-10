"""Incremental W03 CSV checks: 16 base metrics and 8 financial ratios.

Run beside check_base16.py using the project .venv Python. No model calls.
This diagnostic does not replace the final natural-language tests and judge.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import check_base16 as base


# Independent definitions from materials/w03/02_财务邮件.md, not generated YAML.
RATIOS = {
    "avg_order_value": ("net_sales_cents", "valid_order_count", "cents_per_order"),
    "avg_buyer_value": ("net_sales_cents", "buyer_count", "cents_per_account"),
    "purchase_frequency": ("valid_order_count", "buyer_count", "orders_per_account"),
    "refund_amount_rate": ("refund_cents", "payment_cents", "ratio"),
    "cancel_rate": ("cancelled_order_count", "order_count", "ratio"),
    "refund_order_rate": ("refund_order_count", "paid_order_count", "ratio"),
    "discount_rate": ("discount_cents", "gross_cents", "ratio"),
    "items_per_order": ("valid_order_items", "valid_order_count", "items_per_order"),
}
METRICS = base.METRICS + tuple(RATIOS)
UNITS = {m: "cents" if m.endswith("_cents") else "count" for m in base.METRICS}
UNITS.update({m: spec[2] for m, spec in RATIOS.items()})
UNIT_ALIASES = {
    "cents/order": "cents_per_order",
    "cents/account": "cents_per_account",
    "orders/account": "orders_per_account",
    "items/order": "items_per_order",
}
ABS_TOL = Decimal("1e-8")
REL_TOL = Decimal("1e-9")


def canonical_unit(value):
    # Only these four spelling aliases are equivalent. Never convert monetary
    # scales, percentages, denominators, or observed numerical values here.
    return UNIT_ALIASES.get(value, value) if isinstance(value, str) else None


def enrich(values):
    result = dict(values)
    for name, (num, den, _) in RATIOS.items():
        # Strings preserve Decimal precision in the saved expected JSON.
        result[name] = None if values[den] == 0 else str(Decimal(values[num]) / Decimal(values[den]))
    return result


def expectations(orders, members, stores, intent):
    def matches(row):
        for condition in intent["filters"]:
            actual = base.dimension(row, condition["field"], members, stores)
            op, wanted = condition["op"], condition["value"]
            if op == "eq":
                if actual != wanted:
                    return False
            elif op == "in":
                if actual not in wanted:
                    return False
            else:
                raise ValueError("Unsupported oracle filter: " + op)
        return True
    selected = [row for row in orders if matches(row)]
    return {key: enrich(values) for key, values in
            base.expectations(selected, members, stores, intent).items()}


def equal(metric, actual, expected):
    if expected is None:
        return actual is None
    if actual is None or isinstance(actual, bool):
        return False
    try:
        a, e = Decimal(str(actual)), Decimal(str(expected))
        if not a.is_finite() or not e.is_finite():
            return False
        if metric in base.METRICS:
            return a == e
        return abs(a - e) <= max(ABS_TOL, abs(e) * REL_TOL)
    except (InvalidOperation, TypeError, ValueError):
        return False


def compare(result, expected, intent):
    if result.get("status") != "ok":
        return [{"kind": "query_not_ok", "result": result}]
    errors = []
    if result.get("intent") != intent:
        errors.append({"kind": "intent_mismatch"})
    columns = result.get("columns", [])
    wanted = list(intent["group_by"]) + list(METRICS)
    if len(columns) != len(set(columns)) or set(columns) != set(wanted):
        return errors + [{"kind": "columns_mismatch", "expected": wanted, "actual": columns}]
    actual = {}
    for values in result.get("rows", []):
        if len(values) != len(columns):
            errors.append({"kind": "row_width_mismatch", "row": values})
            continue
        row = dict(zip(columns, values))
        key = tuple(str(row[field]) for field in intent["group_by"])
        if key in actual:
            errors.append({"kind": "duplicate_group", "group": key})
        actual[key] = row
    for key in sorted(set(expected) | set(actual)):
        if key not in expected or key not in actual:
            errors.append({"kind": "group_mismatch", "group": key,
                           "expected": key in expected, "actual": key in actual})
            continue
        for metric in METRICS:
            if not equal(metric, actual[key][metric], expected[key][metric]):
                errors.append({"kind": "value_mismatch", "group": key,
                               "metric_id": metric, "expected": expected[key][metric],
                               "actual": actual[key][metric]})
    for metric, unit in UNITS.items():
        if canonical_unit(result.get("units", {}).get(metric)) != unit:
            errors.append({"kind": "unit_mismatch", "metric_id": metric,
                           "expected": unit, "actual": result.get("units", {}).get(metric)})
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--data", default=Path("materials/data/small"), type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = base.read_json(args.data / "manifest.json")
    dataset = base.read_json(args.project / "dataset.json")
    hashes = {}
    for name, expected_hash in manifest["sha256"].items():
        hashes[name] = hashlib.sha256((args.data / name).read_bytes()).hexdigest()
        if hashes[name] != expected_hash or hashes[name] != dataset["sha256"].get(name):
            raise ValueError("RAW_DATA_OR_PROJECT_HASH_MISMATCH: " + name)
    if dataset["coverage"] != manifest["coverage"] or dataset["id"] != manifest["id"]:
        raise ValueError("DATASET_SCOPE_MISMATCH")
    dataset_hash = hashlib.sha256(json.dumps(
        {k: v for k, v in dataset.items() if k != "library_sha256"},
        sort_keys=True).encode()).hexdigest()
    orders = base.read_csv(args.data / "orders.csv")
    if len({r["order_id"] for r in orders}) != len(orders):
        raise ValueError("DUPLICATE_ORDER_ID")
    members = {r["member_id"]: r for r in base.read_csv(args.data / "members.csv")}
    stores = {r["store_id"]: r for r in base.read_csv(args.data / "stores.csv")}
    occupied = {r["ordered_at"] for r in orders}
    empty_date = date.fromisoformat(manifest["coverage"][0])
    coverage_end = date.fromisoformat(manifest["coverage"][1])
    while empty_date < coverage_end and empty_date.isoformat() in occupied:
        empty_date += timedelta(days=1)
    if empty_date >= coverage_end:
        raise ValueError("NO_EMPTY_DAY_IN_DATASET: choose another zero-denominator fixture")
    cases = [
        ("aug_total", "2026-08-01", "2026-09-01", [], []),
        ("jul_total", "2026-07-01", "2026-08-01", [], []),
        ("coverage_total", *manifest["coverage"], [], []),
        ("aug_store", "2026-08-01", "2026-09-01", ["store"], []),
        ("aug_home_store", "2026-08-01", "2026-09-01", ["home_store"], []),
        ("aug_status", "2026-08-01", "2026-09-01", ["order__status"], []),
        ("aug_channel", "2026-08-01", "2026-09-01", ["order__channel"], []),
        ("aug_tier", "2026-08-01", "2026-09-01", ["member__tier"], []),
        ("aug_two_regions", "2026-08-01", "2026-09-01",
         ["store__region", "home_store__region"], []),
        ("aug_cancelled_only", "2026-08-01", "2026-09-01", [],
         [{"field": "order__status", "op": "eq", "value": "cancelled"}]),
        ("covered_empty_day", empty_date.isoformat(),
         (empty_date + timedelta(days=1)).isoformat(), [], []),
    ]
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "kind": "incremental_orders24_csv_check",
        "expected_basis": "Customer materials 01/02/05; original CSV; no generated SQL used",
        "script_sha256": {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                          for p in (__file__, base.__file__)},
        "source_sha256": hashes, "project": str(args.project.resolve()),
        "data_version": dataset["id"], "data_sha256": dataset_hash,
        "catalog_sha256": dataset["library_sha256"],
        "comparison_policy": {"integers": "exact", "null": "strict",
                              "unit_spelling_aliases": UNIT_ALIASES,
                              "ratio_abs_tolerance": str(ABS_TOL),
                              "ratio_rel_tolerance": str(REL_TOL)},
        "cases": [],
    }
    for name, start, end, group_by, filters in cases:
        folder = args.output / name
        folder.mkdir()
        intent = {"metrics": list(METRICS), "start": start, "end": end,
                  "group_by": group_by, "filters": filters}
        expected = expectations(orders, members, stores, intent)
        base.save(folder / "query.json", intent)
        base.save(folder / "expected.json", [
            {"group": list(k), "metrics": v} for k, v in sorted(expected.items())])
        print("RUN " + name, flush=True)
        command = [sys.executable, "tools/w03.py", "query",
                   "--project", str(args.project), "--input", str(folder / "query.json"),
                   "--output", str(folder / "actual.json")]
        try:
            run = subprocess.run(command, capture_output=True, text=True,
                                 encoding="utf-8", timeout=240)
            (folder / "query.log").write_text(run.stdout + run.stderr, encoding="utf-8")
            result = base.read_json(folder / "actual.json") if (folder / "actual.json").exists() else {}
            errors = compare(result, expected, intent)
            if run.returncode:
                errors.append({"kind": "query_process_failed", "returncode": run.returncode})
            if result.get("status") == "ok":
                for field, value in (("data_sha256", dataset_hash),
                                     ("catalog_sha256", dataset["library_sha256"])):
                    if result.get(field) != value:
                        errors.append({"kind": "result_version_mismatch", "field": field})
        except (subprocess.TimeoutExpired, OSError, ValueError) as error:
            errors = [{"kind": "execution_error", "reason": str(error)}]
        case = {"id": name, "passed": not errors, "expected_groups": len(expected),
                "checked_metrics": len(METRICS), "errors": errors}
        base.save(folder / "comparison.json", case)
        report["cases"].append(case)
        report["passed"] = all(c["passed"] for c in report["cases"])
        report["complete"] = len(report["cases"]) == len(cases)
        base.save(args.output / "report.json", report)
        print(("PASS " if case["passed"] else "FAIL ") + name, flush=True)
    print(json.dumps({"passed": report["passed"],
                      "cases_passed": sum(c["passed"] for c in report["cases"]),
                      "cases_total": len(cases), "metrics": len(METRICS),
                      "report": str(args.output / "report.json")},
                     ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
