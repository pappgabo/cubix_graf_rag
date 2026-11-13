"""Offline impact of excerpt reservation and ranking on the saved questions.

For every saved question the saved anchors are replayed through the
project's own `select_context`, so every policy sees the same nodes and
edges. Only the excerpt step (`cited_chunks`) is varied. No model, no
embedding: this does not re-check anchors and cannot say what the model
would have answered. Gold-derived labels (evidence.py) are used only for
scoring. Writes results/03_selection_impact.json.
"""

import re

import common
import evidence
from naive_rag import local_search as ls

LIMITS = (6, 8, 10)


def scorer(nodes, texts, question):
    """The score `cited_chunks` uses: question terms + fully named nodes."""
    terms = ls.question_terms(question)
    entity_words = tuple(
        tuple(w for w in re.findall(r"[a-z0-9]+", n.name.casefold()) if len(w) > 2)
        for n in nodes)

    def score(cid):
        folded = (texts.get(cid) or "").casefold().replace("'", "")
        hits = sum(1 for t in terms if ls._covers(t, folded))
        named = sum(1 for ws in entity_words
                    if ws and all(ls._covers(w, folded) for w in ws))
        return hits + named
    return score


def _fill(order, picked, limit, score, require_hit=True):
    for cid in order:
        if len(picked) >= limit:
            break
        if cid in picked or (require_hit and score(cid) <= 0):
            continue
        picked.append(cid)


def _pool(nodes, edges):
    pool = [c for e in edges for c in e.source_chunk_ids]
    pool += [c for n in nodes for c in n.source_chunk_ids]
    return pool


def _ranked(ids, score, extra=None):
    extra = extra or (lambda _c: 0)
    return sorted(set(ids), key=lambda c: (-extra(c), -score(c), c))


def p_current(nodes, edges, texts, q, limit, anchors):
    return [s["chunk_id"] for s in ls.cited_chunks(edges, nodes, texts, q, limit=limit)]


def p_no_reserve(nodes, edges, texts, q, limit, anchors):
    score = scorer(nodes, texts, q)
    picked = []
    _fill(_ranked(_pool(nodes, edges), score), picked, limit, score)
    return picked


def p_anchor_reserve(nodes, edges, texts, q, limit, anchors):
    score = scorer(nodes, texts, q)
    picked = []
    for n in nodes:
        if n.entity_key in anchors:
            _fill(_ranked(n.source_chunk_ids, score), picked, len(picked) + 1, score)
    _fill(_ranked(_pool(nodes, edges), score), picked, limit, score)
    return picked


def p_edge_sources_first(nodes, edges, texts, q, limit, anchors):
    score = scorer(nodes, texts, q)
    picked = []
    _fill(_ranked([c for e in edges for c in e.source_chunk_ids], score),
          picked, limit, score)
    _fill(_ranked([c for n in nodes for c in n.source_chunk_ids], score),
          picked, limit, score)
    return picked


def p_edge_reserve(nodes, edges, texts, q, limit, anchors):
    score = scorer(nodes, texts, q)
    picked = []
    for e in edges:
        _fill(_ranked(e.source_chunk_ids, score), picked, len(picked) + 1, score)
        if len(picked) >= limit:
            break
    _fill(_ranked(_pool(nodes, edges), score), picked, limit, score)
    return picked


def p_edge_support_rank(nodes, edges, texts, q, limit, anchors):
    """Rank by how many selected edges cite the chunk, then by score."""
    score = scorer(nodes, texts, q)
    support = {}
    for e in edges:
        for c in set(e.source_chunk_ids):
            support[c] = support.get(c, 0) + 1
    picked = []
    _fill(_ranked(_pool(nodes, edges), score, lambda c: support.get(c, 0)),
          picked, limit, score)
    return picked


POLICIES = {
    "A_current": p_current,
    "B_no_reserve": p_no_reserve,
    "C_anchor_reserve_only": p_anchor_reserve,
    "D_edge_sources_first": p_edge_sources_first,
    "E_one_per_selected_edge": p_edge_reserve,
    "F_rank_by_edge_support": p_edge_support_rank,
}


def main():
    texts, meta = common.load_chunks()
    g = common.graph()
    labels = evidence.evidence_sets(texts, meta)
    referenced = {c for n in g.nodes for c in n.source_chunk_ids} | {
        c for e in g.edges for c in e.source_chunk_ids}
    out = {"limits": LIMITS, "questions": {}}
    for r in common.saved_run():
        qid, q = r["id"], common.question_of(r)
        anchors = common.anchors_of(r)
        nodes, edges = ls.select_context(g, q, anchors)
        pool = set(_pool(nodes, edges))
        score = scorer(nodes, texts, q)
        ranked_pool = _ranked(pool, score)
        row = {"pool_size": len(pool), "policies": {}}
        hops = labels.get(qid)
        if hops:
            row["upper_bounds"] = {
                hop: {
                    "in_corpus": len(ids),
                    "linked_to_graph": len(ids & referenced),
                    "in_candidate_pool": len(ids & pool),
                    "best_rank_by_score": min(
                        (ranked_pool.index(c) + 1 for c in ids & pool), default=None),
                }
                for hop, ids in hops.items()
            }
        for name, policy in POLICIES.items():
            row["policies"][name] = {}
            for limit in LIMITS:
                picked = policy(nodes, edges, texts, q, limit, {k for k, _ in anchors})
                cell = {"picked": picked}
                if hops:
                    cell["hops"] = evidence.coverage(set(picked), hops)
                row["policies"][name][str(limit)] = cell
        assert row["policies"]["A_current"]["6"]["picked"] == [
            s["chunk_id"] for s in ls.cited_chunks(edges, nodes, texts, q)]
        out["questions"][qid] = row

    summary = {}
    for name in POLICIES:
        for limit in LIMITS:
            key = f"{name}@{limit}"
            gained, lost, covered, total, chains = [], [], 0, 0, 0
            for qid, row in out["questions"].items():
                if "upper_bounds" not in row:
                    continue
                base = row["policies"]["A_current"]["6"]["hops"]
                now = row["policies"][name][str(limit)]["hops"]
                total += len(now)
                covered += sum(now.values())
                chains += all(now.values())
                gained += [f"{qid}: {h}" for h in now if now[h] and not base[h]]
                lost += [f"{qid}: {h}" for h in now if base[h] and not now[h]]
            overlap = []
            for qid in ("Q09", "Q10", "Q11", "Q12", "Q13"):
                a = set(out["questions"][qid]["policies"]["A_current"]["6"]["picked"])
                b = set(out["questions"][qid]["policies"][name][str(limit)]["picked"])
                overlap.append(round(len(a & b) / len(a | b), 2) if a | b else 1.0)
            summary[key] = {
                "hops_covered": f"{covered}/{total}",
                "complete_chains_Q01_Q08": chains,
                "gained_vs_A@6": gained,
                "lost_vs_A@6": lost,
                "global_Q09_Q13_jaccard_vs_A@6": overlap,
            }
    out["summary"] = summary
    path = common.write_result("03_selection_impact.json", out)

    print("upper bounds (hop: corpus / graph-linked / in pool / best score rank)")
    for qid, row in out["questions"].items():
        for hop, ub in row.get("upper_bounds", {}).items():
            print(f"  {qid} {hop}: {ub['in_corpus']} / {ub['linked_to_graph']} / "
                  f"{ub['in_candidate_pool']} / {ub['best_rank_by_score']}")
    print("policy summary")
    for key, s in summary.items():
        print(f"  {key}: hops {s['hops_covered']}, chains {s['complete_chains_Q01_Q08']}, "
              f"gained {s['gained_vs_A@6']}, lost {s['lost_vs_A@6']}, "
              f"global jaccard {s['global_Q09_Q13_jaccard_vs_A@6']}")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
