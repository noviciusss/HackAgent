from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .identity import Identity
from .ingest import Dataset, Fact, norm_email, norm_phone, parse_time


DIRECT_FIELDS = {"email", "phone", "email_hash", "name", "full_name", "display_name", "requester_name", "requester_email", "requester_phone", "owner_email", "customer_email", "subject_key", "lookup_key", "correlation_key", "match_key"}


@dataclass
class ResourceObservation:
    system_id: str
    resource_id: str
    category: str
    state: str
    evidence_id: str
    facts: list[Fact] = field(default_factory=list)
    direct_pii: bool = False
    fields: set[str] = field(default_factory=set)
    audit_at: datetime | None = None


def _fact_matches(fact: Fact, identity: Identity) -> bool:
    tokens = identity.tokens
    if fact.values & tokens:
        return True
    raw = fact.raw.lower()
    for email in identity.emails:
        if email and email in raw:
            return True
    for phone in identity.phones:
        digits = norm_phone(phone)
        if digits and digits in norm_phone(raw):
            return True
    for digest in identity.hashes:
        if digest and digest in raw:
            return True
    return False


def _fact_pii(fact: Fact, identity: Identity) -> tuple[bool, set[str]]:
    fields: set[str] = set()
    direct = False
    direct_tokens = {token.lower() for token in identity.emails | identity.phones | identity.hashes if token}
    if fact.values & direct_tokens:
        direct = True
        if fact.values & {email.lower() for email in identity.emails}:
            fields.add("email")
        if fact.values & {phone.lower() for phone in identity.phones}:
            fields.add("phone")
        if fact.values & {digest.lower() for digest in identity.hashes}:
            fields.add("email_hash")
    if fact.fields:
        for key, value in fact.fields.items():
            if value is None or value == "":
                continue
            key_low = str(key).lower()
            if key_low in DIRECT_FIELDS:
                fields.add(key_low)
                if key_low in {"email", "phone", "email_hash", "full_name", "display_name", "requester_name", "requester_email", "requester_phone", "owner_email", "customer_email"}:
                    direct = True
    raw = fact.raw.lower()
    if any(email and email in raw for email in identity.emails):
        direct = True
        fields.add("email")
    identity_phone_digits = {norm_phone(p) for p in identity.phones if p}
    if any(p and p in norm_phone(raw) for p in identity_phone_digits):
        direct = True
        fields.add("phone")
    if any(h and h in raw for h in identity.hashes):
        direct = True
        fields.add("email_hash")
    return direct, fields


def _timestamp(fact: Fact) -> datetime | None:
    return fact.event_time


def _fact_order(fact: Fact) -> tuple[datetime, int, str]:
    return (_timestamp(fact) or datetime.min.replace(tzinfo=timezone.utc), 0 if fact.source_kind == "activity" else 1, fact.evidence_id)


def _effective_state(facts: list[Fact], category: str, identity: Identity, cutoff: datetime | None = None) -> tuple[str, bool, set[str], str]:
    if not facts:
        return "", False, set(), ""
    ordered = sorted(facts, key=lambda f: ((_timestamp(f) or datetime.min.replace(tzinfo=timezone.utc)), 0 if f.source_kind == "activity" else 1, f.evidence_id))
    # Readback/snapshot evidence is stronger than generic workflow activity at the same time.
    direct_facts = [f for f in ordered if f.source_kind != "activity"] or ordered
    latest = direct_facts[-1]
    states = [f.state for f in direct_facts if f.state]
    direct_pii = False
    fields: set[str] = set()
    for fact in direct_facts:
        pii, found = _fact_pii(fact, identity)
        direct_pii = direct_pii or pii
        fields.update(found)
    state = latest.state
    if category == "DATA_FLOW":
        if any(s == "ACTIVE" for s in states[-2:]):
            state = "ACTIVE"
        elif any(s == "DISABLED" for s in states[-2:]):
            state = "DISABLED"
    elif category == "BACKUP_ARCHIVE":
        if any(s == "ACTIVE" for s in states[-2:]):
            state = "ACTIVE"
        elif any(s == "BLOCKED" for s in states[-2:]):
            state = "BLOCKED"
        elif not state:
            state = "ACTIVE"
    elif state not in {"ABSENT", "ACTIVE", "DISABLED", "BLOCKED"}:
        if category in {"ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"} and not direct_pii:
            state = "ANONYMIZED"
        elif category == "ACCOUNT_TOMBSTONE" and not direct_pii:
            state = "REDACTED"
        elif category == "SECURITY_AUDIT_LOG":
            state = "PRESENT"
        elif category == "SUPPORT_MESSAGE" and not direct_pii:
            state = "REDACTED"
        else:
            state = "PRESENT"
    evidence_facts = [fact for fact in direct_facts if not cutoff or not fact.captured_at or fact.captured_at <= cutoff]
    evidence = (evidence_facts[-1] if evidence_facts else latest).evidence_id
    return state, direct_pii, fields, evidence


def reconstruct(dataset: Dataset, identity: Identity, audit_at: str | datetime, request: dict[str, str] | None = None) -> list[ResourceObservation]:
    if isinstance(audit_at, str):
        cutoff = parse_time(audit_at)
    else:
        cutoff = audit_at
    direct: list[Fact] = []
    for fact in dataset.facts:
        stamp = _timestamp(fact)
        if cutoff and stamp and stamp > cutoff:
            continue
        if cutoff and not stamp and fact.captured_at and fact.captured_at > cutoff:
            continue
        if fact.source_kind == "activity" and "LINK_RESOURCE_IDENTITY" in fact.raw:
            req_time = parse_time(request.get("requested_at")) if request else None
            if not req_time or not stamp or abs(stamp - req_time) > timedelta(days=7):
                continue
        if _fact_matches(fact, identity):
            direct.append(fact)
    if request and cutoff:
        reported = parse_time(request.get("reported_at"))
        text = request.get("request_text", "").lower()
        wanted_categories: set[str] = {"USER_PROFILE"}
        if any(word in text for word in ("backup", "restore", "archive", "backups")):
            wanted_categories.add("BACKUP_ARCHIVE")
        if any(word in text for word in ("integration", "synchron", "copy", "send my data", "connector")):
            wanted_categories.add("DATA_FLOW")
        if any(word in text for word in ("support", "attachment", "conversation", "message", "document")):
            wanted_categories.update({"SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT"})
        if reported:
            for fact in dataset.facts:
                if fact.source_kind != "activity" or fact.category not in wanted_categories:
                    continue
                stamp = _timestamp(fact)
                window = timedelta(minutes=10) if fact.category == "USER_PROFILE" else timedelta(minutes=90)
                if not stamp or abs(stamp - reported) > window or stamp > cutoff:
                    continue
                if "LINK_RESOURCE_IDENTITY" in fact.raw:
                    continue
                if not _fact_matches(fact, identity):
                    continue
                if fact.resource_id in {item.resource_id for item in direct}:
                    continue
                if fact.category == "USER_PROFILE" and "delete_record" not in fact.raw.lower():
                    continue
                if fact.category != "USER_PROFILE" and "delete_record" not in fact.raw.lower() and fact.category not in wanted_categories - {"USER_PROFILE"}:
                    continue
                related = [candidate for candidate in dataset.facts if candidate.resource_id == fact.resource_id and candidate.source_kind != "activity" and (not candidate.captured_at or candidate.captured_at <= cutoff)]
                if related:
                    evidence_id = sorted(related, key=lambda candidate: (candidate.captured_at or datetime.min.replace(tzinfo=timezone.utc), candidate.evidence_id))[-1].evidence_id
                elif fact.category == "USER_PROFILE":
                    account_files = [entry for entry in dataset.evidence if "account" in entry.get("file_path", "").lower() and (captured := parse_time(entry.get("captured_at"))) and captured <= cutoff]
                    evidence_id = max(account_files, key=lambda entry: parse_time(entry["captured_at"]) or datetime.min.replace(tzinfo=timezone.utc))["file_id"] if account_files else fact.evidence_id
                else:
                    evidence_id = fact.evidence_id
                context_state = "ABSENT" if fact.category == "USER_PROFILE" and "delete_record" in fact.raw.lower() else fact.state
                direct.append(Fact(evidence_id, fact.captured_at, fact.observed_at, fact.system_id, fact.resource_id, fact.category, context_state, fact.values, fact.fields, fact.raw, "context_activity"))
    # The activity stream ties the primary deletion request to its account resource
    # by the reported operation time even when the account is absent from a snapshot.
    if request:
        reported = parse_time(request.get("reported_at"))
        if reported:
            for fact in dataset.facts:
                if fact.source_kind != "activity" or not fact.resource_id.startswith("account_"):
                    continue
                if not any(token in fact.raw.lower() for token in ("delete_record", "delete record")):
                    continue
                stamp = _timestamp(fact)
                if not stamp or abs(stamp - reported) > timedelta(minutes=15) or (cutoff and stamp > cutoff):
                    continue
                direct.append(fact)
                if not any(existing.resource_id == fact.resource_id for existing in direct if existing is not fact):
                    account_evidence = [
                        entry for entry in dataset.evidence
                        if "account" in entry.get("file_path", "").lower()
                        and entry.get("file_path", "").lower().endswith(".sql")
                        and (captured := parse_time(entry.get("captured_at")))
                        and (not cutoff or captured <= cutoff)
                    ]
                    if account_evidence:
                        latest = max(account_evidence, key=lambda entry: parse_time(entry["captured_at"]) or datetime.min.replace(tzinfo=timezone.utc))
                        direct.append(Fact(latest["file_id"], parse_time(latest["captured_at"]), parse_time(latest["captured_at"]), "account_service", fact.resource_id, "USER_PROFILE", "ABSENT", {identity.user_id.lower()}, {}, "resource absent from account snapshot", "sql_absence"))
    by_resource: dict[str, list[Fact]] = {}
    for fact in direct:
        by_resource.setdefault(fact.resource_id, []).append(fact)
    # Once one line/object identifies a resource, include the other readback lines
    # for that same resource (for example lookup_started followed by rows=0).
    direct_resources = set(by_resource)
    for fact in dataset.facts:
        if fact.resource_id not in direct_resources:
            continue
        stamp = _timestamp(fact)
        if cutoff and stamp and stamp > cutoff:
            continue
        if cutoff and not stamp and fact.captured_at and fact.captured_at > cutoff:
            continue
        if fact not in by_resource[fact.resource_id]:
            by_resource[fact.resource_id].append(fact)
    observations: list[ResourceObservation] = []
    for resource_id, facts in by_resource.items():
        facts.sort(key=lambda f: ((_timestamp(f) or datetime.min.replace(tzinfo=timezone.utc)), f.evidence_id))
        category = next((f.category for f in reversed(facts) if f.category), "")
        system = next((f.system_id for f in reversed(facts) if f.system_id), "unknown_service")
        state, pii, fields, evidence = _effective_state(facts, category, identity, cutoff)
        observations.append(ResourceObservation(system, resource_id, category, state, evidence, facts, pii, fields, cutoff))
    # Multiple historical account readbacks can describe the same subject. Keep
    # the latest absent primary profile rather than emitting every old lookup.
    account_observations = [item for item in observations if item.category == "USER_PROFILE" and item.state == "ABSENT"]
    if len(account_observations) > 1:
        keep = max(account_observations, key=lambda item: max((_timestamp(fact) or datetime.min.replace(tzinfo=timezone.utc) for fact in item.facts), default=datetime.min.replace(tzinfo=timezone.utc)))
        observations = [item for item in observations if item not in account_observations or item is keep]
    return observations
