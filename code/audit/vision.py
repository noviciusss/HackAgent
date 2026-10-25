from __future__ import annotations

import hashlib
import json
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any

from .ingest import Fact, _category_from_resource, _identifier_values, _system_for_category, parse_time
from .llm_client import call_vision, vision_api_key, vision_model


PROMPT_VERSION = "vision-facts-v3"
PROMPT = """Read this business-system screenshot as evidence. Return JSON only with this shape:
{
  "facts": [
    {
      "scope": "resource",
      "resource_id": "",
      "identifiers": [],
      "system": "",
      "region": "",
      "created": "",
      "retention_end": "",
      "checksum": "",
      "explicit_block_indicator": null,
      "observed_state": "",
      "timestamp": ""
    },
    {
      "scope": "page",
      "badge_text": "",
      "system": ""
    }
  ]
}
Instructions:
1. If an inspector or details panel is open for the resource shown in the selected row / details pane, extract its full visible attributes: resource_id, account/email identifiers, system, region, created, retention_end, checksum, and any explicit blocked/locked/legal-hold indicator (null if none).
2. For any other resource rows visible, extract their attributes.
3. Separately label page-level status badges or service health badges (such as 'Healthy' under Service health or navigation) with scope="page".
4. Page-level badges apply to the overall platform/page, NOT to individual resources. Do not map page-level badges to resource states.
5. Use empty strings or null when fields are not visible."""



def _usage_path(repo_root: Path) -> Path:
    path = repo_root / "usage" / "usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append_usage(repo_root: Path, record: dict[str, Any]) -> None:
    with _usage_path(repo_root).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _cache_key(data: bytes, model: str) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return hashlib.sha256(f"{digest}:{PROMPT_VERSION}:{model}".encode("utf-8")).hexdigest()


def _cache_file(repo_root: Path, key: str) -> Path:
    path = repo_root / "usage" / "vision_cache" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _structured_facts(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        try:
            parsed, _ = json.JSONDecoder().raw_decode(text.lstrip())
        except json.JSONDecodeError as exc:
            raise RuntimeError("vision response was not valid JSON") from exc
    raw_facts = parsed.get("facts", []) if isinstance(parsed, dict) else []
    if not isinstance(raw_facts, list):
        raise RuntimeError("vision response facts was not an array")
    facts: list[dict[str, Any]] = []
    for item in raw_facts:
        if not isinstance(item, dict):
            continue
        scope = str(item.get("scope", "resource") or "resource").lower()
        if scope == "page":
            facts.append({
                "scope": "page",
                "badge_text": str(item.get("badge_text", "") or ""),
                "system": str(item.get("system", "") or ""),
            })
            continue
        identifiers = item.get("identifiers", [])
        if isinstance(identifiers, str):
            identifiers = [identifiers]
        if not isinstance(identifiers, list):
            identifiers = []
        if item.get("account"):
            identifiers.append(str(item["account"]))
        raw_state = str(item.get("observed_state", "") or "").strip()
        if raw_state.upper() in {"HEALTHY", "ONLINE", "ACTIVE (SERVICE)"}:
            raw_state = ""
        facts.append({
            "scope": "resource",
            "identifiers": [str(value) for value in identifiers if value is not None],
            "resource_id": str(item.get("resource_id", "") or ""),
            "system": str(item.get("system", "") or ""),
            "region": str(item.get("region", "") or ""),
            "created": str(item.get("created", "") or ""),
            "retention_end": str(item.get("retention_end", "") or ""),
            "checksum": str(item.get("checksum", "") or ""),
            "explicit_block_indicator": item.get("explicit_block_indicator"),
            "observed_state": raw_state,
            "timestamp": str(item.get("timestamp", "") or item.get("created", "") or ""),
        })
    return facts


def _fact_from_vision(evidence_id: str, captured_at: datetime | None, item: dict[str, Any]) -> Fact | None:
    if item.get("scope") == "page":
        return None
    resource_id = item.get("resource_id", "")
    if not resource_id:
        return None
    identifiers = list(item.get("identifiers", []))
    for ident in identifiers:
        if any(ident.startswith(p) for p in ("account_", "support_", "analytics_", "marketing_", "search_", "export_", "backup_", "data_flow_", "audit_record_")):
            resource_id = ident
            break

    raw_system = item.get("system", "")
    category = _category_from_resource(resource_id, raw_system)
    if not category:
        return None
    system = _system_for_category(category, raw_system)
    
    # Do NOT map "HEALTHY" to any pipeline state.
    state = ""
    block_ind = item.get("explicit_block_indicator")
    if block_ind is True or (isinstance(block_ind, str) and "block" in block_ind.lower()):
        state = "BLOCKED"
    elif item.get("observed_state"):
        obs_state = item["observed_state"].upper()
        if obs_state not in {"HEALTHY", "ONLINE"}:
            state = obs_state

    observed = parse_time(item.get("timestamp") or item.get("created"))
    values = _identifier_values(identifiers)
    if not values:
        return None
    details = {
        "identifiers": identifiers,
        "region": item.get("region", ""),
        "created": item.get("created", ""),
        "retention_end": item.get("retention_end", ""),
        "checksum": item.get("checksum", ""),
        "explicit_block": item.get("explicit_block_indicator"),
    }
    return Fact(evidence_id, captured_at, observed, system, resource_id, category, state, values, details, json.dumps(item, sort_keys=True), "vision")


def load_screenshot_facts(dataset_root: Path, evidence: list[dict[str, str]]) -> list[Fact]:
    """Read every screenshot; use cached model facts or an explicit no-key fallback."""
    repo_root = dataset_root.parent
    model = vision_model()
    api_key_present = bool(vision_api_key())
    image_entries = [entry for entry in evidence if Path(entry.get("file_path", "")).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    facts: list[Fact] = []
    for entry in image_entries:
        path = dataset_root / entry["file_path"]
        data = path.read_bytes()
        key = _cache_key(data, model)
        cache_path = _cache_file(repo_root, key)
        base = {"kind": "vision", "file_id": entry["file_id"], "cache_key": key, "model": model, "prompt_version": PROMPT_VERSION}
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            _append_usage(repo_root, {**base, "event": "cache_hit", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            for item in payload.get("facts", []):
                fact = _fact_from_vision(entry["file_id"], parse_time(entry.get("captured_at")), item)
                if fact:
                    facts.append(fact)
            continue
        if not api_key_present:
            _append_usage(repo_root, {**base, "event": "text_only_fallback", "reason": "no API key set", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            continue

        try:
            call = call_vision(data, PROMPT, mimetypes.guess_type(path.name)[0] or "image/png")
            structured = _structured_facts(call.content)
            cache_path.write_text(json.dumps({"facts": structured}, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
            _append_usage(repo_root, {**base, "event": "model_call", "model": call.model, "provider": call.provider, "input_tokens": call.input_tokens, "output_tokens": call.output_tokens, "cost_usd": call.cost_usd})
            for item in structured:
                fact = _fact_from_vision(entry["file_id"], parse_time(entry.get("captured_at")), item)
                if fact:
                    facts.append(fact)
            import time
            time.sleep(3)
        except Exception as exc:
            _append_usage(repo_root, {**base, "event": "text_only_fallback", "reason": f"vision API error: {exc}", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            continue

    return facts
