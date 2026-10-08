# AIOps Sentinel — 6-minute demonstration script

> **Superseded (v0).** For the v1 demo run `python -m benchmark.demo F01` (see [PROJECT_GUIDE.md](PROJECT_GUIDE.md)).

## Start the application

From the project root, open two terminals:

```bash
. .venv/bin/activate
uvicorn app.victim:app --port 8001
```

```bash
. .venv/bin/activate
uvicorn app.main:app --port 8000
```

Open `http://localhost:8000`. The default model is the shared Ollama server at `http://100.105.206.57:11434` using `qwen2.5-coder:7b`.

## Suggested presentation flow

1. **Product and application API** — Show the Overview page and say: “This is AIOps Sentinel. It monitors a running order service and connects operational signals back to the source code.” Ask *Why might the orders endpoint be slow?* The answer identifies the Ollama model in the response header.

2. **Knowledge base and embeddings** — Point to the **Knowledge base** metric, then open **Code intelligence**. Search for *delay to detailed order requests*. Explain that the repository has been chunked, embedded, stored in ChromaDB, and ranked by vector similarity. Each returned card shows the exact file and line range.

3. **RAG proof** — Return to Overview. Ask the same question twice: once with **Grounded response** and once with **Base model only**. The grounded answer has retrieved code context; the base-model request intentionally has none. This visibly demonstrates RAG rather than claiming it.

4. **Services and orchestration** — Open **Incident intelligence**. Explain the flow: victim app metrics → Sentinel monitoring API → threshold decision → retrieval service → Ollama reasoning → evidence and approval. The dashboard is the orchestration surface, while `services/` contains the separate monitoring, retrieval, LLM, and diagnosis components.

5. **Live incident and human control** — In a third terminal run:

```bash
. .venv/bin/activate
python scripts/simulate_incident.py
```

Then click **Check now** in Monitoring. Sentinel detects the high p95 latency, switches to the incident workspace, displays the diagnosis and cited source chunks, and waits for a named reviewer to click **Approve handoff**. Show **Audit activity** to prove every decision is recorded.

6. **Docker** — End with:

```bash
sudo docker compose up --build
```

Explain that the Sentinel and victim services run as separate containers and use the shared Ollama server by default. `docker compose --profile local-ollama up` also exposes an optional local Ollama service for a higher-memory host.

## Short answers for questions

- **Why is it responsible AI?** The system shows retrieved source evidence, labels the answering engine, logs decisions, and never merges or changes infrastructure without human approval.
- **What is the deliberately injected issue?** The detailed `/orders` path performs a repeated per-order profile lookup with a delay, simulating an N+1-style latency problem.
- **What is the action?** Sentinel creates an auditable CI/CD handoff recommendation; a person remains responsible for reviewing the test, fix, and pull request.
