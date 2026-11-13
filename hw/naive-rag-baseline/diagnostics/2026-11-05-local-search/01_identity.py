"""Does the current code and data reproduce the saved run? Writes
results/inputs-manifest.json and results/01_identity.json."""

from collections import Counter

import common
from naive_rag import local_search as ls
from naive_rag.entity_index import index_text, load_index
from naive_rag.extract_pilot import PROMPT_VERSION, input_hash, load_titles
from naive_rag.graph_merge import measure

texts, meta = common.load_chunks()
recs = common.records()
titles = load_titles(common.CORPUS_DIR / "metadata.json")
hash_ok = hash_bad = missing = 0
for r in recs:
    cid = r["chunk_id"]
    if cid not in texts:
        missing += 1
        continue
    digest = input_hash(model=r["model"], document_title=titles[meta[cid]["doc_id"]],
                        section=meta[cid]["section"] or None, text=texts[cid])
    if digest == r["input_hash"]:
        hash_ok += 1
    else:
        hash_bad += 1

g = common.graph(recs)
index = load_index(common.INDEX_PATH)
nodes = {n.entity_key: n for n in g.nodes}
index_text_diff = sum(
    1 for k, it in index.by_key.items()
    if k in nodes and it.text != index_text(nodes[k].name, nodes[k].description))
referenced = {c for n in g.nodes for c in n.source_chunk_ids} | {
    c for e in g.edges for c in e.source_chunk_ids}

replay = {}
for r in common.saved_run():
    q = common.question_of(r)
    chosen_nodes, chosen_edges = ls.select_context(g, q, common.anchors_of(r))
    payload = ls.subgraph_payload(chosen_nodes, chosen_edges)
    payload["sources"] = ls.cited_chunks(chosen_edges, chosen_nodes, texts, q)
    replay[r["id"]] = ls.answer_prompt(q, ls.context_text(payload)) == r["prompt"]

result = {
    "chunks_now": len(texts),
    "docs_now": len({m["doc_id"] for m in meta.values()}),
    "chunks_over_500_chars": sum(len(t) > 500 for t in texts.values()),
    "records": len(recs),
    "status": dict(Counter(r["status"] for r in recs)),
    "ok_without_entities": sum(1 for r in recs if r["status"] == "ok"
                               and not r["result"]["entities"]),
    "prompt_version_now": PROMPT_VERSION,
    "record_prompt_versions": dict(Counter(r["prompt_version"] for r in recs)),
    "input_hash": {"match": hash_ok, "mismatch": hash_bad, "missing_chunk": missing},
    "merged_graph": {k: v for k, v in measure(g).items() if k != "component_meaning"},
    "index_entities": len(index.by_key),
    "index_keys_equal_graph_keys": set(index.by_key) == set(nodes),
    "index_text_differs": index_text_diff,
    "chunks_referenced_by_graph": len(referenced),
    "replayed_prompt_identical": replay,
}
common.write_result("inputs-manifest.json", common.input_manifest())
path = common.write_result("01_identity.json", result)
for key, value in result.items():
    print(f"{key}: {value}")
print(f"wrote {path}")
