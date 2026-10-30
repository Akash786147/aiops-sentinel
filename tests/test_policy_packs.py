"""Industry policy packs: deterministic allow / block / escalate decisions with the rule that decided them."""
from pathlib import Path

import pytest

from controlplane import packs

POLICIES = Path(__file__).resolve().parents[1] / "environments" / "policies"


def ctx(**kw):
    base = {"kind": "oom", "has_last_good": True, "approver": "akash", "confirming_tests": True, "capacity_evidence": False, "evidence_sufficient": True}
    return {**base, **kw}


def test_every_shipped_pack_loads_and_says_it_is_a_demonstration_policy():
    names = {p.stem for p in POLICIES.glob("*.yml")}
    assert {"campus", "ecommerce", "travel", "cloud", "fintech"} <= names
    for path in POLICIES.glob("*.yml"):
        pack = packs.load(path)
        assert pack.version >= 1 and "demonstration" in pack.description.lower()


def test_default_pack_keeps_the_original_behaviour():
    pack = packs.DEFAULT
    assert pack.decide("auto_rollback", ctx(kind="crash_loop")).decision == "allow"
    assert pack.decide("auto_rollback", ctx(kind="regression")).decision == "escalate"
    assert pack.decide("auto_rollback", ctx(has_last_good=False)).decision == "escalate"
    assert pack.decide("approve_patch", ctx(approver="anyone")).decision == "allow"


def test_a_cpu_spike_does_not_justify_scaling_and_capacity_evidence_still_needs_a_human():
    pack = packs.load(POLICIES / "campus.yml")
    blocked = pack.decide("scale", ctx(kind="cpu"))
    assert blocked.decision == "block" and "capacity" in blocked.reason
    assert pack.decide("scale", ctx(kind="cpu", capacity_evidence=True)).decision == "escalate"


def test_patches_need_an_authorised_named_approver_and_a_confirming_test():
    pack = packs.load(POLICIES / "campus.yml")
    assert pack.decide("approve_patch", ctx(approver="")).decision == "block"
    stranger = pack.decide("approve_patch", ctx(approver="mallory"))
    assert stranger.decision == "block" and "authorised" in stranger.reason and stranger.rule == "approve_patch.authorised_approvers"
    assert pack.decide("approve_patch", ctx(confirming_tests=False)).decision == "block"
    assert pack.decide("approve_patch", ctx()).decision == "allow"


def test_insufficient_evidence_escalates_instead_of_inventing_a_cause():
    pack = packs.load(POLICIES / "campus.yml")
    decision = pack.decide("auto_rollback", ctx(evidence_sufficient=False))
    assert decision.decision == "escalate" and "insufficient" in decision.reason.lower()


def test_the_fintech_pack_makes_every_rollback_a_human_decision():
    pack = packs.load(POLICIES / "fintech.yml")
    decision = pack.decide("auto_rollback", ctx(kind="crash_loop"))
    assert decision.decision == "escalate" and decision.pack == "fintech" and decision.version >= 1


def test_unknown_actions_are_blocked_not_allowed():
    assert packs.DEFAULT.decide("delete_everything", ctx()).decision == "block"


def test_slo_status_per_journey_with_enough_traffic_only():
    pack = packs.load(POLICIES / "campus.yml")
    samples = [{"routes": {"GET /api/v2/gatepass": {"count": 100, "errors": 8, "p95_ms": 40.0},
                           "GET /api/v2/shuttle": {"count": 100, "errors": 0, "p95_ms": 20.0},
                           "POST /api/v2/biometric/punch": {"count": 3, "errors": 3, "p95_ms": 9.0}}}]
    status = {s["journey"]: s for s in pack.slo_status(samples)}
    assert status["gatepass"]["breached"] is True and status["gatepass"]["availability"] == pytest.approx(0.92)
    assert status["shuttle"]["breached"] is False
    assert status["biometric"]["breached"] is None and status["biometric"]["reason"] == "not enough requests"
