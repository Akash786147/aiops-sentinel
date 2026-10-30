"""The only automatic action Sentinel takes: roll back to the last good version when a service is down or dying.

Rolled back automatically: crash loop, OOM kill, unhealthy beyond the grace period, memory exhaustion.
Never automatic: latency/CPU/error regressions, single crashes, alerts (investigate and propose instead).
At most one automatic rollback per incident; if the rollback itself fails, the incident needs a human.
"""
from __future__ import annotations

from controlplane import packs
from controlplane.core import Core
from controlplane.locks import Busy

AUTO_KINDS = {"crash_loop", "oom", "unhealthy", "memory"}
SEVERITY = {"alert": 0, "regression": 1, "cpu": 2, "stopped": 3, "crash": 3, "build": 3, "unhealthy": 4, "memory": 5, "oom": 6, "crash_loop": 7}


def evaluate(core: Core, incident: dict) -> tuple[str, str, packs.Decision | None]:
    """(action, reason, pack decision) where action is rollback | held | none. ``held`` means the service's policy pack leaves it to a person."""
    svc = core.store.get_service(incident["service"])
    if not svc or not svc["auto_rollback"]:
        return "none", "auto-rollback disabled for this service", None
    if incident["kind"] not in AUTO_KINDS:
        return "none", f"{incident['kind']} is investigated, not rolled back automatically", None
    if incident.get("auto_action"):
        return "none", "already acted on this incident", None
    current = core.store.current_deployment(incident["service"])
    if not current or current["id"] != incident["deployment_id"]:
        return "none", "the affected deployment is not the one serving traffic", None
    last_good = core.store.last_good(incident["service"])
    if not last_good:
        return "none", "no last good version yet", None
    if last_good["id"] == current["id"]:
        return "none", "the failing version is the last good one; a human must decide", None
    verdict = packs.for_service(svc).decide("auto_rollback", {"kind": incident["kind"], "has_last_good": True})
    if verdict.decision != "allow":
        return "held", verdict.reason, verdict
    return "rollback", f"roll back to deployment {last_good['id']} ({last_good['commit'][:7]})", verdict


def decide(core: Core, incident: dict) -> tuple[str, str]:
    """(action, reason) where action is rollback | held | none."""
    action, reason, _ = evaluate(core, incident)
    return action, reason


def apply(core: Core, deployer, incident_id: int) -> str:
    incident = core.store.get_incident(incident_id)
    action, reason, verdict = evaluate(core, incident)
    if action == "held":
        core.audit("sentinel", "policy_decision", service=incident["service"], incident_id=incident_id, requested="auto_rollback", **verdict.as_dict())
        core.store.update_incident(incident_id, auto_action=f"held for a person by policy {verdict.pack} v{verdict.version}: {verdict.reason}")
        core.bus.emit("incident", core.store.get_incident(incident_id))
        return "held"
    if action != "rollback":
        return "none"
    try:
        result = deployer.rollback(incident["service"], actor="sentinel", reason=f"INC-{incident_id} {incident['kind']}")
    except Busy:
        return "deferred"  # a human action is in progress; the next check tries again
    except Exception as exc:  # noqa: BLE001 - a failed mitigation must be recorded, not crash the detector
        result = {"status": "failed", "id": None, "detail": {"reason": str(exc)}}
    if result["status"] == "healthy":
        core.store.update_incident(incident_id, status="rolled_back", auto_action=f"rolled back to {result['commit'][:7]} (deployment {result['id']})")
        core.audit("sentinel", "auto_rollback", service=incident["service"], incident_id=incident_id, deployment=result["id"], reason=reason)
    else:
        core.store.update_incident(incident_id, status="needs_attention", auto_action="automatic rollback failed")
        core.audit("sentinel", "auto_rollback_failed", service=incident["service"], incident_id=incident_id, detail=(result.get("detail") or {}))
    core.bus.emit("incident", core.store.get_incident(incident_id))
    return "rolled_back" if result["status"] == "healthy" else "failed"
