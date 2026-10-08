"""One action per service at a time (deploy, rollback, stop, start, approve, lab apply)."""
from __future__ import annotations

import threading
from contextlib import contextmanager


class Busy(RuntimeError):
    """Another action on this service is in progress."""


class LockTable:
    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, name: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(name, threading.Lock())

    @contextmanager
    def hold(self, name: str):
        lock = self._lock(name)
        if not lock.acquire(blocking=False):
            raise Busy(f"another action on {name} is in progress")
        try:
            yield
        finally:
            lock.release()

    def busy(self, name: str) -> bool:
        return self._lock(name).locked()
