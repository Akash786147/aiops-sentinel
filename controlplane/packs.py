"""Industry policy packs: versioned, declarative rules that decide whether an action is allowed, blocked or needs a person.

A pack is a YAML file under ``environments/policies``. The decision is deterministic and always names the rule that made it;
an LLM may explain or propose, it never decides permission. Packs here are demonstration policies, not any organisation's real ones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

POLICIES_DIR = Path(__file__).resolve().parents[1] / "environments" / "policies"
AUTO_KINDS = ("crash_loop", "oom", "unhealthy", "memory")


@dataclass(frozen=True)
class Decision:
    decision: str  # allow | block | escalate
    rule: str
    reason: str
    pack: str
    version: int

    def as_dict(self) -> dict:
        return {"decision": self.decision, "rule": self.rule, "reason": self.reason, "pack": self.pack, "version": self.version}


@dataclass(frozen=True)
class Pack:
    name: str
    version: int
    description: str
    journeys: dict = field(default_factory=dict)
    actions: dict = field(default_factory=dict)
    data_handling: dict = field(default_factory=dict)

    def _d(self, decision: str, rule: str, reason: str) -> Decision:
        return Decision(decision, rule, reason, self.name, self.version)

    def decide(self, action: str, ctx: dict) -> Decision:
        rules = self.actions.get(action)
        if rules is None:
            return self._d("block", action, f"'{action}' is not an action this policy pack permits")
        if not ctx.get("evidence_sufficient", True):
            return self._d("escalate", f"{action}.evidence", "Insufficient evidence to act: a person must review")
        if action == "auto_rollback":
            kind = ctx.get("kind", "")
            if kind not in rules.get("allow_kinds", ()):
                return self._d("escalate", "auto_rollback.allow_kinds", f"'{kind}' is not an automatic-rollback condition under this pack: a person decides")
            if rules.get("require_last_good", True) and not ctx.get("has_last_good"):
                return self._d("escalate", "auto_rollback.require_last_good", "There is no known-good version to roll back to")
            return self._d("allow", "auto_rollback.allow_kinds", f"'{kind}' may be rolled back to the last good version automatically")
        if action == "approve_patch":
            approver = (ctx.get("approver") or "").strip()
            if not approver:
                return self._d("block", "approve_patch.approver", "A named approver is required")
            allowed = [a.lower() for a in rules.get("authorised_approvers", ())]
            if allowed and approver.lower() not in allowed:
                return self._d("block", "approve_patch.authorised_approvers", f"'{approver}' is not an authorised approver")
            if rules.get("require_confirming_test") and not ctx.get("confirming_tests"):
                return self._d("block", "approve_patch.require_confirming_test", "No confirming test supports this patch")
            return self._d("allow", "approve_patch", f"{approver} may approve this patch")
        if action == "scale":
            if rules.get("require_capacity_evidence", True) and not ctx.get("capacity_evidence"):
                return self._d("block", "scale.require_capacity_evidence", "No capacity evidence: investigate instead of scaling")
            if not rules.get("automatic", False):
                return self._d("escalate", "scale.automatic", "Scaling is never automatic under this pack: a person approves it")
            return self._d("allow", "scale", "Capacity evidence supports scaling")
        return self._d("block", action, f"no rule implements '{action}'")

    def slo_status(self, samples: list[dict]) -> list[dict]:
        """Per business journey: availability (non-5xx share) and request-weighted p95 against the pack's SLO, from monitor samples."""
        out = []
        for name, spec in self.journeys.items():
            count = errors = weighted = 0.0
            for sample in samples:
                for route, stats in sample.get("routes", {}).items():
                    path = route.split(" ", 1)[-1]
                    if any(m in path for m in spec.get("match", ())):
                        count += stats["count"]
                        errors += stats["errors"]
                        weighted += stats["count"] * stats.get("p95_ms", 0.0)
            row = {"journey": name, "requests": int(count), "slo": spec.get("availability"), "latency_p95_target_ms": spec.get("latency_p95_ms")}
            if count < spec.get("min_requests", 20):
                out.append({**row, "availability": None, "p95_ms": None, "breached": None, "reason": "not enough requests"})
                continue
            availability, p95 = 1 - errors / count, weighted / count
            breached = availability < spec.get("availability", 0.0) or p95 > spec.get("latency_p95_ms", float("inf"))
            out.append({**row, "availability": round(availability, 4), "p95_ms": round(p95, 1), "breached": bool(breached), "reason": ""})
        return out


def load(path: Path) -> Pack:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Pack(raw["name"], int(raw["version"]), raw.get("description", ""), raw.get("journeys") or {}, raw.get("actions") or {},
                raw.get("data_handling") or {})


DEFAULT = Pack("default", 1, "Built-in default pack (demonstration): the platform's original behaviour.", {}, {
    "auto_rollback": {"allow_kinds": list(AUTO_KINDS), "require_last_good": True},
    "approve_patch": {"authorised_approvers": [], "require_confirming_test": False},
    "scale": {"require_capacity_evidence": True, "automatic": False}}, {})


def for_service(svc: dict, directory: Path = POLICIES_DIR) -> Pack:
    """The pack named after the service's package (``campus.yml`` for the campus API); the default when there is none."""
    path = Path(directory) / f"{svc.get('package') or svc['name']}.yml"
    return load(path) if path.is_file() else DEFAULT
