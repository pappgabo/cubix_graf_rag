"""Naive RAG query path.

question -> embedding -> similarity search (top-k) -> prompt from the
retrieved chunks -> LLM -> answer + the sources that were used.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from .config import get_settings
from .models import get_chat_model
from .vectorstore import get_vector_store

PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are a question answering assistant. Answer the question using ONLY "
     "the context below. Each context passage starts with a tag like [S1]. "
     "Cite the passages you used in the answer, e.g. [S1][S3]. "
     "If the context does not contain the answer, say that you cannot "
     "answer from the provided documents."),
    ("human", "Context:\n{context}\n\nQuestion: {question}"),
])


def _location(meta: dict) -> str:
    if meta.get("page") is not None:
        return f"page {meta['page']}"
    if meta.get("section"):
        return f"section: {meta['section']}"
    return "n/a"


def source_of(doc: Document, rank: int, score: float | None = None) -> dict:
    m = doc.metadata
    return {
        "tag": f"S{rank}",
        "chunk_id": m.get("chunk_id"),
        "doc_id": m.get("doc_id"),
        "file": m.get("file"),
        "format": m.get("format"),
        "location": _location(m),
        "url": m.get("url"),
        "score": round(score, 4) if score is not None else None,
        "text": doc.page_content,
    }


def format_context(sources: list[dict]) -> str:
    return "\n\n".join(
        f"[{s['tag']}] ({s['file']}, {s['location']})\n{s['text']}"
        for s in sources)


class NaiveRAG:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.store = get_vector_store()

    def retrieve(self, question: str, k: int | None = None) -> list[dict]:
        k = k or self.settings.top_k
        hits = self.store.similarity_search_with_score(question, k=k)
        return [source_of(d, i, sc) for i, (d, sc) in enumerate(hits, 1)]

    def ask(self, question: str, k: int | None = None) -> dict:
        sources = self.retrieve(question, k)
        messages = PROMPT.format_messages(
            context=format_context(sources), question=question)
        answer = get_chat_model().invoke(messages).content
        return {"question": question, "answer": answer, "sources": sources}

    def stream(self, question: str, k: int | None = None
               ) -> Iterator[dict]:
        """Yield {"sources": [...]} first, then {"token": "..."} items."""
        sources = self.retrieve(question, k)
        yield {"sources": sources}
        messages = PROMPT.format_messages(
            context=format_context(sources), question=question)
        for chunk in get_chat_model(streaming=True).stream(messages):
            if chunk.content:
                yield {"token": chunk.content}


@lru_cache
def get_rag() -> NaiveRAG:
    return NaiveRAG()
