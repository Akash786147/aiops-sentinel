"""Turn one evaluator JSON file into transparent quantitative summary metrics."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def average(values: list[float]) -> float | None:
    return round(statistics.mean(values), 3) if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    run = json.loads(args.results.read_text(encoding="utf-8"))
    rows = run["results"]
    precision = [row["retrieval_precision_at_k"] for row in rows]
    recall = [row["retrieval_recall_at_k"] for row in rows]
    latency = [row["latency_ms"] for row in rows if "latency_ms" in row]
    tokens = [row.get("estimated_input_tokens", 0) + row.get("estimated_output_tokens", 0) for row in rows if "answer" in row]
    fallbacks = sum(row.get("engine") == "retrieval-only fallback" for row in rows)
    summary = {
        "model": run["model"], "questions": len(rows), "retrieval_precision_at_k": average(precision),
        "retrieval_recall_at_k": average(recall), "retrieval_hit_rate": round(sum(row["retrieval_hit"] for row in rows) / len(rows), 3) if rows else 0,
        "mean_latency_ms": average(latency), "estimated_mean_total_tokens": average(tokens), "fallback_count": fallbacks,
    }
    print(json.dumps(summary, indent=2))
    if args.output:
        lines = ["# Evaluation summary", "", f"**Model:** `{summary['model']}`  ", f"**Questions:** {summary['questions']}", "", "| Metric | Result |", "| --- | ---: |"]
        for key, value in summary.items():
            if key not in {"model", "questions"}:
                lines.append(f"| {key.replace('_', ' ')} | {value} |")
        lines.extend(["", "Quality scores (correctness, relevance, hallucination, test pass) require human review in `score_template.csv`; they must not be invented automatically."])
        args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Saved report to {args.output}")


if __name__ == "__main__":
    main()
