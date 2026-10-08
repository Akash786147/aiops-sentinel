"""In-memory ordered event log shared by the runner (writer) and SSE clients (readers)."""
from __future__ import annotations

import threading
import time


class EventBus:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._cond = threading.Condition()
        self._run_start = 0

    def emit(self, kind: str, data: dict) -> dict:
        with self._cond:
            event = {"n": len(self._events), "t": round(time.time(), 3), "kind": kind, "data": data}
            if kind == "run" and data.get("state") == "started":
                self._run_start = event["n"]
            self._events.append(event)
            self._cond.notify_all()
            return event

    def current_run(self) -> tuple[list[dict], int]:
        """Events of the latest run and the index the next event will get."""
        with self._cond:
            return list(self._events[self._run_start :]), len(self._events)

    def wait(self, since: int, timeout: float = 15.0) -> list[dict]:
        with self._cond:
            self._cond.wait_for(lambda: len(self._events) > since, timeout)
            return list(self._events[since:])
