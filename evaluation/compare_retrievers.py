"""Compare hashing-vector, lexical-overlap, and hybrid retrieval on the fixed dataset."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
sys.path.insert(0, str(ROOT))

from services.retrieval import RepositoryIndex


def tokens(text: str) -> set[str]:
    return set(TOKEN.findall(text.lower()))


def evaluate(index: RepositoryIndex, questions: list[dict], strategy: str, k: int = 3) -> dict:
    hit_count = 0
    precision, recall = [], []
    for question in questions:
        query_vector = index.embed(question["question"])
        query_tokens = tokens(question["question"])
        scores = []
        for chunk, vector in zip(index.chunks, index.vectors):
            vector_score = sum(a * b for a, b in zip(query_vector, vector))
            document_tokens = tokens(chunk.text)
            lexical_score = len(query_tokens & document_tokens) / max(1, len(query_tokens))
            score = {"vector": vector_score, "lexical": lexical_score, "hybrid": 0.45 * vector_score + 0.55 * lexical_score}[strategy]
            scores.append((score, chunk.path))
        found = [path for _, path in sorted(scores, reverse=True)[:k]]
        hits = [path for path in found if path in question["expected_files"]]
        hit_count += bool(hits)
        precision.append(len(hits) / k)
        recall.append(len(set(hits)) / len(question["expected_files"]))
    return {"strategy": strategy, "precision_at_3": round(sum(precision) / len(precision), 3), "recall_at_3": round(sum(recall) / len(recall), 3), "hit_rate": round(hit_count / len(questions), 3)}


def main() -> None:
    index = RepositoryIndex(ROOT)
    index.ingest()
    questions = json.loads((ROOT / "evaluation" / "questions.json").read_text(encoding="utf-8"))
    rows = [evaluate(index, questions, strategy) for strategy in ("vector", "lexical", "hybrid")]
    output = ROOT / "evaluation" / "results" / "retrieval_strategy_comparison.md"
    output.parent.mkdir(exist_ok=True)
    report = ["# Retrieval strategy comparison", "", "All strategies use the same 25 questions and top-k = 3.", "", "| Strategy | Precision@3 | Recall@3 | File hit rate |", "| --- | ---: | ---: | ---: |"]
    report.extend(f"| {row['strategy']} | {row['precision_at_3']} | {row['recall_at_3']} | {row['hit_rate']} |" for row in rows)
    report.extend(["", "The production retriever currently uses normalized hashing-vector similarity. This experiment is retained as evidence for Week 4 analysis; any production change must be tested separately."])
    output.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
