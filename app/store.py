"""Small file-backed audit store. It makes the demo inspectable without external infrastructure."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
AUDIT_PATH = DATA_DIR / "audit.jsonl"
_lock = Lock()


def now() -> str:
    return datetime.now(UTC).isoformat()


def append(event_type: str, payload: dict) -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    event = {"id": f"evt-{int(datetime.now(UTC).timestamp() * 1000)}", "at": now(), "type": event_type, **payload}
    with _lock, AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")
    return event


def recent(limit: int = 20) -> list[dict]:
    if not AUDIT_PATH.exists():
        return []
    with _lock:
        lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[-limit:]][::-1]
