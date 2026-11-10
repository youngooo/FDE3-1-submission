"""Rejudge saved 24-metric results after a documented judge correction.

No model, query, or expected-value recomputation. Original evidence is retained.
"""
import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path
import check_orders24 as judge


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    previous = judge.base.read_json(source / "report.json")
    if previous.get("kind") != "incremental_orders24_csv_check" or not previous.get("complete"):
        raise ValueError("EXPECTED_COMPLETE_ORDERS24_REPORT")
    if Path(previous["project"]).resolve() != args.project.resolve():
        raise ValueError("WRONG_SOURCE_PROJECT: " + previous["project"])
    dataset = judge.base.read_json(args.project / "dataset.json")
    data_hash = hashlib.sha256(json.dumps(
        {k: v for k, v in dataset.items() if k != "library_sha256"}, sort_keys=True).encode()).hexdigest()
    if previous["catalog_sha256"] != dataset["library_sha256"] or previous["data_sha256"] != data_hash:
        raise ValueError("SOURCE_REPORT_VERSION_MISMATCH")
    cases = previous["cases"]
    ids = [c["id"] for c in cases]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("INVALID_CASE_IDS")
    for case_id in ids:
        if Path(case_id).name != case_id or case_id in (".", ".."):
            raise ValueError("INVALID_CASE_PATH")
        for name in ("query.json", "expected.json", "actual.json"):
            if not (source / case_id / name).is_file():
                raise ValueError("MISSING_SAVED_EVIDENCE: " + case_id + "/" + name)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source / "report.json", output / "source_report.json")
    report = {k: copy.deepcopy(v) for k, v in previous.items()
              if k not in ("cases", "passed", "complete", "script_sha256", "comparison_policy")}
    report.update({
        "cases": [], "source_report": str(source / "report.json"),
        "source_report_sha256": sha(source / "report.json"),
        "query_run_script_sha256": previous["script_sha256"],
        "script_sha256": {Path(p).name: sha(Path(p)) for p in
                          (__file__, judge.__file__, judge.base.__file__)},
        "query_reexecuted": False, "model_called": False,
        "revision_reason": "Accept four explicitly equivalent unit spellings; all value, null, intent, group and scale checks retained",
        "comparison_policy": {**previous["comparison_policy"],
                              "unit_spelling_aliases": judge.UNIT_ALIASES},
        "evidence_sha256": {},
    })
    for old_case in cases:
        case_id = old_case["id"]
        folder = output / case_id
        folder.mkdir()
        for name in ("query.json", "expected.json", "actual.json"):
            shutil.copy2(source / case_id / name, folder / name)
        report["evidence_sha256"][case_id] = {
            name: sha(folder / name) for name in ("query.json", "expected.json", "actual.json")}
        intent = judge.base.read_json(folder / "query.json")
        saved_expected = judge.base.read_json(folder / "expected.json")
        expected = {}
        for entry in saved_expected:
            key = tuple(entry["group"])
            if key in expected:
                raise ValueError("DUPLICATE_EXPECTED_GROUP: " + case_id)
            expected[key] = entry["metrics"]
        actual = judge.base.read_json(folder / "actual.json")
        errors = judge.compare(actual, expected, intent)
        for field in ("data_sha256", "catalog_sha256"):
            if actual.get("status") == "ok" and actual.get(field) != previous[field]:
                errors.append({"kind": "result_version_mismatch", "field": field})
        # A prior execution failure cannot be erased by rejudging its output.
        for error in old_case.get("errors", []):
            if error.get("kind") in ("query_process_failed", "execution_error"):
                errors.append(copy.deepcopy(error))
        case = {"id": case_id, "passed": not errors, "expected_groups": len(expected),
                "checked_metrics": len(judge.METRICS), "errors": errors}
        judge.base.save(folder / "comparison.json", case)
        report["cases"].append(case)
        report["passed"] = all(c["passed"] for c in report["cases"])
        report["complete"] = len(report["cases"]) == len(cases)
        judge.base.save(output / "report.json", report)
        print(("PASS " if case["passed"] else "FAIL ") + case_id, flush=True)
    print(json.dumps({"passed": report["passed"],
                      "cases_passed": sum(c["passed"] for c in report["cases"]),
                      "cases_total": len(cases), "metrics": len(judge.METRICS),
                      "query_reexecuted": False, "model_called": False,
                      "report": str(output / "report.json")}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
