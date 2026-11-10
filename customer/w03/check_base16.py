"""Independent CSV oracle for W03's 16 basic metrics; no model calls.

Run from the WSL project root with its .venv Python. This is an incremental
diagnostic, not a replacement for the course's full tests.json and judge.
Definitions: materials/w03/01_订单日报说明.md and 05_数据字典.md.
"""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


METRICS = (
    "order_count", "paid_order_count", "valid_order_count",
    "cancelled_order_count", "refund_order_count", "partial_refund_order_count",
    "full_refund_order_count", "payment_cents", "refund_cents",
    "net_sales_cents", "gross_cents", "discount_cents", "buyer_count",
    "refund_buyer_count", "selling_store_count", "valid_order_items",
)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def calculate(rows):
    """Read only original CSV values; do not inspect generated SQL or measures."""
    paid = [r for r in rows if r["status"] == "paid"]
    valid = [r for r in paid if int(r["paid_cents"]) > int(r["refund_cents"])]
    refunded = [r for r in paid if int(r["refund_cents"]) > 0]
    return {
        "order_count": len(rows),
        "paid_order_count": len(paid),
        "valid_order_count": len(valid),
        "cancelled_order_count": sum(r["status"] == "cancelled" for r in rows),
        "refund_order_count": len(refunded),
        "partial_refund_order_count": sum(
            0 < int(r["refund_cents"]) < int(r["paid_cents"]) for r in paid),
        "full_refund_order_count": sum(
            int(r["paid_cents"]) > 0 and
            int(r["refund_cents"]) == int(r["paid_cents"]) for r in paid),
        "payment_cents": sum(int(r["paid_cents"]) for r in paid),
        "refund_cents": sum(int(r["refund_cents"]) for r in paid),
        "net_sales_cents": sum(int(r["paid_cents"]) - int(r["refund_cents"])
                               for r in paid),
        "gross_cents": sum(int(r["gross_cents"]) for r in paid),
        "discount_cents": sum(int(r["gross_cents"]) - int(r["paid_cents"])
                              for r in paid),
        "buyer_count": len({r["member_id"] for r in valid}),
        "refund_buyer_count": len({r["member_id"] for r in refunded}),
        "selling_store_count": len({r["store_id"] for r in valid}),
        "valid_order_items": sum(int(r["quantity"]) for r in valid),
    }


def dimension(row, name, members, stores):
    member = members[row["member_id"]]
    values = {
        "store": row["store_id"],
        "home_store": member["home_store_id"],
        "order__status": row["status"],
        "order__channel": row["channel"],
        "member__tier": member["tier"],
        "store__region": stores[row["store_id"]]["region"],
        "home_store__region": stores[member["home_store_id"]]["region"],
    }
    return values[name]


def expectations(orders, members, stores, intent):
    groups = defaultdict(list)
    if not intent["group_by"]:
        groups[()] = []
    for row in orders:
        if intent["start"] <= row["ordered_at"] < intent["end"]:
            key = tuple(dimension(row, name, members, stores)
                        for name in intent["group_by"])
            groups[key].append(row)
    return {key: calculate(rows) for key, rows in groups.items()}


def numeric_equal(value, expected):
    if isinstance(value, bool) or value is None:
        return False
    try:
        number = Decimal(str(value))
        return number.is_finite() and number == Decimal(expected)
    except (InvalidOperation, ValueError, TypeError):
        return False


def compare(result, expected, intent):
    errors = []
    if result.get("status") != "ok":
        return [{"kind": "query_not_ok", "result": result}]
    if result.get("intent") != intent:
        errors.append({"kind": "intent_mismatch"})
    columns = result.get("columns", [])
    wanted = list(intent["group_by"]) + list(METRICS)
    if len(columns) != len(set(columns)) or set(columns) != set(wanted):
        return errors + [{"kind": "columns_mismatch", "actual": columns,
                          "expected": wanted}]
    actual = {}
    for raw in result.get("rows", []):
        if len(raw) != len(columns):
            errors.append({"kind": "row_width_mismatch", "row": raw})
            continue
        row = dict(zip(columns, raw))
        key = tuple(str(row[name]) for name in intent["group_by"])
        if key in actual:
            errors.append({"kind": "duplicate_group", "group": key})
        actual[key] = row
    for key in sorted(set(expected) | set(actual)):
        if key not in actual or key not in expected:
            errors.append({"kind": "group_mismatch", "group": key,
                           "expected": key in expected, "actual": key in actual})
            continue
        for metric in METRICS:
            if not numeric_equal(actual[key][metric], expected[key][metric]):
                errors.append({"kind": "value_mismatch", "group": key,
                               "metric_id": metric, "expected": expected[key][metric],
                               "actual": actual[key][metric]})
    for metric in METRICS:
        unit = "cents" if metric.endswith("_cents") else "count"
        if result.get("units", {}).get(metric) != unit:
            errors.append({"kind": "unit_mismatch", "metric_id": metric,
                           "expected": unit, "actual": result.get("units", {}).get(metric)})
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path("materials/data/small"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = read_json(args.data / "manifest.json")
    dataset = read_json(args.project / "dataset.json")
    hashes = {}
    for name, expected_hash in manifest["sha256"].items():
        actual_hash = hashlib.sha256((args.data / name).read_bytes()).hexdigest()
        if actual_hash != expected_hash or dataset["sha256"].get(name) != actual_hash:
            raise ValueError("RAW_DATA_OR_PROJECT_HASH_MISMATCH: " + name)
        hashes[name] = actual_hash
    if dataset["coverage"] != manifest["coverage"] or dataset["id"] != manifest["id"]:
        raise ValueError("DATASET_SCOPE_MISMATCH")
    dataset_hash = hashlib.sha256(json.dumps(
        {k: v for k, v in dataset.items() if k != "library_sha256"},
        sort_keys=True).encode()).hexdigest()
    orders = read_csv(args.data / "orders.csv")
    if len({r["order_id"] for r in orders}) != len(orders):
        raise ValueError("DUPLICATE_ORDER_ID")
    members = {r["member_id"]: r for r in read_csv(args.data / "members.csv")}
    stores = {r["store_id"]: r for r in read_csv(args.data / "stores.csv")}
    for row in orders:
        if row["member_id"] not in members or row["store_id"] not in stores:
            raise ValueError("ORDER_FOREIGN_KEY_MISSING")
        if members[row["member_id"]]["home_store_id"] not in stores:
            raise ValueError("HOME_STORE_MISSING")
    cases = [
        ("aug_total", "2026-08-01", "2026-09-01", []),
        ("jul_total", "2026-07-01", "2026-08-01", []),
        ("coverage_total", *manifest["coverage"], []),
        ("aug_store", "2026-08-01", "2026-09-01", ["store"]),
        ("aug_home_store", "2026-08-01", "2026-09-01", ["home_store"]),
        ("aug_status", "2026-08-01", "2026-09-01", ["order__status"]),
        ("aug_channel", "2026-08-01", "2026-09-01", ["order__channel"]),
        ("aug_tier", "2026-08-01", "2026-09-01", ["member__tier"]),
        ("aug_two_regions", "2026-08-01", "2026-09-01",
         ["store__region", "home_store__region"]),
    ]
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "kind": "incremental_base16_csv_check",
        "expected_basis": "Customer materials 01/05; original CSV; no generated SQL used",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_sha256": hashes, "project": str(args.project.resolve()),
        "data_version": dataset["id"], "data_sha256": dataset_hash,
        "catalog_sha256": dataset["library_sha256"], "cases": [],
    }
    for name, start, end, group_by in cases:
        folder = args.output / name
        folder.mkdir()
        intent = {"metrics": list(METRICS), "start": start, "end": end,
                  "group_by": group_by, "filters": []}
        expected = expectations(orders, members, stores, intent)
        save(folder / "query.json", intent)
        save(folder / "expected.json", [
            {"group": list(key), "metrics": values}
            for key, values in sorted(expected.items())])
        print("RUN " + name, flush=True)
        command = [sys.executable, "tools/w03.py", "query",
                   "--project", str(args.project), "--input", str(folder / "query.json"),
                   "--output", str(folder / "actual.json")]
        try:
            run = subprocess.run(command, capture_output=True, text=True,
                                 encoding="utf-8", timeout=240)
            (folder / "query.log").write_text(run.stdout + run.stderr, encoding="utf-8")
            result = read_json(folder / "actual.json") if (folder / "actual.json").exists() else {}
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
        save(folder / "comparison.json", case)
        report["cases"].append(case)
        report["passed"] = all(c["passed"] for c in report["cases"])
        report["complete"] = len(report["cases"]) == len(cases)
        save(args.output / "report.json", report)
        print(("PASS " if case["passed"] else "FAIL ") + name, flush=True)
    passed = sum(c["passed"] for c in report["cases"])
    print(json.dumps({"passed": report["passed"], "cases_passed": passed,
                      "cases_total": len(cases), "metrics": len(METRICS),
                      "report": str(args.output / "report.json")},
                     ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
