"""Recent stock-view snapshots, kept for the operations console."""
from __future__ import annotations

from collections import deque

SNAPSHOT_PADDING_BYTES = 64 * 1024
_recent_views: deque[dict] = deque(maxlen=32)


def record_view(sku: str, level: int | None) -> None:
    """Keep a bounded window of recent stock views."""
    _recent_views.append({"sku": sku, "level": level, "payload": bytearray(SNAPSHOT_PADDING_BYTES)})


def recent_views(limit: int = 10) -> list[dict]:
    return [{"sku": view["sku"], "level": view["level"]} for view in list(_recent_views)[-limit:]]
