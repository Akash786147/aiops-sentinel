"""Ollama Code Llama adapter. It never represents the fallback as an LLM answer."""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import httpx


def build_prompt(question: str, context: list[dict]) -> str:
    # Send concise source excerpts, not whole documents, to the shared model.
    compact_context = [{**chunk, "text": chunk["text"][:360]} for chunk in context[:1]]
    return f"""You are AIOps Sentinel, a cautious DevOps code assistant.
Answer only from the supplied repository context. Cite file:line. If evidence is insufficient, say so.
Keep the answer under 70 words.

Repository context:
{chr(10).join(f'[{c["path"]}:{c["start_line"]}-{c["end_line"]}] {c["text"]}' for c in compact_context)}

Question: {question}
Explain in plain English, then provide a safe next step. Do not claim a fix was applied."""


async def answer(question: str, context: list[dict]) -> dict:
    prompt = build_prompt(question, context)
    base_url = os.getenv("OLLAMA_BASE_URL", "http://100.105.206.57:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    try:
        # The shared model can queue or cold-start. The caller explicitly allows it to finish.
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2, "num_predict": 90}},
            )
            response.raise_for_status()
            return {"answer": response.json()["response"], "engine": f"Ollama/{model}", "prompt": prompt}
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        evidence = "; ".join(f"{c['path']}:{c['start_line']}" for c in context[:3]) or "no matching code"
        error = f"{type(exc).__name__}: {str(exc) or 'request timed out or the model server closed the connection'}"
        return {"answer": f"Ollama is not reachable, so this is a retrieval-only preview. Relevant evidence: {evidence}. Start by reviewing those locations before approving a change.", "engine": "retrieval-only fallback", "prompt": prompt, "llm_error": error}


async def stream_answer(question: str, context: list[dict]) -> AsyncIterator[dict]:
    """Yield Ollama generation chunks for the browser's Server-Sent Events stream."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://100.105.206.57:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    try:
        async with httpx.AsyncClient(timeout=None) as client, client.stream(
                "POST",
                f"{base_url}/api/generate",
                json={"model": model, "prompt": build_prompt(question, context), "stream": True, "options": {"temperature": 0.2, "num_predict": 90}},
            ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if text := chunk.get("response"):
                    yield {"type": "token", "text": text}
                if chunk.get("done"):
                    yield {"type": "done", "engine": f"Ollama/{model}"}
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        detail = f"{type(exc).__name__}: {str(exc) or 'model connection closed unexpectedly'}"
        yield {"type": "error", "detail": detail}
