"""Local search over the Neo4j extracted layer.

The existing in-memory searcher stays in ``local_search``. This entry point
uses the same context selection and answer rules. Anchors come from the
Neo4j vector index, the candidate graph is a parameterized neighborhood,
and source text is ``:Chunk.text``. No score cutoff is applied to the
Neo4j anchor scores.
"""

from __future__ import annotations

from typing import Any, Callable

from .graph_merge import DomainEdge, DomainGraph, DomainNode
from .local_search import (
    REFUSAL,
    LocalAnswer,
    answer_prompt,
    cited_chunks,
    context_text,
    fit_context,
    select_context,
    subgraph_payload,
    _as_text,
)
from .neo4j_entity_index import neo4j_anchors

Query = Callable[[str, dict[str, Any]], list[dict[str, Any]]]

# Anchors, their one-hop extracted neighbors, and every extracted edge that
# touches that neighborhood. ``select_context`` still decides which rim edge
# is justified. This is not a scan of every domain edge in the database.
NEIGHBORHOOD_QUERY = """
MATCH (anchor:Extracted)
WHERE anchor.entity_key IN $anchor_keys
OPTIONAL MATCH (anchor)-[hop]-(near:Extracted)
WHERE hop.origin = 'extracted'
WITH collect(DISTINCT anchor.entity_key) AS found_anchors,
     collect(DISTINCT near.entity_key) AS near_keys
WITH found_anchors + [key IN near_keys WHERE key IS NOT NULL] AS keys
MATCH (source:Extracted)-[rel]->(target:Extracted)
WHERE rel.origin = 'extracted'
  AND (source.entity_key IN keys OR target.entity_key IN keys)
RETURN source.entity_key AS source_key,
       head([label IN labels(source) WHERE label <> 'Extracted']) AS source_label,
       source.name AS source_name,
       source.description AS source_description,
       target.entity_key AS target_key,
       head([label IN labels(target) WHERE label <> 'Extracted']) AS target_label,
       target.name AS target_name,
       target.description AS target_description,
       type(rel) AS rel_type,
       rel.rel_key AS rel_key,
       rel.from_year AS from_year,
       rel.to_year AS to_year,
       rel.role AS role,
       rel.description AS description,
       rel.source_chunk_ids AS source_chunk_ids
""".strip()

NODE_QUERY = """
MATCH (n:Extracted)
WHERE n.entity_key IN $entity_keys
RETURN n.entity_key AS entity_key,
       head([label IN labels(n) WHERE label <> 'Extracted']) AS label,
       n.name AS name,
       n.description AS description
""".strip()

MENTIONS_QUERY = """
MATCH (c:Chunk)-[:MENTIONS]->(n:Extracted)
WHERE n.entity_key IN $entity_keys
RETURN n.entity_key AS entity_key, c.chunk_id AS chunk_id
ORDER BY n.entity_key, c.chunk_id
""".strip()

CHUNK_TEXT_QUERY = """
MATCH (c:Chunk)
WHERE c.chunk_id IN $chunk_ids
RETURN c.chunk_id AS chunk_id, c.text AS text
""".strip()


def _chunks(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def _year(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _label(value: object) -> str:
    if isinstance(value, str) and value:
        return value
    return "Extracted"


def fetch_search_graph(anchor_keys: tuple[str, ...] | list[str],
                       query_fn: Query) -> DomainGraph:
    """Read the candidate extracted neighborhood. Seed edges are not queried."""
    keys = [key for key in anchor_keys if key]
    edge_rows = query_fn(NEIGHBORHOOD_QUERY, {"anchor_keys": keys}) if keys else []
    entity_keys: list[str] = []
    for key in keys:
        if key not in entity_keys:
            entity_keys.append(key)
    for row in edge_rows:
        for field in ("source_key", "target_key"):
            key = row.get(field)
            if isinstance(key, str) and key and key not in entity_keys:
                entity_keys.append(key)
    node_rows = query_fn(NODE_QUERY, {"entity_keys": entity_keys}) if entity_keys else []
    mention_rows = (
        query_fn(MENTIONS_QUERY, {"entity_keys": entity_keys}) if entity_keys else []
    )
    mentions: dict[str, list[str]] = {}
    for row in mention_rows:
        key = row.get("entity_key")
        chunk_id = row.get("chunk_id")
        if not isinstance(key, str) or not isinstance(chunk_id, str) or not chunk_id:
            continue
        bucket = mentions.setdefault(key, [])
        if chunk_id not in bucket:
            bucket.append(chunk_id)

    nodes: dict[str, DomainNode] = {}
    for row in node_rows:
        key = row.get("entity_key")
        if not isinstance(key, str) or not key:
            continue
        nodes[key] = DomainNode(
            node_id=key,
            entity_key=key,
            label=_label(row.get("label")),
            name=row.get("name") or "",
            description=row.get("description") or "",
            source_chunk_ids=tuple(mentions.get(key, ())),
        )
    edges: dict[str, DomainEdge] = {}
    for row in edge_rows:
        source = row.get("source_key")
        target = row.get("target_key")
        rel_key = row.get("rel_key")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        if not isinstance(rel_key, str) or rel_key == "":
            continue
        for key, name, description, label in (
            (source, row.get("source_name"), row.get("source_description"),
             row.get("source_label")),
            (target, row.get("target_name"), row.get("target_description"),
             row.get("target_label")),
        ):
            if key not in nodes:
                nodes[key] = DomainNode(
                    node_id=key,
                    entity_key=key,
                    label=_label(label),
                    name=name or "",
                    description=description or "",
                    source_chunk_ids=tuple(mentions.get(key, ())),
                )
        edges[rel_key] = DomainEdge(
            edge_id=rel_key,
            rel_key=rel_key,
            rel_type=str(row.get("rel_type") or ""),
            source_id=source,
            target_id=target,
            from_year=_year(row.get("from_year")),
            to_year=_year(row.get("to_year")),
            role=row.get("role") if isinstance(row.get("role"), str) else None,
            description=row.get("description") or "",
            source_chunk_ids=_chunks(row.get("source_chunk_ids")),
        )
    return DomainGraph("merged", tuple(nodes.values()), tuple(edges.values()))


def _chunk_texts(chunk_ids: list[str], query_fn: Query) -> dict[str, str]:
    if not chunk_ids:
        return {}
    rows = query_fn(CHUNK_TEXT_QUERY, {"chunk_ids": chunk_ids})
    return {
        row["chunk_id"]: row.get("text") or ""
        for row in rows
        if isinstance(row.get("chunk_id"), str)
    }


def neo4j_local_search(question: str, *, embed_query, answer_fn, query_fn: Query,
                       model: str, k: int = 3,
                       budget: dict | None = None) -> LocalAnswer:
    """Search from Neo4j anchors and the extracted neighborhood.

    ``embed_query``, ``answer_fn``, and ``query_fn`` are injected. An empty
    anchor list refuses without calling ``answer_fn``.
    """
    vector = embed_query(question)
    anchors = neo4j_anchors(vector, k=k, query_fn=query_fn, model=model)
    if not anchors:
        return LocalAnswer(
            question=question,
            answer=REFUSAL,
            refused=True,
            model_called=False,
            subgraph=subgraph_payload((), ()),
        )
    graph = fetch_search_graph(
        [item.entity_key for item in anchors], query_fn)
    chosen_nodes, chosen_edges = select_context(graph, question, anchors)
    payload = subgraph_payload(chosen_nodes, chosen_edges)
    payload["sources"] = cited_chunks(
        chosen_edges, chosen_nodes,
        _chunk_texts(payload["chunk_ids"], query_fn), question,
    )
    fitted, report = fit_context(question, payload, budget)
    prompt = answer_prompt(question, context_text(fitted))
    raw_answer = _as_text(answer_fn(prompt))
    text = raw_answer.strip()
    return LocalAnswer(
        question=question,
        answer=text,
        refused=text == REFUSAL,
        model_called=True,
        subgraph=fitted,
        anchors=tuple((item.entity_key, item.score) for item in anchors),
        prompt=prompt,
        raw_answer=raw_answer,
        context_budget=report,
    )
