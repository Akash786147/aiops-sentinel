"""Test-lab recipes: benchmark faults per sample plus generic start-up, memory and CPU faults."""
import time
from dataclasses import replace

import pytest

from controlplane import faults
from controlplane.config import Settings
from controlplane.core import Core
from controlplane.deployer import Deployer
from controlplane.registry import register_sample


@pytest.fixture()
def core(tmp_path):
    settings = replace(Settings.from_env(), home=tmp_path, runtime="process", health_timeout_s=20, stability_window_s=0.1)
    c = Core.create(settings)
    register_sample(c, "orders")
    yield c
    c.runtime.shutdown()


def test_catalog_offers_this_services_faults_and_generic_ones(core):
    ids = {r["id"] for r in faults.catalog(core, "orders") if r["available"]}
    assert {"F01", "F02", "F08", "F10", "F12", "crash_on_start", "oom_leak", "cpu_spin"} <= ids
    assert not ids & {"F03", "F04", "F05", "F11"}
    f01 = next(r for r in faults.catalog(core, "orders") if r["id"] == "F01")
    assert f01["expect"] and f01["files"] == ["orders/repository.py"]


def test_preview_apply_and_reset(core):
    Deployer(core, guard_regression=False).deploy("orders", trigger="initial", actor="test")
    time.sleep(0.2)
    Deployer(core, guard_regression=False).promote_stable()
    diff = faults.preview(core, "orders", "F01")
    assert "+    return [{**order, \"customer\": load_customer" in diff
    ws = core.workspace("orders")
    assert faults.apply(core, "orders", "F01", actor="akash") == ["orders/repository.py"]
    assert ws.changed_files() == ["orders/repository.py"]
    assert not next(r for r in faults.catalog(core, "orders") if r["id"] == "F01")["available"]
    faults.reset(core, "orders", actor="akash")
    assert not ws.dirty()
    assert [a["action"] for a in core.store.audit_events(5, service="orders")][:2] == ["lab_reset", "lab_fault_applied"]


def test_generic_faults_change_only_the_app_module(core):
    for recipe in ("crash_on_start", "oom_leak", "cpu_spin"):
        faults.apply(core, "orders", recipe, actor="akash")
        assert core.workspace("orders").changed_files() == ["orders/app.py"]
        core.workspace("orders").discard()


def test_unknown_recipe_is_rejected(core):
    with pytest.raises(KeyError):
        faults.apply(core, "orders", "nope", actor="akash")


def test_campus_changes_are_real_code_changes_with_a_visible_effect(tmp_path):
    """slow_gatepass / gatepass_error edit the gate-pass journey's source; after Restart the traffic shape is the same but the service is not."""
    import statistics

    import httpx

    settings = replace(Settings.from_env(), home=tmp_path, runtime="process", health_timeout_s=20, stability_window_s=0.1)
    core = Core.create(settings)
    try:
        register_sample(core, "campus-api")
        good = Deployer(core, guard_regression=False).deploy("campus-api", trigger="initial", actor="test")
        catalog = {r["id"]: r for r in faults.catalog(core, "campus-api")}
        assert catalog["slow_gatepass"]["available"] and catalog["gatepass_error"]["available"]
        assert catalog["slow_gatepass"]["files"] == ["campus/gatepass.py"] and catalog["slow_gatepass"]["kind"] == "environment"
        assert "F01" not in catalog

        def p50(url):
            timings = []
            for _ in range(25):
                r = httpx.get(url + "/api/v2/gatepass", timeout=10)
                timings.append(r.elapsed.total_seconds() * 1000)
            return statistics.median(timings)

        before = p50(good["url"])
        assert "+    for step in range(41):" in faults.preview(core, "campus-api", "slow_gatepass")
        assert faults.apply(core, "campus-api", "slow_gatepass", actor="akash") == ["campus/gatepass.py"]
        bad = Deployer(core, guard_regression=False).deploy("campus-api", trigger="restart", actor="akash", message="Test lab: slow_gatepass")
        assert p50(bad["url"]) > 5 * max(before, 4.0)
        faults.reset(core, "campus-api", actor="akash")
        faults.apply(core, "campus-api", "gatepass_error", actor="akash")
        broken = Deployer(core, guard_regression=False).deploy("campus-api", trigger="restart", actor="akash", message="Test lab: gatepass_error")
        codes = {httpx.post(broken["url"] + "/api/v2/gatepass", json={}).status_code for _ in range(10)}
        assert 500 in codes
    finally:
        core.runtime.shutdown()
