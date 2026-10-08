"""Sentinel control plane: HTTP API, live event stream, Alertmanager webhook, Prometheus metrics and the web UI."""
from __future__ import annotations

import json
import logging
import os
import platform
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import psutil
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest
from pydantic import BaseModel, Field

from controlplane import faults
from controlplane.config import Settings
from controlplane.core import Core
from controlplane.deployer import Deployer, DeployError
from controlplane.detector import Detector
from controlplane.investigator import Investigator, NotApprovable
from controlplane.locks import Busy
from controlplane.monitor import Monitor
from controlplane.registry import register_git, register_sample
from controlplane.runtime.base import Runtime
from controlplane.traffic import Traffic
from panel.paths import DEFAULT as PANEL_PATHS
from panel.results import load_results

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("sentinel.app")
LIVE = ("healthy", "starting")


class Actor(BaseModel):
    actor: str = Field(default="user", max_length=60)
    message: str | None = Field(default=None, max_length=200)
    to: int | None = None


class AddService(BaseModel):
    kind: str = "sample"
    name: str = Field(min_length=2, max_length=31)
    url: str | None = None
    branch: str | None = None
    mem_limit_mb: int | None = Field(default=None, ge=32, le=8192)
    cpu_limit: float | None = Field(default=None, gt=0, le=8)
    actor: str = "user"


class ServicePatch(BaseModel):
    mem_limit_mb: int | None = Field(default=None, ge=32, le=8192)
    cpu_limit: float | None = Field(default=None, gt=0, le=8)
    auto_rollback: bool | None = None
    owner: str | None = Field(default=None, max_length=60)


class FileWrite(BaseModel):
    path: str
    content: str = Field(max_length=400_000)
    actor: str = "user"


class Recipe(BaseModel):
    recipe: str
    actor: str = "user"


class Decision(BaseModel):
    approver: str = Field(default="", max_length=60)
    actor: str = "user"
    note: str = Field(default="", max_length=300)


class TrafficToggle(BaseModel):
    enabled: bool


def create_app(settings: Settings | None = None, runtime: Runtime | None = None, start_background: bool = True,
               bootstrap: tuple[str, ...] | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    core = Core.create(settings, runtime)
    monitor = Monitor(core, interval=float(os.getenv("SENTINEL_MONITOR_INTERVAL_S", "1")))
    holder: dict = {}
    deployer = Deployer(core, on_failure=lambda svc, dep, kind, summary: holder["detector"].on_deploy_failure(svc, dep, kind=kind, summary=summary))
    investigator = Investigator(core, monitor, deployer, use_llm=os.getenv("SENTINEL_USE_LLM", "1") != "0",
                                dense=os.getenv("SENTINEL_DENSE", "1") != "0")
    investigations = ThreadPoolExecutor(max_workers=2, thread_name_prefix="investigate")
    jobs = ThreadPoolExecutor(max_workers=4, thread_name_prefix="job")

    def investigate(inc_id: int) -> None:
        def run():
            try:
                investigator.investigate(inc_id)
            except Exception:
                log.exception("investigation of incident %s failed", inc_id)
        investigations.submit(run)

    detector = Detector(core, monitor, deployer, on_incident=investigate)
    holder["detector"] = detector
    traffic = Traffic(core)
    registry = CollectorRegistry()
    gauges = {
        "open": Gauge("sentinel_open_incidents", "Open incidents", ["service"], registry=registry),
        "up": Gauge("sentinel_service_up", "1 when the service's current deployment is healthy", ["service"], registry=registry),
        "deploys": Gauge("sentinel_deployments", "Deployments by status", ["service", "status"], registry=registry),
        "rollbacks": Gauge("sentinel_auto_rollbacks", "Automatic rollbacks", ["service"], registry=registry),
    }
    samples = tuple(s.strip() for s in os.getenv("SENTINEL_BOOTSTRAP", "orders,inventory,payments").split(",") if s.strip()) if bootstrap is None else bootstrap

    def submit(service: str, fn, *args, **kwargs) -> dict:
        if core.store.get_service(service) is None:
            raise HTTPException(404, f"unknown service {service}")
        if core.locks.busy(service):
            raise HTTPException(409, f"another action on {service} is in progress")

        def run():
            try:
                fn(*args, **kwargs)
            except (Busy, DeployError) as exc:
                core.audit("sentinel", "action_refused", service=service, reason=str(exc))
            except Exception as exc:  # noqa: BLE001 - surfaced in the audit trail
                core.audit("sentinel", "action_failed", service=service, error=f"{type(exc).__name__}: {exc}")
        jobs.submit(run)
        return {"accepted": True, "service": service}

    def start_or_adopt() -> None:
        for name in samples:
            if core.store.get_service(name) is None and (settings.samples_dir / name / "sentinel.json").exists():
                register_sample(core, name)
        for svc in core.store.list_services():
            if svc.get("desired", "running") != "running":
                continue
            current = core.store.current_deployment(svc["name"])
            if current and current["instance"] and core.runtime.status(current["instance"]).running:
                core.audit("sentinel", "adopted", service=svc["name"], deployment=current["id"])
                continue
            jobs.submit(lambda n=svc["name"]: _safe(lambda: deployer.start(n, actor="sentinel")))

    def _safe(fn) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            core.audit("sentinel", "action_failed", error=f"{type(exc).__name__}: {exc}")

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_background:
            start_or_adopt()
            monitor.start()
            detector.start()
            if os.getenv("SENTINEL_TRAFFIC", "1") == "1":
                traffic.start()
        yield
        traffic.stop()
        detector.stop()
        monitor.stop()
        jobs.shutdown(wait=False, cancel_futures=True)
        investigations.shutdown(wait=False, cancel_futures=True)
        if core.runtime.name == "process":
            core.runtime.shutdown()

    app = FastAPI(title="AIOps Sentinel", version="2.0", lifespan=lifespan)
    app.state.core = core
    app.state.deployer, app.state.detector, app.state.monitor, app.state.investigator = deployer, detector, monitor, investigator

    def service_view(svc: dict) -> dict:
        name = svc["name"]
        deps = core.store.deployments(name, limit=10)
        current = next((d for d in deps if d["status"] in LIVE), None)
        latest = monitor.latest(name)
        return {**svc, "current": current, "last_good": core.store.last_good(name), "busy": core.locks.busy(name),
                "incident": core.store.open_incident_for(name), "latest": Monitor._slim(latest) if latest else None,
                "dirty": core.workspace(name).dirty() if core.workspace(name).exists() else False}

    def need(name: str) -> dict:
        svc = core.store.get_service(name)
        if svc is None:
            raise HTTPException(404, f"unknown service {name}")
        return svc

    # overview & services ------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/overview")
    def overview() -> dict:
        vm = psutil.virtual_memory()
        return {"host": {"name": platform.node(), "cpu_percent": psutil.cpu_percent(interval=None), "cpus": psutil.cpu_count(),
                         "mem_used_mb": round((vm.total - vm.available) / 2**20), "mem_total_mb": round(vm.total / 2**20),
                         "load": os.getloadavg() if hasattr(os, "getloadavg") else None},
                "runtime": core.runtime.name, "services": [service_view(s) for s in core.store.list_services()],
                "open_incidents": len([i for i in core.store.incidents(limit=200) if i["status"] not in ("resolved", "dismissed")]),
                "traffic": traffic.status(),
                "links": {"grafana": settings.grafana_url, "prometheus": settings.prometheus_url, "alertmanager": settings.alertmanager_url},
                "samples": sorted(p.name for p in settings.samples_dir.iterdir() if (p / "sentinel.json").exists())}

    @app.get("/api/services")
    def services() -> list[dict]:
        return [service_view(s) for s in core.store.list_services()]

    @app.post("/api/services")
    def add_service(body: AddService) -> dict:
        try:
            if body.kind == "sample":
                svc = register_sample(core, body.name, mem_limit_mb=body.mem_limit_mb, cpu_limit=body.cpu_limit)
            elif body.kind == "git" and body.url:
                svc = register_git(core, body.name, body.url, body.branch, mem_limit_mb=body.mem_limit_mb, cpu_limit=body.cpu_limit)
            else:
                raise ValueError("kind must be 'sample' or 'git' (with url)")
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from None
        submit(svc["name"], deployer.deploy, svc["name"], trigger="initial", actor=body.actor)
        return svc

    @app.get("/api/services/{name}")
    def service(name: str) -> dict:
        svc = need(name)
        return {**service_view(svc), "deployments": core.store.deployments(name, limit=30)}

    @app.patch("/api/services/{name}")
    def update_service(name: str, body: ServicePatch) -> dict:
        need(name)
        fields = body.model_dump(exclude_none=True)
        core.store.update_service(name, **fields)
        core.audit("user", "settings_changed", service=name, **fields)
        return core.store.get_service(name)

    @app.post("/api/services/{name}/{action}", status_code=202)
    def act(name: str, action: str, body: Actor) -> dict:
        need(name)
        if action == "restart":
            return submit(name, deployer.deploy, name, trigger="restart", actor=body.actor, message=body.message)
        if action == "rollback":
            return submit(name, deployer.rollback, name, to=body.to, actor=body.actor, reason="manual rollback")
        if action == "stop":
            return submit(name, deployer.stop, name, actor=body.actor)
        if action == "start":
            return submit(name, deployer.start, name, actor=body.actor)
        raise HTTPException(404, f"unknown action {action}")

    @app.get("/api/services/{name}/series")
    def series(name: str, seconds: float = Query(600, ge=10, le=3600)) -> list[dict]:
        need(name)
        return [Monitor._slim(s) for s in monitor.series(name, since=time.time() - seconds)]

    @app.get("/api/services/{name}/logs")
    def logs(name: str, tail: int = Query(200, ge=10, le=2000)) -> dict:
        need(name)
        current = next((d for d in core.store.deployments(name, limit=10) if d["instance"]), None)
        return {"deployment": current["id"] if current else None, "lines": core.runtime.logs(current["instance"], tail) if current else []}

    # code -----------------------------------------------------------------------------------
    @app.get("/api/services/{name}/files")
    def files(name: str) -> dict:
        need(name)
        ws = core.workspace(name)
        return {"files": ws.files(), "changed": ws.changed_files()}

    @app.get("/api/services/{name}/file")
    def read_file(name: str, path: str, ref: str | None = None) -> dict:
        need(name)
        try:
            ws = core.workspace(name)
            return {"path": path, "ref": ref, "content": ws.read_at(ref, path) if ref else ws.read(path)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except FileNotFoundError:
            raise HTTPException(404, path) from None

    @app.put("/api/services/{name}/file")
    def write_file(name: str, body: FileWrite) -> dict:
        need(name)
        if core.locks.busy(name):
            raise HTTPException(409, f"another action on {name} is in progress")
        try:
            core.workspace(name).write(body.path, body.content)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        core.audit(body.actor, "file_edited", service=name, path=body.path)
        return {"saved": body.path, "changed": core.workspace(name).changed_files()}

    @app.get("/api/services/{name}/diff")
    def diff(name: str) -> dict:
        need(name)
        return {"diff": core.workspace(name).working_diff()}

    # incidents ------------------------------------------------------------------------------
    @app.get("/api/incidents")
    def incidents(service: str | None = None) -> list[dict]:
        return [{**{k: v for k, v in i.items() if k not in ("diagnosis", "patch")}, "diagnosed": bool(i["diagnosis"])}
                for i in core.store.incidents(service)]

    @app.get("/api/incidents/{inc_id}")
    def incident(inc_id: int) -> dict:
        inc = core.store.get_incident(inc_id)
        if inc is None:
            raise HTTPException(404, "unknown incident")
        dep = core.store.get_deployment(inc["deployment_id"]) if inc["deployment_id"] else None
        return {"incident": inc, "deployment": dep, "last_good": core.store.last_good(inc["service"]),
                "audit": core.store.audit_events(100, incident_id=inc_id)[::-1]}

    @app.post("/api/incidents/{inc_id}/approve")
    def approve(inc_id: int, body: Decision) -> dict:
        inc = core.store.get_incident(inc_id)
        if inc is None:
            raise HTTPException(404, "unknown incident")
        if len(body.approver.strip()) < 2:
            raise HTTPException(422, "approver name is required")
        try:
            dep = investigator.approve(inc_id, approver=body.approver.strip(), note=body.note)
        except NotApprovable as exc:
            raise HTTPException(409, str(exc)) from None
        except Busy as exc:
            raise HTTPException(409, str(exc)) from None
        return {"deployment": dep, "incident": core.store.get_incident(inc_id)}

    @app.post("/api/incidents/{inc_id}/dismiss")
    def dismiss(inc_id: int, body: Decision) -> dict:
        if core.store.get_incident(inc_id) is None:
            raise HTTPException(404, "unknown incident")
        return investigator.dismiss(inc_id, actor=body.approver or body.actor, note=body.note)

    @app.post("/api/incidents/{inc_id}/investigate", status_code=202)
    def reinvestigate(inc_id: int) -> dict:
        if core.store.get_incident(inc_id) is None:
            raise HTTPException(404, "unknown incident")
        investigate(inc_id)
        return {"accepted": True}

    # lab ------------------------------------------------------------------------------------
    @app.get("/api/lab/{name}")
    def lab(name: str) -> dict:
        need(name)
        ws = core.workspace(name)
        return {"recipes": faults.catalog(core, name), "dirty": ws.dirty(), "changed": ws.changed_files(), "diff": ws.working_diff()}

    @app.post("/api/lab/{name}/preview")
    def lab_preview(name: str, body: Recipe) -> dict:
        need(name)
        try:
            return {"diff": faults.preview(core, name, body.recipe)}
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/lab/{name}/apply")
    def lab_apply(name: str, body: Recipe) -> dict:
        need(name)
        try:
            return {"files": faults.apply(core, name, body.recipe, actor=body.actor)}
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from None
        except (ValueError, Busy) as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/lab/{name}/reset")
    def lab_reset(name: str, body: Actor) -> dict:
        need(name)
        try:
            return {"commit": faults.reset(core, name, actor=body.actor)}
        except Busy as exc:
            raise HTTPException(409, str(exc)) from None

    # alerts, audit, traffic, results ---------------------------------------------------------
    @app.post("/api/alerts")
    async def alerts(request: Request) -> dict:
        payload = await request.json()
        return {"handled": detector.on_alert(payload)}

    @app.get("/api/audit")
    def audit(limit: int = Query(100, ge=1, le=1000), service: str | None = None) -> list[dict]:
        return core.store.audit_events(limit, service=service)

    @app.get("/api/traffic")
    def traffic_status() -> dict:
        return traffic.status()

    @app.post("/api/traffic")
    def traffic_toggle(body: TrafficToggle) -> dict:
        (traffic.start if body.enabled else traffic.stop)()
        core.audit("user", "traffic_on" if body.enabled else "traffic_off")
        return traffic.status()

    @app.get("/api/results")
    def results() -> dict:
        return load_results(PANEL_PATHS)

    @app.get("/api/events")
    def events(since: int = Query(0, ge=0), once: bool = False) -> StreamingResponse:
        def stream():
            position = since
            while True:
                batch = core.bus.wait(position, timeout=10.0)
                for event in batch:
                    yield f"id: {event['n']}\ndata: {json.dumps(event, default=str)}\n\n"
                if batch:
                    position = batch[-1]["n"] + 1
                else:
                    yield ": keepalive\n\n"
                if once:
                    return

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/events/head")
    def events_head() -> dict:
        _, following = core.bus.current_run()
        return {"next": following}

    @app.get("/metrics")
    def metrics() -> Response:
        for svc in core.store.list_services():
            name = svc["name"]
            gauges["open"].labels(name).set(1 if core.store.open_incident_for(name) else 0)
            current = core.store.current_deployment(name)
            gauges["up"].labels(name).set(1 if current and current["status"] == "healthy" else 0)
            counts: dict[str, int] = {}
            for dep in core.store.deployments(name, limit=500):
                counts[dep["status"]] = counts.get(dep["status"], 0) + 1
            for status, count in counts.items():
                gauges["deploys"].labels(name, status).set(count)
            gauges["rollbacks"].labels(name).set(len([a for a in core.store.audit_events(500, service=name) if a["action"] == "auto_rollback"]))
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="ui")
    return app
