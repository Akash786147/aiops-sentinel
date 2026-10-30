"""Service-level root-cause ranking on RCAEval RE1 (CC-BY 4.0): Online Boutique, Sock Shop and Train Ticket with injected faults.

RE1 is metrics only (1 Hz, per-service CPU, memory, latency, ...), with the injection time and the faulty service as the label.
It has no deployments or source code, so it can test one thing: given a known change time, does Sentinel's change-aware robust
score put the faulty service first? It cannot test function-level tracing or confirming tests.

Rules fixed before any scoring; nothing is tuned on labels:

* data: the compact per-service layout (``<service>_cpu``, ``_mem``, ``_workload``, ``_latency``, ``_error``): ``simple_data.csv`` for
  Sock Shop and Train Ticket, ``data.csv`` for Online Boutique, which already has that layout
* candidates: services that have a CPU metric (the workloads that can be faulted)
* ``robust_change`` (Sentinel's method): for every metric, |median after the injection - median before| over a robust scale
  (1.4826 x MAD of the before-window, at least 5% of its median); a service scores its largest metric score
* ``latency_ratio`` (what an operator watches): median latency after / before, largest latency metric of the service
* ``random``: expected accuracy of a uniformly random ranking, min(k, N) / N
* the injection time stands in for a known deployment time; every case is scored and none are re-run

Metrics follow RCAEval: AC@k (the true service is in the top k) and Avg@5 (the mean of AC@1 to AC@5).

    python -m evaluation.external.rcaeval <RE1.zip> [--out evaluation/results/external/rcaeval_re1.json]
"""
from __future__ import annotations

import csv
import io
import json
import math
import statistics
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

METHODS = ("random", "latency_ratio", "robust_change")


@dataclass
class Case:
    system: str
    root_service: str
    fault: str
    run: int
    inject_time: int
    times: list[float]
    columns: dict[str, list[float]]

    def services(self) -> dict[str, dict[str, list[float]]]:
        out: dict[str, dict[str, list[float]]] = defaultdict(dict)
        for name, values in self.columns.items():
            service, _, metric = name.rpartition("_")
            if service:
                out[service][metric] = values
        return dict(out)


def _parse(raw: bytes) -> tuple[list[float], dict[str, list[float]]]:
    rows = csv.reader(io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    header = next(rows)
    columns: dict[str, list[float]] = {name: [] for name in header[1:]}
    times: list[float] = []
    for row in rows:
        if not row or not row[0].strip():
            continue  # rows without a timestamp cannot be placed before or after the injection
        times.append(float(row[0]))
        for name, value in zip(header[1:], row[1:], strict=False):
            columns[name].append(float(value) if value.strip() else math.nan)
    return times, columns


def iter_cases(path: Path):
    with zipfile.ZipFile(path) as z:
        for name in sorted(n for n in z.namelist() if n.endswith("/inject_time.txt")):
            parts = name.split("/")
            if len(parts) < 5:
                continue
            _, system, label, run = parts[0], parts[1], parts[2], parts[3]
            service, _, fault = label.rpartition("_")
            names = set(z.namelist())
            compact = name.replace("inject_time.txt", "simple_data.csv")
            data = compact if compact in names else name.replace("inject_time.txt", "data.csv")
            if data not in names:
                continue
            times, columns = _parse(z.read(data))
            yield Case(system, service, fault, int(run), int(float(z.read(name).decode().strip())), times, columns)


def _finite(values: list[float]) -> list[float]:
    return [v for v in values if not math.isnan(v)]


def _split(case: Case, values: list[float]) -> tuple[list[float], list[float]]:
    pre = _finite([v for t, v in zip(case.times, values, strict=False) if t < case.inject_time])
    post = _finite([v for t, v in zip(case.times, values, strict=False) if t >= case.inject_time])
    return pre, post


def _robust(case: Case, metrics: dict[str, list[float]]) -> float:
    best = 0.0
    for values in metrics.values():
        pre, post = _split(case, values)
        if len(pre) < 10 or len(post) < 10:
            continue
        med = statistics.median(pre)
        mad = statistics.median(abs(v - med) for v in pre)
        scale = max(1.4826 * mad, 0.05 * abs(med), 1e-9)
        best = max(best, abs(statistics.median(post) - med) / scale)
    return best


def _latency_ratio(case: Case, metrics: dict[str, list[float]]) -> float:
    best = 0.0
    for metric, values in metrics.items():
        if not metric.startswith("latency"):
            continue
        pre, post = _split(case, values)
        if len(pre) >= 10 and len(post) >= 10:
            best = max(best, statistics.median(post) / max(statistics.median(pre), 1e-9))
    return best


def rank(case: Case, method: str) -> list[str]:
    services = {s: m for s, m in case.services().items() if "cpu" in m}
    if method == "robust_change":
        scores = {s: _robust(case, m) for s, m in services.items()}
    elif method == "latency_ratio":
        scores = {s: _latency_ratio(case, m) for s, m in services.items()}
    else:
        raise ValueError(method)
    return sorted(scores, key=lambda s: (-scores[s], s))


def accuracy(ranks: list[int | None]) -> dict:
    n = len(ranks)
    ac = [sum(1 for r in ranks if r is not None and r <= k) / n if n else 0.0 for k in range(1, 6)]
    return {"cases": n, "ac@1": round(ac[0], 4), "ac@3": round(ac[2], 4), "avg@5": round(sum(ac) / 5, 4)}


def _expected_random(sizes: list[int]) -> dict:
    ac = [statistics.fmean(min(k, n) / n for n in sizes) if sizes else 0.0 for k in range(1, 6)]
    return {"cases": len(sizes), "ac@1": round(ac[0], 4), "ac@3": round(ac[2], 4), "avg@5": round(sum(ac) / 5, 4)}


def run(path: Path) -> dict:
    ranks: dict[str, list[tuple[str, str, int | None]]] = {m: [] for m in METHODS}
    sizes: list[tuple[str, str, int]] = []
    count = 0
    for case in iter_cases(path):
        count += 1
        candidates = [s for s, m in case.services().items() if "cpu" in m]
        sizes.append((case.system, case.fault, len(candidates)))
        for method in ("latency_ratio", "robust_change"):
            ordered = rank(case, method)
            ranks[method].append((case.system, case.fault, ordered.index(case.root_service) + 1 if case.root_service in ordered else None))
    report: dict = {"dataset": "RCAEval RE1 (CC-BY 4.0)", "cases": count, "level": "service", "no_tuning": True, "methods": {}}
    for method in METHODS:
        if method == "random":
            summary = {"all": _expected_random([n for _, _, n in sizes]),
                       "by_system": {s: _expected_random([n for sy, _, n in sizes if sy == s]) for s in sorted({x[0] for x in sizes})},
                       "by_fault": {f: _expected_random([n for _, fa, n in sizes if fa == f]) for f in sorted({x[1] for x in sizes})}}
        else:
            rows = ranks[method]
            summary = {"all": accuracy([r for _, _, r in rows]),
                       "by_system": {s: accuracy([r for sy, _, r in rows if sy == s]) for s in sorted({x[0] for x in rows})},
                       "by_fault": {f: accuracy([r for _, fa, r in rows if fa == f]) for f in sorted({x[1] for x in rows})}}
        report["methods"][method] = summary
    return report


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path("evaluation/results/external/rcaeval_re1.json")
    report = run(Path(argv[0]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"{report['cases']} cases")
    for method, m in report["methods"].items():
        a = m["all"]
        print(f"{method:14s} AC@1 {a['ac@1']:.2f}  AC@3 {a['ac@3']:.2f}  Avg@5 {a['avg@5']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
