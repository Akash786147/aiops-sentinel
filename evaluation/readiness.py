"""Data-readiness check: what can Sentinel do with this data, and what is missing for the rest?

Point it at a sample of someone's request log, metric export or incident data (JSON, JSON lines or CSV). It reads the structure,
never prints values, and reports which pipeline stages the data can support. It is the first step of a shadow-mode pilot: no
action is taken, nothing leaves the machine.

    python -m evaluation.readiness <file> [--json]
"""
from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from datetime import datetime
from itertools import pairwise
from pathlib import Path

SAMPLE = 5000
ROLES = {  # role -> normalised column names that identify it (first match in this order wins)
    "timestamp": ("timestamp", "time", "datetime", "date", "ts", "attimestamp"),
    "route": ("endpoint", "route", "path", "url", "uri", "operation"),
    "method": ("requesttype", "method", "verb"),
    "status": ("responsecode", "statuscode", "status", "httpstatus", "code"),
    "latency": ("responsetime", "latencyms", "latency", "durationms", "duration", "elapsed"),
    "user": ("userid", "user", "account"),
    "error": ("errormessage", "error", "exception", "errormsg"),
    "service": ("service", "servicename", "application", "app", "component", "container"),
    "deployment": ("version", "deployment", "release", "commit", "build", "sha", "revision", "deployid"),
    "cpu": ("cpu", "cpupercent", "cpuusage"),
    "memory": ("memory", "mem", "rss", "memoryusage"),
    "value": ("value",),
    "label": ("label", "anomaly", "isanomaly", "groundtruth"),
    "payload": ("requestpayload", "responsepayload", "payload", "body", "requestbody", "responsebody"),
}
SENSITIVE = {"access tokens (JWT)": re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{4,}"),
             "email addresses": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
             "bearer credentials": re.compile(r"(?i)bearer\s+[\w.-]{16,}")}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _read(path: Path) -> tuple[str, list[dict], int]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            return "csv", rows[:SAMPLE], len(rows)
        text = path.read_text(encoding="utf-8")
        if suffix == ".jsonl" or (text.lstrip()[:1] == "{" and "\n{" in text):
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
            return "jsonl", rows[:SAMPLE], len(rows)
        data = json.loads(text)
        rows = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
        if rows and all(isinstance(r, dict) for r in rows):
            return "json", rows[:SAMPLE], len(rows)
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    return "unknown", [], 0


def _roles(columns: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    by_norm = {_norm(c): c for c in columns}
    for role, names in ROLES.items():
        for name in names:
            if name in by_norm:
                found[role] = by_norm[name]
                break
    return found


def _times(rows: list[dict], column: str) -> list[datetime]:
    out = []
    for r in rows:
        try:
            out.append(datetime.fromisoformat(str(r[column]).replace("Z", "")[:26]))
        except (ValueError, KeyError):
            continue
    return out


def _stages(fields: dict, fmt: str) -> list[dict]:
    has = fields.keys()
    measurable = "latency" in has or "status" in has or "value" in has
    named = "route" in has or "service" in has
    out = [{"stage": "detection", "status": "yes" if "timestamp" in has and measurable else "no",
            "reason": "time-stamped latency, status or metric values" if "timestamp" in has and measurable
            else "needs a timestamp and at least one of latency, status or a metric value"}]
    out.append({"stage": "service_attribution", "status": "yes" if named else "no",
                "reason": "services or routes are identifiable" if named else "a single unnamed series cannot say which service or route is affected"})
    if "deployment" in has:
        out.append({"stage": "change_correlation", "status": "yes", "reason": f"deployment field '{fields['deployment']}' links data to a release"})
    else:
        out.append({"stage": "change_correlation", "status": "needs input" if named else "no",
                    "reason": "no deployment or version field: supply deployment times or a git history" if named
                    else "no routes or services to attribute a change to"})
    if named:
        out.append({"stage": "function_tracing", "status": "needs input",
                    "reason": "needs the source repository at the deployed commit (the current tracer analyses Python)"})
        out.append({"stage": "confirming_tests", "status": "needs input",
                    "reason": "needs the source repository and a known-good revision to run the test against"})
    else:
        out.append({"stage": "function_tracing", "status": "no", "reason": "the data has no routes or exceptions to trace from"})
        out.append({"stage": "confirming_tests", "status": "no", "reason": "no code or request samples to build a test from"})
    slo = "status" in has and "latency" in has and named
    out.append({"stage": "slo_policy", "status": "yes" if slo else ("partial" if measurable else "no"),
                "reason": "status and latency per route support availability and latency SLOs" if slo
                else "an SLO needs success and latency per route or service" if measurable else "no measurable signal"})
    out.append({"stage": "resource_scaling", "status": "yes" if "cpu" in has or "memory" in has else "no",
                "reason": "CPU or memory is present" if "cpu" in has or "memory" in has else "no CPU or memory: scaling advice is not possible"})
    return out


def inspect(path: str | Path) -> dict:
    path = Path(path)
    fmt, rows, total = _read(path)
    if not rows:
        return {"path": path.name, "format": "unknown", "rows": 0, "fields": {}, "stages": [
            {"stage": "detection", "status": "no", "reason": "could not read structured records (JSON, JSON lines or CSV)"}],
            "privacy_warnings": [], "resolution_seconds": None, "time_range": None}
    fields = _roles(list(rows[0]))
    resolution, span = None, None
    if "timestamp" in fields:
        stamps = sorted(set(_times(rows, fields["timestamp"])))
        if len(stamps) > 1:
            resolution = statistics.median((b - a).total_seconds() for a, b in pairwise(stamps))
            span = [stamps[0].isoformat(), stamps[-1].isoformat()]
    warnings = []
    for label, pattern in SENSITIVE.items():
        if any(pattern.search(str(v)) for r in rows[:1000] for v in r.values() if isinstance(v, str)):
            warnings.append(f"{label} found in the data: redact before any model, export or audit use")
    if "user" in fields:
        warnings.append("user identifiers present: hash or drop them before sharing")
    return {"path": path.name, "format": fmt, "rows": total, "fields": fields, "time_range": span, "resolution_seconds": resolution,
            "stages": _stages(fields, fmt), "privacy_warnings": warnings}


def render(report: dict) -> str:
    lines = [f"{report['path']}: {report['format']}, {report['rows']} rows, time range {report['time_range']}, resolution {report['resolution_seconds']} s",
             "fields found: " + (", ".join(f"{k}={v}" for k, v in report["fields"].items()) or "none"), ""]
    lines += [f"  {s['stage']:20s} {s['status']:12s} {s['reason']}" for s in report["stages"]]
    lines += ["", *[f"  ! {w}" for w in report["privacy_warnings"]]]
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    result = inspect(sys.argv[1])
    print(json.dumps(result, indent=1) if "--json" in sys.argv else render(result))
