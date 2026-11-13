"""Offline review of the current extraction (extraction-reuse-1200-23).

Reads saved JSON only. No model, embedding, or database call. Writes
results/01_graph_review.json in this directory.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naive_rag.graph_merge import measure, merged_graph  # noqa: E402

EXTRACTION = ROOT / "graph" / "corpus" / "extraction-reuse-1200-23"


def records() -> list[dict]:
    out = []
    for path in sorted(EXTRACTION.glob("*.json")):
        out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def main() -> None:
    recs = records()
    status = Counter(r.get("status") for r in recs)
    empty = sum(1 for r in recs if r.get("status") == "ok"
                and not (r.get("result") or {}).get("entities"))
    reused = sum(1 for r in recs if r.get("reused_from"))
    reasons = Counter()
    for r in recs:
        for item in r.get("rejections") or []:
            text = re.sub(r"'[^']*'", "'…'", item["reason"])
            text = re.sub(r"from_year=\S+ to_year=\S+ role=\S+", "<time>", text)
            text = re.sub(r"\d{4}", "YYYY", text)
            reasons[f"{item['element']}: {text}"] += 1
    aligned = Counter(a["action"] for r in recs for a in r.get("alignments") or [])

    graph = merged_graph(recs)
    m = measure(graph)
    by_type = Counter(n.label for n in graph.nodes)
    seasons_non_year = sorted(
        n.entity_key for n in graph.nodes
        if n.label == "Season" and not re.search(r"\b(19|20)\d{2}\b", n.name))
    titles_no_year = [n for n in graph.nodes if n.label == "Title"
                      and not re.search(r"\b(19|20)\d{2}\b", n.name)]

    degree = Counter()
    for e in graph.edges:
        degree[e.source_id] += 1
        degree[e.target_id] += 1

    def info(n):
        return {
            "key": n.entity_key,
            "sources": len(n.source_chunk_ids),
            "desc_chars": len(n.description),
            "desc_lines": n.description.count("\n") + 1 if n.description else 0,
            "degree": degree[n.entity_key],
        }

    biggest = sorted(graph.nodes, key=lambda n: -len(n.description))[:15]
    most_sourced = sorted(graph.nodes, key=lambda n: -len(n.source_chunk_ids))[:15]
    edge_big = sorted(graph.edges, key=lambda e: -len(e.description))[:5]

    # Possible remaining duplicates: same type, key contains a frequent surname/team word.
    probes = ["hamilton", "verstappen", "vettel", "rosberg", "schumacher", "alonso",
              "bottas", "leclerc", "mercedes", "red bull", "ferrari", "mclaren",
              "williams", "renault"]
    dup = {}
    for p in probes:
        keys = sorted(n.entity_key for n in graph.nodes
                      if n.label in ("Driver", "Team") and p in n.entity_key)
        dup[p] = keys

    race_results = [n for n in graph.nodes if n.label == "RaceResult"]
    rr_multi = sorted(race_results, key=lambda n: -len(n.source_chunk_ids))[:8]

    # Bence's named cases.
    named = {}
    for cid in ("driver-nico-rosberg", "season-2016-formula-one-world-championship",
                "driver-valtteri-bottas"):
        named[cid] = None
    q08_keys = [k for k in (n.entity_key for n in graph.nodes)
                if k in ("Driver:nico rosberg", "Driver:valtteri bottas")]
    q08_edges = [
        [e.source_id, e.rel_type, e.target_id, e.from_year, e.to_year,
         list(e.source_chunk_ids)[:4]]
        for e in graph.edges
        if {"Driver:nico rosberg", "Driver:valtteri bottas"} & {e.source_id, e.target_id}
        and e.rel_type in ("REPLACED", "TEAMMATE_OF", "SUCCEEDED")
    ]

    out = {
        "records": len(recs), "status": status, "empty_ok": empty, "reused": reused,
        "merged": m, "by_type": by_type,
        "rejection_reasons_top": reasons.most_common(25),
        "rejections_total": sum(reasons.values()),
        "alignments": aligned,
        "season_non_year": seasons_non_year,
        "title_without_year_count": len(titles_no_year),
        "title_without_year_sample": sorted(n.entity_key for n in titles_no_year)[:60],
        "largest_descriptions": [info(n) for n in biggest],
        "most_sources": [info(n) for n in most_sourced],
        "largest_edge_descriptions": [[e.rel_key, len(e.description)] for e in edge_big],
        "duplicate_probes": dup,
        "race_results": len(race_results),
        "race_results_most_sources": [
            {**info(n), "desc_head": n.description[:300]} for n in rr_multi],
        "q08_edges": q08_edges, "q08_keys": q08_keys,
    }
    res = HERE / "results"
    res.mkdir(exist_ok=True)
    (res / "01_graph_review.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    print(json.dumps({k: out[k] for k in (
        "records", "status", "empty_ok", "reused", "merged", "by_type",
        "rejections_total", "alignments")}, ensure_ascii=False, default=list))
    print("reasons:")
    for r, c in out["rejection_reasons_top"]:
        print(f"  {c:5} {r}")
    print("season_non_year:", seasons_non_year)
    print("title_without_year:", len(titles_no_year))
    print("largest_descriptions:")
    for x in out["largest_descriptions"][:10]:
        print("  ", x)
    print("most_sources:")
    for x in out["most_sources"][:10]:
        print("  ", x)
    print("duplicates:")
    for p, keys in dup.items():
        print(f"  {p}: {keys}")
    print("race_results:", len(race_results))
    for x in out["race_results_most_sources"][:4]:
        print("  ", x["key"], x["sources"], x["desc_lines"], "|", x["desc_head"][:200].replace("\n", " / "))
    print("q08 edges:", q08_edges)


if __name__ == "__main__":
    main()
