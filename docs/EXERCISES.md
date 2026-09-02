# Hands-on exercises — implementation evidence

This is one progressively extended application: **AIOps Sentinel**.

| Exercise | Required concept | Implementation / demonstration |
| --- | --- | --- |
| 1 | Application → API → Ollama → Code Llama → response | `POST /api/ask` calls `services/llm.py`, which uses Ollama's `/api/generate` with `codellama:7b-instruct`. The response declares `engine` so a retrieval-only fallback cannot be mistaken for a model answer. |
| 2 | Knowledge base, chunking, embeddings, vectors | `services/retrieval.py` reads repo files, creates 44-line overlapping chunks, makes normalized 128-d hashing embeddings, and persists them in ChromaDB when installed. |
| 3 | Similarity retrieval and RAG | `/api/ask` embeds the question, ranks chunks by cosine similarity, and passes cited context into the Ollama prompt. Toggle `use_rag` false/true to compare a no-context answer with grounded RAG. |
| 4 | APIs, services, orchestration | FastAPI is the application/orchestration service; `monitor.py`, `retrieval.py`, `llm.py`, and `diagnosis.py` are clean service boundaries. `/api/monitor/check` coordinates metrics → threshold → retrieval → LLM diagnosis. |
| 5 | Docker and service communication | `docker-compose.yml` runs Sentinel, victim, and Ollama as separate services. The Sentinel container reaches `victim:8001` and `ollama:11434`. |

## Commands for the lab demo

```bash
cp .env.example .env
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# Uses qwen2.5-coder:7b on http://100.105.206.57:11434 by default
uvicorn app.victim:app --port 8001 &
uvicorn app.main:app --port 8000
```

Open `http://localhost:8000`, ask “Why might the orders endpoint be slow?”, then run in another terminal:

```bash
python scripts/simulate_incident.py
```

Click **Check metrics & diagnose**, inspect the retrieved chunks, then click approval. The audit trail makes the data, recommendation, and human decision visible.

> Deployment note: this VM sends generation requests to the shared Ollama server at `http://100.105.206.57:11434`, using `qwen2.5-coder:7b`. This avoids the local RAM requirement. The `engine` field identifies the model that answered; if the remote service is unavailable, Sentinel clearly labels the retrieval-only fallback.

## Sourcegraph OSS setup and semantic-search evidence

```bash
docker compose --profile sourcegraph up -d sourcegraph
# open http://localhost:7080, complete local admin setup, then add this local repo
```

In Sourcegraph use queries such as `repo:aiops-sentinel lang:python database`, `repo:aiops-sentinel "include_customer_profile"`, or `repo:aiops-sentinel file:app/victim.py`. The running project also exposes a lightweight natural-language code-search endpoint:

```bash
curl 'http://localhost:8000/api/code-search?q=find+functions+touching+orders'
```

This dual approach means Sourcegraph satisfies repository navigation while the app's vector search provides the natural-language query layer for the classroom demo.
