"""Best-effort detection of a service's listening port from its source tree."""
from __future__ import annotations

import re
from pathlib import Path

SOURCE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


def infer_source_port(root: Path) -> int | None:
    """Find a literal port passed to a Node server's listen() call, then Docker EXPOSE as fallback."""
    root = Path(root)
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix in SOURCE_EXTENSIONS
             and not {".git", "node_modules", "dist", "build"}.intersection(p.parts)]
    files.sort(key=lambda p: (p.name not in {"server.js", "index.js", "app.js"}, str(p)))
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        variables = {name: int(value) for name, value in re.findall(
            r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:process\.env\.[\w$]+\s*\|\|\s*)?(\d{2,5})\b", text
        ) if 1 <= int(value) <= 65535}
        for argument in re.findall(r"\.(?:listen)\s*\(\s*([A-Za-z_$][\w$]*|\d{2,5})\b", text):
            value = int(argument) if argument.isdigit() else variables.get(argument)
            if value and 1 <= value <= 65535:
                return value
    dockerfile = root / "Dockerfile"
    if dockerfile.is_file():
        ports = [int(n) for n in re.findall(r"(?im)^\s*EXPOSE\s+(\d{2,5})\b", dockerfile.read_text(encoding="utf-8", errors="replace"))]
        if ports and 1 <= ports[0] <= 65535:
            return ports[0]
    return None
