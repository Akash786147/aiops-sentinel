"""Turns telemetry, lifecycle events and alerts into incidents (one open incident per service).

Rules
* lifecycle   exit → crash; OOM flag → oom; ≥ N restarts within the window → crash_loop; unhealthy ≥ grace → unhealthy
* resources   memory ≥ 95 % of the limit, or CPU ≥ 90 % of the limit, held for ``guard_hold_s``
* regression  ``regression_after_s`` after a deployment turned healthy, ``sentinel.detection.detect`` compares it with
              the previous deployment's samples (robust z, persistence, exceedance rate)
* alerts      Alertmanager webhook payloads for a known service
Later signals attach to the open incident and can escalate its kind (e.g. crash → crash_loop).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import asdict

from controlplane import policy
from controlplane.core import Core
from sentinel.detection import detect

MAX_SIGNALS = 50
log = logging.getLogger("sentinel.detector")


class Detector:
    def __init__(self, core: Core, monitor, deployer, on_incident: Callable[[int], None] | None = None, interval: float = 5.0) -> None:
        self.core, self.monitor, self.deployer = core, monitor, deployer
        self.on_incident = on_incident or (lambda _id: None)
        self.interval = interval
        self._restarts: dict[int, int] = {}
        self._restart_times: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        self._unhealthy_since: dict[str, float] = {}
        self._guard_since: dict[tuple[str, str], float] = {}
        self._checked: set[int] = set()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    # incidents ------------------------------------------------------------------------------
    def raise_incident(self, service: str, deployment_id: int | None, kind: str, summary: str, signals: list[dict]) -> int:
        with self._lock:
            store = self.core.store
            stamped = [{**s, "at": s.get("at", time.time())} for s in signals]
            current = store.open_incident_for(service)
            if current:
                merged = (current["signals"] + stamped)[-MAX_SIGNALS:]
                update = {"signals": merged}
                if policy.SEVERITY.get(kind, 0) > policy.SEVERITY.get(current["kind"], 0) and not current.get("auto_action"):
                    update.update(kind=kind, summary=summary)
                    self.core.audit("sentinel", "incident_escalated", service=service, incident_id=current["id"], kind=kind, summary=summary)
                store.update_incident(current["id"], **update)
                policy.apply(self.core, self.deployer, current["id"])
                self.core.bus.emit("incident", store.get_incident(current["id"]))
                return current["id"]
            inc_id = store.open_incident(service, deployment_id, kind, summary, stamped)
            self.core.audit("sentinel", "incident_opened", service=service, incident_id=inc_id, kind=kind, summary=summary)
            self.core.bus.emit("incident", store.get_incident(inc_id))
            policy.apply(self.core, self.deployer, inc_id)
            self.on_incident(inc_id)
            return inc_id

    def on_deploy_failure(self, service: str, deployment: dict, kind: str, summary: str) -> int:
        detail = deployment.get("detail") or {}
        evidence = (detail.get("logs") or detail.get("build_log") or "")[-1500:]
        signal = {"kind": kind, "summary": summary, "deployment": deployment["id"], "evidence": evidence}
        return self.raise_incident(service, deployment["id"], kind, f"Deployment {deployment['id']} failed: {summary}", [signal])

    def on_alert(self, payload: dict) -> int:
        handled = 0
        for alert in payload.get("alerts", []):
            labels = alert.get("labels", {})
            service = labels.get("service") or labels.get("container_label_sentinel_service")
            if alert.get("status") != "firing" or not service or not self.core.store.get_service(service):
                continue
            dep = self.core.store.current_deployment(service)
            summary = (alert.get("annotations") or {}).get("summary") or labels.get("alertname", "alert")
            signal = {"kind": "alert", "name": labels.get("alertname"), "summary": summary, "labels": labels}
            self.raise_incident(service, dep["id"] if dep else None, "alert", f"Alert {labels.get('alertname')}: {summary}", [signal])
            handled += 1
        return handled

    # checks ---------------------------------------------------------------------------------
    def check(self, now: float | None = None) -> None:
        now = now or time.time()
        s = self.core.settings
        for svc in self.core.store.list_services():
            name = svc["name"]
            latest = self.monitor.latest(name)
            if latest and svc.get("desired", "running") == "running":
                self._lifecycle(svc, latest, now)
                self._guards(svc, latest, now)
            self._regression(name, now, s.regression_after_s)
        for incident in self.core.store.incidents(limit=50):
            if incident["status"] == "open" and incident["kind"] in policy.AUTO_KINDS and not incident.get("auto_action"):
                policy.apply(self.core, self.deployer, incident["id"])

    def _lifecycle(self, svc: dict, sample: dict, now: float) -> None:
        name, dep, s = svc["name"], sample["deployment"], self.core.settings
        seen = self._restarts.get(dep, 0)
        if sample["restarts"] > seen:
            self._restarts[dep] = sample["restarts"]
            times = self._restart_times[name]
            times.extend([now] * (sample["restarts"] - seen))
            recent = [t for t in times if now - t <= s.crash_loop_window_s]
            if len(recent) >= s.crash_loop_restarts:
                kind = "crash_loop"
            else:
                kind = "oom" if sample["oom_killed"] else "crash"
            summary = f"{name} restarted {len(recent)} time(s) in {s.crash_loop_window_s:.0f} s" + (" after an OOM kill" if sample["oom_killed"] else "")
            self.raise_incident(name, dep, kind, summary, [{"kind": kind, "restarts": sample["restarts"], "exit_code": sample.get("exit_code")}])
        elif not sample["running"]:
            kind = "oom" if sample["oom_killed"] else "crash"
            summary = f"{name} is down (" + ("killed: out of memory" if sample["oom_killed"] else f"exit code {sample.get('exit_code')}") + ")"
            self.raise_incident(name, dep, kind, summary, [{"kind": kind, "exit_code": sample.get("exit_code")}])
        if sample["running"] and sample.get("health") == "unhealthy":
            since = self._unhealthy_since.setdefault(name, now)
            if now - since >= s.unhealthy_grace_s:
                self.raise_incident(name, dep, "unhealthy", f"{name} unhealthy for {now - since:.0f} s", [{"kind": "unhealthy"}])
        else:
            self._unhealthy_since.pop(name, None)

    def _guards(self, svc: dict, sample: dict, now: float) -> None:
        s, name = self.core.settings, svc["name"]
        checks = []
        if sample.get("rss_mb") and sample.get("mem_limit_mb"):
            ratio = sample["rss_mb"] / sample["mem_limit_mb"]
            checks.append(("memory", ratio >= s.memory_guard_ratio, f"memory at {ratio:.0%} of the {sample['mem_limit_mb']:.0f} MiB limit"))
        if sample.get("cpu_percent") is not None and sample.get("cpu_limit"):
            ratio = sample["cpu_percent"] / (sample["cpu_limit"] * 100)
            checks.append(("cpu", ratio >= s.cpu_guard_ratio, f"CPU at {ratio:.0%} of the {sample['cpu_limit']} CPU limit"))
        for kind, hot, text in checks:
            key = (name, kind)
            if not hot:
                self._guard_since.pop(key, None)
                continue
            since = self._guard_since.setdefault(key, now)
            if now - since >= s.guard_hold_s:
                self.raise_incident(name, sample["deployment"], kind, f"{name}: {text} for {now - since:.0f} s",
                                    [{"kind": kind, "rss_mb": sample.get("rss_mb"), "cpu_percent": sample.get("cpu_percent")}])
                self._guard_since[key] = now  # re-arm instead of firing every tick

    def _regression(self, name: str, now: float, after_s: float) -> None:
        dep = self.core.store.current_deployment(name)
        if not dep or dep["status"] != "healthy" or not dep["healthy_at"] or dep["id"] in self._checked:
            return
        if now - dep["healthy_at"] < after_s:
            return
        self._checked.add(dep["id"])
        samples = self.monitor.series(name)
        before = [x for x in samples if x["t"] < dep["healthy_at"] and x["deployment"] != dep["id"]]
        after = [x for x in samples if x["t"] >= dep["healthy_at"] and x["deployment"] == dep["id"]]
        if len(before) < 5 or len(after) < 5:
            return
        found = detect(before[-180:] + after, dep["healthy_at"], [name], end_time=now)
        if not found:
            return
        incident = found[0]
        signals = [{**asdict(sig), "description": sig.description} for sig in incident.signals[:8]]
        summary = f"{name} regressed after deployment {dep['id']}: " + "; ".join(sig.description for sig in incident.signals[:2])
        self.raise_incident(name, dep["id"], "regression", summary, signals)

    # loop -----------------------------------------------------------------------------------
    def start(self) -> None:
        self._halt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="detector")
        self._thread.start()

    def stop(self) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._halt.wait(self.interval):
            try:
                self.check()
                self.deployer.promote_stable()
            except Exception:
                log.exception("detector check failed")
