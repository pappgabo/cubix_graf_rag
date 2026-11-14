"""Aggregate the already-saved Phase 4 run into a short comparison doc.
Pure local reading -- no model call, no recomputation."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / "results"

QUESTION_IDS = ["Q09", "Q10", "Q11", "Q12", "Q13"]

questions_text = {}
import sys
sys.path.insert(0, str(ROOT / "src"))
from naive_rag.global_search import load_questions, questions_by_label  # noqa: E402

all_q = load_questions(ROOT / "questions.md")
for q in questions_by_label(all_q, "global"):
    questions_text[q.question_id] = q.text

totals = {"map_calls": 0, "reduce_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
          "duration_seconds": 0.0, "cost_usd": 0.0}
per_question = {}

for qid in QUESTION_IDS:
    map_records = []
    for f in sorted(RESULTS.glob(f"map-result-{qid}-*.json")):
        map_records.append(json.loads(f.read_text(encoding="utf-8")))
    positive = [r for r in map_records if r.get("usefulness_score", 0) > 0]
    zero = [r for r in map_records if r.get("usefulness_score", 0) == 0]

    for r in map_records:
        totals["map_calls"] += 1
        pt, ct = r.get("usage_prompt_tokens"), r.get("usage_completion_tokens")
        if isinstance(pt, int):
            totals["prompt_tokens"] += pt
        if isinstance(ct, int):
            totals["completion_tokens"] += ct
        totals["duration_seconds"] += r.get("duration_seconds", 0) or 0
        cost = r.get("measured_cost_usd")
        if isinstance(cost, (int, float)):
            totals["cost_usd"] += cost

    reduce_a = json.loads((RESULTS / f"reduce-result-{qid}-A.json").read_text(encoding="utf-8"))
    reduce_b = json.loads((RESULTS / f"reduce-result-{qid}-B.json").read_text(encoding="utf-8"))
    for r in (reduce_a, reduce_b):
        if r.get("no_model_call"):
            continue
        totals["reduce_calls"] += 1
        pt, ct = r.get("usage_prompt_tokens"), r.get("usage_completion_tokens")
        if isinstance(pt, int):
            totals["prompt_tokens"] += pt
        if isinstance(ct, int):
            totals["completion_tokens"] += ct
        totals["duration_seconds"] += r.get("duration_seconds", 0) or 0
        cost = r.get("measured_cost_usd")
        if isinstance(cost, (int, float)):
            totals["cost_usd"] += cost

    per_question[qid] = {
        "text": questions_text.get(qid, "?"),
        "positive_count": len(positive),
        "zero_count": len(zero),
        "answer_a": reduce_a.get("answer"),
        "answer_b": reduce_b.get("answer"),
        "b_reused_a": bool(reduce_b.get("no_model_call")),
        "cited_a": reduce_a.get("cited_partial_answer_ids", []),
        "cited_b": reduce_b.get("cited_partial_answer_ids", []),
    }

print(json.dumps({"totals": totals, "per_question": per_question}, ensure_ascii=False, indent=1))

out_path = RESULTS / "phase4-aggregate.json"
out_path.write_text(json.dumps({"totals": totals, "per_question": per_question}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
print("\nwrote", out_path)
