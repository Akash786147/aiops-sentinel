# AIOps Sentinel

An AI DevOps copilot demo: monitors a victim order service, traces an incident into source code with repository RAG, produces an explainable recommendation, and waits for a human to authorize the CI/CD handoff.

## Quick start

```bash
git clone <your-repository-url> aiops-sentinel
cd aiops-sentinel
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# The defaults use the shared Ollama server at 100.105.206.57:11434.
uvicorn app.victim:app --port 8001 &
uvicorn app.main:app --port 8000
```

Visit `http://localhost:8000`. For the full scripted incident, run `python scripts/simulate_incident.py`, then use the monitoring panel. Or start containers with `docker compose up --build`; this uses the shared Ollama server by default.

Run checks with `pytest -q` and `ruff check app services tests scripts`.

## Model configuration

By default Sentinel calls `qwen2.5-coder:7b` on the shared Ollama host `http://100.105.206.57:11434`, avoiding a local model load. Override `OLLAMA_BASE_URL` and `OLLAMA_MODEL` for your own server. A local Ollama container is available only when explicitly requested: `docker compose --profile local-ollama up`.

## Repository map

- `app/`: Sentinel API/dashboard and intentionally imperfect victim service.
- `services/`: monitoring, repository ingestion/retrieval, Ollama adapter, and diagnosis orchestration.
- `tests/`: regression and retrieval tests.
- `docs/`: charter, exercise evidence, prompts, safety/explainability notes.
- `.github/workflows/ci.yml`: CI validation with a human-approval policy.

See [the exercise implementation guide](docs/EXERCISES.md), [demo script](docs/DEMO_SCRIPT.md), and [project charter](docs/PROJECT_CHARTER.md).
