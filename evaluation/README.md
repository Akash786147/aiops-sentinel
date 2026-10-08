# Evaluation

## v1 benchmark (current)

`benchmark.py` runs the shared-server incident benchmark: 12 injected faults + 3 controls, each
recorded live with 3 seeds, scored against ground truth. The method is described in
[docs/PROJECT_GUIDE.md](../docs/PROJECT_GUIDE.md) §7.

```bash
python -m evaluation.benchmark record  --seeds 0 1 2          # live traffic, ~50 s per scenario
python -m evaluation.benchmark analyze --seeds 0 1 2          # pipeline, baselines, ablations, tests (primary LLM)
python -m evaluation.benchmark analyze-model --seeds 0 --provider groq --model openai/gpt-oss-120b --label gptoss          # localisation + tests
python -m evaluation.benchmark analyze-model --seeds 1 2 --skip-tests --provider groq --model openai/gpt-oss-120b --label gptoss   # localisation only
python -m evaluation.benchmark score                          # results/summary.json + results/summary.md
```

| Output | Content |
| --- | --- |
| `results/summary.md` / `summary.json` | All metrics: detection, localisation (incl. ablations, held-out seeds, per LLM), tests, actions |
| `results/runs/<scenario>-s<seed>.json` | Everything measured for one run, including generated test code and outcomes |
| `results/audit/<scenario>-s<seed>.jsonl` | The pipeline's own audit trail for that run |
| `data/bench/` (not committed) | Raw telemetry recordings and git workspaces |
| `data/llm_cache/` (not committed) | Cached LLM answers keyed by prompt hash |

## v0 evaluation (superseded)

`run_evaluation.py`, `compare_retrievers.py`, `analyze_results.py`, `questions.json` and the older
files in `results/` evaluated the v0 prototype with 25 questions about Sentinel's own code. They
are kept for history; they have no fault ground truth and are not used in the v1 results.
