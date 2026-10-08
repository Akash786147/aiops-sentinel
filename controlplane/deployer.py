"""Deployments: Restart (commit, build, health gate, swap), rollback to last good, stop and start.

A new instance only replaces the old one after it passes the health gate, so a broken change never takes the
service down: the failed deployment is recorded, an incident is opened, and the previous version keeps serving.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import httpx

from controlplane.core import Core
from controlplane.runtime.base import Instance, ServiceSpec

LIVE = ("healthy", "starting")


class DeployError(RuntimeError):
    """The requested deployment cannot be made (nothing to roll back to, unknown service)."""


class Deployer:
    def __init__(self, core: Core, on_failure: Callable[..., None] | None = None, guard_regression: bool = True) -> None:
        self.core = core
        self.on_failure = on_failure or (lambda *a, **k: None)
        self.guard_regression = guard_regression

    # public actions -------------------------------------------------------------------------
    def deploy(self, service: str, trigger: str = "restart", actor: str = "user", message: str | None = None) -> dict:
        with self.core.locks.hold(service):
            return self._deploy(service, trigger, actor, message)

    def rollback(self, service: str, to: int | None = None, actor: str = "sentinel", reason: str = "") -> dict:
        with self.core.locks.hold(service):
            return self._rollback(service, to, actor, reason)

    def stop(self, service: str, actor: str = "user") -> None:
        with self.core.locks.hold(service):
            store = self.core.store
            for dep in store.deployments(service):
                if dep["status"] in LIVE and dep["instance"]:
                    self.core.runtime.stop(dep["instance"])
                    store.update_deployment(dep["id"], status="stopped", ended_at=time.time())
                    self._emit(dep["id"])
            store.update_service(service, desired="stopped")
            self.core.audit(actor, "stopped", service=service)

    def start(self, service: str, actor: str = "user") -> dict:
        with self.core.locks.hold(service):
            store = self.core.store
            previous = next((d for d in store.deployments(service) if d["image"] and d["status"] != "failed"), None)
            if previous is None:
                return self._deploy(service, "initial", actor, None)
            if previous["status"] in LIVE and previous["instance"] and self.core.runtime.status(previous["instance"]).running:
                return previous
            dep_id = store.add_deployment(service, previous["commit"], previous["message"], previous["image"], "start", status="starting")
            self.core.audit(actor, "start_requested", service=service, deployment=dep_id)
            return self._start_and_swap(service, self._spec(service), dep_id, previous["image"], actor)

    def promote_stable(self) -> list[int]:
        """A deployment that stayed healthy for the stability window, with no incident, becomes last good.

        The window is never shorter than the regression check delay (plus a margin), so a version that regresses
        is caught before it can become the rollback target.
        """
        store, now, promoted = self.core.store, time.time(), []
        s = self.core.settings
        window = max(s.stability_window_s, s.regression_after_s + 15) if self.guard_regression else s.stability_window_s
        for svc in store.list_services():
            cur = store.current_deployment(svc["name"])
            if not cur or cur["status"] != "healthy" or cur["last_good"] or not cur["healthy_at"]:
                continue
            if now - cur["healthy_at"] < window:
                continue
            incident = store.open_incident_for(svc["name"])
            if incident and incident["deployment_id"] == cur["id"]:
                continue
            store.set_last_good(cur["id"])
            self.core.audit("sentinel", "promoted_last_good", service=svc["name"], deployment=cur["id"], commit=cur["commit"][:12])
            self._emit(cur["id"])
            promoted.append(cur["id"])
        return promoted

    # internals ------------------------------------------------------------------------------
    def _spec(self, service: str) -> ServiceSpec:
        row = self.core.store.get_service(service)
        if row is None:
            raise DeployError(f"unknown service {service}")
        return ServiceSpec.from_row(row)

    def _emit(self, dep_id: int) -> None:
        self.core.bus.emit("deployment", self.core.store.get_deployment(dep_id))

    def _deploy(self, service: str, trigger: str, actor: str, message: str | None) -> dict:
        spec = self._spec(service)
        store, ws = self.core.store, self.core.workspace(service)
        sha = ws.commit(message or f"{trigger.capitalize()} by {actor}", author=actor) if ws.dirty() else ws.head()
        dep_id = store.add_deployment(service, sha, ws.subject(sha), None, trigger)
        self.core.audit(actor, "deploy_started", service=service, deployment=dep_id, commit=sha[:12], trigger=trigger)
        self._emit(dep_id)
        build = self.core.runtime.build(spec, ws.root, sha[:12])
        if not build.ok:
            return self._fail(service, dep_id, "build", "Build failed", build_log=build.log)
        store.update_deployment(dep_id, image=build.image, status="starting", detail={"build_log": build.log[-2000:]})
        return self._start_and_swap(service, spec, dep_id, build.image, actor)

    def _rollback(self, service: str, to: int | None, actor: str, reason: str) -> dict:
        store, ws = self.core.store, self.core.workspace(service)
        target = store.get_deployment(to) if to else store.last_good(service)
        if not target or not target["image"]:
            raise DeployError("no healthy version to roll back to")
        current = store.current_deployment(service)
        ws.restore(target["commit"])
        sha = ws.commit(f"Rollback to {target['commit'][:7]}" + (f": {reason}" if reason else ""), author=actor)
        dep_id = store.add_deployment(service, sha, ws.subject(sha), target["image"], "rollback", status="starting")
        self.core.audit(actor, "rollback_started", service=service, deployment=dep_id, target=target["id"], reason=reason)
        image = target["image"]
        if self.core.runtime.name == "process" and not Path(image).exists():
            build = self.core.runtime.build(self._spec(service), ws.root, sha[:12])
            image = build.image
            store.update_deployment(dep_id, image=image)
        result = self._start_and_swap(service, self._spec(service), dep_id, image, actor)
        if result["status"] == "healthy" and current and current["id"] != target["id"]:
            store.update_deployment(current["id"], status="rolled_back")
            self._emit(current["id"])
        return result

    def _start_and_swap(self, service: str, spec: ServiceSpec, dep_id: int, image: str, actor: str) -> dict:
        store, runtime = self.core.store, self.core.runtime
        instance = runtime.run(spec, image)
        store.update_deployment(dep_id, instance=instance.id, url=instance.url, status="starting")
        self._emit(dep_id)
        ok, reason, kind = self._gate(spec, instance)
        if not ok:
            logs = "\n".join(runtime.logs(instance.id, 120))
            runtime.stop(instance.id)
            return self._fail(service, dep_id, kind, reason, logs=logs)
        older = [d for d in store.deployments(service) if d["id"] != dep_id and d["status"] in LIVE]
        store.update_deployment(dep_id, status="healthy", healthy_at=time.time())
        store.update_service(service, desired="running")
        for old in older:
            if old["instance"]:
                runtime.stop(old["instance"])
            store.update_deployment(old["id"], status="superseded", ended_at=time.time())
            self._emit(old["id"])
        dep = store.get_deployment(dep_id)
        self.core.audit(actor, "deployed", service=service, deployment=dep_id, commit=dep["commit"][:12], image=image)
        self._emit(dep_id)
        return dep

    def _gate(self, spec: ServiceSpec, instance: Instance) -> tuple[bool, str, str]:
        runtime, deadline = self.core.runtime, time.time() + self.core.settings.health_timeout_s
        with httpx.Client(timeout=2.0) as client:
            while time.time() < deadline:
                status = runtime.status(instance.id)
                if status.oom_killed:
                    return False, "Killed: out of memory during start-up", "oom"
                if status.restarts > 0 or (not status.running and status.exit_code not in (None, 0)):
                    return False, f"Process exited during start-up (exit code {status.exit_code})", "crash"
                try:
                    if client.get(instance.url + spec.health_path).status_code == 200:
                        return True, "healthy", ""
                except httpx.HTTPError:
                    pass
                time.sleep(0.4)
        return False, f"Health check did not pass within {self.core.settings.health_timeout_s:.0f} s", "unhealthy"

    def _fail(self, service: str, dep_id: int, kind: str, reason: str, **detail) -> dict:
        store = self.core.store
        merged = {**(store.get_deployment(dep_id).get("detail") or {}), "reason": reason, "kind": kind, **detail}
        store.update_deployment(dep_id, status="failed", ended_at=time.time(), detail=merged)
        self.core.audit("sentinel", "deploy_failed", service=service, deployment=dep_id, kind=kind, reason=reason)
        self._emit(dep_id)
        dep = store.get_deployment(dep_id)
        self.on_failure(service, dep, kind=kind, summary=reason)
        return dep
