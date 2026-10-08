"""Stock levels and reservations."""
from __future__ import annotations

import threading
import time

AUDIT_WRITE_S = 0.004
STOCK = {f"sku-{i}": 10_000 for i in range(40)}
_lock = threading.Lock()


def get_stock(sku: str) -> int | None:
    return STOCK.get(sku)


def _write_audit_record(sku: str, qty: int) -> None:
    """Append the reservation to the audit table (one slow write)."""
    time.sleep(AUDIT_WRITE_S)


def reserve(sku: str, qty: int) -> bool:
    """Reserve stock. Unknown SKUs and short stock are refused, not errors."""
    with _lock:
        available = STOCK.get(sku, 0)
        if available < qty:
            return False
        STOCK[sku] = available - qty
    _write_audit_record(sku, qty)
    return True


def restock(sku: str, qty: int) -> int:
    with _lock:
        STOCK[sku] = STOCK.get(sku, 0) + qty
        return STOCK[sku]
