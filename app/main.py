from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.models import ApprovalRequest, AskRequest
from app.store import append, recent
from services.diagnosis import diagnose
from services.llm import answer, stream_answer
from services.monitor import collect, is_incident
from services.retrieval import repository_index

app = FastAPI(title="AIOps Sentinel", version="0.1.0", description="Code-aware monitoring with human-approved remediation.")
WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
last_diagnosis: dict | None = None
app.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")


@app.on_event("startup")
def build_repository_knowledge_base() -> None:
    count = repository_index.ingest()
    append("knowledge_base_indexed", {"chunks": count, "backend": repository_index.backend})


@app.get("/")
def dashboard():
    # Keep the dashboard HTML self-contained while layering the streaming client script.
    page = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    page = page.replace("</head>", '<link rel="stylesheet" href="/assets/notion-theme.css"></head>')
    return HTMLResponse(page.replace("</body>", '<script src="/assets/stream-ui.js"></script></body>'))


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "aiops-sentinel", "knowledge_chunks": len(repository_index.chunks), "vector_backend": repository_index.backend}


@app.get("/api/code-search")
def code_search(q: str, limit: int = 4):
    if not q.strip():
        raise HTTPException(400, "q is required")
    evidence = repository_index.search(q, min(max(limit, 1), 8))
    append("code_search", {"query": q, "result_ids": [item["id"] for item in evidence]})
    return {"query": q, "backend": repository_index.backend, "results": evidence}


@app.post("/api/ask")
async def ask(request: AskRequest):
    evidence = repository_index.search(request.question, limit=3, preferred_paths=("app/victim.py", "services/")) if request.use_rag else []
    result = await answer(request.question, evidence)
    audit = append("rag_question", {"question": request.question, "rag_enabled": request.use_rag, "engine": result["engine"], "evidence": [{"path": item["path"], "line": item["start_line"]} for item in evidence]})
    return {"question": request.question, "answer": result["answer"], "engine": result["engine"], "llm_error": result.get("llm_error"), "retrieved_evidence": evidence, "audit_id": audit["id"]}


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@app.post("/api/ask/stream")
async def ask_stream(request: AskRequest):
    evidence = repository_index.search(request.question, limit=3, preferred_paths=("app/victim.py", "services/")) if request.use_rag else []

    async def events() -> AsyncIterator[str]:
        yield sse("context", {"engine": "Ollama/qwen2.5-coder:7b", "retrieved_evidence": evidence})
        async for item in stream_answer(request.question, evidence):
            if item["type"] == "token":
                yield sse("token", {"text": item["text"]})
            elif item["type"] == "done":
                append("rag_question", {"question": request.question, "rag_enabled": request.use_rag, "engine": item["engine"], "evidence": [{"path": source["path"], "line": source["start_line"]} for source in evidence]})
                yield sse("done", {"engine": item["engine"]})
            else:
                yield sse("error", {"detail": item["detail"]})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/monitor/check")
async def monitor_check(target_url: str = os.getenv("VICTIM_URL", "http://localhost:8001")):
    global last_diagnosis
    metrics = await collect(target_url)
    audit = append("monitor_snapshot", {"target_url": target_url, "metrics": metrics})
    if is_incident(metrics):
        last_diagnosis = await diagnose(metrics)
        last_diagnosis["audit_id"] = append("incident_diagnosed", last_diagnosis)["id"]
        return {"incident_detected": True, "snapshot_audit_id": audit["id"], "diagnosis": last_diagnosis}
    return {"incident_detected": False, "snapshot_audit_id": audit["id"], "metrics": metrics}


@app.get("/api/incidents/latest")
def latest_incident():
    return last_diagnosis or {"status": "no_incident"}


@app.post("/api/incidents/approve")
def approve(request: ApprovalRequest):
    if not last_diagnosis:
        raise HTTPException(404, "No diagnosis awaiting approval")
    # This is deliberately an approval record, not an auto-merge or production mutation.
    event = append("remediation_approved", {"incident_audit_id": last_diagnosis.get("audit_id"), "approved_by": request.approved_by, "action": request.action, "next_pipeline": "GitHub Actions validates tests and prepares a reviewable PR."})
    return {"status": "approval_recorded", "audit": event, "message": "No code was merged automatically. Trigger the CI workflow or create a PR for human review."}


@app.get("/api/audit")
def audit(limit: int = 20):
    return {"events": recent(min(max(limit, 1), 100))}
