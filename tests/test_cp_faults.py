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
