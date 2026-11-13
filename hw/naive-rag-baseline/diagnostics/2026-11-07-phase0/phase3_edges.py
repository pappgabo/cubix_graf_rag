"""Phase 3 edge replay. Read-only Neo4j, no embedding and no answer call.

``--before`` records the edges ``select_context`` keeps for Q01–Q13.
``--after`` records them again and lists added and removed edges.
``--loops`` lists self-loops in the saved extraction files. No database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neo4j import READ_ACCESS  # noqa: E402

from naive_rag.graph import GraphUnavailable, get_driver, get_settings  # noqa: E402
from naive_rag import local_search as search  # noqa: E402
from naive_rag.local_search import select_context  # noqa: E402
from naive_rag.neo4j_local_search import fetch_search_graph  # noqa: E402

RUN = ROOT / "docs" / "osszehasonlitas-section-1200-23-run.json"
EXTRACTION = ROOT / "graph" / "corpus" / "extraction-reuse-1200-23"
_WRITE = frozenset({"CREATE", "MERGE", "SET", "DELETE", "REMOVE", "DROP", "INSERT"})


class WriteRefused(RuntimeError):
    """The statement is not a read. It was not sent."""


def write_keywords(cypher: str) -> list[str]:
    found: list[str] = []
    i = 0
    n = len(cypher)
    while i < n:
        char = cypher[i]
        if char.isspace():
            i += 1
            continue
        if char == "/" and i + 1 < n and cypher[i + 1] == "/":
            newline = cypher.find("\n", i)
            i = n if newline < 0 else newline + 1
            continue
        if char == "/" and i + 1 < n and cypher[i + 1] == "*":
            end = cypher.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if char in "'\"":
            quote = char
            i += 1
            while i < n:
                if cypher[i] == "\\":
                    i += 2
                    continue
                if cypher[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if char == "`":
            i += 1
            while i < n and cypher[i] != "`":
                i += 1
            i = min(i + 1, n)
            continue
        if char.isalpha() or char == "_":
            end = i + 1
            while end < n and (cypher[end].isalnum() or cypher[end] == "_"):
                end += 1
            word = cypher[i:end].upper()
            if word in _WRITE:
                found.append(word)
            i = end
            continue
        i += 1
    return found


def question_of(prompt: str) -> str:
    start = prompt.find("Kérdés: ")
    end = prompt.find("\n\nKontextus:")
    if start < 0 or end < 0:
        raise ValueError("saved prompt has no question")
    return prompt[start + len("Kérdés: "):end]


def read_query(session, cypher: str, params: dict) -> list[dict]:
    keywords = write_keywords(cypher)
    if keywords:
        raise WriteRefused(
            "refused before sending; write keyword: " + ", ".join(keywords))

    def work(tx):
        result = tx.run(cypher, params)
        return [record.data() for record in result]

    return session.execute_read(work)


def edge_row(edge) -> dict:
    return {
        "rel_key": edge.rel_key,
        "rel_type": edge.rel_type,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
    }


def legacy_rank(edge, terms, years, names, anchor_set):
    """The sort key before this phase named it. Same four elements."""
    return (
        -search._hits(edge, terms, years, names),
        -int(search._year_match(edge, years)),
        -len({edge.source_id, edge.target_id} & anchor_set),
        edge.rel_key,
    )


def choose(graph, question, anchors, rank):
    previous = search._context_rank
    search._context_rank = rank
    try:
        _nodes, edges = select_context(graph, question, anchors)
    finally:
        search._context_rank = previous
    return edges


def selected(session, rows: list[dict]) -> list[dict]:
    def query_fn(cypher: str, params: dict) -> list[dict]:
        return read_query(session, cypher, params)

    checked = []
    for row in rows:
        print(f"  start {row['id']}", flush=True)
        question = question_of(row["prompt"])
        anchors = tuple(
            (item["entity_key"], float(item["score"])) for item in row["anchors"]
        )
        graph = fetch_search_graph([key for key, _score in anchors], query_fn)
        before = choose(graph, question, anchors, legacy_rank)
        after = choose(graph, question, anchors, search._context_rank)
        removed = [edge.rel_key for edge in before if edge.rel_key not in {item.rel_key for item in after}]
        added = [edge.rel_key for edge in after if edge.rel_key not in {item.rel_key for item in before}]
        by_key = {edge.rel_key: edge for edge in (*before, *after)}
        print(
            f"  checked {row['id']} edges={len(after)} "
            f"removed={len(removed)} added={len(added)}",
            flush=True,
        )
        checked.append({
            "id": row["id"],
            "edges": [edge_row(edge) for edge in after],
            "removed": [edge_row(by_key[key]) for key in removed],
            "added": [edge_row(by_key[key]) for key in added],
        })
    return checked


def scan_loops() -> dict:
    local_hits = []
    for path in sorted(EXTRACTION.glob("*.json")):
        saved = json.loads(path.read_text(encoding="utf-8"))
        result = saved.get("result") or {}
        relationships = result.get("relationships") or []
        entities = {
            entity.get("local_id"): entity.get("name")
            for entity in result.get("entities") or []
            if isinstance(entity, dict)
        }
        for index, rel in enumerate(relationships):
            if not isinstance(rel, dict):
                continue
            if rel.get("source_id") != rel.get("target_id"):
                continue
            description = rel.get("description") or ""
            local_hits.append({
                "file": path.name,
                "index": index,
                "relationship_type": rel.get("relationship_type"),
                "local_id": rel.get("source_id"),
                "name": entities.get(rel.get("source_id")) or "",
                "description": description[:180],
            })
    return {"local_source_equals_target": local_hits}


def diff_edges(before: list[dict], after: list[dict]) -> list[dict]:
    after_by_id = {row["id"]: row for row in after}
    changed = []
    for row in before:
        previous = [edge["rel_key"] for edge in row["edges"]]
        current_edges = after_by_id[row["id"]]["edges"]
        current = [edge["rel_key"] for edge in current_edges]
        by_key = {edge["rel_key"]: edge for edge in current_edges}
        by_key.update({edge["rel_key"]: edge for edge in row["edges"]})
        removed = [key for key in previous if key not in current]
        added = [key for key in current if key not in previous]
        changed.append({
            "id": row["id"],
            "removed": [by_key[key] for key in removed],
            "added": [by_key[key] for key in added],
        })
    return changed


def main() -> int:
    destination = HERE / "results"
    destination.mkdir(exist_ok=True)
    if "--loops" in sys.argv:
        found = scan_loops()
        (destination / "phase3_loops.json").write_text(
            json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
        print(
            "local self-loops: "
            f"{len(found['local_source_equals_target'])}"
        )
        for item in found["local_source_equals_target"]:
            print(
                f"  {item['file']} {item['relationship_type']} "
                f"{item['name']} | {item['description']}"
            )
        return 0

    print("imported select_context", flush=True)
    try:
        settings = get_settings()
        driver = get_driver()
        database = settings.neo4j_database
    except GraphUnavailable:
        print("Neo4j connection failed. No query was sent.")
        return 1
    rows = json.loads(RUN.read_text(encoding="utf-8"))
    try:
        with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
            checked = selected(session, rows)
    except WriteRefused as exc:
        print(str(exc))
        return 2
    changes = [
        {"id": item["id"], "removed": item["removed"], "added": item["added"]}
        for item in checked
    ]
    (destination / "phase3_edges_after.json").write_text(
        json.dumps(checked, ensure_ascii=False, indent=1), encoding="utf-8")
    (destination / "phase3_edge_diff.json").write_text(
        json.dumps(changes, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote phase3_edge_diff.json")
    for item in changes:
        print(
            f"  {item['id']} removed={len(item['removed'])} "
            f"added={len(item['added'])}"
        )
        for edge in item["removed"]:
            print(f"    - {edge['source_id']} {edge['rel_type']} {edge['target_id']}")
        for edge in item["added"]:
            print(f"    + {edge['source_id']} {edge['rel_type']} {edge['target_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
