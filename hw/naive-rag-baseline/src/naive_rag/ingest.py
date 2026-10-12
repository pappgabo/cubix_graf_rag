"""Build the vector index: load corpus -> chunk -> embed -> Qdrant."""

from __future__ import annotations

import json

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from .config import get_settings
from .loaders import MARKDOWN_FORMATS, load_corpus
from .vectorstore import build_index


_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]


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


def chunk_documents(chunk_size: int | None = None,
                    chunk_overlap: int | None = None) -> list[Document]:
    s = get_settings()
    size = chunk_size or s.chunk_size
    overlap = s.chunk_overlap if chunk_overlap is None else chunk_overlap
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
        add_start_index=True,
    )
    chunks = splitter.split_documents(split_by_headings(load_corpus()))
    counters: dict[str, int] = {}
    for c in chunks:
        doc_id = c.metadata.get("doc_id", "doc")
        n = counters.get(doc_id, 0)
        counters[doc_id] = n + 1
        # Stable, human-readable id used for source citation.
        c.metadata["chunk_id"] = f"{doc_id}#{n}"
    return chunks


def run_ingest(chunk_size: int | None = None,
               chunk_overlap: int | None = None) -> int:
    s = get_settings()
    size = chunk_size or s.chunk_size
    overlap = s.chunk_overlap if chunk_overlap is None else chunk_overlap
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
