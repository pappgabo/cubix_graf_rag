"""Build the vector index: load corpus -> chunk -> embed -> Qdrant."""

from __future__ import annotations

import json
import re

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from .config import get_settings
from .loaders import MARKDOWN_FORMATS, load_corpus
from .vectorstore import build_index


_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]
# A section whose entire text is one Markdown heading. The heading splitter
# emits these when a parent heading has no body before the next heading.
_HEADING_ONLY = re.compile(r"#{1,6} [^\n]*")
# Paragraph, line, sentence, word, then character. Character is only the
# last resort for a unit that is itself longer than chunk_size.
_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


class ChunkConfigError(ValueError):
    """chunk_size or chunk_overlap cannot be used."""


def validate_chunk_config(chunk_size: object, chunk_overlap: object) -> None:
    """Reject a size or overlap that would drop text or repeat without end."""
    if (not isinstance(chunk_size, int) or isinstance(chunk_size, bool)
            or chunk_size <= 0):
        raise ChunkConfigError(
            f"chunk_size must be a positive integer, got {chunk_size!r}")
    if (not isinstance(chunk_overlap, int) or isinstance(chunk_overlap, bool)
            or chunk_overlap < 0 or chunk_overlap >= chunk_size):
        raise ChunkConfigError(
            "chunk_overlap must be an integer >= 0 and < chunk_size, "
            f"got {chunk_overlap!r} for size {chunk_size!r}")


def _heading_only(text: str) -> bool:
    return _HEADING_ONLY.fullmatch(text.strip()) is not None


def _same_source_unit(left: Document, right: Document) -> bool:
    return (left.metadata.get("doc_id") == right.metadata.get("doc_id")
            and left.metadata.get("page") == right.metadata.get("page"))


def _section_path(documents: list[Document]) -> str:
    parts: list[str] = []
    for doc in documents:
        section = doc.metadata.get("section")
        text = section.strip() if isinstance(section, str) and section.strip() else ""
        if text and text not in parts:
            parts.append(text)
    return " > ".join(parts)


def attach_bare_headings(docs: list[Document]) -> list[Document]:
    """Keep a body-less heading with the following section of the same unit.

    The heading line is prepended, so the source text is not dropped. A
    heading with nothing after it stays its own section. Pages and documents
    are not joined.
    """
    out: list[Document] = []
    pending: list[Document] = []
    for doc in docs:
        if _heading_only(doc.page_content):
            pending.append(doc)
            continue
        matched: list[Document] = []
        while pending and _same_source_unit(pending[-1], doc):
            matched.append(pending.pop())
        out.extend(pending)
        pending = []
        if not matched:
            out.append(doc)
            continue
        matched.reverse()
        meta = {**doc.metadata}
        parent = _section_path(matched)
        child = meta.get("section")
        if isinstance(child, str) and child.strip():
            if parent and not child.startswith(parent):
                meta["section"] = f"{parent} > {child}"
        elif parent:
            meta["section"] = parent
        heading_text = "\n\n".join(item.page_content.strip() for item in matched)
        out.append(Document(
            page_content=f"{heading_text}\n\n{doc.page_content}",
            metadata=meta,
        ))
    out.extend(pending)
    return out


def split_by_headings(docs: list[Document]) -> list[Document]:
    """Split Markdown-derived documents on headings and record `section`.

    Heading text is kept inside the chunk (strip_headers=False) so the
    embedding also sees the topic. PDF / XLSX documents pass through.
    """
    md = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS, strip_headers=False)
    out: list[Document] = []
    for doc in docs:
        if doc.metadata.get("format") not in MARKDOWN_FORMATS:
            out.append(doc)
            continue
        for part in md.split_text(doc.page_content):
            section = " > ".join(
                part.metadata[k] for k in ("h1", "h2", "h3", "h4")
                if k in part.metadata)
            meta = {**doc.metadata}
            if section:
                meta["section"] = section
            out.append(Document(page_content=part.page_content, metadata=meta))
    return out


def _resolved_chunk_config(chunk_size: int | None,
                           chunk_overlap: int | None) -> tuple[int, int]:
    settings = get_settings()
    size = settings.chunk_size if chunk_size is None else chunk_size
    overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap
    validate_chunk_config(size, overlap)
    return size, overlap


def chunk_sources(sources: list[Document], chunk_size: int | None = None,
                  chunk_overlap: int | None = None) -> list[Document]:
    """Split already loaded documents. Does not read the corpus or embed."""
    size, overlap = _resolved_chunk_config(chunk_size, chunk_overlap)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=_SEPARATORS,
        add_start_index=True,
    )
    pieces = attach_bare_headings(split_by_headings(sources))
    chunks = splitter.split_documents(pieces)
    counters: dict[str, int] = {}
    for chunk in chunks:
        doc_id = chunk.metadata.get("doc_id", "doc")
        ordinal = counters.get(doc_id, 0)
        counters[doc_id] = ordinal + 1
        # Stable for one configuration. A different size or overlap assigns
        # different ordinals, so these ids must not reuse an older extraction.
        chunk.metadata["chunk_id"] = f"{doc_id}#{ordinal}"
        chunk.metadata["ordinal"] = ordinal
        chunk.metadata["chunk_size"] = size
        chunk.metadata["chunk_overlap"] = overlap
    return chunks


def load_and_chunk(chunk_size: int | None = None,
                   chunk_overlap: int | None = None,
                   ) -> tuple[list[Document], list[Document]]:
    """Load the corpus and split it: returns (source documents, chunks).

    The graph loader needs the *sources* too, to record true document length
    (summing chunk lengths would double-count the overlap).
    """
    sources = load_corpus()
    return sources, chunk_sources(sources, chunk_size, chunk_overlap)


def chunk_documents(chunk_size: int | None = None,
                    chunk_overlap: int | None = None) -> list[Document]:
    return load_and_chunk(chunk_size, chunk_overlap)[1]


def run_ingest(chunk_size: int | None = None,
               chunk_overlap: int | None = None) -> int:
    s = get_settings()
    size, overlap = _resolved_chunk_config(chunk_size, chunk_overlap)
    chunks = chunk_documents(size, overlap)
    print(f"Split into {len(chunks)} chunks (size={size}, overlap={overlap}).")
    build_index(chunks)
    # Remember how the index was built, so baseline runs record the truth.
    s.index_info_file.write_text(json.dumps({
        "chunk_size": size, "chunk_overlap": overlap,
        "num_chunks": len(chunks), "embedding_model": s.embedding_model,
    }, indent=2), encoding="utf-8")
    target = s.qdrant_url or str(s.qdrant_path)
    print(f"Indexed into Qdrant collection '{s.collection_name}' at {target}.")
    return len(chunks)
