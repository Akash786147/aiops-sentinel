"""Real services and traffic: slow (about 1.5 minutes), so opt in with PANEL_LIVE_TEST=1."""
import os
import time

import pytest

from panel.bus import EventBus
from panel.paths import DEFAULT
from panel.runner import Runner

pytestmark = pytest.mark.skipif(not os.getenv("PANEL_LIVE_TEST"), reason="set PANEL_LIVE_TEST=1 to run live tests")


def test_live_f04_detects_and_confirms(monkeypatch):
    monkeypatch.setenv("PANEL_LIVE_SECONDS", "10")
    bus = EventBus()
    Runner(bus, DEFAULT).start("F04", "live", use_llm=False)
    deadline = time.time() + 240
    events = []
    while time.time() < deadline:
        events, _ = bus.current_run()
        if any(e["kind"] == "run" and e["data"].get("state") in ("done", "failed") for e in events):
            break
        time.sleep(0.5)
    assert events[-1]["data"]["state"] == "done", events[-1]["data"]
    kinds = [e["kind"] for e in events]
    assert {"service", "telemetry", "deploy", "stage", "result"} <= set(kinds)
    result = next(e for e in events if e["kind"] == "result")["data"]
    assert result["incident"]["service"] == "inventory" and result["action"] == "code_fix"
    assert result["tests"]["template"]["confirming"] is True
