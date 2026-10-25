from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable


def natural_case_key(case_id: str) -> tuple[str, int]:
    match = re.search(r"(\d+)$", case_id)
    return case_id[: match.start()] if match else case_id, int(match.group(1)) if match else -1


def write_output(rows: Iterable[dict[str, object]], path: str | Path) -> None:
    ordered = sorted(rows, key=lambda row: natural_case_key(str(row["case_id"])))
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "deletion_status", "steps_json"])
        writer.writeheader()
        for row in ordered:
            writer.writerow({
                "case_id": row["case_id"],
                "deletion_status": row["deletion_status"],
                "steps_json": json.dumps(row["steps_json"], separators=(",", ":"), ensure_ascii=False),
            })


def validate_output(path: str | Path, expected_case_ids: list[str] | None = None) -> tuple[int, list[str]]:
    errors: list[str] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if expected_case_ids is not None:
        expected = sorted(expected_case_ids, key=natural_case_key)
        actual = [row.get("case_id", "") for row in rows]
        if actual != expected:
            errors.append("case ids are missing, duplicated, or unsorted")
    allowed = {
        ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"), ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
        ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"), ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),
        ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"), ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
        ("REMEDIATION", "DELETE_RECORD", "ABSENT"), ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
        ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),
        ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"), ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
        ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"), ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
        ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"), ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
    }
    for row in rows:
        status = row.get("deletion_status")
        try:
            steps = json.loads(row.get("steps_json", ""))
        except json.JSONDecodeError:
            errors.append(f"{row.get('case_id')}: invalid JSON")
            continue
        if not isinstance(steps, list):
            errors.append(f"{row.get('case_id')}: steps is not an array")
            continue
        if status == "NOT_APPLICABLE" and steps != []:
            errors.append(f"{row.get('case_id')}: NOT_APPLICABLE must have []")
        if [step.get("step_no") for step in steps] != list(range(1, len(steps) + 1)):
            errors.append(f"{row.get('case_id')}: step numbers are not consecutive")
        for step in steps:
            if (step.get("phase"), step.get("operation"), step.get("state")) not in allowed:
                errors.append(f"{row.get('case_id')}: invalid operation/state")
            if status == "COMPLETE" and step.get("phase") != "VERIFICATION":
                errors.append(f"{row.get('case_id')}: COMPLETE has non-verification step")
            if step.get("phase") == "FINDING" and not step.get("evidence_id"):
                errors.append(f"{row.get('case_id')}: finding lacks evidence")
            if status == "INCOMPLETE" and step.get("phase") != "FINDING" and step.get("evidence_id"):
                errors.append(f"{row.get('case_id')}: incomplete future step has evidence")
    return len(rows), errors
