from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .ingest import parse_time
from .state import ResourceObservation


@dataclass
class PolicyAssessment:
    observation: ResourceObservation
    required_action: str
    compliant: bool
    violation_operation: str = ""
    remediation_operation: str = ""
    verification_operation: str = ""


ACTION_BY_CATEGORY = {
    "USER_PROFILE": "DELETE",
    "SECONDARY_IDENTIFIER": "DELETE",
    "SEARCH_INDEX_ENTRY": "DELETE",
    "CACHE_ENTRY": "DELETE",
    "SUPPORT_MESSAGE": "REDACT",
    "SUPPORT_ATTACHMENT": "DELETE",
    "ANALYTICS_PROFILE": "ANONYMIZE",
    "PRODUCT_TELEMETRY": "ANONYMIZE",
    "USER_EXPORT": "DELETE",
    "MARKETING_PROFILE": "DELETE",
    "EMAIL_DELIVERY_LOG": "REDACT",
    "SECURITY_AUDIT_LOG": "RETAIN",
    "LEGAL_HOLD_RECORD": "RETAIN",
    "BACKUP_ARCHIVE": "RETAIN",
    "ACCOUNT_TOMBSTONE": "REDACT",
}


def assess(observation: ResourceObservation, request_text: str = "", audit_at: Any = None) -> PolicyAssessment:
    category = observation.category
    action = ACTION_BY_CATEGORY.get(category, "DELETE")
    low_request = request_text.lower()
    if category == "SUPPORT_MESSAGE" and observation.direct_pii and re.search(r"old|current|earlier|both addresses", low_request) and not re.search(r"conversation|shared|another customer|agent|order context|support|analytics|search|integration", low_request):
        action = "DELETE"
    if category in {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"} and observation.direct_pii and "nothing tied" in low_request:
        action = "DELETE"
    state = observation.state
    if category == "DATA_FLOW":
        return PolicyAssessment(observation, "FLOW", state == "DISABLED", "REPORT_ACTIVE_DATA_FLOW", "DISABLE_DATA_FLOW", "VERIFY_DATA_FLOW_DISABLED")
    if category == "BACKUP_ARCHIVE":
        # Rule 14: A retained backup archive is compliant only when its restore path is blocked.
        # Decided deterministically: archive exists, contains this user's identifiers,
        # retention_end is after audit_at, and no explicit block indicator.
        is_blocked = False
        retention_after_audit = True
        cutoff = audit_at or observation.audit_at
        if isinstance(cutoff, str):
            from .ingest import parse_time
            cutoff = parse_time(cutoff)

        for fact in observation.facts:
            if fact.state == "BLOCKED":
                is_blocked = True
            if isinstance(fact.fields, dict):
                if fact.fields.get("explicit_block") or fact.fields.get("explicit_block_indicator"):
                    is_blocked = True
                ret_str = fact.fields.get("retention_end")
                if ret_str and cutoff:
                    from .ingest import parse_time
                    ret_dt = parse_time(str(ret_str))
                    if ret_dt and ret_dt <= cutoff:
                        retention_after_audit = False
            raw_low = fact.raw.lower()
            if "block" in raw_low and "unblock" not in raw_low:
                if "block_restore" in raw_low or "blocked" in raw_low:
                    is_blocked = True

        if state == "BLOCKED" or is_blocked or not retention_after_audit or state == "ABSENT":
            return PolicyAssessment(observation, action, True, "", "", "VERIFY_RESTORE_BLOCKED")
        return PolicyAssessment(observation, action, False, "REPORT_RESTORE_RISK", "BLOCK_RESTORE", "VERIFY_RESTORE_BLOCKED")

    if action == "DELETE":
        return PolicyAssessment(observation, action, state == "ABSENT", "REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")
    if action == "REDACT":
        compliant = state == "REDACTED" and not observation.direct_pii
        return PolicyAssessment(observation, action, compliant, "REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED")
    if action == "ANONYMIZE":
        compliant = state == "ANONYMIZED" and not observation.direct_pii
        return PolicyAssessment(observation, action, compliant, "REPORT_EXPOSED_PII", "ANONYMIZE_RECORD", "VERIFY_RECORD_ANONYMIZED")
    if action == "RETAIN":
        return PolicyAssessment(observation, action, state in {"PRESENT", "REDACTED", "ANONYMIZED"}, "", "", "VERIFY_RECORD_PRESENT")
    return PolicyAssessment(observation, action, False, "REPORT_REMAINING_RECORD", "DELETE_RECORD", "VERIFY_RECORD_ABSENT")


def assess_all(observations: list[ResourceObservation], request_text: str = "", audit_at: Any = None) -> list[PolicyAssessment]:
    return [assess(observation, request_text, audit_at) for observation in observations]

