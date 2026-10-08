"""Deployer: Restart = commit, build, health gate, swap; last good; rollback; one action per service at a time."""
import time
from dataclasses import replace

import httpx
import pytest

from controlplane.config import Settings
from controlplane.core import Core
from controlplane.deployer import Deployer
from controlplane.locks import Busy
from controlplane.registry import register_sample


@pytest.fixture()
def core(tmp_path):
    settings = replace(Settings.from_env(), home=tmp_path, runtime="process", health_timeout_s=20, stability_window_s=0.5)
    c = Core.create(settings)
    yield c
    c.runtime.shutdown()


@pytest.fixture()
def deployer(core):
    failures = []
    d = Deployer(core, on_failure=lambda *args, **kw: failures.append((args, kw)), guard_regression=False)
    d.failures = failures
    return d


def health(dep):
    return httpx.get(dep["url"] + "/health", timeout=3).status_code


def test_initial_deploy_is_healthy_and_current(core, deployer):
    register_sample(core, "orders")
    dep = deployer.deploy("orders", trigger="initial", actor="test")
    assert dep["status"] == "healthy" and health(dep) == 200
    assert core.store.current_deployment("orders")["id"] == dep["id"]
    assert [a["action"] for a in core.store.audit_events(10, service="orders")][:2] == ["deployed", "deploy_started"]


def test_restart_commits_the_change_and_replaces_the_instance(core, deployer):
    register_sample(core, "orders")
    first = deployer.deploy("orders", trigger="initial", actor="test")
    ws = core.workspace("orders")
    ws.write("orders/pricing.py", ws.read("orders/pricing.py").replace("GOLD_DISCOUNT = 0.10", "GOLD_DISCOUNT = 0.15"))
    second = deployer.deploy("orders", trigger="restart", actor="akash")
    assert second["status"] == "healthy" and second["commit"] != first["commit"] and not ws.dirty()
    assert core.store.get_deployment(first["id"])["status"] == "superseded"
    assert core.runtime.status(first["instance"]).running is False and health(second) == 200


def test_failed_health_gate_keeps_the_previous_instance_serving(core, deployer):
    register_sample(core, "orders")
    good = deployer.deploy("orders", trigger="initial", actor="test")
    ws = core.workspace("orders")
    ws.write("orders/app.py", "raise RuntimeError('missing PAYMENT_KEY')\n")
    bad = deployer.deploy("orders", trigger="restart", actor="akash")
    assert bad["status"] == "failed" and "missing PAYMENT_KEY" in bad["detail"]["logs"]
    assert core.store.current_deployment("orders")["id"] == good["id"] and health(good) == 200
    (args, kw) = deployer.failures[-1]
    assert args[0] == "orders" and kw["kind"] == "crash"


def test_build_failure_is_a_failed_deployment(core, deployer):
    register_sample(core, "orders")
    deployer.deploy("orders", trigger="initial", actor="test")
    core.workspace("orders").write("orders/pricing.py", "def broken(:\n")
    bad = deployer.deploy("orders", trigger="restart", actor="akash")
    assert bad["status"] == "failed" and "pricing.py" in bad["detail"]["build_log"]
    assert deployer.failures[-1][1]["kind"] == "build"


def test_promote_stable_after_window_then_rollback_restores_last_good(core, deployer):
    register_sample(core, "orders")
    good = deployer.deploy("orders", trigger="initial", actor="test")
    assert deployer.promote_stable() == []  # window not elapsed yet
    time.sleep(0.6)
    assert deployer.promote_stable() == [good["id"]]
    ws = core.workspace("orders")
    original = ws.read("orders/pricing.py")
    ws.write("orders/pricing.py", original.replace("GOLD_DISCOUNT = 0.10", "GOLD_DISCOUNT = 0.5"))
    changed = deployer.deploy("orders", trigger="restart", actor="akash")
    back = deployer.rollback("orders", actor="sentinel", reason="test")
    assert back["trigger"] == "rollback" and back["image"] == good["image"] and back["status"] == "healthy"
    assert core.store.get_deployment(changed["id"])["status"] == "rolled_back"
    assert ws.read("orders/pricing.py") == original and not ws.dirty()


@pytest.mark.parametrize("guard", [True, False])
def test_a_version_cannot_become_last_good_before_the_regression_check(core, guard):
    core.settings = replace(core.settings, stability_window_s=0.1, regression_after_s=30)
    register_sample(core, "orders")
    d = Deployer(core, guard_regression=guard)
    dep = d.deploy("orders", trigger="initial", actor="test")
    time.sleep(0.3)
    promoted = d.promote_stable()
    if guard:
        assert promoted == [] and core.store.last_good("orders") is None  # waits regression_after_s + 15 s
    else:
        assert promoted == [dep["id"]]  # without the guard the bad interleaving is possible


def test_one_action_per_service_at_a_time(core, deployer):
    register_sample(core, "orders")
    with core.locks.hold("orders"), pytest.raises(Busy):
        deployer.deploy("orders", trigger="restart", actor="akash")


def test_stop_and_start(core, deployer):
    register_sample(core, "orders")
    dep = deployer.deploy("orders", trigger="initial", actor="test")
    deployer.stop("orders", actor="akash")
    assert core.runtime.status(dep["instance"]).running is False and core.store.get_service("orders")["desired"] == "stopped"
    started = deployer.start("orders", actor="akash")
    assert started["status"] == "healthy" and started["image"] == dep["image"] and health(started) == 200
