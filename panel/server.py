"""HTTP API, server-sent events and static files for the console."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from benchmark.scenarios import SCENARIOS
from panel import enrich, results
from panel.bus import EventBus
from panel.paths import DEFAULT, Paths
from panel.runner import Busy, NotReady, Runner, Unavailable
from sentinel import llm
from sentinel.registry import load_registry

STATIC = Path(__file__).parent / "static"
TERMINAL = ("done", "failed")


class RunRequest(BaseModel):
    scenario: str
    mode: Literal["live", "replay"] = "replay"
    llm: bool = True
    seed: int = Field(default=0, ge=0, le=9)


class ApproveRequest(BaseModel):
    approver: str = Field(min_length=2, max_length=60)
    note: str = Field(default="", max_length=300)


def create_app(paths: Paths = DEFAULT, speed: float = 3.0) -> FastAPI:
    app = FastAPI(title="Sentinel Console")
    bus = EventBus()
    runner = Runner(bus, paths, speed)
    registry = load_registry(paths.root / "shared_server")

    @app.get("/api/scenarios")
    def scenarios() -> list[dict]:
        return [{"id": s.id, "title": s.title, "service": s.service, "fault_class": s.fault_class, "expected_action": s.expected_action,
                 "replay_available": runner.replay_available(s.id, 0), "code_available": (paths.bench / f"{s.id}-s0").exists()}
                for s in SCENARIOS]

    @app.post("/api/run")
    def run(request: RunRequest) -> dict:
        try:
            return runner.start(request.scenario, request.mode, request.llm, request.seed)
        except KeyError:
            raise HTTPException(404, f"unknown scenario {request.scenario}") from None
        except Busy as exc:
            raise HTTPException(409, str(exc)) from None
        except Unavailable as exc:
            raise HTTPException(503, str(exc)) from None

    @app.get("/api/state")
    def state() -> dict:
        events, following = bus.current_run()
        return {"run": runner.public(), "events": events, "next": following, "server": registry.server,
                "tenants": [{"name": s.name, "owner": s.owner, "port": s.port} for s in registry.services],
                "llm_available": llm.available()}

    @app.get("/api/events")
    def events(since: int = Query(0, ge=0), until_done: bool = False) -> StreamingResponse:
        def stream():
            position = since
            while True:
                batch = bus.wait(position, timeout=10.0)
                for event in batch:
                    yield f"id: {event['n']}\ndata: {json.dumps(event)}\n\n"
                if not batch:
                    yield ": keepalive\n\n"
                    continue
                position = batch[-1]["n"] + 1
                if until_done and any(e["kind"] == "run" and e["data"].get("state") in TERMINAL for e in batch):
                    return

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/results")
    def benchmark_results() -> dict:
        return results.load_results(paths)

    @app.get("/api/code")
    def code(path: str, run: str | None = None) -> dict:
        workspace = runner.workspace(run)
        if workspace is None or not workspace.exists():
            raise HTTPException(404, "no workspace for this run")
        try:
            return {"path": path, "text": enrich.read_source(workspace, path)}
        except FileNotFoundError:
            raise HTTPException(404, path) from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/approve")
    def approve(request: ApproveRequest) -> dict:
        try:
            return runner.approve(request.approver.strip(), request.note.strip())
        except NotReady as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/audit")
    def audit() -> list[dict]:
        events, _ = bus.current_run()
        return [e["data"] for e in events if e["kind"] == "stage"]

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
