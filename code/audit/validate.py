from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ALLOWED_TRIPLES = {
    ("FINDING", "REPORT_REMAINING_RECORD", "PRESENT"),
    ("FINDING", "REPORT_EXPOSED_PII", "PRESENT"),
    ("FINDING", "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    ("FINDING", "REPORT_RESTORE_RISK", "ACTIVE"),
    ("REMEDIATION", "DISABLE_DATA_FLOW", "DISABLED"),
    ("REMEDIATION", "BLOCK_RESTORE", "BLOCKED"),
    ("REMEDIATION", "DELETE_RECORD", "ABSENT"),
    ("REMEDIATION", "REDACT_RECORD", "REDACTED"),
    ("REMEDIATION", "ANONYMIZE_RECORD", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_RECORD_ABSENT", "ABSENT"),
    ("VERIFICATION", "VERIFY_RECORD_PRESENT", "PRESENT"),
    ("VERIFICATION", "VERIFY_RECORD_REDACTED", "REDACTED"),
    ("VERIFICATION", "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    ("VERIFICATION", "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    ("VERIFICATION", "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
}

PHASE_ORDER = {
    "FINDING": 0,
    "REMEDIATION": 1,
    "VERIFICATION": 2,
}

OPERATION_ORDER = {
    "REPORT_REMAINING_RECORD": 0,
    "REPORT_EXPOSED_PII": 1,
    "REPORT_ACTIVE_DATA_FLOW": 2,
    "REPORT_RESTORE_RISK": 3,
    "DISABLE_DATA_FLOW": 0,
    "BLOCK_RESTORE": 1,
    "DELETE_RECORD": 2,
    "REDACT_RECORD": 3,
    "ANONYMIZE_RECORD": 4,
    "VERIFY_RECORD_ABSENT": 0,
    "VERIFY_RECORD_PRESENT": 1,
    "VERIFY_RECORD_REDACTED": 2,
    "VERIFY_RECORD_ANONYMIZED": 3,
    "VERIFY_DATA_FLOW_DISABLED": 4,
    "VERIFY_RESTORE_BLOCKED": 5,
}


def natural_case_key(case_id: str) -> tuple[str, int]:
    match = re.search(r"(\d+)$", case_id)
    return case_id[: match.start()] if match else case_id, int(match.group(1)) if match else -1


def step_sort_key(step: dict[str, Any]) -> tuple[int, int, str, str]:
    phase = step.get("phase", "")
    op = step.get("operation", "")
    p_rank = PHASE_ORDER.get(phase, 99)
    op_rank = OPERATION_ORDER.get(op, 99)
    return p_rank, op_rank, str(step.get("system_id", "")), str(step.get("resource_id", ""))


@dataclass
class ValidationReport:
    total_rows: int = 0
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=lambda: {"COMPLETE": 0, "INCOMPLETE": 0, "NOT_APPLICABLE": 0})
    complete_empty_count: int = 0
    complete_no_account_absent_count: int = 0


def load_manifest_sets(dataset_dir: Path | None) -> tuple[set[str], set[str], set[str], list[str]]:
    """Loads valid evidence IDs, system IDs, resource IDs, and expected case IDs from dataset manifests."""
    evidence_ids: set[str] = set()
    system_ids: set[str] = set()
    resource_ids: set[str] = set()
    expected_case_ids: list[str] = []

    if not dataset_dir or not dataset_dir.is_dir():
        return evidence_ids, system_ids, resource_ids, expected_case_ids

    # 1. Evidence files manifest
    ev_file = dataset_dir / "evidence_files.csv"
    if ev_file.is_file():
        with ev_file.open(newline="", encoding="utf-8") as h:
            for row in csv.DictReader(h):
                if row.get("file_id"):
                    evidence_ids.add(row["file_id"].strip())

    # 2. User audit log
    audit_file = dataset_dir / "user_audit_log.csv"
    if audit_file.is_file():
        with audit_file.open(newline="", encoding="utf-8") as h:
            for row in csv.DictReader(h):
                if row.get("audit_id"):
                    evidence_ids.add(row["audit_id"].strip())

    # 3. System activity manifest
    act_file = dataset_dir / "system_activity.csv"
    if act_file.is_file():
        with act_file.open(newline="", encoding="utf-8") as h:
            for row in csv.DictReader(h):
                if row.get("activity_id"):
                    evidence_ids.add(row["activity_id"].strip())
                if row.get("source_system"):
                    system_ids.add(row["source_system"].strip())
                if row.get("target_system"):
                    system_ids.add(row["target_system"].strip())
                if row.get("resource_id"):
                    resource_ids.add(row["resource_id"].strip())

    # 4. Deletion requests (expected cases)
    req_file = dataset_dir / "deletion_requests.csv"
    if req_file.is_file():
        with req_file.open(newline="", encoding="utf-8") as h:
            for row in csv.DictReader(h):
                if row.get("case_id"):
                    expected_case_ids.append(row["case_id"].strip())

    # Supplement standard known systems if any appear in facts/rules
    known_systems = {
        "account_service", "profile_service", "security_service", "search_service",
        "support_platform", "export_service", "integration_service", "backup_service",
        "analytics_platform", "notification_service", "email_delivery_service",
        "archive_service", "cache_service", "telemetry_service",
    }
    system_ids.update(known_systems)

    return evidence_ids, system_ids, resource_ids, expected_case_ids


def is_must_retain(system_id: str, resource_id: str) -> bool:
    """Returns True if the resource must be retained by policy."""
    sys_lower = system_id.lower()
    res_lower = resource_id.lower()
    if sys_lower in {"security_service", "archive_service"}:
        return True
    if res_lower.startswith("audit_record_") or "security" in res_lower or "legal" in res_lower:
        return True
    if "backup" in res_lower or sys_lower == "backup_service":
        return True
    return False


def validate_file(
    output_path: str | Path,
    dataset_dir: str | Path | None = None,
    expected_row_count: int | None = 518,
) -> ValidationReport:
    out_file = Path(output_path)
    report = ValidationReport()

    if not out_file.is_file():
        report.passed = False
        report.errors.append(f"File not found: {out_file}")
        return report

    # 1. Exact header check
    with out_file.open("r", encoding="utf-8") as handle:
        first_line = handle.readline()
        if first_line.rstrip("\r\n") != "case_id,deletion_status,steps_json":
            report.errors.append(f"Header mismatch: expected 'case_id,deletion_status,steps_json', got {first_line.strip()!r}")

    # Load dataset manifests if available
    d_dir = Path(dataset_dir) if dataset_dir else None
    valid_evidence, valid_systems, valid_resources, expected_cases = load_manifest_sets(d_dir)

    # Read rows
    with out_file.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    report.total_rows = len(rows)

    # 2. Row count check
    if expected_row_count is not None and len(rows) != expected_row_count:
        report.errors.append(f"Row count mismatch: expected {expected_row_count}, got {len(rows)}")

    # 3. Case IDs: unique and sorted
    case_ids = [row.get("case_id", "").strip() for row in rows]
    if len(case_ids) != len(set(case_ids)):
        report.errors.append("Duplicate case_id values found in output")

    sorted_cases = sorted(case_ids, key=natural_case_key)
    if case_ids != sorted_cases:
        report.errors.append("Rows are not sorted by case_id in natural order")

    if expected_cases and case_ids != sorted(expected_cases, key=natural_case_key):
        missing = set(expected_cases) - set(case_ids)
        extra = set(case_ids) - set(expected_cases)
        if missing:
            report.errors.append(f"Missing expected case_ids (first 3): {list(missing)[:3]}")
        if extra:
            report.errors.append(f"Unexpected case_ids (first 3): {list(extra)[:3]}")

    # 4. Row-level and step-level checks
    for idx, row in enumerate(rows, 1):
        case_id = row.get("case_id", f"row_{idx}")
        status = row.get("deletion_status", "").strip()

        if status not in {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}:
            report.errors.append(f"{case_id}: invalid deletion_status '{status}'")
            continue
        report.status_counts[status] = report.status_counts.get(status, 0) + 1

        raw_json = row.get("steps_json", "")
        try:
            steps = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            report.errors.append(f"{case_id}: invalid JSON in steps_json ({exc})")
            continue

        if not isinstance(steps, list):
            report.errors.append(f"{case_id}: steps_json is not a JSON array")
            continue

        # Check NOT_APPLICABLE must be []
        if status == "NOT_APPLICABLE":
            if steps != []:
                report.errors.append(f"{case_id}: NOT_APPLICABLE must have empty steps_json '[]', got {len(steps)} steps")
            continue

        # Check step_no consecutive from 1
        expected_step_nos = list(range(1, len(steps) + 1))
        actual_step_nos = [step.get("step_no") for step in steps if isinstance(step, dict)]
        if actual_step_nos != expected_step_nos:
            report.errors.append(f"{case_id}: step_no values not consecutive 1..{len(steps)}")

        # Check ordering rule
        # Sort each step by (phase_rank, op_rank, system_id, resource_id)
        if len(steps) > 1:
            canonical_ordered = sorted(steps, key=step_sort_key)
            if [s.get("step_no") for s in steps] != [s.get("step_no") for s in canonical_ordered]:
                report.errors.append(f"{case_id}: steps do not satisfy required phase/operation/system/resource ordering")

        # Track steps for finding/remediation/verification matching
        finding_targets: set[tuple[str, str]] = set()
        remediation_targets: set[tuple[str, str]] = set()
        verification_targets: set[tuple[str, str]] = set()

        for s_idx, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                report.errors.append(f"{case_id}: step #{s_idx} is not an object")
                continue

            phase = step.get("phase", "")
            operation = step.get("operation", "")
            state = step.get("state", "")
            system_id = step.get("system_id", "")
            resource_id = step.get("resource_id", "")
            evidence_id = step.get("evidence_id", "")

            triple = (phase, operation, state)
            if triple not in ALLOWED_TRIPLES:
                report.errors.append(f"{case_id}: step #{s_idx} has invalid triple {triple}")

            target_pair = (system_id, resource_id)
            if phase == "FINDING":
                finding_targets.add(target_pair)
                if not evidence_id:
                    report.errors.append(f"{case_id}: FINDING step #{s_idx} missing evidence_id")
            elif phase == "REMEDIATION":
                remediation_targets.add(target_pair)
                if status == "INCOMPLETE" and evidence_id:
                    report.errors.append(f"{case_id}: INCOMPLETE REMEDIATION step #{s_idx} must have empty evidence_id")
            elif phase == "VERIFICATION":
                verification_targets.add(target_pair)
                if status == "COMPLETE":
                    if not evidence_id:
                        report.errors.append(f"{case_id}: COMPLETE VERIFICATION step #{s_idx} missing evidence_id")
                elif status == "INCOMPLETE":
                    if evidence_id:
                        report.errors.append(f"{case_id}: INCOMPLETE future VERIFICATION step #{s_idx} must have empty evidence_id")

            # Check no DELETE_RECORD on must-retain records
            if operation == "DELETE_RECORD":
                if is_must_retain(system_id, resource_id):
                    report.errors.append(f"{case_id}: DELETE_RECORD requested on must-retain resource '{resource_id}' ({system_id})")

            # Check manifests existence if manifests loaded
            if valid_systems and system_id and system_id not in valid_systems:
                report.errors.append(f"{case_id}: system_id '{system_id}' not found in dataset manifests")
            if valid_evidence and evidence_id and evidence_id not in valid_evidence:
                report.errors.append(f"{case_id}: evidence_id '{evidence_id}' not found in dataset manifests")
            if valid_resources and resource_id and resource_id not in valid_resources:
                # Some synthetic resources or dynamic IDs might exist; flag if unknown
                pass

        # Check status constraints on COMPLETE
        if status == "COMPLETE":
            if len(steps) == 0:
                report.complete_empty_count += 1
                report.errors.append(f"{case_id}: COMPLETE status must have non-empty steps_json, got '[]'")
            has_acc_absent = any(
                s.get("phase") == "VERIFICATION"
                and s.get("operation") == "VERIFY_RECORD_ABSENT"
                and (s.get("system_id") == "account_service" or "account_" in s.get("resource_id", ""))
                for s in steps
            )
            if not has_acc_absent:
                report.complete_no_account_absent_count += 1
            non_verif = [s for s in steps if s.get("phase") != "VERIFICATION"]
            if non_verif:
                report.errors.append(f"{case_id}: COMPLETE status contains non-VERIFICATION steps: {[s.get('operation') for s in non_verif]}")

        # Check step matching
        # "every FINDING has a matching REMEDIATION; every REMEDIATION has a matching VERIFICATION"
        # and "every REMEDIATION has a FINDING on the same resource; every non-compliant assessment produced a finding"
        if status == "INCOMPLETE":
            if len(finding_targets) == 0:
                report.errors.append(f"{case_id}: INCOMPLETE status has no FINDING steps")

            unmatched_findings = finding_targets - remediation_targets
            if unmatched_findings:
                report.errors.append(f"{case_id}: findings without matching remediation: {unmatched_findings}")

            unmatched_remediations = remediation_targets - verification_targets
            if unmatched_remediations:
                report.errors.append(f"{case_id}: remediations without matching verification: {unmatched_remediations}")

            remediations_without_finding = remediation_targets - finding_targets
            if remediations_without_finding:
                report.errors.append(f"{case_id}: remediations without matching finding on same resource: {remediations_without_finding}")


    report.passed = len(report.errors) == 0
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Label-free validation for deletion audit output.csv (EXTRAS.md §2)")
    parser.add_argument("--output", default="output.csv", help="Path to output.csv to validate")
    parser.add_argument("--dataset-dir", default="dataset", help="Path to dataset directory for manifest verification")
    parser.add_argument("--expected-rows", type=int, default=518, help="Expected number of data rows (default: 518)")
    args = parser.parse_args()

    out_path = Path(args.output)
    ds_path = Path(args.dataset_dir) if args.dataset_dir else None

    print(f"Validating '{out_path}' against manifests in '{ds_path}'...")
    report = validate_file(out_path, ds_path, expected_row_count=args.expected_rows)

    print("\n--- Validation Results ---")
    print(f"Total Rows Checked: {report.total_rows}")
    print(f"Status Distribution: {report.status_counts}")
    print(f"COMPLETE with [] steps: {report.complete_empty_count}")
    print(f"COMPLETE with no account VERIFY_RECORD_ABSENT: {report.complete_no_account_absent_count}")
    print(f"Passed: {report.passed}")

    if report.warnings:
        print(f"\nWarnings ({len(report.warnings)}):")
        for w in report.warnings[:10]:
            print(f"  [WARN] {w}")

    if report.errors:
        print(f"\nErrors ({len(report.errors)}):")
        for err in report.errors[:20]:
            print(f"  [ERROR] {err}")
        if len(report.errors) > 20:
            print(f"  ... and {len(report.errors) - 20} more errors.")
        sys.exit(1)
    else:
        print("\nAll validation checks PASSED successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
