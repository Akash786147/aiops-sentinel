"""Step 2: detect and attribute incidents per service.

Method: compare each signal in the window after a change (deployment or traffic shift)
with the same signal before it. A signal is anomalous when its robust z-score (median and
MAD of the baseline) is at least ``Z_THRESHOLD`` *and* the absolute change is large enough
to matter *and* this holds for at least ``PERSISTENCE`` buckets. Missing data is never an
anomaly. A naive fixed-threshold detector is kept here as the baseline it is compared with.
"""
from __future__ import annotations

import hashlib
import statistics
from dataclasses import asdict, dataclass, field
from itertools import pairwise

Z_THRESHOLD = 6.0
PERSISTENCE = 3
MIN_RATE_INCREASE = 0.3
WARMUP_S = 3.0
MIN_ROUTE_COUNT = 2

# Signal kind -> (scale floor, minimum absolute change). Floors stop a perfectly flat baseline
# from turning a 1 ms wobble into an "infinite" z-score.
FLOORS = {
    "latency": lambda base: (max(2.0, 0.05 * base), max(15.0, 0.5 * base)),
    "errors": lambda base: (0.005, 0.02),
    "cpu": lambda base: (5.0, 15.0),
    "traffic": lambda base: (max(1.0, 0.1 * base), max(5.0, 0.5 * base)),
}
MEMORY_MIN_GROWTH_MB = 10.0
MEMORY_MIN_SLOPE_MB_S = 0.3

STATIC_THRESHOLDS = {"latency_ms": 500.0, "error_rate": 0.05, "cpu_percent": 80.0, "rss_mb": 500.0}


@dataclass
class Signal:
    kind: str
    name: str
    route: str | None
    baseline: float
    observed: float
    z: float
    anomalous_buckets: int

    @property
    def description(self) -> str:
        where = f" on {self.route}" if self.route else ""
        return f"{self.kind}{where}: {self.baseline:g} -> {self.observed:g} (z={self.z:.1f}, {self.anomalous_buckets} buckets)"


@dataclass
class Incident:
    id: str
    service: str
    symptoms: list[str]
    signals: list[Signal]
    window: tuple[float, float]
    severity: float
    detector: str = "robust-z"
    notes: list[str] = field(default_factory=list)

    @property
    def routes(self) -> list[str]:
        return list(dict.fromkeys(signal.route for signal in self.signals if signal.route))

    def to_dict(self) -> dict:
        data = asdict(self)
        data["routes"] = self.routes
        return data


def split_windows(samples: list[dict], change_time: float, end_time: float | None = None) -> tuple[list[dict], list[dict]]:
    """Baseline = before the change; incident = after it. Skip warm-up after any (re)start."""
    starts: dict[str, float] = {}
    for sample in samples:
        starts.setdefault(sample["service"], sample["t"])
    baseline, incident = [], []
    for sample in samples:
        if sample["t"] < change_time:
            if sample["t"] - starts[sample["service"]] >= WARMUP_S:
                baseline.append(sample)
        elif sample["t"] >= change_time + WARMUP_S and (end_time is None or sample["t"] <= end_time):
            incident.append(sample)
    return baseline, incident


def _series(samples: list[dict], service: str) -> dict[tuple[str, str | None], list[float]]:
    """Turn raw scrapes into named numeric series for one service."""
    series: dict[tuple[str, str | None], list[float]] = {}
    for sample in samples:
        if sample["service"] != service or not sample["up"]:
            continue
        total = sum(stats["count"] for stats in sample["routes"].values())
        errors = sum(stats["errors"] for stats in sample["routes"].values())
        series.setdefault(("traffic", None), []).append(float(total))
        if total >= MIN_ROUTE_COUNT:
            series.setdefault(("errors", None), []).append(errors / total)
        if sample.get("cpu_percent") is not None:
            series.setdefault(("cpu", None), []).append(sample["cpu_percent"])
        if sample.get("rss_mb") is not None:
            series.setdefault(("memory", None), []).append(sample["rss_mb"])
        for route, stats in sample["routes"].items():
            if stats["count"] >= MIN_ROUTE_COUNT:
                series.setdefault(("latency", route), []).append(stats["p95_ms"])
                series.setdefault(("errors", route), []).append(stats["errors"] / stats["count"])
    return series


def _robust_signal(kind: str, route: str | None, base: list[float], observed: list[float]) -> Signal | None:
    if len(base) < 3 or len(observed) < PERSISTENCE:
        return None  # not enough data is "cannot conclude", never "anomaly"
    median = statistics.median(base)
    mad = 1.4826 * statistics.median(abs(value - median) for value in base)
    scale_floor, min_change = FLOORS[kind](median)
    scale = max(mad, scale_floor)
    zs = [(value - median) / scale for value in observed]
    hits = [z for z, value in zip(zs, observed) if z >= Z_THRESHOLD and value - median >= min_change]
    # A shift must be sustained: the share of buckets over the bar must rise clearly above the
    # share that already crossed it before the change (bursty signals cross it now and then).
    bar = median + max(Z_THRESHOLD * scale, min_change)
    base_rate = sum(value >= bar for value in base) / len(base)
    if len(hits) < PERSISTENCE or len(hits) / len(observed) - base_rate < MIN_RATE_INCREASE:
        return None
    return Signal(kind, f"{kind}:{route or 'service'}", route, round(median, 2), round(statistics.median(observed), 2),
                  round(statistics.median(sorted(hits)[-3:]), 1), len(hits))


def _memory_signal(base: list[float], observed: list[float]) -> Signal | None:
    """A leak is a sustained rise, not a spike: require net growth and a positive slope."""
    if len(base) < 3 or len(observed) < PERSISTENCE:
        return None
    median = statistics.median(base)
    growth = statistics.median(observed[-3:]) - median
    slopes = [(observed[j] - observed[i]) / (j - i) for i in range(len(observed)) for j in range(i + 1, len(observed))]
    slope = statistics.median(slopes) if slopes else 0.0  # Theil-Sen, MB per bucket
    if growth < MEMORY_MIN_GROWTH_MB or slope < MEMORY_MIN_SLOPE_MB_S:
        return None
    rising = sum(1 for a, b in pairwise(observed) if b >= a)
    scale = max(2.0, 1.4826 * statistics.median(abs(value - median) for value in base))
    return Signal("memory", "memory:service", None, round(median, 2), round(observed[-1], 2), round(growth / scale, 1), rising)


def detect(samples: list[dict], change_time: float, services: list[str], end_time: float | None = None) -> list[Incident]:
    baseline, after = split_windows(samples, change_time, end_time)
    incidents = []
    for service in services:
        base_series, obs_series = _series(baseline, service), _series(after, service)
        signals = []
        for key, observed in obs_series.items():
            kind, route = key
            base = base_series.get(key, [])
            signal = _memory_signal(base, observed) if kind == "memory" else _robust_signal(kind, route, base, observed)
            if signal:
                signals.append(signal)
        if not signals:
            continue
        signals.sort(key=lambda signal: signal.z, reverse=True)
        symptoms = list(dict.fromkeys(signal.kind for signal in signals))
        if symptoms == ["traffic"]:
            continue  # more traffic alone, served fine, is not an incident
        window = (min(s["t"] for s in after), max(s["t"] for s in after)) if after else (change_time, change_time)
        incident_id = "INC-" + hashlib.sha1(f"{service}{change_time}".encode()).hexdigest()[:8]
        severity = max(signal.z for signal in signals if signal.kind != "traffic")
        incidents.append(Incident(incident_id, service, symptoms, signals, window, round(severity, 1)))
    incidents.sort(key=lambda incident: incident.severity, reverse=True)
    return incidents


def detect_threshold(samples: list[dict], change_time: float, services: list[str], end_time: float | None = None) -> list[Incident]:
    """Baseline detector: classic fixed alert rules, no baseline period, no persistence."""
    _, after = split_windows(samples, change_time, end_time)
    incidents = []
    for service in services:
        signals = []
        for sample in (s for s in after if s["service"] == service):
            if not sample["up"]:
                continue
            for route, stats in sample["routes"].items():
                if stats["p95_ms"] > STATIC_THRESHOLDS["latency_ms"]:
                    signals.append(Signal("latency", f"latency:{route}", route, 0, stats["p95_ms"], 0, 1))
                if stats["count"] >= 5 and stats["errors"] / stats["count"] > STATIC_THRESHOLDS["error_rate"]:
                    signals.append(Signal("errors", f"errors:{route}", route, 0, stats["errors"] / stats["count"], 0, 1))
            if (sample.get("cpu_percent") or 0) > STATIC_THRESHOLDS["cpu_percent"]:
                signals.append(Signal("cpu", "cpu:service", None, 0, sample["cpu_percent"], 0, 1))
            if (sample.get("rss_mb") or 0) > STATIC_THRESHOLDS["rss_mb"]:
                signals.append(Signal("memory", "memory:service", None, 0, sample["rss_mb"], 0, 1))
        if signals:
            symptoms = list(dict.fromkeys(signal.kind for signal in signals))
            incidents.append(Incident(f"THR-{service}", service, symptoms, signals[:10], (change_time, change_time), float(len(signals)), "threshold"))
    incidents.sort(key=lambda incident: incident.severity, reverse=True)
    return incidents
