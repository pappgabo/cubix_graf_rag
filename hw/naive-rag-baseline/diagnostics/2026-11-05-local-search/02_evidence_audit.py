"""List every chunk the gold-derived labels accept, with its extraction
status and the sentence that matched, so the labels can be reviewed by
hand. Chunks listed in evidence.REJECTED are reported but not counted.
Writes results/02_evidence_audit.json."""

import common
import evidence

texts, meta = common.load_chunks()
status = {r["chunk_id"]: r["status"] for r in common.records()}
out = {}
for qid, hops in evidence.HOPS.items():
    out[qid] = {}
    for hop, alternatives in hops.items():
        rows = []
        for cid in sorted(texts):
            sentence = evidence.matching_sentence(alternatives, texts[cid],
                                                  meta[cid]["doc_id"])
            if sentence is None:
                continue
            rows.append({
                "chunk_id": cid,
                "status": status.get(cid, "not_extracted"),
                "rejected_by_review": evidence.REJECTED.get((qid, hop, cid)),
                "sentence": sentence[:400],
            })
        out[qid][hop] = rows
        kept = [r for r in rows if not r["rejected_by_review"]]
        counts = {}
        for row in kept:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        print(f"{qid} | {hop}: kept {len(kept)} {counts}, "
              f"rejected by review {len(rows) - len(kept)}")
path = common.write_result("02_evidence_audit.json", out)
print(f"wrote {path}")
