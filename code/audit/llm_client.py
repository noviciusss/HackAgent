from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class VisionCall:
    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _load_env_file() -> dict[str, str]:
    candidate_paths = [
        os.path.join(os.getcwd(), ".env"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env")),
    ]
    env_vars: dict[str, str] = {}
    for p in candidate_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip().strip("'\"")
            except Exception:
                pass
            break
    return env_vars


def get_gemini_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    return _load_env_file().get("GEMINI_API_KEY", "").strip()


def vision_api_key() -> str:
    gemini_key = get_gemini_api_key()
    if gemini_key:
        return gemini_key
    return os.environ.get("VISION_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()


def vision_model() -> str:
    configured = os.environ.get("VISION_MODEL", "").strip()
    if configured:
        return configured
    if get_gemini_api_key():
        return "gemini-3-flash-preview"
    return "gpt-4o-mini"



def call_vision(image_bytes: bytes, prompt: str, mime_type: str = "image/png") -> VisionCall:
    """Call the configured vision provider; callers handle caching and logging."""
    key = vision_api_key()
    if not key:
        raise RuntimeError("vision API key is not configured (neither GEMINI_API_KEY nor OPENAI_API_KEY is set)")
    model = vision_model()

    # Gemini via REST
    gemini_key = get_gemini_api_key()
    if gemini_key:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ]
            }],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
                "thinkingConfig": {
                    "thinkingBudget": 0,
                },
            },
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        body = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    break
            except urllib.error.HTTPError as exc:
                err_body = ""
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")
                    if gemini_key:
                        err_body = err_body.replace(gemini_key, "[REDACTED]")
                except Exception:
                    pass
                if exc.code == 429 and attempt < 4:
                    import time
                    time.sleep(18)
                    continue
                raise RuntimeError(f"Gemini HTTP {exc.code} {exc.reason}: {err_body}") from None
            except (urllib.error.URLError, TimeoutError) as exc:
                err_msg = str(exc)
                if gemini_key:
                    err_msg = err_msg.replace(gemini_key, "[REDACTED]")
                raise RuntimeError(f"Gemini vision request failed: {err_msg}") from None
        try:
            content = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Gemini vision response did not contain expected content: {body}") from exc

        usage = body.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount", 0))
        output_tokens = int(usage.get("candidatesTokenCount", 0))
        input_rate = float(os.environ.get("VISION_INPUT_COST_PER_1M", "0.075") or 0.075)
        output_rate = float(os.environ.get("VISION_OUTPUT_COST_PER_1M", "0.30") or 0.30)
        cost = input_tokens * input_rate / 1_000_000 + output_tokens * output_rate / 1_000_000
        return VisionCall(str(content), model, "google-gemini", input_tokens, output_tokens, cost)

    # OpenAI-compatible fallback
    endpoint = os.environ.get("VISION_BASE_URL", "https://api.openai.com/v1/chat/completions").rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}", "detail": "high"}},
            ],
        }],
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise RuntimeError(f"vision request failed: {exc}") from exc
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("vision response did not contain chat content") from exc
    usage = body.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    input_rate = float(os.environ.get("VISION_INPUT_COST_PER_1M", "0") or 0)
    output_rate = float(os.environ.get("VISION_OUTPUT_COST_PER_1M", "0") or 0)
    cost = input_tokens * input_rate / 1_000_000 + output_tokens * output_rate / 1_000_000
    return VisionCall(str(content), model, "openai-compatible", input_tokens, output_tokens, cost)

