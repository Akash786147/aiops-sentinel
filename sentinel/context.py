"""Step 3: build the incident evidence packet before any model is asked anything.

The packet joins what telemetry saw (anomalous signals, slow/failed request samples, one
normal request per route) with what the logs saw (exceptions and their stack frames in this
service's code) and what changed (the deployment's commits and changed line ranges, from
git). It is versioned and hashed so the audit trail can say exactly what a decision used.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sentinel.detection import Incident
from sentinel.registry import Registry

PACKET_VERSION = "1.0"
SECRET = re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)([\"'\s:=]+)([^\s\"',}]+)")
CARD = re.compile(r"(?<![\d.])\d{13,19}(?![\d.])")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def redact(text: str) -> str:
    """Strip credentials and card numbers before text reaches a model, a file or the audit log."""
    return CARD.sub("[CARD]", SECRET.sub(r"\1\2[REDACTED]", text))


@dataclass
class ChangedRange:
    file: str
    start: int
    end: int
    commit: str
    message: str
    order: int  # 1 = oldest commit in the deployment
    behavioural: bool  # False when only comments/docstrings/formatting changed


@dataclass
class EvidencePacket:
    incident: dict
    service: str
    owner: str
    code_path: str
    exceptions: list[dict] = field(default_factory=list)
    slow_or_failed_requests: list[dict] = field(default_factory=list)
    exemplar_requests: list[dict] = field(default_factory=list)
    route_baselines: dict[str, dict] = field(default_factory=dict)
    changes: list[ChangedRange] = field(default_factory=list)
    commits: list[dict] = field(default_factory=list)
    version: str = PACKET_VERSION

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, default=str).encode()).hexdigest()[:16]

    def to_text(self) -> str:
        """Compact, model-facing rendering. Every line is data, not instructions."""
        lines = [f"Service: {self.service} (owner {self.owner}, code under {self.code_path}/)",
                 f"Symptoms: {', '.join(self.incident['symptoms'])}", "Anomalous signals:"]
        for signal in self.incident["signals"][:6]:
            where = f" route {signal['route']}" if signal["route"] else ""
            lines.append(f"- {signal['kind']}{where}: baseline {signal['baseline']} -> {signal['observed']} (z={signal['z']})")
        for exc in self.exceptions[:3]:
            frames = " <- ".join(f"{f['file']}:{f['line']} {f['function']}" for f in reversed(exc["frames"]))
            lines.append(f"Exception x{exc['count']}: {exc['exception']}: {exc['message']} at {frames}; request body {exc['body']}")
        for sample in self.slow_or_failed_requests[:4]:
            lines.append(f"Slow/failed request: {sample['method']} {sample['path']} body={sample['body']} -> {sample['status']} in {sample['latency_ms']} ms")
        lines.append("Deployment commits (oldest first):")
        for commit in self.commits:
            lines.append(f"- {commit['sha']} {commit['message']}: {', '.join(commit['files'])}")
        return redact("\n".join(lines))


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return tree


def behavioural_change(before: str, after: str) -> bool:
    """True when the code's syntax tree changed once comments and docstrings are ignored."""
    try:
        return ast.dump(_strip_docstrings(ast.parse(before))) != ast.dump(_strip_docstrings(ast.parse(after)))
    except SyntaxError:
        return True


def deployment_changes(root: Path, previous: str = "deploy-prev", current: str = "deploy-current") -> tuple[list[dict], list[ChangedRange]]:
    """Changed line ranges in the deployed code, each attributed to its commit with git blame."""
    commits, behavioural = [], {}
    log = _git(root, "log", "--reverse", "--format=%h%x09%s", f"{previous}..{current}").strip().splitlines()
    for order, line in enumerate(log, start=1):
        sha, message = line.split("\t", 1)
        files = [f for f in _git(root, "show", "--name-only", "--format=", sha).split() if f]
        commits.append({"sha": sha, "message": message, "files": files, "order": order})
        for file in files:
            if file.endswith(".py"):
                behavioural[(sha, file)] = behavioural_change(_git(root, "show", f"{sha}~1:{file}"), _git(root, "show", f"{sha}:{file}"))
    by_sha = {c["sha"]: c for c in commits}
    ranges, file = [], None
    for diff_line in _git(root, "diff", "-U0", previous, current, "--", "*.py").splitlines():
        if diff_line.startswith("+++ b/"):
            file = diff_line[6:]
            continue
        match = HUNK.match(diff_line)
        if not match or file is None:
            continue
        start, count = int(match.group(1)), int(match.group(2) if match.group(2) is not None else 1)
        line_count = len(_git(root, "show", f"{current}:{file}").splitlines())
        start = min(max(start, 1), line_count)
        end = min(start + max(count, 1) - 1, line_count)  # a pure deletion is pinned to the next line
        blame = _git(root, "blame", "--porcelain", "-L", f"{start},{start}", current, "--", file).split()[0]
        commit = next((c for sha, c in by_sha.items() if blame.startswith(sha)), None)
        if commit is None:  # deleted-only hunk: the surviving line is older; attribute via log of the file
            sha = _git(root, "log", "-1", "--format=%h", f"{previous}..{current}", "--", file).strip()
            commit = by_sha[sha]
        ranges.append(ChangedRange(file, start, end, commit["sha"], commit["message"], commit["order"],
                                   behavioural.get((commit["sha"], file), True)))
    return commits, ranges


def _exceptions(root: Path, service: str, window: tuple[float, float]) -> list[dict]:
    log_path = root / "logs" / f"{service}.jsonl"
    if not log_path.exists():
        return []
    grouped: dict[tuple, dict] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if not window[0] - 5 <= event["at"] <= window[1] + 5:
            continue
        top = event["frames"][-1] if event["frames"] else {}
        key = (event["exception"], top.get("file"), top.get("line"))
        entry = grouped.setdefault(key, {**{k: event[k] for k in ("exception", "message", "frames", "path", "method", "body")}, "count": 0})
        entry["count"] += 1
    return sorted(grouped.values(), key=lambda entry: entry["count"], reverse=True)


def build_packet(root: Path, registry: Registry, incident: Incident, samples: list[dict]) -> EvidencePacket:
    service = registry.get(incident.service)
    window = incident.window
    in_window = [s for s in samples if s["service"] == incident.service and window[0] - 1 <= s["t"] <= window[1] + 1]
    slow = sorted((r for s in in_window for r in s.get("samples", [])), key=lambda r: (r["status"] < 500, -r["latency_ms"]))
    exemplars: dict[str, dict] = {}
    for sample in in_window:
        for request in sample.get("exemplars", []):
            exemplars.setdefault(request["route"], request)
    baselines = {}
    for signal in incident.signals:
        if signal.route:
            baselines.setdefault(signal.route, {})[signal.kind] = {"baseline": signal.baseline, "observed": signal.observed}
    commits, changes = deployment_changes(root)
    packet = EvidencePacket(
        incident=incident.to_dict(), service=service.name, owner=service.owner, code_path=service.path,
        exceptions=_exceptions(root, service.name, window), slow_or_failed_requests=slow[:8],
        exemplar_requests=list(exemplars.values()), route_baselines=baselines, changes=changes, commits=commits,
    )
    return packet


def route_baseline_stats(samples: list[dict], service: str, route: str, before: float) -> dict:
    """Pre-change p50/p95 of one route: the budget a confirming test is written against."""
    p50s = [s["routes"][route]["p50_ms"] for s in samples if s["service"] == service and s["t"] < before and route in s["routes"]]
    p95s = [s["routes"][route]["p95_ms"] for s in samples if s["service"] == service and s["t"] < before and route in s["routes"]]
    if not p50s:
        return {}
    return {"p50_ms": sorted(p50s)[len(p50s) // 2], "p95_ms": sorted(p95s)[len(p95s) // 2]}
