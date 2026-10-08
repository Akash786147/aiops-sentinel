"""Repository knowledge base: chunking, deterministic embeddings and vector similarity.

ChromaDB is used when installed. The small hashing-vector fallback keeps the lab demo
usable in restricted classrooms and makes all ranking behaviour reproducible.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ALLOWED = {".py", ".md", ".yml", ".yaml", ".txt"}


@dataclass
class Chunk:
    id: str
    path: str
    start_line: int
    end_line: int
    text: str


class RepositoryIndex:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.getenv("CODE_ROOT", Path(__file__).resolve().parents[1])).resolve()
        self.chunks: list[Chunk] = []
        self.vectors: list[list[float]] = []
        self.backend = "hashing-vector"

    @staticmethod
    def embed(text: str, dimensions: int = 128) -> list[float]:
        vector = [0.0] * dimensions
        for token in TOKEN.findall(text.lower()):
            position = int(hashlib.sha256(token.encode()).hexdigest(), 16) % dimensions
            vector[position] += 1.0
        length = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / length for value in vector]

    def ingest(self) -> int:
        ignored = {".git", ".venv", "__pycache__", "data", ".pytest_cache", ".chromadb"}
        collected: list[Chunk] = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix not in ALLOWED or any(part in ignored for part in path.relative_to(self.root).parts):
                continue
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for start in range(0, len(lines), 36):
                body = "\n".join(lines[start : start + 44]).strip()
                if body:
                    relative = str(path.relative_to(self.root))
                    collected.append(Chunk(f"{relative}:{start + 1}", relative, start + 1, min(start + 44, len(lines)), body))
        self.chunks = collected
        self.vectors = [self.embed(chunk.text) for chunk in collected]
        self._persist_chroma()
        return len(self.chunks)

    def _persist_chroma(self) -> None:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(self.root / ".chromadb"))
            collection = client.get_or_create_collection("aiops_sentinel_code")
            if self.chunks:
                collection.upsert(ids=[c.id for c in self.chunks], documents=[c.text for c in self.chunks], metadatas=[{"path": c.path, "start_line": c.start_line, "end_line": c.end_line} for c in self.chunks], embeddings=self.vectors)
            self.backend = "ChromaDB + hashing embeddings"
        except (ImportError, OSError, RuntimeError, TypeError, ValueError, AttributeError):
            # No silent invented source: the API reports which backend actually answered.
            self.backend = "hashing-vector (ChromaDB unavailable)"

    def search(self, query: str, limit: int = 4, preferred_paths: tuple[str, ...] = ()) -> list[dict]:
        if not self.chunks:
            self.ingest()
        query_vector = self.embed(query)
        scored = []
        for chunk, vector in zip(self.chunks, self.vectors):
            score = sum(a * b for a, b in zip(query_vector, vector))
            # An incident diagnosis should favour monitored application code over its own prompts/docs.
            if preferred_paths and any(chunk.path.startswith(prefix) for prefix in preferred_paths):
                score += 0.25
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{**asdict(chunk), "score": round(score, 3)} for score, chunk in scored[:limit]]


repository_index = RepositoryIndex()
