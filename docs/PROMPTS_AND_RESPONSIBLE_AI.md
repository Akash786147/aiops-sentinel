# Prompt engineering, explainability, and limits

## Production diagnosis prompt

The exact controlled prompt is constructed in `services/llm.py`. Its important constraints are:

1. Answer only from supplied repository context.
2. Cite `file:line` evidence.
3. State uncertainty when evidence is insufficient.
4. Offer a safe next step and never state that a fix was applied.

This reduces unsupported root-cause claims and produces a reviewable explanation. The dashboard returns both the model answer and every retrieved chunk.

## Test-generation prompt template

```text
Using only this incident evidence and function signature, write one focused pytest regression test.
The test must fail on the described defect and pass after the proposed fix.
Do not change application code. State assumptions and keep external dependencies mocked.
```

In the prototype, `tests/test_victim_app.py` contains the resulting latency-budget guard candidate. A developer must review it: an AI-generated test can encode a wrong assumption.

## Audit fields and controls

Every index, search, question, monitor check, diagnosis, and approval is appended to `data/audit.jsonl`. The panel displays the original metrics, retrieved source chunks, answer engine, recommendation, and approver.

Known limitations include stale code indexes, incomplete telemetry, noisy thresholds, embedding ranking errors, and model hallucination. The human-in-the-loop gate prevents auto-merge; GitHub Actions runs lint/tests, but CI success is not proof that a remediation is safe.
