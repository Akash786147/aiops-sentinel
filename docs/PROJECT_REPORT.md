# AIOps Sentinel — Technical Project Report

## 1. Project summary

**AIOps Sentinel** is a code-aware incident-assistance prototype for small DevOps teams. A running order-service demo exposes metrics. When latency or errors cross a threshold, Sentinel retrieves relevant source code, asks a coding model for an evidence-grounded explanation, proposes a safe next action, and records a human approval before any CI/CD handoff.

The problem it addresses is the gap between an operational alert and the source code that likely caused it. A high p95 latency alone does not tell an operator which endpoint or code path should be reviewed. Sentinel narrows that gap with visible source evidence.

## 2. Current architecture

```text
Browser dashboard
       │
FastAPI application / API gateway (`app/main.py`)
       ├── Monitoring service (`services/monitor.py`) ──> victim order API
       ├── Retrieval service (`services/retrieval.py`) ──> ChromaDB + vector index
       ├── LLM service (`services/llm.py`) ──> shared Ollama / qwen2.5-coder:7b
       ├── Diagnosis orchestration (`services/diagnosis.py`)
       └── Audit data service (`app/store.py`) ──> JSONL audit log
```

The interface is deliberately human-in-the-loop. It can create an approval record and describe a CI/CD handoff, but it does not merge code, restart a service, or change production infrastructure.

## 3. Data and demo scenario

The knowledge source is this repository: application code, service modules, tests, configuration, and documentation. The monitored victim app is `app/victim.py`. Its detailed `/orders?include_customer_profile=true` route has a deliberate repeated per-order delay. `scripts/simulate_incident.py` safely exercises that path locally so its p95 latency breaches the configured threshold.

## 4. RAG implementation

1. `RepositoryIndex.ingest()` reads eligible repository files.
2. Files are divided into overlapping chunks of up to 44 lines, advancing every 36 lines.
3. Each chunk and incoming question receive a normalized 128-dimensional hashing embedding.
4. Chunks are ranked by vector similarity; ChromaDB persists the resulting collection when available.
5. The API passes concise retrieved code context to the Ollama model.
6. The dashboard displays file path, line range, score, answer engine, and streamed Markdown response.

The current embedding method is intentionally lightweight and reproducible. It is appropriate for the lab prototype but is not equivalent to a modern semantic embedding model; the Week 4 retrieval evaluation identifies this as a future improvement area.

## 5. Week 3 evidence

| Requirement | Implemented evidence |
| --- | --- |
| Application and LLM API | FastAPI routes `/api/ask` and `/api/ask/stream`; `services/llm.py` calls the Ollama generate API. |
| Knowledge base and embeddings | Repository ingestion, chunking, hashing embeddings, and ChromaDB persistence in `services/retrieval.py`. |
| Retrieval and RAG | Grounded code retrieval is supplied to the prompt; the UI permits base-model versus grounded response comparison. |
| Services and orchestration | Monitoring, retrieval, LLM, diagnosis, audit, application gateway, and dashboard have separate responsibilities. |
| Docker | `Dockerfile` and `docker-compose.yml`; Sentinel and victim images were built successfully. |

The initial course wording refers to Code Llama. This deployment uses the Ollama-compatible remote model `qwen2.5-coder:7b` because the local VM lacks enough RAM to load Code Llama. The integration remains Ollama-based; the model choice is a documented resource constraint, not a hidden substitution.

## 6. Week 4 evaluation assets completed

| Asset | Purpose |
| --- | --- |
| `evaluation/questions.json` | Fixed 25-question evaluation dataset covering the actual AIOps Sentinel use case. |
| `evaluation/run_evaluation.py` | Repeatable evaluator for any Ollama-compatible model; captures retrieval results, response latency, estimated token count, client memory delta, answer, and errors. |
| `evaluation/score_template.csv` | Human scoring sheet for correctness, relevance, hallucination, and generated-test pass rate. |
| `evaluation/analyze_results.py` | Generates metric summaries from a model run. |
| `evaluation/compare_retrievers.py` | Compares hashing-vector, lexical-overlap, and hybrid retrieval on the same dataset. |

### Metrics definitions

- **Retrieval precision@k** = relevant retrieved files / retrieved files.
- **Retrieval recall@k** = unique expected files retrieved / expected files.
- **Retrieval hit rate** = questions with at least one expected file retrieved / all questions.
- **Correctness** = 1 only if a human reviewer confirms the answer matches repository behaviour.
- **Relevance** = human score from 1 to 5 based on whether the answer directly addresses the task.
- **Hallucination rate** = responses with unsupported claims / reviewed responses.
- **Latency** = wall-clock milliseconds from model request to final response.
- **Token use** = whitespace-token approximation for prompt plus output; it is labelled an estimate.
- **Client memory delta** = evaluator process RSS after request minus before request. It does not claim to measure remote model-server memory.

### Retrieval baseline recorded

The 25-question retrieval-only evaluation was run and saved in `evaluation/results/qwen2.5-coder_7b_retrieval_only.json`.

| Configuration | Precision@3 | Recall@3 | File hit rate |
| --- | ---: | ---: | ---: |
| Current request-routing retrieval | 0.200 | 0.383 | 0.480 |
| Raw hashing-vector comparison | 0.067 | 0.130 | 0.200 |
| Lexical-overlap comparison | 0.080 | 0.170 | 0.240 |
| Raw hybrid comparison | 0.067 | 0.150 | 0.200 |

This is a useful engineering result: the preferred-path routing in the application improves the lightweight raw similarity baseline, but a 48% file-hit rate is not sufficient for a production code-assistant claim. The next improvement should be a code-aware embedding model, better function-level chunking, and rerunning the same dataset. This is evidence-based RAG analysis, not a claim that the first retriever is perfect.

## 7. RAG analysis examples

| Case | Observation | Interpretation |
| --- | --- | --- |
| Slow detailed orders request | `app/victim.py` is retrieved and exposes `include_customer_profile` plus the repeated `time.sleep`. | Relevant context can support a code-level latency explanation. |
| Repository stream endpoint question | Multiple files (`app/main.py`, `services/llm.py`, `web/stream-ui.js`) are relevant. | Multi-file questions need broader, dependency-aware retrieval than one short prompt excerpt. |
| Generic process/documentation wording | Documentation can outrank application code in the raw vector retriever. | Irrelevant retrieval is a measurable failure mode; preferred-path routing and improved chunking are required. |

For the presentation, show the UI's **Grounded response** option and then **Base model only** for the same question. Explain that the retrieved-source panel lets the reviewer judge whether the context deserves trust.

## 8. Week 4 work still dependent on multiple models

The full three-model comparison cannot honestly be completed until two additional accessible models are supplied. Everything else is ready. For every model, run:

```bash
python evaluation/run_evaluation.py --model MODEL_NAME --ollama-url http://MODEL_HOST:11434
python evaluation/analyze_results.py evaluation/results/MODEL_FILE.json --output evaluation/results/MODEL_summary.md
```

Then manually score each answer in `evaluation/score_template.csv`. Do not assign correctness, hallucination, or test-pass values without review.

## 9. Running and demonstrating the project

```bash
. .venv/bin/activate
uvicorn app.victim:app --port 8001
```

In a second terminal:

```bash
. .venv/bin/activate
uvicorn app.main:app --port 8000
```

Open `http://localhost:8000`. Ask a code question to demonstrate streaming Markdown RAG. Run `python scripts/simulate_incident.py`, click **Check now**, inspect the retrieved evidence, and approve the handoff. See `docs/DEMO_SCRIPT.md` for the full presentation sequence.

## 10. Limitations and responsible-AI controls

- The system depends on code index freshness and the completeness of metrics/logs.
- Lightweight hashing embeddings can retrieve irrelevant chunks; the measured baseline documents this limitation.
- The shared remote model can queue or respond slowly; UI output is streamed so the user sees generation as it arrives.
- Model answers can hallucinate. Evidence is visible, and a human must approve every remediation handoff.
- CI success does not prove that a code change is safe; code review remains mandatory.
