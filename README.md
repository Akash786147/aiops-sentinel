# AIOps Sentinel

AIOps Sentinel monitors a **shared server**. When a tenant service gets into trouble it does not
scale it blindly: it attributes the incident to one service and owner, builds an evidence packet
(telemetry, exceptions, the deployment diff), uses **semantic code search and an LLM** to trace the
symptom to the responsible **function**, and **generates a test that confirms it** (fails on the
deployed code, passes on the known-good code). Every decision is written to an audit trail and a
human approves any change.

Start here: **[docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md)** (what, why, how, tools, evaluation,
results, limitations, team responsibilities). Slides: `docs/AIOps_Sentinel_Review.pptx`.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
echo OPENAI_API_KEY=sk-... > .env                    # or GROQ_API_KEY=gsk-... (optional: LLM steps)

python -m benchmark.demo F01                         # live: shared server -> incident -> diagnosis -> test
pytest -q && ruff check app services tests scripts sentinel benchmark evaluation
```

## Reproduce the evaluation

```bash
python -m evaluation.benchmark record  --seeds 0 1 2   # ~50 s live traffic per scenario, 45 runs
python -m evaluation.benchmark analyze --seeds 0 1 2   # pipeline + baselines (+ LLM if a key is set)
python -m evaluation.benchmark analyze-model --seeds 0 1 2 --provider groq --model openai/gpt-oss-120b --label gptoss
python -m evaluation.benchmark score                   # evaluation/results/summary.json
```

## Repository map

| Path | What it is |
| --- | --- |
| `sentinel/` | The pipeline, one module per step: `telemetry`, `detection`, `context`, `indexing`, `tracing`, `testgen`, `audit`, `pipeline`, `llm`, `registry` |
| `shared_server/` | System under observation: orders, inventory, payments + shared telemetry middleware + `services.yaml` |
| `benchmark/` | 12 faults + 3 controls with ground truth, git deployment builder, load generator, live recorder, demo |
| `evaluation/` | `benchmark.py` harness, results (`results/summary.json`, per-run JSON, audit logs) |
| `tests/` | Unit tests for detection, indexing, tracing, test guard (+ v0 tests) |
| `docs/` | Project guide, workflow, slides (+ superseded v0 documents) |
| `app/`, `services/`, `microservices/`, `web/` | v0 prototype; `services/retrieval.py` is kept as the "v0" retrieval baseline |

## Safety boundary

Sentinel reads telemetry, logs and code; it never edits code, restarts or scales services. Generated
tests pass a static guard and run in a throw-away copy with API keys stripped. Steps 7–10 (fix PR,
CI/CD rollout, post-deploy watch) are designed but intentionally not automated.
