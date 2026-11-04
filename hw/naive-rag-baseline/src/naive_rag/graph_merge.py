"""Occurrence graph and merged domain graph from raw extraction records.

Both graphs contain only entities and relationships that passed structural
validation (``status == ok``). They do not contain seed nodes, document
nodes, or MENTIONS edges.

An occurrence node is one entity inside one chunk. An occurrence edge is
one relationship inside that chunk. Endpoints are the chunk-local
occurrences, not the durable keys.

A merged node is one ``entity_key``. A merged edge is one ``rel_key``.
Sources are the union of the chunk ids, in first-seen order. Descriptions
are the union of description lines. Different years or roles stay different
edges because they are part of ``rel_key``.

``ALIAS_MAP`` is the only alias list. It is empty: normalization already
decides which names share a key. No extra names are merged.

Weak connectivity ignores edge direction. An isolated node is a component
of one node. The reported size is the number of nodes in the largest such
component, not the number of edges.
"""

from __future__ import annotations

from dataclasses import dataclass

from .extraction_identity import (
    make_entity_key,
    make_rel_key,
    merge_descriptions,
    merge_source_ids,
)
from .extraction_models import ExtractionResult, validate_extraction

# entity_key -> canonical entity_key. Empty until a reviewed pair is added.
ALIAS_MAP: dict[str, str] = {}

COMPONENT_MEANING = (
    "Az irányított szakterületi gráf legnagyobb gyengén összefüggő "
    "komponense: az irány nem számít, a méret a csomópontok száma. "
    "A seed, a dokumentumgráf és a MENTIONS élek nincsenek benne."
)


@dataclass(frozen=True)
class DomainNode:
    node_id: str
    entity_key: str
    label: str
    name: str
    description: str
    source_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class DomainEdge:
    edge_id: str
    rel_key: str
    rel_type: str
    source_id: str
    target_id: str
    from_year: int | None
    to_year: int | None
    role: str | None
    description: str
    source_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class DomainGraph:
    kind: str
    nodes: tuple[DomainNode, ...]
    edges: tuple[DomainEdge, ...]


def canonical_key(entity_key: str) -> str:
    """Apply ``ALIAS_MAP``. The map is empty, so this returns the key."""
    seen = set()
    current = entity_key
    while current in ALIAS_MAP and current not in seen:
        seen.add(current)
        current = ALIAS_MAP[current]
    return current


def occurrence_graph(records: list[dict]) -> DomainGraph:
    """One node and edge per accepted occurrence. No cross-chunk merge."""
    nodes: list[DomainNode] = []
    edges: list[DomainEdge] = []
    for record in records:
        result = _accepted_result(record)
        if result is None:
            continue
        chunk_id = str(record["chunk_id"])
        local_keys: dict[str, str] = {}
        for entity in result.entities:
            node_id = f"{chunk_id}|{entity.local_id}"
            key = canonical_key(make_entity_key(entity.entity_type, entity.name))
            local_keys[entity.local_id] = node_id
            nodes.append(DomainNode(
                node_id=node_id,
                entity_key=key,
                label=entity.entity_type.value,
                name=entity.name,
                description=entity.description or "",
                source_chunk_ids=(chunk_id,),
            ))
        for index, rel in enumerate(result.relationships):
            edges.append(DomainEdge(
                edge_id=f"{chunk_id}|r{index}",
                rel_key=make_rel_key(
                    canonical_key(make_entity_key(
                        _type_of(result, rel.source_id),
                        _name_of(result, rel.source_id),
                    )),
                    rel.relationship_type.value,
                    canonical_key(make_entity_key(
                        _type_of(result, rel.target_id),
                        _name_of(result, rel.target_id),
                    )),
                    rel.from_year,
                    rel.to_year,
                    rel.role,
                ),
                rel_type=rel.relationship_type.value,
                source_id=local_keys[rel.source_id],
                target_id=local_keys[rel.target_id],
                from_year=rel.from_year,
                to_year=rel.to_year,
                role=rel.role,
                description=rel.description,
                source_chunk_ids=(chunk_id,),
            ))
    return DomainGraph("occurrence", tuple(nodes), tuple(edges))


def merged_graph(records: list[dict]) -> DomainGraph:
    """One node per entity_key and one edge per rel_key."""
    nodes: dict[str, DomainNode] = {}
    edges: dict[str, DomainEdge] = {}
    for record in records:
        result = _accepted_result(record)
        if result is None:
            continue
        chunk_id = str(record["chunk_id"])
        keys: dict[str, str] = {}
        for entity in result.entities:
            key = canonical_key(make_entity_key(entity.entity_type, entity.name))
            keys[entity.local_id] = key
            previous = nodes.get(key)
            sources = merge_source_ids(
                list(previous.source_chunk_ids) if previous else None,
                chunk_id,
            )
            description = merge_descriptions(
                previous.description if previous else None,
                entity.description or "",
            )
            nodes[key] = DomainNode(
                node_id=key,
                entity_key=key,
                label=entity.entity_type.value,
                name=previous.name if previous else entity.name,
                description=description,
                source_chunk_ids=tuple(sources or []),
            )
        for rel in result.relationships:
            source_key = keys[rel.source_id]
            target_key = keys[rel.target_id]
            rel_key = make_rel_key(
                source_key, rel.relationship_type.value, target_key,
                rel.from_year, rel.to_year, rel.role,
            )
            previous = edges.get(rel_key)
            sources = merge_source_ids(
                list(previous.source_chunk_ids) if previous else None,
                chunk_id,
            )
            description = merge_descriptions(
                previous.description if previous else None,
                rel.description,
            )
            edges[rel_key] = DomainEdge(
                edge_id=rel_key,
                rel_key=rel_key,
                rel_type=rel.relationship_type.value,
                source_id=source_key,
                target_id=target_key,
                from_year=rel.from_year,
                to_year=rel.to_year,
                role=rel.role,
                description=description,
                source_chunk_ids=tuple(sources or []),
            )
    return DomainGraph(
        "merged",
        tuple(nodes.values()),
        tuple(edges.values()),
    )


def undirected_degree(graph: DomainGraph) -> dict[str, int]:
    """Incident domain edges, with direction ignored. MENTIONS is absent."""
    degree = {node.node_id: 0 for node in graph.nodes}
    for edge in graph.edges:
        if edge.source_id in degree:
            degree[edge.source_id] += 1
        if edge.target_id in degree and edge.target_id != edge.source_id:
            degree[edge.target_id] += 1
    return degree


def largest_weak_component_size(graph: DomainGraph) -> int:
    """Node count of the largest component when direction is ignored."""
    adjacent: dict[str, set[str]] = {node.node_id: set() for node in graph.nodes}
    for edge in graph.edges:
        adjacent.setdefault(edge.source_id, set()).add(edge.target_id)
        adjacent.setdefault(edge.target_id, set()).add(edge.source_id)
    seen: set[str] = set()
    largest = 0
    for start in adjacent:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        size = 0
        while stack:
            current = stack.pop()
            size += 1
            for nxt in adjacent[current]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if size > largest:
            largest = size
    return largest


def measure(graph: DomainGraph) -> dict[str, int | str]:
    return {
        "kind": graph.kind,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "largest_weak_component_nodes": largest_weak_component_size(graph),
        "component_meaning": COMPONENT_MEANING,
    }


def _accepted_result(record: dict) -> ExtractionResult | None:
    if record.get("status") != "ok":
        return None
    result = ExtractionResult.model_validate(record["result"])
    validate_extraction(result)
    return result


def _type_of(result: ExtractionResult, local_id: str):
    for entity in result.entities:
        if entity.local_id == local_id:
            return entity.entity_type
    raise KeyError(local_id)


def _name_of(result: ExtractionResult, local_id: str) -> str:
    for entity in result.entities:
        if entity.local_id == local_id:
            return entity.name
    raise KeyError(local_id)
