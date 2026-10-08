from fastapi import FastAPI, Query

from services.retrieval import RepositoryIndex

app = FastAPI(title="AIOps Sentinel Retrieval Service", version="0.1.0")
index = RepositoryIndex()


@app.on_event("startup")
def ingest_repository() -> None:
    index.ingest()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "chunks": len(index.chunks), "backend": index.backend}


@app.get("/search")
def search(q: str = Query(min_length=3), limit: int = Query(default=3, ge=1, le=8)) -> dict:
    return {"query": q, "backend": index.backend, "results": index.search(q, limit, preferred_paths=("app/victim.py", "services/"))}
