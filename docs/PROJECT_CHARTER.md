# AIOps Sentinel — Project Charter

**Pitch:** AIOps Sentinel monitors an application and, when latency or failures rise, uses code search and retrieval-augmented reasoning to explain the likely code-level cause, proposes a tested remediation, and records a human-approved CI/CD handoff.

## Problem and users

Small DevOps teams often see a CPU, error, or latency alert without quickly knowing which endpoint or code path caused it. The target users are developers and operators responding to an incident. The project addresses the gap between operational telemetry and source code.

## Knowledge/data sources

- Live victim-service metrics: request count, error rate, p95 latency.
- Application source, test code, prompts, and incident/audit records.
- Future extension: historical logs and deployment metadata.

## Architecture

```text
Browser / API client
        |
 AIOps Sentinel orchestration API (FastAPI)
   |              |                 |
Monitor      Repository RAG       Ollama / Code Llama
   |              |                 |
Victim app   chunks -> embeddings -> vector similarity
   |              \                 /
  metrics ------ incident diagnosis + cited evidence
                            |
                 human approval -> GitHub Actions checks -> reviewable PR
```

## Scope and safety

The shipped demo deliberately **does not** merge code, restart services, or scale infrastructure. It records approval and directs the reviewer into CI. This makes the system auditable and prevents a hallucinated diagnosis from changing production.

## Success scenario

The scripted load exercises the victim app's intentionally slow per-order profile lookup. Sentinel sees the p95 threshold breach, retrieves `app/victim.py`, explains the N+1-style issue with citations, proposes a latency guard test, and waits for a named human approval.
