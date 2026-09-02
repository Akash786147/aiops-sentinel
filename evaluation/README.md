# Week 4 evaluation pack

`questions.json` is the fixed 25-question dataset. Use that exact dataset for every model and keep RAG settings, prompt, retrieval top-k, machine, and network conditions as consistent as possible.

## Run retrieval analysis now

```bash
. .venv/bin/activate
python evaluation/run_evaluation.py --retrieval-only
python evaluation/analyze_results.py evaluation/results/qwen2.5-coder_7b_retrieval_only.json --output evaluation/results/retrieval_summary.md
```

## Run a full model evaluation

```bash
python evaluation/run_evaluation.py --model qwen2.5-coder:7b
```

For another model, use the same questions and conditions:

```bash
python evaluation/run_evaluation.py --model MODEL_NAME --ollama-url http://MODEL_HOST:11434
```

## Metrics and scoring

- **Retrieval precision@k:** relevant retrieved files ÷ retrieved files.
- **Retrieval recall@k:** unique expected files retrieved ÷ expected files.
- **Retrieval hit rate:** questions where at least one expected file was retrieved ÷ all questions.
- **Latency:** wall-clock time from LLM request to completed response, in milliseconds.
- **Estimated tokens:** whitespace-token estimate for input plus output; explicitly an approximation.
- **Client memory delta:** Python evaluator RSS after request minus before request. This is not remote-server memory use.
- **Correctness:** human reviewer gives 1 only when answer matches expected code behaviour.
- **Relevance:** human reviewer gives 1–5 based on how directly it answers the task.
- **Hallucination rate:** answers containing unsupported claims ÷ reviewed answers.
- **Test-pass rate:** generated tests that execute and pass ÷ generated tests submitted for execution.

Enter human quality scores in `score_template.csv`. Do not fabricate them: the purpose is quantitative, reviewable comparison.
