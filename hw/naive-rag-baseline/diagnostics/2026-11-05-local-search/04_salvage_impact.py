"""How much structurally valid data the rejected records still hold, and
what it would change in graph coverage and in the saved-anchor replay.

Salvage rule, applied in memory only: a rejected record's candidate entities
are kept; each candidate relationship is kept only if the project's own
`validate_extraction` accepts it alone with those entities. Nothing is
rewritten (no year is dropped to make an edge pass). A record whose entities
themselves fail (duplicate local_id) is not salvaged. Kept items are
STRUCTURALLY valid against the schema; this says nothing about whether the
source text supports them.

The saved anchors are replayed on the salvaged graph. New entities have no
embedding and cannot become anchors, and merged descriptions would change
the embedded text of existing entities, so a rebuilt index could choose
different anchors. Writes results/04_salvage_impact.json.
"""

import re
from collections import Counter

import common
import evidence
from naive_rag import local_search as ls
from naive_rag.entity_index import index_text, load_index
from naive_rag.extraction_models import (
    ExtractionResult,
    ExtractionValidationError,
    load_saved_extraction,
)
from naive_rag.graph_merge import measure

import importlib
selection = importlib.import_module("03_selection_impact")

YEAR = re.compile(r"^(19|20)\d{2}$")


def salvage(record):
    candidate = ExtractionResult.model_validate(record["candidate_result"])
    ids = [e.local_id for e in candidate.entities]
    if len(ids) != len(set(ids)):
        return None, Counter({"record_duplicate_local_id": 1})
    kept, reasons = [], Counter()
    for rel in candidate.relationships:
        try:
            accepted, dropped = load_saved_extraction(ExtractionResult(
                entities=candidate.entities, relationships=[rel]))
        except ExtractionValidationError as exc:
            reasons[re.sub(r"'[^']*'", "'x'", str(exc))] += 1
            continue
        for reason in dropped:
            reasons[re.sub(r"'[^']*'", "'x'", reason)] += 1
        kept.extend(accepted.relationships)
    result = ExtractionResult(entities=candidate.entities, relationships=kept)
    return result, reasons


def shape_flags(recs):
    """Structural oddities, counted per entity occurrence (not semantic)."""
    flags = Counter()
    total = 0
    for r in recs:
        for e in r["result"]["entities"]:
            total += 1
            name = e["name"].strip()
            if e["entity_type"] == "Season" and not YEAR.match(name):
                flags["Season name is not a year"] += 1
            if e["entity_type"] == "Title" and YEAR.match(name):
                flags["Title name is only a year"] += 1
            if e["entity_type"] == "RaceResult" and re.fullmatch(r"\d+(st|nd|rd|th)?", name):
                flags["RaceResult name is only a number or position"] += 1
    return total, dict(flags)


def main():
    texts, meta = common.load_chunks()
    recs = common.records()
    ok = [r for r in recs if r["status"] == "ok"]
    errors = [r for r in recs if r["status"] == "error"]
    salvaged, dropped_reasons, not_salvaged = [], Counter(), 0
    rel_candidates = rel_kept = 0
    yearless_would_pass = 0
    for r in errors:
        result, reasons = salvage(r)
        if result is None:
            not_salvaged += 1
            dropped_reasons.update(reasons)
            continue
        rel_candidates += len(r["candidate_result"].get("relationships") or [])
        rel_kept += len(result.relationships)
        dropped_reasons.update(reasons)
        yearless_would_pass += sum(v for k, v in reasons.items() if "is not temporal" in k)
        salvaged.append({**r, "status": "ok",
                         "result": result.model_dump(mode="json")})

    before = common.graph(recs)
    after = common.graph(ok + salvaged)
    index = load_index(common.INDEX_PATH)
    after_nodes = {n.entity_key: n for n in after.nodes}
    new_keys = set(after_nodes) - set(index.by_key)
    text_changed = sum(
        1 for k, it in index.by_key.items()
        if k in after_nodes
        and it.text != index_text(after_nodes[k].name, after_nodes[k].description))

    def referenced(g):
        return {c for n in g.nodes for c in n.source_chunk_ids} | {
            c for e in g.edges for c in e.source_chunk_ids}
    ref_before, ref_after = referenced(before), referenced(after)
    edge_ref_after = {c for e in after.edges for c in e.source_chunk_ids}

    labels = evidence.evidence_sets(texts, meta)
    per_question = {}
    for r in common.saved_run():
        qid = r["id"]
        if qid not in labels:
            continue
        q, anchors = common.question_of(r), common.anchors_of(r)
        row = {}
        for tag, g in (("before", before), ("after", after)):
            nodes, edges = ls.select_context(g, q, anchors)
            pool = set(selection._pool(nodes, edges))
            ref = referenced(g)
            picked = {
                f"{name}@{limit}": set(fn(nodes, edges, texts, q, limit, None))
                for name, fn in (("A_current", selection.p_current),
                                 ("B_no_reserve", selection.p_no_reserve))
                for limit in (6, 8)
            }
            row[tag] = {
                hop: {
                    "linked_to_graph": bool(ids & ref),
                    "in_pool": bool(ids & pool),
                    **{key: bool(ids & chosen) for key, chosen in picked.items()},
                }
                for hop, ids in labels[qid].items()
            }
            row[tag + "_pool_size"] = len(pool)
        per_question[qid] = row

    changes = {}
    for level in ("linked_to_graph", "in_pool", "A_current@6", "A_current@8",
                  "B_no_reserve@6", "B_no_reserve@8"):
        gained, lost, n_before, n_after = [], [], 0, 0
        for qid, row in per_question.items():
            for hop in row["before"]:
                b, a = row["before"][hop][level], row["after"][hop][level]
                n_before += b
                n_after += a
                if a and not b:
                    gained.append(f"{qid}: {hop}")
                if b and not a:
                    lost.append(f"{qid}: {hop}")
        changes[level] = {"before": n_before, "after": n_after,
                          "gained": gained, "lost": lost}

    null_like = sorted(k for k in new_keys
                       if k.split(":", 1)[1] in {"null", "none", "unknown", "n/a", ""})
    ok_total, ok_flags = shape_flags(ok)
    sv_total, sv_flags = shape_flags(salvaged)
    out = {
        "rejected_records": len(errors),
        "salvaged_records": len(salvaged),
        "not_salvaged_records": not_salvaged,
        "candidate_entities_kept": sum(len(r["result"]["entities"]) for r in salvaged),
        "salvaged_records_with_entities": sum(1 for r in salvaged if r["result"]["entities"]),
        "candidate_relationships": rel_candidates,
        "relationships_kept_structurally_valid": rel_kept,
        "relationships_dropped_by_reason": dict(dropped_reasons.most_common()),
        "dropped_only_because_years_on_non_temporal_edge": yearless_would_pass,
        "graph_before": {k: v for k, v in measure(before).items() if k != "component_meaning"},
        "graph_after": {k: v for k, v in measure(after).items() if k != "component_meaning"},
        "chunks_referenced_before": len(ref_before),
        "chunks_referenced_after": len(ref_after),
        "chunks_referenced_by_edges_after": len(edge_ref_after),
        "new_entity_keys_without_embedding": len(new_keys),
        "existing_index_entities_whose_text_would_change": text_changed,
        "new_placeholder_named_entities": null_like,
        "shape_flags": {
            "accepted": {"entity_occurrences": ok_total, **ok_flags},
            "salvaged": {"entity_occurrences": sv_total, **sv_flags},
        },
        "evidence_changes": changes,
        "per_question": per_question,
    }
    path = common.write_result("04_salvage_impact.json", out)
    for key, value in out.items():
        if key == "relationships_dropped_by_reason":
            print(f"{key} (top 8): {dict(list(value.items())[:8])}")
        elif key == "evidence_changes":
            for level, change in value.items():
                print(f"  {level}: {change}")
        elif key != "per_question":
            print(f"{key}: {value}")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
