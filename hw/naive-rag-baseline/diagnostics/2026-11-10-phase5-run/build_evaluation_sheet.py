"""Build the filled (but PRELIMINARY) Phase 5 evaluation sheet from the
already-saved run results. No new model call. The original template
(docs/week4-ertekelesi-lap-sablon.json) is left untouched; this writes a
separate file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
LOG_DIR = HERE / "logs"

from naive_rag.evaluation_sheet import EvaluationRow, save_template  # noqa: E402

naiv = json.loads((RESULTS / "week4-phase5-naiv-answers.json").read_text(encoding="utf-8"))
lokalis = json.loads((RESULTS / "week4-phase5-lokalis-answers.json").read_text(encoding="utf-8"))
globalis = json.loads((RESULTS / "week4-phase5-globalis-rerun.json").read_text(encoding="utf-8"))
ledger = json.loads((RESULTS / "week4-phase5-ledger.json").read_text(encoding="utf-8"))

QUESTION_IDS = [f"Q{i:02d}" for i in range(1, 14)]

# Preliminary (NOT final) correctness/support judgements, from a single
# read-through against the gold answers in questions.md -- not an
# exhaustive audit. Missing keys default to "nem eldönthető".
PRELIM = {
    ("naiv", "Q01"): ("helyes", "forrásrészletben alátámasztott", None, "Hamilton 7, ties Schumacher -- matches gold."),
    ("naiv", "Q02"): ("helyes", "forrásrészletben alátámasztott", None, "Vettel 23, 2010 -- matches gold."),
    ("naiv", "Q03"): ("helyes", "forrásrészletben alátámasztott", None, "Verstappen, Red Bull, 2021 -- matches gold."),
    ("naiv", "Q04"): ("elutasított", None, "keresési hiba", "Naiv refused outright; a multi-hop question, as the router itself predicted naiv is weak here."),
    ("naiv", "Q05"): ("téves", "egyikben sem", "generálási hiba", "Names Räikkönen as the 2012 champion and Lotus as his team -- gold says Vettel/Red Bull. Confidently wrong, not a refusal."),
    ("naiv", "Q06"): ("helyes", "forrásrészletben alátámasztott", None, "Schumacher/Hamilton with matching teams -- matches gold on visible text."),
    ("naiv", "Q07"): ("hiányos", "forrásrészletben alátámasztott", None, "Names the teammates and 2nd/3rd places but omits that Räikkönen won the title by one point -- the actual question asked."),
    ("naiv", "Q08"): ("helyes", "forrásrészletben alátámasztott", None, "Bottas from Williams -- matches gold."),
    ("naiv", "Q09"): ("helyes", "forrásrészletben alátámasztott", None, "Schumacher AND Hamilton, 7 each -- matches gold exactly (better than this run's globalis answer)."),
    ("naiv", "Q10"): ("hiányos", "forrásrészletben alátámasztott", None, "5 of the 6 gold names (missing Hamilton)."),
    ("naiv", "Q11"): ("helyes", "forrásrészletben alátámasztott", None, "Ferrari, 15 titles -- matches gold exactly (globalis refused this same question)."),
    ("naiv", "Q13"): ("elutasított", None, "keresési hiba", "Naiv refused outright on the open synthesis question -- expected weakness per the question's own rationale in questions.md."),
    ("lokalis", "Q01"): ("helyes", "forrásrészletben alátámasztott", None, "Matches gold."),
    ("lokalis", "Q02"): ("helyes", "forrásrészletben alátámasztott", None, "Matches gold."),
    ("lokalis", "Q03"): ("elutasított", None, "keresési hiba", "Refused on a simple fact question -- likely an anchoring/entity-match gap, not investigated further here."),
    ("lokalis", "Q04"): ("helyes", "forrásrészletben alátámasztott", None, "Matches gold exactly; better than naiv here."),
    ("lokalis", "Q05"): ("elutasított", None, "keresési hiba", "Refused; same information gap as naiv for this question."),
    ("lokalis", "Q06"): ("helyes", "forrásrészletben alátámasztott", None, "Matches gold on visible text."),
    ("lokalis", "Q07"): ("helyes", "forrásrészletben alátámasztott", None, "Correctly states Räikkönen won by one point -- matches gold precisely."),
    ("lokalis", "Q08"): ("helyes", "forrásrészletben alátámasztott", None, "Matches gold."),
    ("lokalis", "Q09"): ("helyes", "forrásrészletben alátámasztott", None, "Both Hamilton and Schumacher, 7 each -- matches gold exactly."),
    ("lokalis", "Q11"): ("téves", "egyikben sem", "generálási hiba", "States Renault, 12 titles -- gold is Ferrari, 15. A clear factual error, not a refusal."),
    ("lokalis", "Q12"): ("hiányos", "forrásrészletben alátámasztott", None, "Missing most of the 2000s champions present in gold (Schumacher, Alonso, Button)."),
    ("lokalis", "Q13"): ("elutasított", None, "keresési hiba", "Refused on the open synthesis question."),
}


def context_size_for(mode: str, question_id: str) -> tuple[int | str, bool]:
    if mode == "naiv":
        path = LOG_DIR / f"naive-log-naiv-{question_id}.json"
    elif mode == "lokalis":
        path = LOG_DIR / f"local-log-lokalis-{question_id}.json"
    else:
        return "lásd: globalis külön mérés (37 map + 1 reduce hívás összesítve)", True
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        tokens = data.get("usage_prompt_tokens")
        if isinstance(tokens, int):
            return tokens, False
    return "ismeretlen", True


def call_count_and_cost(mode: str, question_id: str) -> tuple[int, float | str]:
    if mode == "globalis":
        entries = [e for e in ledger if e.get("question_id") == question_id
                  and e.get("step") in ("embedding",) and question_id in str(e.get("label", ""))]
        # globalis cost is distributed over many map calls; report from the rerun result file instead
        return -1, "lásd globalis összesítés"
    entries = [e for e in ledger if e.get("question_id") == question_id and e.get("mode") == mode]
    cost = sum(e.get("cost_usd", 0) or 0 for e in entries if isinstance(e.get("cost_usd"), (int, float)))
    embed_entries = [e for e in ledger if e.get("step") == "embedding" and f"{mode}-query-{question_id}" == e.get("label")]
    embed_cost = sum(e.get("cost_usd", 0) or 0 for e in embed_entries if isinstance(e.get("cost_usd"), (int, float)))
    return len(entries) + len(embed_entries), round(cost + embed_cost, 8)


rows: list[EvaluationRow] = []
for qid in QUESTION_IDS:
    for mode, answers in (("naiv", naiv), ("lokalis", lokalis)):
        entry = answers.get(qid) or {}
        answer = entry.get("answer")
        context_size, is_estimate = context_size_for(mode, qid)
        call_count, cost = call_count_and_cost(mode, qid)
        prelim = PRELIM.get((mode, qid))
        row = EvaluationRow(
            question_id=qid, mode=mode, answer=answer,
            context_size_tokens=context_size, context_size_is_estimate=is_estimate,
            call_count=call_count, cost_usd=cost,
            correctness=prelim[0] if prelim else "nem eldönthető",
            support=prelim[1] if prelim else "nem eldönthető",
            error_category=prelim[2] if prelim else None,
            justification=prelim[3] if prelim else "Nincs mélyreható összevetés ebben a körben.",
            evidence_reference=f"diagnostics/2026-11-10-phase5-run/logs/"
                               f"{'naive' if mode=='naiv' else 'local'}-log-{mode}-{qid}.json",
        )
        rows.append(row)
    if qid in globalis:
        g = globalis[qid]
        answer = g.get("reduce_a", {}).get("answer")
        row = EvaluationRow(
            question_id=qid, mode="globalis", answer=answer,
            context_size_tokens="lásd week4-phase5-globalis-rerun.json (37 map + legfeljebb 1 reduce hívás)",
            context_size_is_estimate=True,
            call_count=38, cost_usd="lásd az összesített globalis tételt",
            correctness="nem eldönthető", support="nem eldönthető", error_category=None,
            justification="Phase 2/3/4 és a mostani rerun már részletesen elemezte Q09-Q11-et külön jelentésben; "
                          "itt nem ismételtem meg azt a mély elemzést.",
            evidence_reference="diagnostics/2026-11-10-phase5-run/results/week4-phase5-globalis-rerun.json",
        )
        rows.append(row)

out_path = ROOT / "docs" / "week4-ertekelesi-lap-kitoltott.json"
save_template(out_path, rows)
print("wrote", out_path, "rows:", len(rows))
