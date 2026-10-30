"""Policy packs gate the platform's real actions: the automatic rollback and the Approve button."""
from dataclasses import replace

import pytest

from controlplane import policy
from controlplane.config import Settings
from controlplane.core import Core
from controlplane.investigator import Investigator, NotApprovable, PolicyBlocked


@pytest.fixture()
def core(tmp_path):
    return Core.create(replace(Settings.from_env(), home=tmp_path, runtime="process"))


def add_service(core, name, package):
    core.store.add_service({"name": name, "source": "sample", "kind": "sample", "package": package, "module": f"{package}.app:app", "port": 8000,
                            "health_path": "/health", "metrics_path": None, "mem_limit_mb": 256, "cpu_limit": 0.5, "owner": "t", "auto_rollback": True})
    good = core.store.add_deployment(name, "a" * 40, "good", "img", "initial", status="healthy")
    core.store.update_deployment(good, instance="i-1", url="http://x")
    core.store.set_last_good(good)
    bad = core.store.add_deployment(name, "b" * 40, "bad", "img", "restart", status="healthy")
    core.store.update_deployment(bad, instance="i-2", url="http://x")
    return core.store.open_incident(name, bad, "oom", "out of memory", [])


def test_default_pack_still_rolls_back_an_oom_service(core):
    inc_id = add_service(core, "orders", "orders")
    assert policy.decide(core, core.store.get_incident(inc_id))[0] == "rollback"


def test_the_fintech_pack_leaves_even_an_oom_rollback_to_a_person_and_audits_why(core):
    inc_id = add_service(core, "payments", "fintech")  # package name selects the pack; fintech makes every rollback a human decision
    assert policy.decide(core, core.store.get_incident(inc_id))[0] == "held"
    assert policy.apply(core, None, inc_id) == "held"  # no deployer is needed: nothing is rolled back
    assert policy.apply(core, None, inc_id) == "none"  # decided once, not on every detector tick
    event = next(e for e in core.store.audit_events(10, service="payments") if e["action"] == "policy_decision")
    assert event["detail"]["decision"] == "escalate" and event["detail"]["pack"] == "fintech" and event["detail"]["rule"] == "auto_rollback.allow_kinds"
    assert "held for a person by policy fintech" in core.store.get_incident(inc_id)["auto_action"]
    assert len([e for e in core.store.audit_events(20, service="payments") if e["action"] == "policy_decision"]) == 1


def test_approve_is_limited_to_the_packs_authorised_named_approvers(core):
    add_service(core, "campus-api", "campus")
    investigator = Investigator(core, monitor=None, deployer=None, use_llm=False, dense=False)
    inc = core.store.incidents(limit=1)[0]
    with pytest.raises(PolicyBlocked) as stranger:
        investigator.authorise(inc, "mallory", confirmed=True)
    assert "not an authorised approver" in str(stranger.value) and isinstance(stranger.value, NotApprovable)
    investigator.authorise(inc, "Akash", confirmed=True)  # names are compared case-insensitively
    assert any(e["action"] == "policy_decision" and e["detail"]["decision"] == "block" for e in core.store.audit_events(10, service="campus-api"))
