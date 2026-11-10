"""Deterministically repair unambiguous measure-as-metric ratio references.

Preserve the original live model response and provenance. Publish through the
course framework's native checks into a new directory. No model calls.
"""
import argparse
import copy
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(response):
    result = copy.deepcopy(response)
    metrics = result["metrics"]
    names = [m["name"] for m in metrics]
    if len(set(names)) != len(names):
        raise ValueError("DUPLICATE_METRIC_NAMES")
    measures = {m["name"] for sm in result["semantic_models"] for m in sm.get("measures", [])}
    providers = defaultdict(list)
    for metric in metrics:
        if metric.get("type") == "simple":
            reference = metric["type_params"].get("measure")
            measure = reference.get("name") if isinstance(reference, dict) else reference
            # Filters and measure parameters can change the meaning. Only plain
            # one-to-one wrappers are eligible for automatic name correction.
            plain = isinstance(reference, str) or (isinstance(reference, dict) and set(reference) == {"name"})
            if plain and not metric.get("filter") and measure in measures:
                providers[measure].append(metric["name"])
    changes = []
    for metric in metrics:
        if metric.get("type") != "ratio":
            continue
        for side in ("numerator", "denominator"):
            reference = metric["type_params"][side]
            if not isinstance(reference, str):
                raise ValueError("STRUCTURED_RATIO_REF_REQUIRES_REVIEW: " + metric["name"])
            if reference in names:
                continue
            matches = providers.get(reference, [])
            if len(matches) != 1:
                raise ValueError("RATIO_REF_UNRESOLVED_OR_AMBIGUOUS: " + metric["name"] + "." + side + "=" + reference)
            metric["type_params"][side] = matches[0]
            changes.append({"metric_id": metric["name"], "field": side,
                            "before": reference, "after": matches[0],
                            "basis": "unique unfiltered simple metric referencing this existing measure"})
    return result, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--data", type=Path, default=Path("materials/data/small"))
    args = parser.parse_args()
    source, output, data = args.source.resolve(), args.output.resolve(), args.data.resolve()
    if output.exists():
        raise ValueError("OUTPUT_ALREADY_EXISTS")
    source_check = read(source / "source_check.json")
    if source_check.get("passed") is not True:
        raise ValueError("SOURCE_CHECK_NOT_PASSED")
    original = read(source / "response.json")
    corrected, changes = normalize(original)
    provenance = read(source / "provenance.json")
    scope = read(source / "candidate/scope.json")
    dimension_targets = read(source / "candidate/dimension_targets.json")
    manifest = read(data / "manifest.json")
    old_dataset = source / "validation-project/dataset.json"
    if old_dataset.exists():
        previous = read(old_dataset)
        if any(previous.get(k) != manifest.get(k) for k in ("id", "coverage", "sha256")):
            raise ValueError("SOURCE_DATA_VERSION_CHANGED")
    platform = Path.cwd() / "platform"
    if not (platform / "fde_product/metrics/builder.py").is_file():
        raise ValueError("RUN_FROM_W03_PROJECT_ROOT")
    sys.path.insert(0, str(platform))
    from fde_product.metrics.builder import publish_candidate
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source / "response.json", output / "source_response.json")
    shutil.copy2(source / "provenance.json", output / "source_provenance.json")
    for name in ("input.json", "skill_used.md", "source_check.json"):
        shutil.copy2(source / name, output / name)
    write(output / "response.json", corrected)
    record = {
        "kind": "deterministic_ratio_reference_normalization",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_build": str(source),
        "source_response_sha256": sha(source / "response.json"),
        "normalized_response_sha256": sha(output / "response.json"),
        "script_sha256": sha(Path(__file__)),
        "changes": changes,
        "status": "pending_native_validation",
        "note": "Original model output retained. Only ratio reference names corrected; no business formula or observed result rewritten.",
    }
    write(output / "normalization.json", record)
    # Retain the Skill hash that actually generated this response. The updated
    # Skill is for future model calls; do not relabel historical provenance.
    new_provenance = copy.deepcopy(provenance)
    new_provenance["transformation"] = {
        "kind": record["kind"], "source_build": str(source),
        "source_response_sha256": record["source_response_sha256"],
        "script_sha256": record["script_sha256"], "record": "normalization.json",
    }
    write(output / "provenance.json", new_provenance)
    try:
        publish_candidate(corrected, scope, dimension_targets, data, output)
    except Exception as error:
        record["status"] = "native_validation_failed"
        record["error"] = str(error)
        write(output / "normalization.json", record)
        print(json.dumps({"status": "error", "output": str(output), "reason": str(error)}, ensure_ascii=False), flush=True)
        return 1
    record["status"] = "native_validation_passed"
    write(output / "normalization.json", record)
    print(json.dumps({"output": str(output), "defined": len(corrected["metrics"]),
                      "references_corrected": len(changes),
                      "ratio_metrics_corrected": len({x["metric_id"] for x in changes}),
                      "checks_passed": True, "model_called": False},
                     ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
