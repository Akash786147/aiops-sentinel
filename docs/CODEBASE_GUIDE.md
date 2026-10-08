# AIOps Sentinel — Codebase Guide

> **Superseded (v0).** Covers `app/`, `services/`, `microservices/` only. For the v1 pipeline
> (`sentinel/`, `shared_server/`, `benchmark/`) see [PROJECT_GUIDE.md](PROJECT_GUIDE.md).

This guide explains how the codebase works, where to make changes, and how one request moves through the system.

## What this project does

AIOps Sentinel is a DevOps-assistance prototype. It monitors a small order-service demo, identifies a latency/error incident, retrieves relevant source code, asks an Ollama coding model for an explanation, and records a human-approved remediation handoff.

It is intentionally safe: it **does not** merge code, restart services, or modify infrastructure automatically.

## Top-level repository map

```text
aiops-sentinel/
├── app/                 Gateway API, data models, audit store, victim service
├── microservices/       HTTP wrappers for retrieval, LLM, and monitoring
├── services/            Core business logic used by gateway and service wrappers
├── web/                 Dashboard HTML, Notion-like theme, stream client
├── evaluation/          Week 4 dataset, measurement scripts, baseline results
├── tests/               Automated tests
├── scripts/             Safe incident-load simulation
├── docs/                Charter, demo script, reports, this guide
├── Dockerfile           Shared container image definition
└── docker-compose.yml   Multi-service local deployment
```

## Main components

| Area | Files | Responsibility |
| --- | --- | --- |
| Gateway / dashboard | `app/main.py` | Serves the UI, exposes public APIs, calls services, orchestrates incidents, and records audit events. |
| Victim application | `app/victim.py` | Small order API that has a deliberate slow detailed-order path for a repeatable demo incident. |
| Retrieval core | `services/retrieval.py` | Reads files, makes chunks/embeddings, persists ChromaDB vectors, and ranks source-code evidence. |
| LLM core | `services/llm.py` | Builds guarded prompts and calls the remote Ollama model. Supports whole-answer and token streaming modes. |
| Monitoring core | `services/monitor.py` | Fetches `/metrics`, gathers local CPU/RAM, and decides whether thresholds indicate an incident. |
| Diagnosis core | `services/diagnosis.py` | Builds the incident question and formats evidence, model result, recommendation, and proposed test. |
| Audit data | `app/store.py` | Appends timestamped events to `data/audit.jsonl`. |
| API models | `app/models.py` | Validates incoming question and approval request bodies. |

## Multi-service deployment

Docker Compose runs these active services:

```text
Browser
  │
  ▼
sentinel gateway :8000
  ├── retrieval-service :8010 ──> ChromaDB / repository index
  ├── llm-service :8011 ────────> shared Ollama at 100.105.206.57:11434
  ├── monitor-service :8012 ────> victim :8001 /metrics
  └── audit JSONL file
```

`sentinel` is the API gateway and dashboard service. When the following variables are set, it uses HTTP service calls instead of calling the core modules directly:

```text
RETRIEVAL_SERVICE_URL=http://retrieval-service:8010
LLM_SERVICE_URL=http://llm-service:8011
MONITOR_SERVICE_URL=http://monitor-service:8012
```

Without those variables, the gateway uses the same core logic in-process. This makes simple local development easier while Docker demonstrates real service orchestration.

## Service APIs

### Gateway: `app/main.py` — port 8000

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/` | GET | Dashboard page. |
| `/api/health` | GET | Gateway health and local-index information. |
| `/api/code-search?q=...` | GET | Direct code-search view for the dashboard. |
| `/api/ask` | POST | Whole RAG answer; useful for scripts/evaluation. |
| `/api/ask/stream` | POST | Server-Sent Events stream for the dashboard. |
| `/api/monitor/check` | POST | Fetch metrics and, if needed, begin diagnosis. |
| `/api/incidents/latest` | GET | Last incident diagnosis. |
| `/api/incidents/approve` | POST | Records a named human approval. |
| `/api/audit` | GET | Most recent audit events. |

### Retrieval service: `microservices/retrieval_api.py` — port 8010

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | GET | Index status and vector backend. |
| `/search?q=...&limit=3` | GET | Returns relevant code chunks, line ranges, and scores. |

### LLM service: `microservices/llm_api.py` — port 8011

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | GET | LLM proxy status. |
| `/generate` | POST | Sends question + context to Ollama and returns one JSON response. |
| `/generate/stream` | POST | Returns newline-delimited JSON chunks from Ollama. |

### Monitoring service: `microservices/monitor_api.py` — port 8012

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | GET | Monitoring service status. |
| `/check?target_url=...` | POST | Reads victim metrics and returns the threshold decision. |

### Victim service: `app/victim.py` — port 8001

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/orders` | GET | Returns orders; `include_customer_profile=true` enables the intentional slow path. |
| `/orders/{order_id}` | GET | Returns one order. |
| `/metrics` | GET | Returns request count, error rate, and p95 latency. |

## Flow 1: Code question with RAG and streamed Markdown

1. User enters a question in `web/index.html`.
2. `web/stream-ui.js` calls `POST /api/ask/stream`.
3. Gateway calls `retrieve()`.
4. In Docker mode, gateway calls `retrieval-service /search`; otherwise it calls `RepositoryIndex.search()` directly.
5. Gateway sends question + retrieved chunks to `model_events()`.
6. In Docker mode, gateway calls `llm-service /generate/stream`; otherwise it calls `services.llm.stream_answer()` directly.
7. The model proxy calls Ollama using `qwen2.5-coder:7b`.
8. Tokens travel back as NDJSON → gateway converts them into SSE → browser renders live Markdown.
9. Gateway writes a `rag_question` audit event when the stream completes.

## Flow 2: Incident detection and approval

1. `scripts/simulate_incident.py` sends local traffic to the detailed order route.
2. User clicks **Check now** in the dashboard.
3. Gateway calls `monitor_metrics()`; in Docker it calls `monitor-service /check`.
4. The monitor reads victim `/metrics` and compares error rate/p95 latency against configured thresholds.
5. If an incident exists, gateway creates the diagnosis question using `incident_question()`.
6. Gateway retrieves source evidence and asks the LLM service for an explanation.
7. `format_diagnosis()` returns the evidence, explanation, safe recommendation, and proposed test reference.
8. User reviews evidence and sends a named approval to `/api/incidents/approve`.
9. `app/store.py` writes every important event to the audit trail.

## Retrieval design

`services/retrieval.py` is intentionally small enough to explain in class.

- Eligible source files: `.py`, `.md`, `.yml`, `.yaml`, `.txt`.
- Chunking: 44-line windows with a 36-line stride, so adjacent chunks overlap.
- Embedding: deterministic normalized 128-dimensional hashing vector.
- Similarity: dot product of normalized vectors, equivalent to cosine similarity.
- Persistence: ChromaDB is used when installed. A deterministic in-memory ranking remains available as fallback.
- Routing: gateway RAG queries favour `app/victim.py` and `services/`, because these are more relevant than project documentation for incident questions.

The `evaluation/` folder measures this design. It records that a lightweight hashing retriever is a prototype with limitations, not a production semantic-search claim.

## UI files

| File | Purpose |
| --- | --- |
| `web/index.html` | Dashboard layout, navigation, controls, incident/evidence panels. |
| `web/notion-theme.css` | Final minimal Notion-like visual layer; it intentionally overrides the earlier decorative styles. |
| `web/stream-ui.js` | Opens streaming requests, parses SSE events, updates answer text token-by-token, and safely renders basic Markdown. |

## Evaluation folder

| File | Purpose |
| --- | --- |
| `questions.json` | Fixed 25-question dataset for fair cross-model comparison. |
| `run_evaluation.py` | Runs retrieval-only or model evaluation and records output JSON. |
| `analyze_results.py` | Calculates summary metrics from a run. |
| `compare_retrievers.py` | Compares vector, lexical, and hybrid retrieval strategies. |
| `score_template.csv` | Human-review sheet for correctness, relevance, hallucination, and test scores. |
| `results/` | Recorded baseline output and reports. |

## Local development

For the simple in-process mode, open two terminals:

```bash
cd /home/ubuntu/aiops-sentinel
. .venv/bin/activate
uvicorn app.victim:app --port 8001
```

```bash
cd /home/ubuntu/aiops-sentinel
. .venv/bin/activate
uvicorn app.main:app --port 8000
```

Open `http://localhost:8000`.

## Docker multi-service mode

```bash
cd /home/ubuntu/aiops-sentinel
sudo docker compose up --build
```

The dashboard remains at `http://localhost:8000`. Health checks can be inspected at ports 8010, 8011, and 8012. The Ollama model remains remote by default to avoid this VM's memory limitation.

## Tests and checks

```bash
. .venv/bin/activate
ruff check app services microservices tests scripts evaluation
pytest -q
```

Current test coverage verifies repository retrieval and the victim service's normal/latency-budget behaviour. Add a test whenever you change monitoring thresholds, the retrieval algorithm, service contracts, or approval behaviour.

## Common changes

| Goal | Start here |
| --- | --- |
| Change incident thresholds | `.env.example`, `services/monitor.py` |
| Change the monitored app defect | `app/victim.py` |
| Improve search quality | `services/retrieval.py`, then rerun `evaluation/compare_retrievers.py` |
| Change Ollama model/host | `.env.example`, `docker-compose.yml`, `services/llm.py` |
| Change the dashboard look | `web/notion-theme.css` |
| Change streaming output behaviour | `web/stream-ui.js`, `app/main.py`, `microservices/llm_api.py` |
| Add a metric | `app/victim.py` and `services/monitor.py` |
| Add a new evaluation question | `evaluation/questions.json` and `evaluation/score_template.csv` |

## Safety rules to preserve

1. Never represent retrieval-only fallback text as a model answer.
2. Always show retrieved source evidence with a diagnosis.
3. Keep human approval before PR/merge, restart, or scaling actions.
4. Keep audit entries for question, diagnosis, and approval events.
5. Do not fabricate evaluation quality scores; keep human scores reviewable.
