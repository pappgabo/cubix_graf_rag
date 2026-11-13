"""Neo4j vector index for :Extracted entities.

Dry-run reads the graph and does not embed or write. ``--run`` embeds with
the configured model, stores vectors on the existing nodes, and creates a
cosine vector index when that exact configuration is absent.

The Neo4j query score is not the Python cosine in ``entity_index.cosine``.
This module does not apply that function's 0.25 cutoff.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any, Callable

from .entity_index import Anchor, index_text

VECTOR_INDEX_NAME = "extracted_entity_embedding"
VECTOR_PROPERTY = "embedding"

Query = Callable[..., list[dict[str, Any]]]
EmbedTexts = Callable[[list[str]], list[list[float]]]

NODE_QUERY = """
MATCH (n:Extracted)
RETURN n.entity_key AS entity_key,
       n.name AS name,
       n.description AS description,
       n.embedding_model AS embedding_model,
       n.embedding_dimensions AS embedding_dimensions,
       n.embedding_text_sha256 AS embedding_text_sha256,
       n.embedding IS NOT NULL AS has_embedding,
       CASE WHEN n.embedding IS NULL THEN 0 ELSE size(n.embedding) END
           AS embedding_size
ORDER BY n.entity_key
""".strip()

INDEX_QUERY = """
SHOW INDEXES YIELD name, type, labelsOrTypes, properties, options, state
WHERE type = 'VECTOR'
RETURN name, labelsOrTypes, properties, options, state
ORDER BY name
""".strip()

SET_EMBEDDING = """
MATCH (n:Extracted {entity_key: $entity_key})
SET n.embedding = $embedding,
    n.embedding_model = $embedding_model,
    n.embedding_dimensions = $embedding_dimensions,
    n.embedding_text_sha256 = $embedding_text_sha256
RETURN n.entity_key AS entity_key
""".strip()

VECTOR_QUERY = """
CALL db.index.vector.queryNodes($index_name, $k, $vector)
YIELD node, score
RETURN node.entity_key AS entity_key,
       node.name AS name,
       node.description AS description,
       node.embedding_model AS embedding_model,
       node.embedding_dimensions AS embedding_dimensions,
       node.embedding_text_sha256 AS embedding_text_sha256,
       score
""".strip()


class IndexRejected(RuntimeError):
    """The vector index is present with a different configuration."""


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def configured_embedding_model(settings: Any | None = None) -> str:
    """Model id only. This does not construct an embedding client."""
    if settings is None:
        from .config import get_settings

        settings = get_settings()
    if settings.llm_provider == "ollama":
        return settings.ollama_embedding_model
    return settings.embedding_model


def create_vector_index_cypher(dimensions: int) -> str:
    if not isinstance(dimensions, int) or isinstance(dimensions, bool) or dimensions < 1:
        raise IndexRejected(f"vector dimensions are not usable: {dimensions!r}")
    return (
        f"CREATE VECTOR INDEX {VECTOR_INDEX_NAME} IF NOT EXISTS\n"
        "FOR (n:Extracted) ON (n.embedding)\n"
        "OPTIONS {indexConfig: {\n"
        f"  `vector.dimensions`: {dimensions},\n"
        "  `vector.similarity_function`: 'cosine'\n"
        "}}"
    )


def _index_config(options: object) -> dict[str, Any]:
    if not isinstance(options, dict):
        return {}
    config = options.get("indexConfig")
    return config if isinstance(config, dict) else {}


def describe_index(row: dict) -> dict[str, Any]:
    config = _index_config(row.get("options"))
    labels = [str(item) for item in row.get("labelsOrTypes") or []]
    properties = [str(item) for item in row.get("properties") or []]
    similarity = config.get("vector.similarity_function")
    if isinstance(similarity, str):
        similarity = similarity.casefold()
    return {
        "name": row.get("name"),
        "state": row.get("state"),
        "labels": labels,
        "properties": properties,
        "dimensions": config.get("vector.dimensions"),
        "similarity": similarity,
    }


def _targets_extracted_embedding(info: dict) -> bool:
    return info["labels"] == ["Extracted"] and info["properties"] == [VECTOR_PROPERTY]


def index_decision(indexes: list[dict], dimensions: int | None) -> str:
    """Return ``create``, ``reuse``, or raise when a different index exists.

    Nothing is dropped. A different configuration blocks both creation and
    replacement.
    """
    described = [describe_index(row) for row in indexes]
    relevant = [item for item in described if _targets_extracted_embedding(item)]
    if not relevant:
        return "create"
    if len(relevant) != 1:
        raise IndexRejected(
            "more than one vector index targets :Extracted.embedding; "
            "none will be dropped")
    current = relevant[0]
    if (current["name"] != VECTOR_INDEX_NAME
            or current["similarity"] != "cosine"):
        raise IndexRejected(
            f"vector index {current['name']!r} has similarity "
            f"{current['similarity']!r} and dimensions {current['dimensions']!r}; "
            "it will not be dropped or replaced")
    if dimensions is None:
        return "present"
    if current["dimensions"] != dimensions:
        raise IndexRejected(
            f"vector index {current['name']!r} has dimensions "
            f"{current['dimensions']!r}, not {dimensions}; "
            "it will not be dropped or replaced")
    return "reuse"


def _readable(row: dict) -> bool:
    return isinstance(row.get("entity_key"), str) and row["entity_key"] != "" \
        and isinstance(row.get("name"), str)


def classify_row(row: dict, *, model: str) -> str:
    """``reusable``, ``stale``, ``missing``, or ``unreadable``."""
    if not _readable(row):
        return "unreadable"
    digest = text_hash(index_text(row["name"], row.get("description")))
    if not row.get("has_embedding"):
        return "missing"
    dimensions = row.get("embedding_dimensions")
    size = row.get("embedding_size")
    if (row.get("embedding_model") == model
            and row.get("embedding_text_sha256") == digest
            and isinstance(dimensions, int) and not isinstance(dimensions, bool)
            and dimensions > 0 and dimensions == size):
        return "reusable"
    return "stale"


def plan_index(rows: list[dict], indexes: list[dict], *,
               model: str) -> dict[str, Any]:
    counts = {"reusable": 0, "stale": 0, "missing": 0, "unreadable": 0}
    dimensions: set[int] = set()
    for row in rows:
        kind = classify_row(row, model=model)
        counts[kind] += 1
        if kind == "reusable":
            dimensions.add(row["embedding_dimensions"])
    described = [describe_index(row) for row in indexes]
    relevant = [item for item in described if _targets_extracted_embedding(item)]
    known_dimensions = next(iter(dimensions)) if len(dimensions) == 1 else None
    decision = None
    decision_error = None
    if len(dimensions) > 1:
        decision_error = "reusable vectors have different dimensions"
    else:
        try:
            decision = index_decision(indexes, known_dimensions)
        except IndexRejected as exc:
            decision_error = str(exc)
    return {
        "model": model,
        "entities": len(rows),
        "existing_vectors": counts["reusable"] + counts["stale"],
        "reusable_vectors": counts["reusable"],
        "vectors_to_create": counts["missing"] + counts["stale"],
        "unreadable": counts["unreadable"],
        "dimensions": sorted(dimensions),
        "indexes": relevant,
        "index_decision": decision,
        "index_error": decision_error,
    }


def plan_summary(plan: dict) -> str:
    lines = [
        "write: no",
        f"entities: {plan['entities']}",
        f"embedding_model: {plan['model']}",
        f"existing_vectors: {plan['existing_vectors']}",
        f"reusable_vectors: {plan['reusable_vectors']}",
        f"vectors_to_create: {plan['vectors_to_create']}",
        f"unreadable: {plan['unreadable']}",
    ]
    if not plan["indexes"]:
        lines.append("vector_index: none")
    for item in plan["indexes"]:
        lines.append(
            "vector_index: "
            f"name={item['name']} state={item['state']} "
            f"similarity={item['similarity']} dimensions={item['dimensions']}"
        )
    if plan["index_error"]:
        lines.append(f"index_decision: blocked {plan['index_error']}")
    else:
        lines.append(f"index_decision: {plan['index_decision']}")
    return "\n".join(lines)


def neo4j_anchors(query_vector: list[float] | tuple[float, ...], *,
                  k: int, query_fn: Query, model: str,
                  index_name: str = VECTOR_INDEX_NAME) -> tuple[Anchor, ...]:
    """Nearest extracted entities according to the Neo4j vector index.

    ``Anchor.score`` is the score Neo4j returned. It is not checked against
    the in-memory cosine cutoff. Rows for another model, another indexed
    text, or another dimension are omitted and not replaced.
    """
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise ValueError("k must be a positive integer")
    rows = query_fn(VECTOR_QUERY, {
        "index_name": index_name,
        "k": k,
        "vector": [float(item) for item in query_vector],
    })
    anchors: list[Anchor] = []
    width = len(query_vector)
    for row in rows:
        if not _readable(row):
            continue
        digest = text_hash(index_text(row["name"], row.get("description")))
        if row.get("embedding_model") != model:
            continue
        if row.get("embedding_text_sha256") != digest:
            continue
        if row.get("embedding_dimensions") != width:
            continue
        anchors.append(Anchor(row["entity_key"], float(row["score"])))
    return tuple(anchors)


def _read_query(cypher: str, params: dict | None = None) -> list[dict[str, Any]]:
    from .graph import query

    return query(cypher, **(params or {}))


def load_plan(query_fn: Query | None = None, *,
              model: str | None = None) -> dict[str, Any]:
    reader = query_fn if query_fn is not None else _read_query
    chosen = model if model is not None else configured_embedding_model()
    return plan_index(reader(NODE_QUERY), reader(INDEX_QUERY), model=chosen)


def copy_matching_embeddings(path: Path, query_fn: Query, write_fn: Query, *,
                             model: str, dimensions: int) -> int:
    """Copy backup vectors onto current entities when the text still matches.

    The backup text hash, model, and dimension must agree with the current
    entity's embedding input. A hash is usable only when it also matches the
    backup node's own name and description. Conflicting vectors for one hash
    are refused before any write.
    """
    from .extraction_load import _embedding_params, read_extracted_backup

    if not isinstance(dimensions, int) or isinstance(dimensions, bool) or dimensions < 1:
        raise IndexRejected(f"vector dimensions are not usable: {dimensions!r}")
    payload = read_extracted_backup(path)
    by_hash: dict[str, list[float]] = {}
    for node in payload["nodes"]:
        props = node["properties"]
        stored = _embedding_params(props)
        if stored is None:
            continue
        if (stored["embedding_model"] != model
                or stored["embedding_dimensions"] != dimensions):
            continue
        name = props.get("name")
        if not isinstance(name, str):
            continue
        digest = text_hash(index_text(name, props.get("description")))
        if stored["embedding_text_sha256"] != digest:
            continue
        previous = by_hash.get(digest)
        if previous is not None and previous != stored["embedding"]:
            raise IndexRejected(
                "backup has two different vectors for one embedding text")
        by_hash[digest] = stored["embedding"]
    rows = query_fn(NODE_QUERY)
    pending: list[dict] = []
    vectors: list[list[float]] = []
    for row in rows:
        if not _readable(row):
            continue
        digest = text_hash(index_text(row["name"], row.get("description")))
        vector = by_hash.get(digest)
        if vector is None:
            continue
        pending.append(row)
        vectors.append(vector)
    if not pending:
        return 0
    return _write_embeddings(pending, vectors, model=model, write_fn=write_fn)


def _write_embeddings(rows: list[dict], vectors: list[list[float]], *,
                      model: str, write_fn: Query) -> int:
    if len(rows) != len(vectors):
        raise ValueError("The embedder returned a different number of vectors.")
    written = 0
    for row, vector in zip(rows, vectors):
        if not vector:
            raise ValueError(f"empty vector for {row['entity_key']}")
        text = index_text(row["name"], row.get("description"))
        found = write_fn(SET_EMBEDDING, {
            "entity_key": row["entity_key"],
            "embedding": [float(item) for item in vector],
            "embedding_model": model,
            "embedding_dimensions": len(vector),
            "embedding_text_sha256": text_hash(text),
        })
        if not found:
            raise RuntimeError(
                f"no :Extracted node for {row['entity_key']}; nothing else is written")
        written += 1
    return written


def build_neo4j_index(query_fn: Query, write_fn: Query, embed_texts: EmbedTexts, *,
                      model: str) -> dict[str, Any]:
    """Embed missing or stale texts and store them by entity_key.

    Creates the cosine index only when :Extracted.embedding has no index.
    A different existing index is left in place and this function stops
    before writing vectors.
    """
    rows = query_fn(NODE_QUERY)
    indexes = query_fn(INDEX_QUERY)
    plan = plan_index(rows, indexes, model=model)
    if plan["unreadable"]:
        raise IndexRejected("an :Extracted node has no entity_key or name")
    if plan["index_error"]:
        raise IndexRejected(plan["index_error"])
    pending = [row for row in rows if classify_row(row, model=model) != "reusable"]
    vectors: list[list[float]] = []
    if pending:
        texts = [index_text(row["name"], row.get("description")) for row in pending]
        vectors = [list(item) for item in embed_texts(texts)]
        widths = {len(vector) for vector in vectors}
        if len(widths) != 1:
            raise IndexRejected("the embedder returned mixed dimensions")
        width = next(iter(widths))
        if plan["dimensions"] and plan["dimensions"] != [width]:
            raise IndexRejected(
                "new vectors do not match the reusable dimension; "
                "no vector was written")
        index_decision(indexes, width)
    elif plan["dimensions"]:
        width = plan["dimensions"][0]
        index_decision(indexes, width)
    else:
        width = None
    if pending:
        _write_embeddings(pending, vectors, model=model, write_fn=write_fn)
    if width is not None and index_decision(indexes, width) == "create":
        write_fn(create_vector_index_cypher(width), {})
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m naive_rag.neo4j_entity_index")
    parser.add_argument("--run", action="store_true",
                        help="embed, store vectors, and create the cosine index")
    args = parser.parse_args(argv)
    if not args.run:
        print(plan_summary(load_plan()))
        return 0
    from .models import get_embeddings

    model = configured_embedding_model()
    embedder = get_embeddings()
    build_neo4j_index(_read_query, _read_query, embedder.embed_documents, model=model)
    print("write: yes")
    print(plan_summary(load_plan(model=model)).replace("write: no", "write: yes", 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
