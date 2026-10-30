"""Turn a raw Unisphere API request log into an aggregated, anonymous traffic profile.

The raw log (request/response payloads, tokens, emails, user ids) stays outside the repository. The profile keeps only what a
replay service needs to look like the real application from the outside: which endpoints are called and how often, how long they take,
which status codes they return, and how load varies over the day.

    python -m environments.unisphere.build_profile <raw.json> [samples/campus-api/campus/profile.json]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

CURVE_Q = (0, 10, 25, 50, 75, 90, 95, 99, 99.9, 99.99, 100)
JOURNEYS = (("gatepass", "gatepass"), ("shuttle", "shuttle"), ("biometric", "biometric"), ("auth", "auth"), ("user", "account"),
            ("fest", "events"), ("logs", "admin"), ("menu", "app"), ("app", "app"), ("participants", "events"))
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
NUMBER = re.compile(r"/\d+(?=/|$)")


def normalise(endpoint: str) -> str:
    path = endpoint.split("?")[0]
    return NUMBER.sub("/{id}", UUID.sub("{id}", path))


def journey(path: str) -> str:
    parts = [p for p in path.split("/") if p and p not in ("api", "v1", "v2")]
    head = parts[0] if parts else "root"
    for prefix, name in JOURNEYS:
        if head.startswith(prefix):
            return name
    return "other"


def _curve(values: list[float]) -> list[float]:
    ordered = sorted(values)
    n = len(ordered)
    return [round(ordered[min(n - 1, int(q / 100 * (n - 1) + 0.5))], 2) for q in CURVE_Q]


def build_profile(rows: list[dict], min_requests: int = 20) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    hours = [0] * 24
    stamps = []
    for r in rows:
        if not r.get("timestamp") or r.get("responseTime") in (None, ""):
            continue
        groups[f"{r['requestType']} {normalise(r['endpoint'])}"].append(r)
        hours[int(r["timestamp"][11:13])] += 1
        stamps.append(r["timestamp"][:19])
    total = sum(len(v) for v in groups.values())
    kept = {k: v for k, v in groups.items() if len(v) >= min_requests}
    kept_total = sum(len(v) for v in kept.values())
    endpoints = []
    for key, items in sorted(kept.items(), key=lambda kv: -len(kv[1])):
        method, path = key.split(" ", 1)
        ms = [float(r["responseTime"]) for r in items]
        codes = Counter(r["responseCode"] for r in items)
        curve = _curve(ms)
        endpoints.append({"key": key, "method": method, "path": path, "journey": journey(path), "share": len(items) / kept_total,
                          "requests": len(items), "status": {c: round(n / len(items), 4) for c, n in codes.most_common()},
                          "latency_ms": {"p50": curve[3], "p90": curve[5], "p95": curve[6], "p99": curve[7], "max": curve[10], "curve": curve}})
    span = (datetime.fromisoformat(max(stamps)) - datetime.fromisoformat(min(stamps))).days + 1 if stamps else 0
    return {"source": {"name": "Unisphere campus API request log", "requests": total, "days": span,
                       "note": "Aggregated: no tokens, emails, user ids or payloads. Traffic shape and latency are real; any change in a replay "
                               "deployment is injected."},
            "other_share": round(1 - kept_total / total, 6) if total else 0.0, "curve_quantiles": list(CURVE_Q),
            "endpoints": endpoints, "journeys": sorted({e["journey"] for e in endpoints}),
            "hourly_load": [round(h / sum(hours), 6) for h in hours] if sum(hours) else [1 / 24] * 24}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    rows = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    out = Path(argv[1]) if len(argv) > 1 else Path("samples/campus-api/campus/profile.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    profile = build_profile(rows)
    out.write_text(json.dumps(profile, indent=1) + "\n", encoding="utf-8")
    print(f"{profile['source']['requests']} requests, {len(profile['endpoints'])} endpoints -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
