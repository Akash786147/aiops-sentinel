import json
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.llm import answer, stream_answer

app = FastAPI(title="AIOps Sentinel LLM Service", version="0.1.0")


class GenerateRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    context: list[dict] = []


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "provider": "Ollama proxy"}


@app.post("/generate")
async def generate(request: GenerateRequest) -> dict:
    return await answer(request.question, request.context)


@app.post("/generate/stream")
async def generate_stream(request: GenerateRequest) -> StreamingResponse:
    async def chunks() -> AsyncIterator[str]:
        async for item in stream_answer(request.question, request.context):
            yield json.dumps(item) + "\n"

    return StreamingResponse(chunks(), media_type="application/x-ndjson")
