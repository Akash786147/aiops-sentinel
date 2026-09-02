"""Run a repeatable AIOps Sentinel evaluation against one Ollama-compatible model."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
QUESTION_SET = ROOT / "evaluation" / "questions.json"
WORD = re.compile(r"\S+")
sys.path.insert(0, str(ROOT))

from services.llm import answer
from services.retrieval import repository_index


def retrieval_scores(expected: list[str], evidence: list[dict]) -> dict:
    paths = [item["path"] for item in evidence]
    hits = [path for path in paths if path in expected]
    return {
        "retrieved_paths": paths,
        "expected_paths": expected,
        "retrieval_precision_at_k": round(len(hits) / len(paths), 3) if paths else 0.0,
        "retrieval_recall_at_k": round(len(set(hits)) / len(expected), 3) if expected else 0.0,
        "retrieval_hit": bool(hits),
    }


async def evaluate_question(item: dict, run_llm: bool) -> dict:
    evidence = repository_index.search(item["question"], limit=3, preferred_paths=("app/victim.py", "services/"))
    retrieval = retrieval_scores(item["expected_files"], evidence)
    record = {"id": item["id"], "category": item["category"], "question": item["question"], **retrieval}
    if not run_llm:
        return record

    process = psutil.Process()
    memory_before = process.memory_info().rss
    started = time.perf_counter()
    response = await answer(item["question"], evidence)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    memory_after = process.memory_info().rss
    answer_text = response["answer"]
    record.update(
        {
            "engine": response["engine"],
            "answer": answer_text,
            "llm_error": response.get("llm_error"),
            "latency_ms": latency_ms,
            # Approximation is explicit because Ollama does not return token use in this API mode.
            "estimated_input_tokens": len(WORD.findall(item["question"] + " " + " ".join(item["text"][:360] for item in evidence[:1]))),
            "estimated_output_tokens": len(WORD.findall(answer_text)),
            "client_memory_delta_mb": round((memory_after - memory_before) / 1024 / 1024, 3),
        }
    )
    return record


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"))
    parser.add_argument("--ollama-url", default=os.getenv("OLLAMA_BASE_URL", "http://100.105.206.57:11434"))
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N questions (0 means all).")
    parser.add_argument("--retrieval-only", action="store_true", help="Skip model calls for a fast retrieval analysis.")
    parser.add_argument("--output", default="", help="Optional explicit JSON output path.")
    args = parser.parse_args()
    os.environ["OLLAMA_MODEL"] = args.model
    os.environ["OLLAMA_BASE_URL"] = args.ollama_url
    questions = json.loads(QUESTION_SET.read_text(encoding="utf-8"))
    if args.limit:
        questions = questions[: args.limit]
    repository_index.ingest()
    results = []
    for position, item in enumerate(questions, start=1):
        print(f"[{position}/{len(questions)}] {item['id']} — {item['question']}", flush=True)
        results.append(await evaluate_question(item, run_llm=not args.retrieval_only))
    payload = {"model": args.model, "ollama_url": args.ollama_url, "rag_enabled": True, "run_type": "retrieval_only" if args.retrieval_only else "full_model", "results": results}
    output = Path(args.output) if args.output else ROOT / "evaluation" / "results" / f"{args.model.replace(':', '_')}_{payload['run_type']}.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Saved {len(results)} results to {output}")


if __name__ == "__main__":
    asyncio.run(main())
