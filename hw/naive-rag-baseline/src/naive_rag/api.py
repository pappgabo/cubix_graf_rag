"""FastAPI app exposing the naive RAG pipeline.

Run:  uv run naive-rag serve     (docs at http://127.0.0.1:8000/docs)
"""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .rag import get_rag

app = FastAPI(title="Naive RAG baseline", version="0.1.0")


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    k: int | None = Field(None, ge=1, le=20, description="top-k override")
    stream: bool = False


class Source(BaseModel):
    tag: str
    chunk_id: str | None
    doc_id: str | None
    file: str | None
    format: str | None
    location: str
    url: str | None
    score: float | None
    text: str


class ChatResponse(BaseModel):
    question: str
    answer: str
    sources: list[Source]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    rag = get_rag()
    if req.stream:
        def events():
            # NDJSON: first line has the sources, then one line per token.
            for item in rag.stream(req.question, req.k):
                yield json.dumps(item, ensure_ascii=False) + "\n"
        return StreamingResponse(events(), media_type="application/x-ndjson")
    return rag.ask(req.question, req.k)
