"""Detector and auto-rollback policy, driven by synthetic samples and a recording deployer."""
from dataclasses import replace

import pytest

from controlplane.config import Settings
from controlplane.core import Core
from controlplane.detector import Detector
from controlplane.registry import register_sample

T0 = 1_900_000_000.0


class FakeMonitor:
    def __init__(self):
        self.rows = {}

    def add(self, sample):
        self.rows.setdefault(sample["service"], []).append(sample)

    def latest(self, service):
        rows = self.rows.get(service)
        return rows[-1] if rows else None

    def series(self, service, since=None):
        return [r for r in self.rows.get(service, []) if since is None or r["t"] >= since]


class FakeDeployer:
    def __init__(self, core, ok=True):
        self.core, self.ok, self.calls = core, ok, []

    def rollback(self, service, to=None, actor="sentinel", reason=""):
        self.calls.append((service, reason))
        dep_id = self.core.store.add_deployment(service, "r" * 40, "rollback", "img:good", "rollback", status="healthy" if self.ok else "failed")
        return self.core.store.get_deployment(dep_id)


def sample(t, *, running=True, restarts=0, oom=False, health="healthy", p95=8.0, rss=60.0, cpu=5.0, dep=2, exit_code=None):
    return {"t": t, "service": "orders", "up": running, "running": running, "restarts": restarts, "oom_killed": oom, "health": health,
            "exit_code": exit_code, "deployment": dep, "cpu_percent": cpu, "rss_mb": rss, "mem_limit_mb": 256, "cpu_limit": 0.5,
            "routes": {"GET /orders": {"count": 10, "errors": 0, "p50_ms": p95 / 2, "p95_ms": p95, "max_ms": p95}} if running else {},
            "samples": [], "exemplars": []}


@pytest.fixture()
def env(tmp_path):
    settings = replace(Settings.from_env(), home=tmp_path, runtime="process", unhealthy_grace_s=45, guard_hold_s=30,
                       regression_after_s=60, crash_loop_restarts=3)
    core = Core.create(settings)
    register_sample(core, "orders")
    good = core.store.add_deployment("orders", "g" * 40, "good", "img:good", "initial", status="superseded")
    core.store.set_last_good(good)
    bad = core.store.add_deployment("orders", "b" * 40, "bad", "img:bad", "restart", status="healthy")
    core.store.update_deployment(bad, healthy_at=T0)
    monitor, deployer, opened = FakeMonitor(), FakeDeployer(core), []
    detector = Detector(core, monitor, deployer, on_incident=opened.append)
    yield core, monitor, deployer, detector, opened, good, bad
    core.runtime.shutdown()


def kinds(core):
    return [i["kind"] for i in core.store.incidents("orders")]


def test_exit_opens_one_crash_incident_and_attaches_later_signals(env):
    core, monitor, deployer, detector, opened, _, bad = env
    monitor.add(sample(T0 + 5, running=False, exit_code=1, dep=bad))
    detector.check(now=T0 + 5)
    detector.check(now=T0 + 6)
    assert kinds(core) == ["crash"] and opened == [core.store.incidents("orders")[0]["id"]]
    assert len(core.store.incidents("orders")[0]["signals"]) >= 1
    assert deployer.calls == []  # a single crash is investigated, not rolled back


def test_crash_loop_rolls_back_to_last_good_exactly_once(env):
    core, monitor, deployer, detector, _, _good, bad = env
    for n, t in enumerate((T0 + 5, T0 + 10, T0 + 15), start=1):
        monitor.add(sample(t, restarts=n, dep=bad))
        detector.check(now=t)
    detector.check(now=T0 + 20)
    incident = core.store.incidents("orders")[0]
    assert incident["kind"] == "crash_loop" and incident["status"] == "rolled_back"
    assert len(deployer.calls) == 1 and "crash_loop" in deployer.calls[0][1]
    assert "auto_rollback" in [a["action"] for a in core.store.audit_events(20, service="orders")]


def test_oom_kill_rolls_back(env):
    core, monitor, deployer, detector, *_ , bad = env
    monitor.add(sample(T0 + 5, running=False, oom=True, exit_code=137, dep=bad))
    detector.check(now=T0 + 5)
    assert kinds(core) == ["oom"] and len(deployer.calls) == 1


def test_failed_rollback_needs_attention_and_is_not_retried(env):
    core, monitor, deployer, detector, *_, bad = env
    deployer.ok = False
    monitor.add(sample(T0 + 5, running=False, oom=True, exit_code=137, dep=bad))
    detector.check(now=T0 + 5)
    detector.check(now=T0 + 10)
    assert core.store.incidents("orders")[0]["status"] == "needs_attention" and len(deployer.calls) == 1


def test_unhealthy_only_after_grace(env):
    core, monitor, _, detector, *_, bad = env
    monitor.add(sample(T0 + 1, health="unhealthy", dep=bad))
    detector.check(now=T0 + 1)
    detector.check(now=T0 + 30)
    assert kinds(core) == []
    detector.check(now=T0 + 47)
    assert kinds(core) == ["unhealthy"]


def test_memory_guard_after_hold_time(env):
    core, monitor, deployer, detector, *_, bad = env
    monitor.add(sample(T0 + 1, rss=250, dep=bad))
    detector.check(now=T0 + 1)
    detector.check(now=T0 + 20)
    assert kinds(core) == []
    detector.check(now=T0 + 32)
    assert kinds(core) == ["memory"] and len(deployer.calls) == 1


def test_regression_of_a_new_deployment_is_investigated_not_rolled_back(env):
    core, monitor, deployer, detector, opened, good, bad = env
    assert good != bad
    for i in range(30):
        monitor.add(sample(T0 - 30 + i, p95=8.0 + (i % 3) * 0.2, dep=good))
    for i in range(62):
        monitor.add(sample(T0 + i, p95=125.0, dep=bad))
    detector.check(now=T0 + 30)
    assert kinds(core) == []  # too early: needs regression_after_s of the new version
    detector.check(now=T0 + 61)
    detector.check(now=T0 + 62)
    incident = core.store.incidents("orders")[0]
    assert kinds(core) == ["regression"] and incident["signals"][0]["kind"] == "latency"
    assert deployer.calls == [] and opened == [incident["id"]]


def test_alert_webhook_opens_or_attaches(env):
    core, _, _, detector, *_ = env
    payload = {"alerts": [{"status": "firing", "labels": {"alertname": "HighErrorRate", "service": "orders"},
                           "annotations": {"summary": "5xx above 5%"}},
                          {"status": "firing", "labels": {"alertname": "Unknown", "service": "nope"}}]}
    assert detector.on_alert(payload) == 1
    assert kinds(core) == ["alert"]
    detector.on_alert(payload)
    assert len(core.store.incidents("orders")) == 1 and len(core.store.incidents("orders")[0]["signals"]) == 2


def test_failed_deploy_opens_incident_without_rollback(env):
    core, _, deployer, detector, opened, *_ = env
    failed = core.store.add_deployment("orders", "f" * 40, "broken", None, "restart", status="failed")
    detector.on_deploy_failure("orders", core.store.get_deployment(failed), kind="crash", summary="exited during start-up")
    incident = core.store.incidents("orders")[0]
    assert incident["kind"] == "crash" and incident["deployment_id"] == failed and deployer.calls == [] and opened
