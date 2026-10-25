from __future__ import annotations

import csv
import base64
import json
import re
import sqlite3
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RESOURCE_RE = re.compile(
    r"\b(?:account|search|analytics|support|export|data_flow|backup|audit_record|tombstone|cache|email_delivery|marketing|telemetry|customer)_[A-Za-z0-9-]*\d[A-Za-z0-9-]*\b",
    re.I,
)
EMAIL_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
USER_RE = re.compile(r"\buser_[A-Za-z0-9-]+\b", re.I)
PHONE_RE = re.compile(r"(?<![A-Za-z0-9])\+?[0-9][0-9 ()-]{6,}[0-9](?![A-Za-z0-9])")
TRACE_RE = re.compile(r"\b(?:trace_id|trace)\s*[\"']?\s*[:=]\s*[\"']?([^\s\"'|,}]+)", re.I)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def norm_email(value: str | None) -> str:
    return (value or "").strip().lower()


def norm_phone(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _flatten_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            values.append(str(key))
            values.extend(_flatten_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_flatten_values(child))
    elif value is not None:
        values.append(str(value))
    return values


def _resource_id_from_values(values: Iterable[str]) -> str | None:
    for value in values:
        match = RESOURCE_RE.search(value)
        if match:
            return match.group(0)
    return None


def _system_for_category(category: str, fallback: str = "") -> str:
    mapping = {
        "USER_PROFILE": "account_service",
        "SECONDARY_IDENTIFIER": "identity_service",
        "SEARCH_INDEX_ENTRY": "search_service",
        "CACHE_ENTRY": "cache_service",
        "SUPPORT_MESSAGE": "support_platform",
        "SUPPORT_ATTACHMENT": "support_platform",
        "ANALYTICS_PROFILE": "analytics_platform",
        "PRODUCT_TELEMETRY": "analytics_platform",
        "USER_EXPORT": "export_service",
        "MARKETING_PROFILE": "marketing_platform",
        "EMAIL_DELIVERY_LOG": "email_delivery_service",
        "SECURITY_AUDIT_LOG": "security_service",
        "LEGAL_HOLD_RECORD": "legal_service",
        "BACKUP_ARCHIVE": "backup_service",
        "ACCOUNT_TOMBSTONE": "identity_service",
        "DATA_FLOW": "integration_service",
    }
    return mapping.get(category, fallback or "unknown_service")


def _category_from_resource(resource_id: str | None, text: str = "") -> str:
    rid = (resource_id or "").lower()
    low = text.lower()
    if rid.startswith("account_"):
        return "USER_PROFILE"
    if rid.startswith("search_"):
        return "SEARCH_INDEX_ENTRY"
    if rid.startswith("analytics_"):
        return "ANALYTICS_PROFILE"
    if rid.startswith("support_"):
        return "SUPPORT_ATTACHMENT" if any(x in low for x in ("attachment", ".pdf", "file ")) else "SUPPORT_MESSAGE"
    if rid.startswith("export_"):
        return "USER_EXPORT"
    if rid.startswith("data_flow_"):
        return "DATA_FLOW"
    if rid.startswith("backup_"):
        return "BACKUP_ARCHIVE"
    if rid.startswith("audit_record_"):
        return "SECURITY_AUDIT_LOG"
    if rid.startswith("tombstone_"):
        return "ACCOUNT_TOMBSTONE"
    if rid.startswith("cache_"):
        return "CACHE_ENTRY"
    if rid.startswith("email_delivery_"):
        return "EMAIL_DELIVERY_LOG"
    if "legal" in low or "hold" in low:
        return "LEGAL_HOLD_RECORD"
    if "marketing" in low:
        return "MARKETING_PROFILE"
    return ""


def _state_from_text(text: str, category: str = "") -> str:
    low = text.lower()
    if re.search(r"\b(?:404|rows=0|not_found|not found|result=miss|status_code[=: ]+404)\b", low):
        return "ABSENT"
    if re.search(r"\b(?:restore_allowed[=: ]+(?:false|0)|deletion_block[=: ]+true|blocked|block_restore)\b", low):
        return "BLOCKED"
    if re.search(r"\b(?:enabled[=: ]+false|disabled|stopped)\b", low):
        return "DISABLED"
    if re.search(r"\b(?:enabled[=: ]+true|active=true|\bactive\b|eligible=true|restore_allowed[=: ]+(?:true|1))\b", low):
        return "ACTIVE"
    if re.search(r"\b(?:anonymized|anonymous|no direct identifier)\b", low):
        return "ANONYMIZED"
    if re.search(r"\b(?:redacted|redact)\b", low):
        return "REDACTED"
    if re.search(r"\b(?:not_found|not found|absent|rows=0)\b", low):
        return "ABSENT"
    if re.search(r"\b(?:found|hit|identifiable|present|200|available=true)\b", low):
        return "PRESENT"
    return "PRESENT" if category not in {"DATA_FLOW", "BACKUP_ARCHIVE"} else ""


def _identifier_values(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        if not value:
            continue
        result.add(value.strip().lower())
        email = EMAIL_RE.search(value)
        if email:
            result.add(norm_email(email.group(0).rsplit("=", 1)[-1].strip("\"'")))
        for user in USER_RE.findall(value):
            result.add(user.lower())
        phone = PHONE_RE.search(value)
        if phone:
            result.add(norm_phone(phone.group(0)))
    return {v for v in result if v}


@dataclass
class Fact:
    evidence_id: str
    captured_at: datetime | None
    observed_at: datetime | None
    system_id: str
    resource_id: str
    category: str
    state: str
    values: set[str] = field(default_factory=set)
    fields: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    source_kind: str = ""

    @property
    def event_time(self) -> datetime | None:
        return self.observed_at or self.captured_at


@dataclass
class Dataset:
    root: Path
    requests: list[dict[str, str]]
    identities: list[dict[str, str]]
    audit_log: list[dict[str, str]]
    activity: list[dict[str, str]]
    rules: list[dict[str, str]]
    evidence: list[dict[str, str]]
    facts: list[Fact]


def _fact_from_obj(evidence_id: str, captured: datetime | None, obj: dict[str, Any], raw: str, kind: str, system_hint: str = "") -> Fact | None:
    values = _flatten_values(obj)
    resource = str(obj.get("resource_id") or _resource_id_from_values(values) or "")
    if not resource:
        return None
    category = str(obj.get("data_category") or obj.get("record_type") or obj.get("category") or "").upper()
    if category in {"DATA_FLOW", "BACKUP_ARCHIVE", "USER_PROFILE", "SEARCH_INDEX_ENTRY", "ANALYTICS_PROFILE", "SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT", "SECURITY_AUDIT_LOG", "ACCOUNT_TOMBSTONE", "USER_EXPORT"}:
        pass
    else:
        category = _category_from_resource(resource, raw)
    system = str(obj.get("system") or obj.get("data_store") or obj.get("source_system") or system_hint)
    system = _system_for_category(category, system)
    combined = " ".join(values) + " " + raw
    state = _state_from_text(combined, category)
    if category == "DATA_FLOW" and "enabled" in obj:
        state = "ACTIVE" if str(obj.get("enabled")).lower() in {"true", "1"} else "DISABLED"
    if category == "BACKUP_ARCHIVE" and "restore_allowed" in obj:
        state = "ACTIVE" if str(obj.get("restore_allowed")).lower() in {"true", "1"} else "BLOCKED"
    observed = None
    for key in ("observed_at", "captured_at", "recorded_at", "updated_at", "created_at", "exported_at"):
        if obj.get(key):
            observed = parse_time(str(obj[key]))
            if observed:
                break
    return Fact(evidence_id, captured, observed, system, resource, category, state, _identifier_values(values), obj, raw, kind)


def _json_facts(evidence_id: str, captured: datetime | None, data: Any, raw: str) -> list[Fact]:
    facts: list[Fact] = []
    def walk(value: Any, inherited: dict[str, Any] | None = None) -> None:
        if isinstance(value, dict):
            merged = dict(inherited or {})
            for key in ("data_store", "system", "record_type", "category", "captured_at", "observed_at"):
                if key in value:
                    merged[key] = value[key]
            if "resource_id" in value:
                obj = dict(merged)
                obj.update(value)
                object_raw = json.dumps(obj, ensure_ascii=False, default=str)
                fact = _fact_from_obj(evidence_id, captured, obj, object_raw, "json")
                if fact:
                    facts.append(fact)
            for child in value.values():
                walk(child, merged)
        elif isinstance(value, list):
            for child in value:
                walk(child, inherited)
    walk(data)
    return facts


def _sql_facts(evidence_id: str, captured: datetime | None, path: Path) -> list[Fact]:
    facts: list[Fact] = []
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(path.read_text(encoding="utf-8"))
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_map = {
            "customer_profiles": ("account_service", "USER_PROFILE"),
            "customer_search_documents": ("search_service", "SEARCH_INDEX_ENTRY"),
            "customer_analytics_profiles": ("analytics_platform", "ANALYTICS_PROFILE"),
            "support_records": ("support_platform", "SUPPORT_MESSAGE"),
            "customer_exports": ("export_service", "USER_EXPORT"),
            "connector_subscriptions": ("integration_service", "DATA_FLOW"),
            "backup_restore_entries": ("backup_service", "BACKUP_ARCHIVE"),
            "security_audit_records": ("security_service", "SECURITY_AUDIT_LOG"),
        }
        for (table,) in tables:
            if table == "snapshot_scope":
                continue
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                obj = dict(zip(columns, row))
                system, category = table_map.get(table, ("", _category_from_resource(str(obj.get("resource_id", "")), table)))
                obj.update({"system": system, "data_category": category})
                fact = _fact_from_obj(evidence_id, captured, obj, json.dumps(obj, default=str), "sql", system)
                if fact:
                    facts.append(fact)
    finally:
        conn.close()
    return facts


def _pdf_text(data: bytes) -> str:
    chunks: list[bytes] = []
    for match in re.finditer(rb"(?<!end)stream\r?\n", data):
        start = match.end()
        end = data.find(b"endstream", start)
        if end < 0:
            continue
        raw = data[start:end]
        try:
            chunks.append(zlib.decompress(raw))
        except zlib.error:
            try:
                chunks.append(zlib.decompress(base64.a85decode(raw.strip(), adobe=True)))
            except Exception:
                continue
    text_parts: list[str] = []
    for chunk in chunks:
        for match in re.finditer(rb"\(([^()]*)\)\s*Tj", chunk):
            text_parts.append(match.group(1).decode("latin1", errors="ignore"))
        for match in re.finditer(rb"\[(.*?)\]\s*TJ", chunk, re.S):
            for part in re.findall(rb"\(([^()]*)\)", match.group(1)):
                text_parts.append(part.decode("latin1", errors="ignore"))
    return " ".join(text_parts)


def _text_facts(evidence_id: str, captured: datetime | None, text: str, kind: str) -> list[Fact]:
    facts: list[Fact] = []
    lines = text.splitlines() or [text]
    trace_values: dict[str, set[str]] = {}
    for line in lines:
        trace = TRACE_RE.search(line)
        if trace:
            trace_values.setdefault(trace.group(1), set()).update(_identifier_values([line]))
    for line in lines:
        resources = list(dict.fromkeys(m.group(0) for m in RESOURCE_RE.finditer(line)))
        if not resources:
            continue
        event_time = None
        stamp = re.search(r"\b20\d{2}-\d{2}-\d{2}T[^ ]+", line)
        if stamp:
            event_time = parse_time(stamp.group(0).rstrip("|,"))
        values = _identifier_values([line])
        trace = TRACE_RE.search(line)
        if trace:
            values.update(trace_values.get(trace.group(1), set()))
        for resource in resources:
            category = _category_from_resource(resource, line)
            system = _system_for_category(category, "")
            facts.append(Fact(evidence_id, captured, event_time, system, resource, category, _state_from_text(line, category), values, {}, line, kind))
    return facts


def load_dataset(dataset_dir: str | Path, requests_file: str | Path | None = None, enable_vision: bool = True) -> Dataset:
    root = Path(dataset_dir).resolve()
    requests = read_csv(Path(requests_file).resolve() if requests_file else root / "deletion_requests.csv")
    identities = read_csv(root / "user_identities.csv")
    audit_log = read_csv(root / "user_audit_log.csv")
    activity = read_csv(root / "system_activity.csv")
    rules = read_csv(root / "deletion_rules.csv")
    evidence = read_csv(root / "evidence_files.csv")
    facts: list[Fact] = []
    for entry in evidence:
        path = root / entry["file_path"]
        captured = parse_time(entry.get("captured_at"))
        suffix = path.suffix.lower()
        try:
            if suffix == ".json":
                raw = path.read_text(encoding="utf-8")
                facts.extend(_json_facts(entry["file_id"], captured, json.loads(raw), raw))
            elif suffix == ".sql":
                facts.extend(_sql_facts(entry["file_id"], captured, path))
            elif suffix == ".pdf":
                text = _pdf_text(path.read_bytes())
                facts.extend(_text_facts(entry["file_id"], captured, text, "pdf"))
            else:
                facts.extend(_text_facts(entry["file_id"], captured, path.read_text(encoding="utf-8", errors="ignore"), suffix.lstrip(".")))
        except Exception:
            continue
    if enable_vision:
        from .vision import load_screenshot_facts
        facts.extend(load_screenshot_facts(root, evidence))

    for row in activity:
        resource = row.get("resource_id", "")
        if not resource:
            continue
        raw = " ".join(row.values())
        category = _category_from_resource(resource, raw)
        system = _system_for_category(category, row.get("target_system", ""))
        state = _state_from_text(raw, category)
        if row.get("event_type") in {"RESTORE_BACKUP", "CHECK_RESTORE_ACCESS"}:
            state = "ACTIVE"
        elif row.get("event_type") == "BLOCK_RESTORE":
            state = "BLOCKED"
        elif row.get("event_type") == "DISABLE_DATA_FLOW":
            state = "DISABLED"
        elif row.get("event_type") == "CHECK_DATA_FLOW":
            state = "ACTIVE" if "enabled" in row.get("details", "").lower() else state
        facts.append(Fact(row["activity_id"], parse_time(row.get("event_time")), parse_time(row.get("event_time")), system, resource, category, state, _identifier_values([raw]), {}, raw, "activity"))
    return Dataset(root, requests, identities, audit_log, activity, rules, evidence, facts)
