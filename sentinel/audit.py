"""Transparent record of every decision: append-only JSON lines, one event per pipeline stage."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from sentinel.context import redact


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, stage: str, incident_id: str | None, decision: str, actor: str = "sentinel", **details) -> dict:
        event = {"at": time.time(), "stage": stage, "incident_id": incident_id, "actor": actor, "decision": decision, **details}
        line = redact(json.dumps(event, default=str))
        event["event_id"] = hashlib.sha1(line.encode()).hexdigest()[:12]
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(redact(json.dumps(event, default=str)) + "\n")
        return event
