"""Phase 0 baseline counts and offline context replay.

Reads saved extraction records, the chunk jsonl, and the saved local-search
run. No model call, no embedding call, and no database call. Does not
import settings, so it does not read ``.env``.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naive_rag.extraction_identity import ALIAS_MAP  # noqa: E402
from naive_rag.graph_merge import merged_graph  # noqa: E402
from naive_rag.local_search import (  # noqa: E402
    answer_prompt,
    cited_chunks,
    context_text,
    estimate_tokens,
    fit_context,
    select_context,
    subgraph_payload,
)

EXTRACTION = ROOT / "graph" / "corpus" / "extraction-reuse-1200-23"
CHUNKS = ROOT / "graph" / "corpus" / "chunks-section-1200-23" / "chunks.jsonl"
RUN = ROOT / "docs" / "osszehasonlitas-section-1200-23-run.json"

# Code defaults in config.py. The saved run's context_budget is compared
# with these; this script does not load Settings.
BUDGET = {
    "model_window": 8192,
    "answer_reserve": 1024,
    "graph_share": 0.5,
}

NAMED_ANCHOR = {
    "Q01": "Driver:lewis hamilton",
    "Q02": "Driver:sebastian vettel",
    "Q04": "Driver:sebastian vettel",
    "Q05": "Driver:sebastian vettel",
    "Q06": "Driver:michael schumacher",
    "Q08": "Team:mercedes-amg petronas formula one team",
    "Q10": "Team:scuderia ferrari",
    "Q13": "Team:scuderia ferrari",
}

PLACEMENT = re.compile(
    r"\b(?:finished|placed|ranked)\b.{0,40}\b(?:second|third|fourth|fifth|"
    r"sixth|seventh|eighth|ninth|tenth|2nd|3rd|4th|5th|6th|7th|8th|9th|"
    r"10th|\d+(?:st|nd|rd|th))\b"
    r"|\brunner-up\b"
    r"|\b\d+(?:st|nd|rd|th) place\b",
    re.IGNORECASE,
)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def load_records() -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(EXTRACTION.glob("*.json"))
    ]


def load_chunks() -> dict[str, str]:
    texts = {}
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        texts[row["chunk_id"]] = row.get("text") or ""
    return texts


def rejection_bucket(reason: str) -> str:
    if reason.startswith("ACHIEVED Driver -> GrandPrix has "):
        return "ACHIEVED Driver->GrandPrix with year or role"
    match = re.match(r"^(\S+) does not allow (.+)$", reason)
    if match:
        return f"{match.group(1)} {match.group(2).replace(' -> ', '->')}"
    return reason


def baseline(records: list[dict], graph) -> dict:
    status = Counter(record.get("status") for record in records)
    empty = sum(
        1 for record in records
        if record.get("status") == "ok"
        and not (record.get("result") or {}).get("entities")
    )
    with_candidate = sum(1 for record in records if "candidate_result" in record)
    relationship_loss = 0
    reasons: Counter[str] = Counter()
    for record in records:
        items = record.get("rejections") or []
        if any(item.get("element") == "relationship" for item in items):
            relationship_loss += 1
        for item in items:
            reasons[rejection_bucket(str(item.get("reason") or ""))] += 1

    by_label = Counter(node.label for node in graph.nodes)
    hamilton = next(
        node for node in graph.nodes
        if node.entity_key == "Driver:lewis hamilton"
    )
    loops = [
        {
            "rel_type": edge.rel_type,
            "key": edge.source_id,
            "description": edge.description[:240],
        }
        for edge in graph.edges
        if edge.source_id == edge.target_id
    ]
    won_title = [
        edge for edge in graph.edges
        if edge.rel_type == "WON" and edge.target_id.startswith("Title:")
    ]
    placement = []
    for edge in won_title:
        if PLACEMENT.search(edge.description or ""):
            placement.append({
                "source": edge.source_id,
                "target": edge.target_id,
                "description": (edge.description or "")[:240],
            })
    race_results = [node for node in graph.nodes if node.label == "RaceResult"]
    multi = [node for node in race_results if len(node.source_chunk_ids) > 1]
    contradictory = []
    for node in multi:
        lines = [line.strip() for line in node.description.splitlines() if line.strip()]
        if len(set(lines)) > 1:
            contradictory.append(node.entity_key)
    seasons = sorted(
        node.entity_key for node in graph.nodes
        if node.label == "Season" and not YEAR.search(node.name)
    )
    titles_no_year = sorted(
        node.entity_key for node in graph.nodes
        if node.label == "Title" and not YEAR.search(node.name)
    )
    present = {
        key: any(node.entity_key == key for node in graph.nodes)
        for key in (
            "RaceResult:142 points",
            "Season:season",
            "Season:formula one",
            "Season:drivers' championship",
            "Season:130",
            "Season:190",
            "Title:9",
            "Title:seventh title",
            "Title:world drivers' championship",
            "Team:mercedes-amg petronas f1 team",
            "Team:mercedes-benz",
            "Team:oracle red bull racing",
            "Driver:verstappen",
            "Driver:vettel",
            "Driver:alonso",
            "Driver:bottas",
            "Driver:leclerc",
            "Driver:räikkönen",
            "Driver:rosberg",
            "Driver:schumacher",
        )
    }
    return {
        "records": len(records),
        "status": dict(status),
        "empty_ok": empty,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "candidate_result_records": with_candidate,
        "records_with_rejected_relationship": relationship_loss,
        "rejection_buckets": reasons.most_common(20),
        "hamilton": {
            "description_chars": len(hamilton.description),
            "description_lines": hamilton.description.count("\n") + 1,
            "source_chunks": len(hamilton.source_chunk_ids),
        },
        "self_loops": loops,
        "won_to_title": len(won_title),
        "won_to_title_with_placement_language": len(placement),
        "won_placement_examples": placement[:8],
        "race_results": len(race_results),
        "race_results_multi_chunk": len(multi),
        "race_results_multi_chunk_distinct_lines": len(contradictory),
        "seasons_without_year": seasons,
        "titles_without_year": len(titles_no_year),
        "by_label": dict(by_label),
        "named_keys_present": present,
        "alias_map": dict(ALIAS_MAP),
    }


def question_of(prompt: str) -> str:
    start = prompt.find("Kérdés: ")
    end = prompt.find("\n\nKontextus:")
    if start < 0 or end < 0:
        raise ValueError("saved prompt has no question")
    return prompt[start + len("Kérdés: "):end]


def prompt_ids(prompt: str) -> list[str]:
    return re.findall(r"^- azonosító: (.+)$", prompt, re.MULTILINE)


def prompt_edges(prompt: str) -> list[str]:
    return re.findall(r"^- .+ -> .+$", prompt, re.MULTILINE)


def replay_one(graph, texts: dict[str, str], row: dict) -> dict:
    question = question_of(row["prompt"])
    anchors = tuple(
        (item["entity_key"], float(item["score"])) for item in row["anchors"]
    )
    nodes, edges = select_context(graph, question, anchors)
    payload = subgraph_payload(nodes, edges)
    payload["sources"] = cited_chunks(edges, nodes, texts, question)
    fitted, report = fit_context(question, payload, BUDGET)
    context = context_text(fitted)
    prompt = answer_prompt(question, context)
    saved_budget = row.get("context_budget") or {}
    fitted_keys = [node["entity_key"] for node in fitted["nodes"]]
    saved_keys = prompt_ids(row["prompt"])
    missing_anchors = [
        key for key, _score in anchors if key not in fitted_keys
    ]
    named = NAMED_ANCHOR.get(row["id"])
    return {
        "id": row["id"],
        "anchors": [key for key, _score in anchors],
        "missing_anchors": missing_anchors,
        "named_anchor": named,
        "named_anchor_in_saved_anchors": named in {key for key, _score in anchors} if named else None,
        "named_anchor_in_replay_prompt": (named in fitted_keys) if named else None,
        "named_anchor_in_saved_prompt": (named in saved_keys) if named else None,
        "selected_before_fit": [edge.rel_key for edge in edges],
        "selected_after_fit": [edge["rel_key"] for edge in fitted["edges"]],
        "omitted_oversized": report["omitted_oversized"],
        "omitted_for_budget": report["omitted_for_budget"],
        "prompt_estimate": report["prompt_estimate"],
        "prompt_chars": len(prompt),
        "saved_prompt_estimate": saved_budget.get("prompt_estimate"),
        "saved_prompt_chars": len(row["prompt"]),
        "saved_model_window": saved_budget.get("model_window"),
        "saved_omitted_oversized": saved_budget.get("omitted_oversized"),
        "saved_selected_nodes": saved_budget.get("selected_nodes"),
        "replay_selected_nodes": report["selected_nodes"],
        "node_keys_match": fitted_keys == saved_keys,
        "edge_lines_match": prompt_edges(prompt) == prompt_edges(row["prompt"]),
        "prompt_equal": prompt == row["prompt"],
        "only_in_replay_nodes": sorted(set(fitted_keys) - set(saved_keys)),
        "only_in_saved_nodes": sorted(set(saved_keys) - set(fitted_keys)),
    }


def main() -> None:
    records = load_records()
    graph = merged_graph(records)
    texts = load_chunks()
    facts = baseline(records, graph)
    rows = json.loads(RUN.read_text(encoding="utf-8"))
    replayed = [replay_one(graph, texts, row) for row in rows]
    named_missing = [
        item["id"] for item in replayed
        if item["named_anchor"] and not item["named_anchor_in_replay_prompt"]
    ]
    out = {
        "budget": BUDGET,
        "baseline": facts,
        "replay": replayed,
        "named_anchors_missing_from_replay_prompt": named_missing,
        "prompts_equal": sum(1 for item in replayed if item["prompt_equal"]),
        "node_sets_equal": sum(1 for item in replayed if item["node_keys_match"]),
    }
    destination = HERE / "results"
    destination.mkdir(exist_ok=True)
    (destination / "baseline_and_replay.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps({
        "records": facts["records"],
        "status": facts["status"],
        "empty_ok": facts["empty_ok"],
        "nodes": facts["nodes"],
        "edges": facts["edges"],
        "candidate_result_records": facts["candidate_result_records"],
        "records_with_rejected_relationship": facts["records_with_rejected_relationship"],
        "hamilton": facts["hamilton"],
        "self_loops": len(facts["self_loops"]),
        "won_to_title": facts["won_to_title"],
        "won_placement": facts["won_to_title_with_placement_language"],
        "race_results": facts["race_results"],
        "race_multi": facts["race_results_multi_chunk"],
        "race_contradictory_lines": facts["race_results_multi_chunk_distinct_lines"],
        "titles_without_year": facts["titles_without_year"],
        "prompts_equal": out["prompts_equal"],
        "node_sets_equal": out["node_sets_equal"],
        "named_missing": named_missing,
    }, ensure_ascii=False, indent=1))
    print("rejection buckets:")
    for reason, count in facts["rejection_buckets"]:
        print(f"  {count:5} {reason}")
    print("replay:")
    for item in replayed:
        print(
            f"  {item['id']} equal={item['prompt_equal']} "
            f"nodes={item['node_keys_match']} edges={item['edge_lines_match']} "
            f"est={item['prompt_estimate']}/{item['saved_prompt_estimate']} "
            f"oversized={item['omitted_oversized']}/{item['saved_omitted_oversized']} "
            f"missing={item['missing_anchors']}"
        )


if __name__ == "__main__":
    main()
