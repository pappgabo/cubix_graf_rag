"""In-memory entity index. The embedding input is name and description.

No embedding client is constructed on import. The caller supplies vectors,
or `--run` builds them with the configured embedding model. A missing
description stays empty; this module does not fill it with a chat model.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .graph_merge import DomainGraph, DomainNode


def index_text(name: str, description: str | None) -> str:
    """Text that is embedded for one entity. Both parts are always present."""
    return f"{name}\n{description or ''}"


@dataclass(frozen=True)
class IndexedEntity:
    entity_key: str
    label: str
    name: str
    description: str
    text: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class Anchor:
    entity_key: str
    score: float


class EntityIndex:
    def __init__(self, entities: tuple[IndexedEntity, ...]) -> None:
        self.entities = entities
        self.by_key = {item.entity_key: item for item in entities}

    def anchor(self, query_vector: list[float] | tuple[float, ...], *,
               k: int = 3, min_score: float = 0.25) -> tuple[Anchor, ...]:
        """Highest cosine scores at or above `min_score`, at most `k`."""
        scored = [
            Anchor(item.entity_key, cosine(query_vector, item.vector))
            for item in self.entities
        ]
        scored.sort(key=lambda item: (-item.score, item.entity_key))
        return tuple(item for item in scored if item.score >= min_score)[:k]


def build_index(graph: DomainGraph,
                embed_texts) -> EntityIndex:
    """Embed each merged entity once. `embed_texts` receives the index texts."""
    if graph.kind != "merged":
        raise ValueError("The entity index is built from the merged domain graph.")
    ordered = tuple(sorted(graph.nodes, key=lambda node: node.entity_key))
    texts = [index_text(node.name, node.description) for node in ordered]
    vectors = list(embed_texts(texts)) if texts else []
    if len(vectors) != len(texts):
        raise ValueError("The embedder returned a different number of vectors.")
    entities = tuple(
        _indexed(node, texts[index], vectors[index])
        for index, node in enumerate(ordered)
    )
    return EntityIndex(entities)


def cosine(left, right) -> float:
    left_list = [float(item) for item in left]
    right_list = [float(item) for item in right]
    if not left_list or len(left_list) != len(right_list):
        return 0.0
    dot = sum(a * b for a, b in zip(left_list, right_list))
    left_norm = math.sqrt(sum(a * a for a in left_list))
    right_norm = math.sqrt(sum(b * b for b in right_list))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def save_index(index: EntityIndex, path: Path) -> None:
    payload = {
        "entities": [
            {
                "entity_key": item.entity_key,
                "label": item.label,
                "name": item.name,
                "description": item.description,
                "text": item.text,
                "vector": list(item.vector),
            }
            for item in index.entities
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def load_index(path: Path) -> EntityIndex:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entities = tuple(
        IndexedEntity(
            entity_key=item["entity_key"],
            label=item["label"],
            name=item["name"],
            description=item["description"],
            text=item["text"],
            vector=tuple(item["vector"]),
        )
        for item in payload["entities"]
    )
    return EntityIndex(entities)


def main(argv: list[str] | None = None) -> int:
    """Count index texts. Embed only when ``--run`` is set."""
    parser = argparse.ArgumentParser(prog="python -m naive_rag.entity_index")
    parser.add_argument("--extraction-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--run", action="store_true",
                        help="call the configured embedding model")
    args = parser.parse_args(argv)
    from .graph_merge import merged_graph
    from .quality_report import load_records

    graph = merged_graph(load_records(Path(args.extraction_dir)))
    ordered = tuple(sorted(graph.nodes, key=lambda node: node.entity_key))
    print(f"entities: {len(ordered)}")
    for node in ordered:
        print(index_text(node.name, node.description).split("\n", 1)[0])
    if not args.run:
        print("no embedding call (--run not set)")
        return 0
    from .models import get_embeddings

    index = build_index(graph, get_embeddings().embed_documents)
    save_index(index, Path(args.out))
    print(f"wrote {args.out}")
    return 0


def _indexed(node: DomainNode, text: str, vector) -> IndexedEntity:
    return IndexedEntity(
        entity_key=node.entity_key,
        label=node.label,
        name=node.name,
        description=node.description,
        text=text,
        vector=tuple(float(item) for item in vector),
    )


if __name__ == "__main__":
    raise SystemExit(main())
