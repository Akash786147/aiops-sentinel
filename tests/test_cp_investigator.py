"""Investigator: live incident → evidence packet → ranked suspects → confirming test → proposed patch → Approve."""
import time
from dataclasses import replace

import pytest

from benchmark.scenarios import by_id
from controlplane.config import Settings
from controlplane.core import Core
from controlplane.deployer import Deployer
from controlplane.investigator import Investigator, NotApprovable, parse_tracebacks
from controlplane.registry import register_sample


class SeriesMonitor:
    def __init__(self, rows):
        self.rows = rows

    def series(self, service, since=None):
        return [r for r in self.rows if since is None or r["t"] >= since]

    def latest(self, service):
        return self.rows[-1] if self.rows else None


def latency_samples(good_id, bad_id, healthy_at):
    rows = []
    for i in range(30):
        t = healthy_at - 30 + i
        rows.append({"t": t, "service": "orders", "up": True, "deployment": good_id, "cpu_percent": 5.0, "rss_mb": 60.0,
                     "routes": {"GET /orders": {"count": 10, "errors": 0, "p50_ms": 4.0, "p95_ms": 8.0, "max_ms": 9.0}},
                     "samples": [], "exemplars": [{"route": "GET /orders", "method": "GET", "path": "/orders", "query": "", "body": "",
                                                   "status": 200, "latency_ms": 4.0}]})
    for i in range(40):
        t = healthy_at + i
        slow = {"route": "GET /orders", "method": "GET", "path": "/orders", "query": "", "body": "", "status": 200, "latency_ms": 128.0}
        rows.append({"t": t, "service": "orders", "up": True, "deployment": bad_id, "cpu_percent": 6.0, "rss_mb": 61.0,
                     "routes": {"GET /orders": {"count": 10, "errors": 0, "p50_ms": 120.0, "p95_ms": 128.0, "max_ms": 130.0}},
                     "samples": [slow], "exemplars": [slow]})
    return rows


@pytest.fixture()
def core(tmp_path):
    settings = replace(Settings.from_env(), home=tmp_path, runtime="process", health_timeout_s=20, stability_window_s=0.1)
    c = Core.create(settings)
    yield c
    c.runtime.shutdown()


def deploy_fault(core, deployer, scenario_id):
    register_sample(core, "orders")
    good = deployer.deploy("orders", trigger="initial", actor="test")
    time.sleep(0.2)
    deployer.promote_stable()
    patch = by_id(scenario_id).fault.patches[0]
    ws = core.workspace("orders")
    ws.write(patch.file, ws.read(patch.file).replace(patch.old, patch.new))
    bad = deployer.deploy("orders", trigger="restart", actor="akash", message=by_id(scenario_id).fault.message)
    return good, bad


def test_regression_is_traced_confirmed_and_patched(core):
    deployer = Deployer(core, guard_regression=False)
    good, bad = deploy_fault(core, deployer, "F01")
    healthy_at = core.store.get_deployment(bad["id"])["healthy_at"]
    signals = [{"kind": "latency", "name": "latency:GET /orders", "route": "GET /orders", "baseline": 8.0, "observed": 128.0, "z": 60.0,
                "anomalous_buckets": 30}]
    inc = core.store.open_incident("orders", bad["id"], "regression", "orders regressed", signals)
    investigator = Investigator(core, SeriesMonitor(latency_samples(good["id"], bad["id"], healthy_at)), deployer, use_llm=False, dense=False)
    result = investigator.investigate(inc)
    assert result["suspects"][0]["symbol"] == "fetch_orders_with_profiles"
    assert result["tests"]["template"]["confirming"] is True
    incident = core.store.get_incident(inc)
    assert incident["status"] == "diagnosed" and incident["patch"] and incident["diagnosis"]["patch"]["applies"] is True
    assert incident["diagnosis"]["patch"]["source"] == "revert" and "orders/repository.py" in incident["diagnosis"]["patch"]["files"]

    approved = investigator.approve(inc, approver="Akash", note="ship it")
    assert approved["status"] == "healthy" and approved["trigger"] == "approve" and "INC-" in approved["message"]
    assert core.store.get_incident(inc)["status"] == "resolved"
    assert "load_customers(" in core.workspace("orders").read("orders/repository.py")
    assert "approved_fix" in [a["action"] for a in core.store.audit_events(30, service="orders")]


def test_patch_that_does_not_apply_cannot_be_approved(core):
    deployer = Deployer(core, guard_regression=False)
    _, bad = deploy_fault(core, deployer, "F01")
    inc = core.store.open_incident("orders", bad["id"], "regression", "x", [])
    core.store.update_incident(inc, status="diagnosed", patch="--- a/nope.py\n+++ b/nope.py\n@@ -1 +1 @@\n-a\n+b\n",
                               diagnosis={"patch": {"applies": False, "source": "llm", "files": ["nope.py"]}})
    with pytest.raises(NotApprovable):
        Investigator(core, SeriesMonitor([]), deployer, use_llm=False, dense=False).approve(inc, approver="Akash")


def test_crash_on_start_is_traced_from_the_traceback(core):
    deployer = Deployer(core, guard_regression=False)
    register_sample(core, "orders")
    deployer.deploy("orders", trigger="initial", actor="test")
    time.sleep(0.2)
    deployer.promote_stable()
    ws = core.workspace("orders")
    ws.write("orders/app.py", ws.read("orders/app.py").replace("app = FastAPI(title=\"orders\")",
                                                                "app = FastAPI(title=\"orders\")\nraise RuntimeError(\"missing PAYMENT_KEY\")"))
    bad = deployer.deploy("orders", trigger="restart", actor="akash", message="Read payment key at start-up")
    assert bad["status"] == "failed"
    inc = core.store.open_incident("orders", bad["id"], "crash", "failed to start", [])
    result = Investigator(core, SeriesMonitor([]), deployer, use_llm=False, dense=False).investigate(inc)
    assert result["exceptions"][0]["exception"] == "RuntimeError"
    assert result["suspects"][0]["path"] == "orders/app.py"
    assert result["tests"]["template"]["confirming"] is True


def test_parse_tracebacks_maps_container_paths_to_repo_files():
    lines = ['Traceback (most recent call last):', '  File "/usr/lib/python3/site.py", line 9, in <module>',
             '  File "/app/orders/app.py", line 12, in <module>', '    raise RuntimeError("missing PAYMENT_KEY")',
             'RuntimeError: missing PAYMENT_KEY']
    events = parse_tracebacks(lines, ["orders/app.py", "orders/pricing.py"], "orders")
    assert events[0]["exception"] == "RuntimeError" and events[0]["message"] == "missing PAYMENT_KEY"
    assert events[0]["frames"] == [{"file": "orders/app.py", "line": 12, "function": "<module>"}]
