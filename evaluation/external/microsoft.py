"""Event-level evaluation of detectors on the Microsoft Cloud Monitoring Dataset (MIT licence).

60 expert-labelled production series (per hour or per minute) from cloud services. The data has no deployments or code, so this
evaluates detection only. Rules fixed from the series granularity alone, before any scoring; nothing is tuned on labels:

* window: 7 days of points, but at most a quarter of the series (at least 24 points); no alerts inside the first window
* ``static_threshold``: mean +/- 3 sd of the first window, alert on a single point (the fixed alert rule an operator has)
* ``rolling_zscore``: |z| >= 3 against the trailing window, 3 consecutive points
* ``robust_persistence``: Sentinel's method, median / MAD with |z| >= 6, 3 consecutive points. Two-sided, because a drop in a
  request rate is also an incident; integer-valued series get a one-unit noise floor, the others 5% of the median.

An alert is a run that reaches 3 consecutive flagged points (1 for the static rule), counted at the point it is raised. It is a true
positive when it falls inside a labelled segment or within 3 points after one; otherwise a false alarm.

    python -m evaluation.external.microsoft <dataset/data dir> [--out evaluation/results/external/microsoft.json]
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

METHODS = ("static_threshold", "rolling_zscore", "robust_persistence")
PERSISTENCE = {"static_threshold": 1, "rolling_zscore": 3, "robust_persistence": 3}
TOLERANCE = 3


@dataclass
class Series:
    name: str
    domain: str
    step: int
    values: list[float]
    labels: list[int]


@dataclass
class Result:
    points: int
    segments: int
    detected: list[bool]
    delays: list[int]
    alerts: int
    false_alarms: int
    anomaly_free: bool
    name: str = ""
    domain: str = ""


def _fill(raw: list[str]) -> list[float]:
    """Missing values carry the last observation forward (leading gaps take the first value that exists)."""
    first = next((float(v) for v in raw if v.strip()), 0.0)
    out, last = [], first
    for v in raw:
        last = float(v) if v.strip() else last
        out.append(last)
    return out


def load_series(root: Path) -> list[Series]:
    out = []
    for path in sorted(Path(root).glob("*/*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) < 3:
            continue
        stamps = [datetime.fromisoformat(r["TimeStamp"]) for r in rows]
        out.append(Series(path.stem, path.parent.name, int((stamps[1] - stamps[0]).total_seconds()),
                          _fill([r["Value"] for r in rows]), [int(r["Label"]) for r in rows]))
    return out


def segments(labels: list[int]) -> list[tuple[int, int]]:
    out, start = [], None
    for i, flag in enumerate([*labels, 0]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def window_size(n: int, step: int) -> int:
    week = 7 * 86400 // step
    return max(24, min(week, n // 4))


def _flags(s: Series, method: str) -> list[bool]:
    x, n = s.values, len(s.values)
    w = window_size(n, s.step)
    out = [False] * n
    integer = all(float(v).is_integer() for v in x)
    if method == "static_threshold":
        base = x[:w]
        mu, sd = statistics.fmean(base), statistics.pstdev(base) or 1e-9
        for i in range(w, n):
            out[i] = abs(x[i] - mu) > 3 * sd
        return out
    for i in range(w, n):
        window = x[i - w:i]
        if method == "rolling_zscore":
            mu, sd = statistics.fmean(window), statistics.pstdev(window) or 1e-9
            out[i] = abs(x[i] - mu) / sd >= 3
        else:
            med = statistics.median(window)
            mad = statistics.median(abs(v - med) for v in window)
            scale = max(1.4826 * mad, 1.0 if integer else 0.05 * abs(med), 1e-9)
            out[i] = abs(x[i] - med) / scale >= 6
    return out


def evaluate(s: Series, method: str) -> Result:
    need = PERSISTENCE[method]
    raised, run = [], 0
    for i, flag in enumerate(_flags(s, method)):
        run = run + 1 if flag else 0
        if run == need:
            raised.append(i)
    segs = segments(s.labels)
    detected, delays, hit = [], [], set()
    for start, end in segs:
        inside = [a for a in raised if start <= a <= end + TOLERANCE]
        detected.append(bool(inside))
        if inside:
            delays.append(inside[0] - start)
            hit.update(inside)
    return Result(points=len(s.values), segments=len(segs), detected=detected, delays=delays, alerts=len(raised),
                  false_alarms=len([a for a in raised if a not in hit]), anomaly_free=not segs, name=s.name, domain=s.domain)


def aggregate(results: list[Result]) -> dict:
    alerts = sum(r.alerts for r in results)
    true_alerts = alerts - sum(r.false_alarms for r in results)
    segs = sum(r.segments for r in results)
    found = sum(sum(r.detected) for r in results)
    precision = true_alerts / alerts if alerts else 0.0
    recall = found / segs if segs else 0.0
    delays = sorted(d for r in results for d in r.delays)
    quiet = [r for r in results if r.anomaly_free]
    quiet_points = sum(r.points for r in quiet)
    return {"series": len(results), "segments": segs, "alerts": alerts, "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            "median_delay_points": statistics.median(delays) if delays else None,
            "false_alarms_per_1000_points_anomaly_free": round(1000 * sum(r.false_alarms for r in quiet) / quiet_points, 4) if quiet_points else None,
            "anomaly_free_series": len(quiet)}


def split_of(name: str) -> str:
    return "A" if zlib.crc32(name.encode()) % 2 == 0 else "B"


def run(root: Path) -> dict:
    data = load_series(root)
    report = {"dataset": "microsoft/cloud-monitoring-dataset (MIT)", "series": len(data), "no_tuning": True, "methods": {}}
    for method in METHODS:
        results = [evaluate(s, method) for s in data]
        by_domain: dict[str, list[Result]] = {}
        for r in results:
            by_domain.setdefault(r.domain, []).append(r)
        report["methods"][method] = {
            "all": aggregate(results),
            "split_A": aggregate([r for r in results if split_of(r.name) == "A"]),
            "split_B": aggregate([r for r in results if split_of(r.name) == "B"]),
            "by_domain": {d: aggregate(v) for d, v in sorted(by_domain.items())}}
    return report


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("evaluation/results/external/microsoft.json")
    report = run(Path(argv[0]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    for method, m in report["methods"].items():
        a = m["all"]
        print(f"{method:20s} precision {a['precision']:.2f} recall {a['recall']:.2f} F1 {a['f1']:.2f} delay {a['median_delay_points']} pts  "
              f"false alarms/1000 pts (anomaly-free) {a['false_alarms_per_1000_points_anomaly_free']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
