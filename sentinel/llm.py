"""One LLM client for the pipeline: OpenAI (default), Groq or Ollama, with a response cache.

Every call is cached on disk by a hash of (provider, model, messages), so an experiment can be
re-run and re-scored without new model calls, and the exact prompt and answer behind each
decision can be audited later. Groq/Ollama run at temperature 0; GPT-5-family models do not
expose temperature, so they use a fixed seed and the cache provides repeatability.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data" / "llm_cache"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
# Reasoning models spend tokens thinking; keep that out of the answer and leave budget for it.
MODEL_OPTIONS = {
    "openai/gpt-oss-120b": {"reasoning_effort": "medium", "include_reasoning": False},
    "openai/gpt-oss-20b": {"reasoning_effort": "medium", "include_reasoning": False},
    "qwen/qwen3.8-27b": {"reasoning_format": "hidden"},
}
REASONING_TOKEN_ALLOWANCE = 3000


def load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    cached: bool


class LLMUnavailable(RuntimeError):
    pass


def _openai_key() -> str | None:
    return os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_API_KEY")


def provider() -> tuple[str, str]:
    """SENTINEL_LLM picks openai | groq | ollama; default is OpenAI when a key exists, else Groq."""
    load_dotenv()
    name = os.getenv("SENTINEL_LLM") or ("openai" if _openai_key() else "groq")
    if name == "ollama":
        return "ollama", os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    if name == "openai":
        return "openai", os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    return "groq", os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)


def available() -> bool:
    name, _ = provider()
    return name == "ollama" or bool(_openai_key() if name == "openai" else os.getenv("GROQ_API_KEY"))


def chat(messages: list[dict], json_mode: bool = False, max_tokens: int = 1200) -> LLMResult:
    name, model = provider()
    key = hashlib.sha256(json.dumps([name, model, messages, json_mode, 0], sort_keys=True).encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        data.pop("messages", None)
        return LLMResult(**{**data, "cached": True})
    started = time.perf_counter()
    if name == "groq":
        text, usage = _groq(model, messages, json_mode, max_tokens)
    elif name == "openai":
        text, usage = _openai(model, messages, json_mode, max_tokens)
    else:
        text, usage = _ollama(model, messages, json_mode, max_tokens)
    result = LLMResult(text, model, usage[0], usage[1], round(time.perf_counter() - started, 2), False)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({**result.__dict__, "cached": False, "messages": messages}), encoding="utf-8")
    return result


def _groq(model: str, messages: list[dict], json_mode: bool, max_tokens: int) -> tuple[str, tuple[int, int]]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise LLMUnavailable("GROQ_API_KEY is not set (put it in .env)")
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens + REASONING_TOKEN_ALLOWANCE,
            **MODEL_OPTIONS.get(model, {})}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    for attempt in range(6):
        response = httpx.post(GROQ_URL, json=body, headers={"Authorization": f"Bearer {api_key}"}, timeout=120)
        if response.status_code in (429, 500, 502, 503) and attempt < 5:
            time.sleep(float(response.headers.get("retry-after", 2 ** attempt)))
            continue
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage", {})
        return data["choices"][0]["message"]["content"], (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    raise LLMUnavailable("Groq kept rate-limiting")


def _openai(model: str, messages: list[dict], json_mode: bool, max_tokens: int) -> tuple[str, tuple[int, int]]:
    """GPT-5-family models are reasoning models: no temperature knob, a reasoning-effort knob instead."""
    api_key = _openai_key()
    if not api_key:
        raise LLMUnavailable("OPENAI_API_KEY is not set (put it in .env)")
    body = {"model": model, "messages": messages, "max_completion_tokens": max_tokens + REASONING_TOKEN_ALLOWANCE,
            "reasoning_effort": os.getenv("OPENAI_REASONING_EFFORT", "medium"), "seed": 7}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    for attempt in range(6):
        response = httpx.post(OPENAI_URL, json=body, headers={"Authorization": f"Bearer {api_key}"}, timeout=180)
        if response.status_code in (429, 500, 502, 503) and attempt < 5:
            time.sleep(float(response.headers.get("retry-after", 2 ** attempt)))
            continue
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage", {})
        return data["choices"][0]["message"]["content"] or "", (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    raise LLMUnavailable("OpenAI kept rate-limiting")


def _ollama(model: str, messages: list[dict], json_mode: bool, max_tokens: int) -> tuple[str, tuple[int, int]]:
    url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
    body = {"model": model, "messages": messages, "stream": False, "options": {"temperature": 0, "num_predict": max_tokens}}
    if json_mode:
        body["format"] = "json"
    try:
        data = httpx.post(url, json=body, timeout=None).json()
    except httpx.HTTPError as exc:
        raise LLMUnavailable(str(exc)) from exc
    return data["message"]["content"], (data.get("prompt_eval_count", 0), data.get("eval_count", 0))
