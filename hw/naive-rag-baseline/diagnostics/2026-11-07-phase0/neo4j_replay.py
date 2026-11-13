"""Replay the saved local-search prompts from Neo4j.

Reads the saved anchors, then calls ``fetch_search_graph`` and
``_chunk_texts``. No embedding call and no answer call. The session is
read-only. A statement that writes is refused before it is sent.
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
from naive_rag.graph_merge import merged_graph  # noqa: E402
from naive_rag.local_search import (  # noqa: E402
    answer_prompt,
    cited_chunks,
    context_text,
    fit_context,
    select_context,
    subgraph_payload,
)
from naive_rag.neo4j_local_search import (  # noqa: E402
    _chunk_texts,
    fetch_search_graph,
)

RUN = ROOT / "docs" / "osszehasonlitas-section-1200-23-run.json"
EXTRACTION = ROOT / "graph" / "corpus" / "extraction-reuse-1200-23"
BUDGET = {"model_window": 8192, "answer_reserve": 1024, "graph_share": 0.5}
_WRITE = frozenset({"CREATE", "MERGE", "SET", "DELETE", "REMOVE", "DROP", "INSERT"})

EDGE_QUERY = """
MATCH (s:Extracted)-[r]->(t:Extracted)
WHERE r.origin = 'extracted' AND r.rel_key IS NOT NULL
RETURN r.rel_key AS rel_key, r.description AS description
""".strip()

ORACLE_QUERY = """
MATCH (n:Extracted)
WHERE n.entity_key STARTS WITH 'Team:'
  AND toLower(n.entity_key) CONTAINS 'red bull'
RETURN n.entity_key AS entity_key, n.name AS name,
       n.description AS description
""".strip()


class WriteRefused(RuntimeError):
    """The statement is not a read. It was not sent."""


def write_keywords(cypher: str) -> list[str]:
    """Clause keywords that write. Strings, comments, and backtick names are skipped."""
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


def first_difference(replay: str, saved: str) -> dict:
    left = replay.encode("utf-8")
    right = saved.encode("utf-8")
    limit = min(len(left), len(right))
    index = next((i for i in range(limit) if left[i] != right[i]), limit)
    line = left[:index].count(b"\n") + 1
    replay_lines = replay.splitlines()
    saved_lines = saved.splitlines()
    row = line - 1
    return {
        "byte": index,
        "line": line,
        "replay_bytes": len(left),
        "saved_bytes": len(right),
        "replay_line": replay_lines[row][:180] if row < len(replay_lines) else "",
        "saved_line": saved_lines[row][:180] if row < len(saved_lines) else "",
    }


def read_query(session, cypher: str, params: dict) -> list[dict]:
    keywords = write_keywords(cypher)
    if keywords:
        raise WriteRefused(
            "refused before sending; write keyword: " + ", ".join(keywords))

    def work(tx):
        result = tx.run(cypher, params)
        return [record.data() for record in result]

    return session.execute_read(work)


def acceptance_rows(session, rows: list[dict]) -> list[dict]:
    """Phase 1 check: anchors are not dropped as oversized, and the prompt fits."""
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
        nodes, edges = select_context(graph, question, anchors)
        payload = subgraph_payload(nodes, edges)
        payload["sources"] = cited_chunks(
            edges, nodes, _chunk_texts(payload["chunk_ids"], query_fn), question,
        )
        fitted, report = fit_context(question, payload, BUDGET)
        prompt = answer_prompt(question, context_text(fitted))
        present = {
            node["entity_key"] for node in fitted["nodes"]
            if isinstance(node.get("entity_key"), str)
        }
        oversized = set(report.get("oversized_nodes") or [])
        anchor_keys = [key for key, _score in anchors]
        print(f"  checked {row['id']}", flush=True)
        checked.append({
            "id": row["id"],
            "anchors": anchor_keys,
            "missing_anchors": [key for key in anchor_keys if key not in present],
            "oversized_anchors": [key for key in anchor_keys if key in oversized],
            "prompt_estimate": report["prompt_estimate"],
            "input_budget": report["input_budget"],
            "fits": report["prompt_estimate"] <= report["input_budget"],
            "omitted_oversized": report["omitted_oversized"],
            "selected_nodes": report["selected_nodes"],
            "selected_sources": report["selected_sources"],
        })
    return checked


def replay_rows(session, rows: list[dict]) -> list[dict]:
    def query_fn(cypher: str, params: dict) -> list[dict]:
        return read_query(session, cypher, params)

    compared = []
    for row in rows:
        question = question_of(row["prompt"])
        anchors = tuple(
            (item["entity_key"], float(item["score"])) for item in row["anchors"]
        )
        graph = fetch_search_graph([key for key, _score in anchors], query_fn)
        nodes, edges = select_context(graph, question, anchors)
        payload = subgraph_payload(nodes, edges)
        payload["sources"] = cited_chunks(
            edges, nodes, _chunk_texts(payload["chunk_ids"], query_fn), question,
        )
        fitted, _report = fit_context(question, payload, BUDGET)
        prompt = answer_prompt(question, context_text(fitted))
        same = prompt.encode("utf-8") == row["prompt"].encode("utf-8")
        item = {"id": row["id"], "byte_identical": same}
        if not same:
            item["first_difference"] = first_difference(prompt, row["prompt"])
        compared.append(item)
    return compared


def description_lines(text: object) -> list[str]:
    if not isinstance(text, str):
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def compare_edges(session) -> dict:
    stored = {
        row["rel_key"]: row.get("description") or ""
        for row in read_query(session, EDGE_QUERY, {})
        if isinstance(row.get("rel_key"), str)
    }
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(EXTRACTION.glob("*.json"))
    ]
    merged = {
        edge.rel_key: edge.description
        for edge in merged_graph(records).edges
    }
    only_neo4j = sorted(set(stored) - set(merged))
    only_merged = sorted(set(merged) - set(stored))
    equal = 0
    first_line_only = 0
    other = 0
    lost_lines = 0
    examples = []
    for key in sorted(set(stored) & set(merged)):
        neo = description_lines(stored[key])
        full = description_lines(merged[key])
        if neo == full:
            equal += 1
            continue
        lost = [line for line in full if line not in neo]
        lost_lines += len(lost)
        if full and neo == full[:1] and len(full) > 1:
            first_line_only += 1
        else:
            other += 1
        if len(examples) < 5 and lost:
            examples.append({
                "rel_key": key,
                "neo4j_lines": len(neo),
                "merged_lines": len(full),
                "lost_line": lost[0][:180],
            })
    return {
        "neo4j_edges": len(stored),
        "merged_edges": len(merged),
        "equal": equal,
        "differ": first_line_only + other,
        "neo4j_keeps_first_line_only": first_line_only,
        "differ_other": other,
        "lost_description_lines": lost_lines,
        "only_neo4j": len(only_neo4j),
        "only_merged": len(only_merged),
        "examples": examples,
    }


def oracle_keys(session) -> list[dict]:
    rows = read_query(session, ORACLE_QUERY, {})
    kept = []
    for row in rows:
        key = row.get("entity_key")
        if not isinstance(key, str):
            continue
        if "oracle" not in key and key != "Team:red bull racing":
            continue
        description = description_lines(row.get("description"))
        kept.append({
            "entity_key": key,
            "name": row.get("name") or "",
            "description_line": description[0][:180] if description else "",
        })
    return kept


def main() -> int:
    try:
        settings = get_settings()
        driver = get_driver()
        database = settings.neo4j_database
    except GraphUnavailable:
        print("Neo4j connection failed. No query was sent.")
        return 1
    rows = json.loads(RUN.read_text(encoding="utf-8"))
    acceptance = "--acceptance" in sys.argv
    try:
        with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
            if acceptance:
                checked = acceptance_rows(session, rows)
                destination = HERE / "results"
                destination.mkdir(exist_ok=True)
                (destination / "phase1_acceptance.json").write_text(
                    json.dumps(checked, ensure_ascii=False, indent=1),
                    encoding="utf-8",
                )
                failed = [
                    item["id"] for item in checked
                    if item["oversized_anchors"] or not item["fits"]
                    or item["missing_anchors"]
                ]
                for item in checked:
                    print(
                        f"  {item['id']} fits={item['fits']} "
                        f"estimate={item['prompt_estimate']}/{item['input_budget']} "
                        f"oversized_anchors={item['oversized_anchors']} "
                        f"missing={item['missing_anchors']}"
                    )
                print(f"acceptance failed: {failed or 'none'}")
                return 0 if not failed else 3
            compared = replay_rows(session, rows)
            edges = compare_edges(session)
            teams = oracle_keys(session)
    except WriteRefused as exc:
        print(str(exc))
        return 2
    identical = sum(1 for item in compared if item["byte_identical"])
    destination = HERE / "results"
    destination.mkdir(exist_ok=True)
    (destination / "neo4j_replay.json").write_text(
        json.dumps(
            {"identical": identical, "questions": len(compared),
             "replay": compared, "edge_descriptions": edges, "red_bull_keys": teams},
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    print(f"prompts byte-identical: {identical}/{len(compared)}")
    for item in compared:
        if item["byte_identical"]:
            print(f"  {item['id']} identical")
            continue
        diff = item["first_difference"]
        print(
            f"  {item['id']} differs at byte {diff['byte']} line {diff['line']}"
        )
        print(f"    replay: {diff['replay_line']}")
        print(f"    saved:  {diff['saved_line']}")
    print(
        "edge descriptions: "
        f"equal={edges['equal']} differ={edges['differ']} "
        f"first_line_only={edges['neo4j_keeps_first_line_only']} "
        f"other={edges['differ_other']} lost_lines={edges['lost_description_lines']}"
    )
    print("red bull / oracle keys:")
    for item in teams:
        print(f"  {item['entity_key']} | {item['name']} | {item['description_line']}")
    return 0 if identical == len(compared) else 3


if __name__ == "__main__":
    raise SystemExit(main())
