"""Ground-truth incident scenarios for the shared-server benchmark.

Every fault scenario is a realistic code change ("deployment") that breaks one service.
Because the change is known, the faulty file and lines are known, and the reverse patch is
a known-good fix: this is what lets us *score* detection, localisation and test generation.

Each deployment also contains decoy commits (harmless changes, sometimes in the same
service) so that "blame the latest commit" is a fair baseline rather than a free answer.
Control scenarios contain no fault and measure false alarms and the scaling decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Patch:
    file: str
    old: str
    new: str


@dataclass(frozen=True)
class Commit:
    message: str
    patches: tuple[Patch, ...]


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    service: str | None  # service that is broken; None for controls
    fault_class: str  # latency | cpu | memory | errors | none | capacity
    expected_action: str  # code_fix | capacity_scale | none
    fault: Commit | None
    traffic_multiplier: dict[str, int] = field(default_factory=dict)
    extra_commits: tuple[Commit, ...] = ()


def _c(message: str, file: str, old: str, new: str) -> Commit:
    return Commit(message, (Patch(file, old, new),))


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("F01", "N+1 profile lookup", "orders", "latency", "code_fix", _c(
        "Load customer profile next to each order",
        "orders/repository.py",
        "    profiles = load_customers({order[\"customer_id\"] for order in orders})\n"
        "    return [{**order, \"customer\": profiles.get(order[\"customer_id\"])} for order in orders]",
        "    return [{**order, \"customer\": load_customer(order[\"customer_id\"])} for order in orders]")),
    Scenario("F02", "Quadratic bundle-discount search", "orders", "cpu", "code_fix", _c(
        "Give bundle discount for repeated SKUs",
        "orders/pricing.py",
        "    subtotal = sum(line_total(item) for item in items)\n",
        "    subtotal = sum(line_total(item) for item in items)\n"
        "    bundle_hits = 0\n"
        "    for _round in range(20000):\n"
        "        for first in items:\n"
        "            for second in items:\n"
        "                if first is not second and first[\"sku\"] == second[\"sku\"]:\n"
        "                    bundle_hits += 1\n"
        "    subtotal -= 0.01 * min(bundle_hits, 3)\n")),
    Scenario("F03", "Unbounded view history (memory leak)", "inventory", "memory", "code_fix", _c(
        "Keep full view history for the ops console",
        "inventory/cache.py",
        "_recent_views: deque[dict] = deque(maxlen=32)",
        "_recent_views: list[dict] = []")),
    Scenario("F04", "KeyError on unknown SKU", "inventory", "errors", "code_fix", _c(
        "Simplify stock lookup in reserve",
        "inventory/store.py",
        "        available = STOCK.get(sku, 0)",
        "        available = STOCK[sku]")),
    Scenario("F05", "Gateway timeout raised 10x", "payments", "latency", "code_fix", _c(
        "Be more patient with the card gateway",
        "payments/config.py",
        "GATEWAY_TIMEOUT_S = 0.05",
        "GATEWAY_TIMEOUT_S = 0.5")),
    Scenario("F06", "Connection pool bypassed", "payments", "latency", "code_fix", _c(
        "Use a fresh gateway connection per attempt",
        "payments/gateway.py",
        "        connection = _pool.acquire()\n        try:\n            return connection.send(amount)\n"
        "        except TimeoutError as exc:\n            last_error = exc\n        finally:\n            _pool.release(connection)",
        "        connection = Connection()\n        try:\n            return connection.send(amount)\n"
        "        except TimeoutError as exc:\n            last_error = exc")),
    Scenario("F07", "Catastrophic regex backtracking", "payments", "cpu", "code_fix", _c(
        "Allow dotted QA account names",
        "payments/fraud.py",
        "_TEST_ACCOUNT = re.compile(r\"^(test|qa)[a-z0-9._-]*@example\\.com$\")",
        "_TEST_ACCOUNT = re.compile(r\"^(test|qa)([a-z0-9._-]+)*@example\\.com$\")")),
    Scenario("F08", "Full-table serialisation per request", "orders", "cpu", "code_fix", _c(
        "Include export size in the dashboard summary",
        "orders/repository.py",
        "    return {\"count\": len(ORDERS), \"recent\": [order[\"id\"] for order in ORDERS[-limit:]]}",
        "    size = sum(len(export_snapshot()) for _ in range(60))\n"
        "    return {\"count\": len(ORDERS), \"recent\": [order[\"id\"] for order in ORDERS[-limit:]], \"export_bytes\": size}")),
    Scenario("F09", "Lock held during audit write", "inventory", "latency", "code_fix", _c(
        "Write the reservation audit atomically with the stock update",
        "inventory/store.py",
        "        STOCK[sku] = available - qty\n    _write_audit_record(sku, qty)",
        "        STOCK[sku] = available - qty\n        _write_audit_record(sku, qty)")),
    Scenario("F10", "Division by zero on empty cart", "orders", "errors", "code_fix", _c(
        "Tidy average price helper",
        "orders/pricing.py",
        "    if not items:\n        return 0.0\n    return round(sum(item[\"price\"] for item in items) / len(items), 2)",
        "    return round(sum(item[\"price\"] for item in items) / len(items), 2)")),
    Scenario("F11", "Refund reason assumed present", "payments", "errors", "code_fix", _c(
        "Normalise refund reason",
        "payments/app.py",
        "    reason = (payload.get(\"reason\") or \"unspecified\").strip()",
        "    reason = payload[\"reason\"].strip()")),
    Scenario("F12", "Full table scan on order lookup", "orders", "latency", "code_fix", _c(
        "Read order through the reporting replica",
        "orders/repository.py",
        "    _query()\n    logger.debug(\"order lookup %s\", order_id)",
        "    _query(len(ORDERS) // 10)\n    logger.debug(\"order lookup %s\", order_id)")),
    # Controls: no fault. A good system stays quiet (H01, H02) or recommends capacity, not a code fix (H03).
    Scenario("H01", "Docs-only deployment", None, "none", "none", None, extra_commits=(_c(
        "Document refund API",
        "payments/app.py",
        "\"\"\"Payments service: charges and refunds.\"\"\"",
        "\"\"\"Payments service: charges and refunds.\n\nRefunds accept an optional free-text reason.\n\"\"\""),)),
    Scenario("H02", "Behaviour-neutral refactor", None, "none", "none", None, extra_commits=(_c(
        "Rename local variable in reserve",
        "inventory/store.py",
        "        if available < qty:\n            return False\n        STOCK[sku] = available - qty",
        "        if available < qty:\n            return False\n        remaining = available - qty\n        STOCK[sku] = remaining"),)),
    Scenario("H03", "Traffic surge, no code fault", None, "capacity", "capacity_scale", None, traffic_multiplier={"orders": 4}),
)

# Harmless changes mixed into each deployment. Some touch the same service as the fault.
DECOYS: tuple[Commit, ...] = (
    _c("Note finance sign-off on gold discount", "orders/pricing.py",
       "GOLD_DISCOUNT = 0.10", "GOLD_DISCOUNT = 0.10  # agreed with finance for this quarter"),
    _c("Describe the views endpoint", "inventory/app.py",
       "def views():\n    return", "def views():\n    \"\"\"Recent stock views for the operations console.\"\"\"\n    return"),
    _c("Add supported currencies", "payments/config.py",
       "CURRENCY = \"EUR\"", "CURRENCY = \"EUR\"\nSUPPORTED_CURRENCIES = (\"EUR\", \"USD\")"),
    _c("Document order summary route", "orders/app.py",
       "def order_summary():\n    return", "def order_summary():\n    \"\"\"Dashboard tile data.\"\"\"\n    return"),
    _c("Explain high-value limit", "payments/fraud.py",
       "HIGH_VALUE_EUR = 5000", "HIGH_VALUE_EUR = 5000  # card-scheme manual review limit"),
    _c("Document restock", "inventory/store.py",
       "def restock(sku: str, qty: int) -> int:\n", "def restock(sku: str, qty: int) -> int:\n    \"\"\"Add stock after a delivery.\"\"\"\n"),
    _c("Keep more request samples", "common/telemetry.py", "MAX_SAMPLES = 20", "MAX_SAMPLES = 25"),
    _c("Clarify connection cost", "payments/gateway.py",
       "CONNECT_S = 0.015", "CONNECT_S = 0.015  # measured TLS handshake time"),
    _c("Show more views by default", "inventory/cache.py",
       "def recent_views(limit: int = 10)", "def recent_views(limit: int = 12)"),
    _c("Name the customer tiers", "orders/repository.py",
       "DB_ROUND_TRIP_S = 0.002", "DB_ROUND_TRIP_S = 0.002\nCUSTOMER_TIERS = (\"standard\", \"gold\")"),
)


def by_id(scenario_id: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.id == scenario_id:
            return scenario
    raise KeyError(scenario_id)
