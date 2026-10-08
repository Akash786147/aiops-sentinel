# AIOps Sentinel — Project Charter

**Pitch:** an AI system that monitors shared servers and, when trouble appears, doesn't just scale
blindly: it uses semantic code search and RAG to trace the problem back to the actual code,
generates a test to confirm it, proposes a fix through a CI/CD pipeline, and keeps a transparent
record of every decision it made.

## Team and ownership

| Member | Owns | Deliverables |
| --- | --- | --- |
| Akash (P1) | Steps 1–2: shared-server monitoring, service registry, detection | `shared_server/common/telemetry.py`, `sentinel/telemetry.py`, `sentinel/registry.py`, `sentinel/detection.py`, detection results |
| Aryan (P2) | Steps 3–5: evidence packet, code index, hybrid tracing, LLM re-rank, action decision | `sentinel/context.py`, `sentinel/indexing.py`, `sentinel/tracing.py`, localisation and ablation results |
| Syna (P3) | Step 6 and evaluation: test generation, guard, sandbox, LLM client, benchmark harness | `sentinel/testgen.py`, `sentinel/llm.py`, `benchmark/`, `evaluation/benchmark.py`, test results |
| Whole team | Audit trail, guardrails, docs, slides; each member can explain all parts | `sentinel/audit.py`, `sentinel/pipeline.py`, `docs/` |

## Problem and users

Developers and operators of services that share a server. An alert says *something* is slow or
failing; it does not say which tenant, which function, or whether a fix is justified. Scaling often
hides code faults.

## Scope

In scope: steps 1–6 (monitor → detect → evidence → index → trace → confirming test), action
decision, audit, guardrails, and a quantitative benchmark with baselines. Designed but not
automated: fix proposal, draft PR, CI/CD rollout, post-deploy watch (steps 7–10).

## Success criteria

Measured on 12 injected faults + 3 controls × 3 seeds (see PROJECT_GUIDE.md §7): detection recall
and false alarms vs fixed thresholds; Top-1 function localisation vs blame-deploy, BM25, dense,
plain RAG + LLM and the v0 retriever; confirming-test rate; action accuracy vs scale-on-alert.
