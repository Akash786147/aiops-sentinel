"""Client for the external card gateway (simulated).

A small share of upstream calls are slow. The client gives up after ``GATEWAY_TIMEOUT_S``
and retries, so one slow upstream call costs at most one timeout.
"""
from __future__ import annotations

import random
import threading
import time

from payments import config

CONNECT_S = 0.015
UPSTREAM_FAST_S = 0.003
_rng = random.Random(7)
_rng_lock = threading.Lock()


class Connection:
    def __init__(self) -> None:
        time.sleep(CONNECT_S)  # TLS handshake with the gateway

    def send(self, amount: float) -> dict:
        with _rng_lock:
            slow = _rng.random() < config.GATEWAY_SLOW_CALL_RATE
        upstream_s = config.GATEWAY_SLOW_CALL_S if slow else UPSTREAM_FAST_S
        if upstream_s > config.GATEWAY_TIMEOUT_S:
            time.sleep(config.GATEWAY_TIMEOUT_S)
            raise TimeoutError("gateway did not answer in time")
        time.sleep(upstream_s)
        return {"status": "captured", "amount": amount}


class ConnectionPool:
    def __init__(self, size: int = 8) -> None:
        self._idle = [Connection() for _ in range(size)]
        self._lock = threading.Lock()

    def acquire(self) -> Connection:
        with self._lock:
            if self._idle:
                return self._idle.pop()
        return Connection()

    def release(self, connection: Connection) -> None:
        with self._lock:
            self._idle.append(connection)


_pool = ConnectionPool()


def charge(amount: float) -> dict:
    """Capture a payment, retrying timed-out upstream calls."""
    last_error: Exception | None = None
    for _attempt in range(config.MAX_RETRIES + 1):
        connection = _pool.acquire()
        try:
            return connection.send(amount)
        except TimeoutError as exc:
            last_error = exc
        finally:
            _pool.release(connection)
    return {"status": "declined", "reason": str(last_error)}
