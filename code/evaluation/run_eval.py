from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


STEP_FIELDS = ["phase", "system_id", "resource_id", "operation", "state"]
FULL_FIELDS = STEP_FIELDS + ["evidence_id"]


def _case_key(case_id: str) -> tuple[str, int]:
    prefix = case_id.rstrip("0123456789")
    suffix = case_id[len(prefix):]
    return prefix, int(suffix or -1)


def load(path: str | Path) -> dict[str, dict[str, Any]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows: dict[str, dict[str, Any]] = {}
        for row in csv.DictReader(handle):
            row["steps"] = json.loads(row.get("steps_json", "[]"))
            rows[row["case_id"]] = row
        return rows


def tuples(steps: list[dict[str, Any]], fields: Iterable[str] = FULL_FIELDS) -> list[tuple[Any, ...]]:
    return [tuple(step.get(field) for field in fields) for step in steps]


def f1(tp: int, fp: int, fn: int) -> float:
    return 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 1.0


def _metrics(pred: dict[str, dict[str, Any]], labels: dict[str, dict[str, Any]]) -> dict[str, Any]:
    statuses = sum(pred.get(key, {}).get("deletion_status") == label["deletion_status"] for key, label in labels.items())
    exact = 0
    tp = fp = fn = 0
    loose_tp = loose_fp = loose_fn = 0
    for key, label in labels.items():
        p_steps = pred.get(key, {}).get("steps", [])
        label_steps = label.get("steps", [])
        if p_steps == label_steps:
            exact += 1
        p_set = Counter(tuples(p_steps))
        l_set = Counter(tuples(label_steps))
        tp += sum((p_set & l_set).values())
        fp += sum((p_set - l_set).values())
        fn += sum((l_set - p_set).values())
        p_set = Counter(tuples(p_steps, STEP_FIELDS))
        l_set = Counter(tuples(label_steps, STEP_FIELDS))
        loose_tp += sum((p_set & l_set).values())
        loose_fp += sum((p_set - l_set).values())
        loose_fn += sum((l_set - p_set).values())
    count = len(labels)
    return {
        "cases": count,
        "status_accuracy": statuses / count if count else 1.0,
        "step_f1_with_evidence": f1(tp, fp, fn),
        "step_f1_without_evidence": f1(loose_tp, loose_fp, loose_fn),
        "exact_array_match": exact / count if count else 1.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "loose_tp": loose_tp,
        "loose_fp": loose_fp,
        "loose_fn": loose_fn,
    }


def split_cases(labels: dict[str, dict[str, Any]], dev_count: int) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    ordered = sorted(labels, key=_case_key)
    dev_ids = set(ordered[:dev_count])
    return ({key: value for key, value in labels.items() if key in dev_ids},
            {key: value for key, value in labels.items() if key not in dev_ids})


def _remove_common(counter: Counter[tuple[Any, ...]], other: Counter[tuple[Any, ...]]) -> Counter[tuple[Any, ...]]:
    return counter - other


def mismatch_buckets(pred: dict[str, dict[str, Any]], labels: dict[str, dict[str, Any]]) -> dict[str, Any]:
    buckets: Counter[str] = Counter()
    cases: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    details: dict[str, dict[str, Any]] = {}
    for key, label in labels.items():
        p_steps = pred.get(key, {}).get("steps", [])
        l_steps = label.get("steps", [])
        p_full = tuples(p_steps)
        l_full = tuples(l_steps)
        p_loose = tuples(p_steps, STEP_FIELDS)
        l_loose = tuples(l_steps, STEP_FIELDS)
        if p_full == l_full:
            continue
        p_loose_counter = Counter(p_loose)
        l_loose_counter = Counter(l_loose)
        missing = _remove_common(l_loose_counter, p_loose_counter)
        extra = _remove_common(p_loose_counter, l_loose_counter)
        case_detail: dict[str, Any] = {}
        if missing:
            buckets["missing_step"] += sum(missing.values())
            cases["missing_step"].add(key)
            if len(examples["missing_step"]) < 5:
                examples["missing_step"].append({"case_id": key, "steps": [list(item) for item in missing.elements()]})
            case_detail["missing_step"] = [list(item) for item in missing.elements()]
        if extra:
            buckets["extra_step"] += sum(extra.values())
            cases["extra_step"].add(key)
            if len(examples["extra_step"]) < 5:
                examples["extra_step"].append({"case_id": key, "steps": [list(item) for item in extra.elements()]})
            case_detail["extra_step"] = [list(item) for item in extra.elements()]
        # Pair equal semantic steps with different evidence identifiers.
        p_by_loose: dict[tuple[Any, ...], list[tuple[Any, ...]]] = defaultdict(list)
        l_by_loose: dict[tuple[Any, ...], list[tuple[Any, ...]]] = defaultdict(list)
        for item in tuples(p_steps):
            p_by_loose[item[:-1]].append(item)
        for item in tuples(l_steps):
            l_by_loose[item[:-1]].append(item)
        evidence_diffs: list[dict[str, Any]] = []
        for semantic, expected_items in l_by_loose.items():
            predicted_items = p_by_loose.get(semantic, [])
            for expected, actual in zip(expected_items, predicted_items):
                if expected[-1] != actual[-1]:
                    evidence_diffs.append({"expected": expected[-1], "predicted": actual[-1], "step": list(semantic)})
        if evidence_diffs:
            buckets["wrong_evidence_id"] += len(evidence_diffs)
            cases["wrong_evidence_id"].add(key)
            if len(examples["wrong_evidence_id"]) < 5:
                examples["wrong_evidence_id"].append({"case_id": key, "differences": evidence_diffs})
            case_detail["wrong_evidence_id"] = evidence_diffs
        if not missing and not extra and p_full != l_full:
            buckets["wrong_order"] += 1
            cases["wrong_order"].add(key)
            if len(examples["wrong_order"]) < 5:
                examples["wrong_order"].append({"case_id": key, "predicted": p_full, "expected": l_full})
            case_detail["wrong_order"] = {"predicted": p_full, "expected": l_full}
        if case_detail:
            details[key] = case_detail
    return {
        "counts": dict(buckets),
        "cases": {bucket: sorted(ids, key=_case_key) for bucket, ids in cases.items()},
        "examples": dict(examples),
        "details": details,
    }


def score(pred_path: str, label_path: str, dev_count: int = 22, report_path: str | None = None) -> dict[str, Any]:
    pred = load(pred_path)
    labels = load(label_path)
    metrics = _metrics(pred, labels)
    dev, holdout = split_cases(labels, dev_count)
    result = {
        "all": metrics,
        "dev": _metrics(pred, dev),
        "holdout": _metrics(pred, holdout),
        "split": {"dev_cases": len(dev), "holdout_cases": len(holdout)},
        "mismatches": mismatch_buckets(pred, labels),
    }
    print(f"cases={metrics['cases']} status_accuracy={metrics['status_accuracy']:.3f}")
    print(f"step_f1_with_evidence={metrics['step_f1_with_evidence']:.3f} step_f1_without_evidence={metrics['step_f1_without_evidence']:.3f}")
    print(f"exact_array_match={metrics['exact_array_match']:.3f} tp={metrics['tp']} fp={metrics['fp']} fn={metrics['fn']}")
    print(f"dev_cases={len(dev)} dev_step_f1={result['dev']['step_f1_without_evidence']:.3f} holdout_cases={len(holdout)} holdout_step_f1={result['holdout']['step_f1_without_evidence']:.3f}")
    print("mismatch_buckets=" + json.dumps(result["mismatches"]["counts"], sort_keys=True))
    if report_path:
        Path(report_path).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--dev-count", type=int, default=22)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    score(args.pred, args.labels, args.dev_count, args.report)


if __name__ == "__main__":
    main()
