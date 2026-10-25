from __future__ import annotations

from dataclasses import dataclass

from .policy import PolicyAssessment


PHASE_RANK = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
OPERATION_RANK = {
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


@dataclass
class Step:
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str


def _state_for(operation: str) -> str:
    if operation in {"REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII"}:
        return "PRESENT"
    if operation in {"REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"}:
        return "ACTIVE"
    if operation == "DISABLE_DATA_FLOW":
        return "DISABLED"
    if operation == "BLOCK_RESTORE":
        return "BLOCKED"
    if operation == "DELETE_RECORD":
        return "ABSENT"
    if operation == "REDACT_RECORD":
        return "REDACTED"
    if operation == "ANONYMIZE_RECORD":
        return "ANONYMIZED"
    if operation == "VERIFY_RECORD_ABSENT":
        return "ABSENT"
    if operation == "VERIFY_RECORD_PRESENT":
        return "PRESENT"
    if operation == "VERIFY_RECORD_REDACTED":
        return "REDACTED"
    if operation == "VERIFY_RECORD_ANONYMIZED":
        return "ANONYMIZED"
    if operation == "VERIFY_DATA_FLOW_DISABLED":
        return "DISABLED"
    if operation == "VERIFY_RESTORE_BLOCKED":
        return "BLOCKED"
    raise ValueError(operation)


def _verification_step(assessment: PolicyAssessment) -> Step:
    observation = assessment.observation
    return Step("VERIFICATION", observation.system_id, observation.resource_id, assessment.verification_operation, _state_for(assessment.verification_operation), "")


def build_steps(assessments: list[PolicyAssessment], status: str) -> list[dict[str, object]]:
    if status == "NOT_APPLICABLE":
        return []
    steps: list[Step] = []
    if status == "COMPLETE":
        for assessment in assessments:
            if assessment.compliant and assessment.verification_operation:
                observation = assessment.observation
                steps.append(Step("VERIFICATION", observation.system_id, observation.resource_id, assessment.verification_operation, _state_for(assessment.verification_operation), observation.evidence_id))
    else:
        missing_op_count = 0
        for assessment in assessments:
            if not assessment.compliant:
                if not assessment.violation_operation:
                    missing_op_count += 1
                observation = assessment.observation
                steps.append(Step("FINDING", observation.system_id, observation.resource_id, assessment.violation_operation, _state_for(assessment.violation_operation), observation.evidence_id))
        for assessment in assessments:
            if not assessment.compliant:
                if not assessment.remediation_operation:
                    missing_op_count += 1
                observation = assessment.observation
                steps.append(Step("REMEDIATION", observation.system_id, observation.resource_id, assessment.remediation_operation, _state_for(assessment.remediation_operation), ""))
        if missing_op_count > 0:
            print(f"non_compliant_lacking_operation_count={missing_op_count}")
        for assessment in assessments:
            if assessment.verification_operation:
                steps.append(_verification_step(assessment))
    steps.sort(key=lambda step: (PHASE_RANK[step.phase], OPERATION_RANK[step.operation], step.system_id, step.resource_id))
    result: list[dict[str, object]] = []
    for number, step in enumerate(steps, 1):
        result.append({
            "step_no": number,
            "phase": step.phase,
            "system_id": step.system_id,
            "resource_id": step.resource_id,
            "operation": step.operation,
            "state": step.state,
            "evidence_id": step.evidence_id,
        })
    return result
