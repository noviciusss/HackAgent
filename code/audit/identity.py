from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from .ingest import Dataset, norm_email, norm_phone, parse_time


@dataclass
class Identity:
    user_id: str
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    hashes: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)
    audit_ids: set[str] = field(default_factory=set)

    @property
    def tokens(self) -> set[str]:
        values = {self.user_id.lower()}
        values.update(e.lower() for e in self.emails)
        values.update(p for p in self.phones if p)
        values.update(h.lower() for h in self.hashes)
        values.update(n.lower() for n in self.names if n)
        return values


def resolve_identity(dataset: Dataset, email: str, requested_at: str | datetime) -> Identity | None:
    requested = parse_time(requested_at) if isinstance(requested_at, str) else requested_at
    by_user: dict[str, Identity] = {}
    for row in dataset.identities:
        ident = by_user.setdefault(row["user_id"], Identity(row["user_id"]))
        if row.get("email"):
            ident.emails.add(norm_email(row["email"]))
            ident.hashes.add(row.get("email_hash", "").lower())
        if row.get("phone"):
            ident.phones.add(norm_phone(row["phone"]))
        if row.get("name"):
            ident.names.add(row["name"].strip())
    for row in dataset.audit_log:
        ident = by_user.setdefault(row["user_id"], Identity(row["user_id"]))
        ident.audit_ids.add(row["audit_id"])
        field = row.get("field_name", "")
        if field == "email":
            ident.emails.update({norm_email(row.get("old_value")), norm_email(row.get("new_value"))})
        elif field == "email_hash":
            ident.hashes.update({row.get("old_value", "").lower(), row.get("new_value", "").lower()})
        elif field == "phone":
            ident.phones.update({norm_phone(row.get("old_value")), norm_phone(row.get("new_value"))})
    target = norm_email(email)
    candidates = [ident for ident in by_user.values() if target in ident.emails]
    if not candidates:
        target_hash = hashlib.sha256(target.encode()).hexdigest()
        candidates = [ident for ident in by_user.values() if target_hash in ident.hashes]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # Prefer the candidate whose identity history contains the address at request time.
    for candidate in candidates:
        events = [r for r in dataset.audit_log if r["user_id"] == candidate.user_id and r.get("field_name") == "email"]
        valid = True
        for event in events:
            at = parse_time(event.get("event_time"))
            if at and requested and norm_email(event.get("old_value")) == target and requested > at:
                valid = False
        if valid:
            return candidate
    return candidates[0]
