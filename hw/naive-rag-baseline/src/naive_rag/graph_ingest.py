"""Document graph: the real corpus as nodes, with no entity extraction.

    (:Corpus)-[:HAS_DOCUMENT]->(:Document)-[:CONTAINS]->(:Chunk)
                                         -[:HAS_SECTION]->(:Section)-[:CONTAINS]->
                               (:Chunk)-[:NEXT_CHUNK]->(:Chunk)

Chunks come from `ingest.load_and_chunk()`, i.e. exactly the same splitter and
the same `chunk_id`s as the Qdrant index. That is deliberate: a chunk_id from a
vector hit can be looked up in the graph (and vice versa) without a mapping
table, which is what the hybrid retriever in a later week needs.

Idempotency is mark-and-sweep: every node is MERGEd on its business key and
stamped with this run's `run_id`, then anything in this corpus still carrying
an older stamp is deleted. So re-running never duplicates, and re-running with
a different chunk size leaves no stale chunks behind.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from itertools import pairwise

from langchain_core.documents import Document

from .config import get_settings
from .graph import query, write_batched
from .ingest import load_and_chunk

# Chunk metadata copied onto the node. `source` is the citation handle (URL or
# file name) that week 1 already settled on; `page` / `section` / `ordinal` are
# the location metadata the task asks for.
_CHUNK_PROPS = ["chunk_id", "doc_id", "ordinal", "page", "section",
                "start_index", "source"]

_WORD = re.compile(r"\S+")

_MERGE_CORPUS = """
MERGE (c:Corpus {name: $name})
  ON CREATE SET c.created_at = datetime()
SET c.updated_at = datetime(), c.run_id = $run_id,
    c.chunk_size = $chunk_size, c.chunk_overlap = $chunk_overlap
"""

_MERGE_DOCUMENTS = """
UNWIND $rows AS row
MATCH (corpus:Corpus {name: $corpus})
MERGE (d:Document {doc_id: row.doc_id})
SET d += row.props, d.run_id = $run_id
MERGE (corpus)-[:HAS_DOCUMENT]->(d)
"""

_MERGE_SECTIONS = """
UNWIND $rows AS row
MATCH (d:Document {doc_id: row.doc_id})
MERGE (s:Section {section_id: row.section_id})
SET s += row.props, s.run_id = $run_id
MERGE (d)-[:HAS_SECTION]->(s)
"""

_MERGE_CHUNKS = """
UNWIND $rows AS row
MATCH (d:Document {doc_id: row.doc_id})
MERGE (c:Chunk {chunk_id: row.chunk_id})
SET c += row.props, c.text = row.text, c.run_id = $run_id
MERGE (d)-[:CONTAINS]->(c)
WITH row, c
WHERE row.section_id IS NOT NULL
MATCH (s:Section {section_id: row.section_id})
MERGE (s)-[:CONTAINS]->(c)
"""

# Reading order inside a document. Directed: `a -[:NEXT_CHUNK]-> b` means b
# follows a, which is what lets a retriever widen a hit to its neighbours.
_MERGE_NEXT = """
UNWIND $rows AS row
MATCH (a:Chunk {chunk_id: row.prev})
MATCH (b:Chunk {chunk_id: row.next})
MERGE (a)-[:NEXT_CHUNK]->(b)
"""

# --- sweep: drop what an earlier run left behind ---------------------------
# `run_id` is cheaper than passing thousands of ids back as a NOT IN list, and
# it also catches nodes whose key changed (e.g. after a chunk-size change).
_SWEEP = """
MATCH (:Corpus {name: $name})-[:HAS_DOCUMENT]->(d:Document)
OPTIONAL MATCH (d)-[:CONTAINS|HAS_SECTION]->(child)
WITH collect(DISTINCT d) + collect(DISTINCT child) AS nodes
UNWIND nodes AS n
WITH n WHERE n IS NOT NULL AND coalesce(n.run_id, '') <> $run_id
DETACH DELETE n
RETURN count(*) AS deleted
"""


def _section_id(doc_id: str, section: str) -> str:
    return f"{doc_id}::{section}"


def _document_rows(sources: list[Document], chunks: list[Document],
                   corpus_name: str) -> list[dict]:
    """One row per document, with aggregates measured on the source text."""
    meta_keys = ["title", "file", "format", "category", "url", "source",
                 "license", "revision_id", "revision_timestamp"]
    by_doc: dict[str, dict] = {}
    for d in sources:
        doc_id = d.metadata["doc_id"]
        row = by_doc.setdefault(doc_id, {
            "doc_id": doc_id,
            "corpus": corpus_name,
            "props": {k: d.metadata[k] for k in meta_keys
                      if d.metadata.get(k) is not None},
        })
        props = row["props"]
        props["n_chars"] = props.get("n_chars", 0) + len(d.page_content)
        if d.metadata.get("page") is not None:
            props["n_pages"] = max(props.get("n_pages", 0), d.metadata["page"])

    for c in chunks:
        props = by_doc[c.metadata["doc_id"]]["props"]
        props["n_chunks"] = props.get("n_chunks", 0) + 1
    return list(by_doc.values())


def _section_rows(chunks: list[Document]) -> list[dict]:
    """One row per (document, section path), in order of first appearance."""
    rows: dict[str, dict] = {}
    ordinals: dict[str, int] = {}
    for c in chunks:
        section = c.metadata.get("section")
        if not section:
            continue
        doc_id = c.metadata["doc_id"]
        sid = _section_id(doc_id, section)
        if sid in rows:
            continue
        ordinal = ordinals.get(doc_id, 0)
        ordinals[doc_id] = ordinal + 1
        parts = [p.strip() for p in section.split(">")]
        rows[sid] = {
            "doc_id": doc_id,
            "section_id": sid,
            "props": {
                "path": section,
                "title": parts[-1],
                "level": len(parts),
                "ordinal": ordinal,
                "doc_id": doc_id,
            },
        }
    return list(rows.values())


def _chunk_rows(chunks: list[Document]) -> list[dict]:
    rows = []
    for c in chunks:
        m = c.metadata
        section = m.get("section")
        text = c.page_content
        props = {k: m[k] for k in _CHUNK_PROPS if m.get(k) is not None}
        # Counted here rather than in Cypher: `split(text, ' ')` would count
        # newlines as part of a word and miscount the short/garbage chunks
        # that query Q4 is looking for.
        props["n_chars"] = len(text)
        props["n_words"] = len(_WORD.findall(text))
        rows.append({
            "chunk_id": m["chunk_id"],
            "doc_id": m["doc_id"],
            "text": text,
            "section_id": _section_id(m["doc_id"], section) if section
                          else None,
            "props": props,
        })
    return rows


def _next_rows(chunks: list[Document]) -> list[dict]:
    rows = []
    for prev, nxt in pairwise(chunks):
        if prev.metadata["doc_id"] == nxt.metadata["doc_id"]:
            rows.append({"prev": prev.metadata["chunk_id"],
                         "next": nxt.metadata["chunk_id"]})
    return rows


def load_document_graph(chunk_size: int | None = None,
                        chunk_overlap: int | None = None) -> dict[str, int]:
    """Load corpus -> Document / Section / Chunk nodes. Safe to re-run."""
    s = get_settings()
    size = chunk_size or s.chunk_size
    overlap = s.chunk_overlap if chunk_overlap is None else chunk_overlap
    sources, chunks = load_and_chunk(size, overlap)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    doc_rows = _document_rows(sources, chunks, s.corpus_name)
    section_rows = _section_rows(chunks)
    chunk_rows = _chunk_rows(chunks)
    next_rows = _next_rows(chunks)

    query(_MERGE_CORPUS, name=s.corpus_name, run_id=run_id,
          chunk_size=size, chunk_overlap=overlap)
    write_batched(_MERGE_DOCUMENTS, doc_rows,
                  corpus=s.corpus_name, run_id=run_id)
    write_batched(_MERGE_SECTIONS, section_rows, run_id=run_id)
    # Chunks carry the full text, so keep the batches small.
    write_batched(_MERGE_CHUNKS, chunk_rows, batch_size=200, run_id=run_id)
    write_batched(_MERGE_NEXT, next_rows, batch_size=1000)

    return {
        "documents": len(doc_rows),
        "sections": len(section_rows),
        "chunks": len(chunk_rows),
        "next_chunk_edges": len(next_rows),
        "swept_stale_nodes": query(_SWEEP, name=s.corpus_name,
                                   run_id=run_id)[0]["deleted"],
    }
