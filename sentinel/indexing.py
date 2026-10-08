"""Step 4: index the code semantically.

Python files are split along the syntax tree (one chunk per function or method, one per
group of module-level statements) so a chunk is a unit a human would name in a diagnosis.
Each chunk keeps its path, symbol, line range, the routes it serves (from decorators) and
the names it calls or reads, which gives a call/reference graph. Two retrievers sit on top:
BM25 over identifier-aware tokens (lexical) and bge-small sentence embeddings (dense).
"""
from __future__ import annotations

import ast
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
IGNORED_DIRS = {".git", "__pycache__", "logs", "sentinel_generated", ".venv"}
DENSE_MODEL = "BAAI/bge-small-en-v1.5"


@dataclass
class CodeChunk:
    id: str
    path: str
    symbol: str
    kind: str  # function | method | module
    start: int
    end: int
    text: str
    routes: list[str] = field(default_factory=list)
    refs: set[str] = field(default_factory=set)  # names called or read inside the chunk
    defines: set[str] = field(default_factory=set)  # names this chunk defines

    def overlaps(self, file: str, start: int, end: int) -> bool:
        return self.path == file and self.start <= end and start <= self.end


def tokenize(text: str) -> list[str]:
    tokens = []
    for word in WORD.findall(text):
        parts = [p for p in re.split(r"_+", CAMEL.sub("_", word)) if p]
        tokens.append(word.lower())
        if parts != [word]:
            tokens.extend(p.lower() for p in parts)
    return tokens


def _routes(node: ast.AST) -> list[str]:
    routes = []
    for decorator in getattr(node, "decorator_list", []):
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr in HTTP_METHODS \
                and decorator.args and isinstance(decorator.args[0], ast.Constant):
            routes.append(f"{decorator.func.attr.upper()} {decorator.args[0].value}")
    return routes


def _refs(node: ast.AST) -> set[str]:
    """Names used in the body. Decorators (``@app.get``) are wiring, not calls, so they are skipped."""
    names = set()
    body = ast.Module(body=list(node.body), type_ignores=[]) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else node
    for child in ast.walk(body):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
    return names


def chunk_python(path: str, source: str) -> list[CodeChunk]:
    tree = ast.parse(source)
    lines = source.splitlines()
    chunks: list[CodeChunk] = []

    def add(symbol: str, kind: str, node: ast.AST, start: int, end: int, defines: set[str]) -> None:
        text = "\n".join(lines[start - 1 : end])
        chunks.append(CodeChunk(f"{path}:{start}-{end}", path, symbol, kind, start, end, text, _routes(node), _refs(node), defines))

    module_block: list[ast.stmt] = []

    def flush() -> None:
        if module_block:
            start, end = module_block[0].lineno, module_block[-1].end_lineno
            defines = {t.id for s in module_block for t in ast.walk(s) if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
            holder = ast.Module(body=list(module_block), type_ignores=[])
            add(f"{Path(path).stem} (module)", "module", holder, start, end, defines)
            module_block.clear()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            flush()
            start = min([d.lineno for d in node.decorator_list] + [node.lineno])
            add(node.name, "function", node, start, node.end_lineno, {node.name})
        elif isinstance(node, ast.ClassDef):
            flush()
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            header_end = (methods[0].lineno - 1) if methods else node.end_lineno
            add(node.name, "class", ast.Module(body=[n for n in node.body if n not in methods], type_ignores=[]),
                node.lineno, header_end, {node.name})
            for method in methods:
                start = min([d.lineno for d in method.decorator_list] + [method.lineno])
                add(f"{node.name}.{method.name}", "method", method, start, method.end_lineno, {method.name})
        else:
            module_block.append(node)
    flush()
    return chunks


class CodeIndex:
    def __init__(self, root: Path, include: tuple[str, ...] | None = None, dense: bool = True) -> None:
        self.root = Path(root)
        self.chunks: list[CodeChunk] = []
        for path in sorted(self.root.rglob("*.py")):
            relative = path.relative_to(self.root).as_posix()
            if any(part in IGNORED_DIRS for part in path.parts) or relative.startswith("tests/"):
                continue
            if include and relative.split("/", 1)[0] not in include:
                continue
            self.chunks.extend(chunk_python(relative, path.read_text(encoding="utf-8")))
        self._bm25_setup()
        self.vectors = _embed([f"{c.path} {c.symbol}\n{c.text}" for c in self.chunks]) if dense else None

    # ---- lexical: Okapi BM25 ------------------------------------------------------------
    def _bm25_setup(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.doc_tokens = [Counter(tokenize(f"{c.path} {c.symbol} {c.text}")) for c in self.chunks]
        self.doc_len = [sum(t.values()) for t in self.doc_tokens]
        self.avg_len = sum(self.doc_len) / max(1, len(self.doc_len))
        df = Counter(token for tokens in self.doc_tokens for token in tokens)
        n = len(self.chunks)
        self.idf = {token: math.log(1 + (n - count + 0.5) / (count + 0.5)) for token, count in df.items()}

    def bm25(self, query: str) -> list[float]:
        terms = tokenize(query)
        scores = []
        for tokens, length in zip(self.doc_tokens, self.doc_len):
            score = 0.0
            for term in terms:
                tf = tokens.get(term, 0)
                if tf:
                    score += self.idf.get(term, 0.0) * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
            scores.append(score)
        return scores

    # ---- dense: cosine similarity of normalised embeddings ------------------------------
    def dense(self, query: str) -> list[float]:
        if self.vectors is None:
            return [0.0] * len(self.chunks)
        query_vector = _embed([query], query=True)[0]
        return [sum(a * b for a, b in zip(query_vector, vector)) for vector in self.vectors]

    # ---- structure -----------------------------------------------------------------------
    def handlers(self, route: str) -> list[int]:
        return [i for i, chunk in enumerate(self.chunks) if route in chunk.routes]

    def callees(self, index: int) -> list[int]:
        chunk = self.chunks[index]
        return [i for i, other in enumerate(self.chunks) if i != index and other.defines & chunk.refs]

    def reachable(self, start: list[int], max_depth: int = 3) -> dict[int, int]:
        """Breadth-first walk of the call/reference graph: chunk index -> depth."""
        depth = {i: 0 for i in start}
        frontier = list(start)
        for level in range(1, max_depth + 1):
            next_frontier = []
            for index in frontier:
                for callee in self.callees(index):
                    if callee not in depth:
                        depth[callee] = level
                        next_frontier.append(callee)
            frontier = next_frontier
        return depth


_embedder = None
_embedding_cache: dict[str, list[float]] = {}


def _embed(texts: list[str], query: bool = False) -> list[list[float]]:
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(DENSE_MODEL)
    prefix = "Represent this sentence for searching relevant passages: " if query else ""
    keys = [hashlib.sha1((prefix + t).encode()).hexdigest() for t in texts]
    missing = [(k, prefix + t) for k, t in zip(keys, texts) if k not in _embedding_cache]
    if missing:
        for (key, _), vector in zip(missing, _embedder.embed([t for _, t in missing])):
            norm = math.sqrt(float((vector * vector).sum())) or 1.0
            _embedding_cache[key] = [float(v) / norm for v in vector]
    return [_embedding_cache[k] for k in keys]
