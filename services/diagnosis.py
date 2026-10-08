from __future__ import annotations

from services.llm import answer
from services.retrieval import repository_index


def incident_question(metrics: dict) -> str:
    return (
        f"Production incident: error_rate={metrics.get('error_rate')}, p95_ms={metrics.get('p95_ms')}ms. "
        "Inspect the /orders endpoint and include_customer_profile code path for repeated per-order work, "
        "N+1-style lookups, or missing caching. Find responsible code and a safe tested remediation."
    )


def format_diagnosis(question: str, metrics: dict, evidence: list[dict], result: dict) -> dict:
    recommendation = "Create a guarded test and propose a bounded-query/cache fix; require human approval before merge."
    return {"status": "needs_human_approval", "incident_question": question, "metrics": metrics, "retrieved_evidence": evidence, "explanation": result["answer"], "engine": result["engine"], "recommendation": recommendation, "proposed_test": "tests/test_victim_app.py::test_orders_endpoint_stays_under_latency_budget"}


async def diagnose(metrics: dict) -> dict:
    question = incident_question(metrics)
    evidence = repository_index.search(question, limit=5, preferred_paths=("app/",))
    result = await answer(question, evidence)
    return format_diagnosis(question, metrics, evidence, result)
