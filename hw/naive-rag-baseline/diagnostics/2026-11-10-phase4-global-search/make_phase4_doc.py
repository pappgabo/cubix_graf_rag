"""Generate docs/week4-globalis-kereses-phase4.md from the already-saved
Phase 4 aggregate. Pure local formatting -- no model call."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / "results"
agg = json.loads((RESULTS / "phase4-aggregate.json").read_text(encoding="utf-8"))
totals = agg["totals"]
per_q = agg["per_question"]

CHANGE_NOTES = {
    "Q09": "Nincs érdemi tartalmi eltérés -- mindkettő Lewis Hamiltont nevezi meg 7 címmel; B tömörebb megfogalmazású. Megjegyzés: egyik válasz sem említi, hogy a gold szerint Schumacher is 7 címmel holtversenyben áll -- ez hiányzó, nem téves információ.",
    "Q10": "A két válasz szövege szó szerint megegyezik (Schumacher, Räikkönen, Leclerc). A gold 6 pilótát sorol fel (+ Alonso, Vettel, Hamilton) -- a riportkészlet ezekre nem talált/nem pontszámozott elég közvetlen bizonyítékot.",
    "Q11": "Mindkét válasz elutasít, elégtelen bizonyítékra hivatkozva, gyakorlatilag azonos szöveggel. Egyik sem szintetizálta a konstruktőri összesítést, noha a gold szerint ez (Ferrari, 15 cím) a riportokból elvben levezethető lenne.",
    "Q12": "Tartalmilag hasonlóak; B egy explicit bizonytalansági megjegyzést told hozzá (\"specific championship years ... not provided\"). Mindkettő pontatlanságot tartalmaz a gold-hoz képest (pl. Schumacher éveinek rossz tartománya).",
    "Q13": "Apró eltérés: A 3, B csak 2 közösségre hivatkozik (263 kimarad B-ből), miközben B szövege ennek ellenére megnevez Schumachert és Räikkönent is -- ez hivatkozás és tartalom közti kisebb következetlenség, amit észlelésként dokumentálok, nem javítok.",
}

lines: list[str] = []
lines.append("# Globális keresés (Phase 4) -- map-reduce a 37 közösségi riportból")
lines.append("")
lines.append(
    "run_id = `week4-leiden-elokeszitett-6f05327d7d88ebf0`. Neo4j-írás nem történt, új "
    "közösségi riport nem készült, router/háromoldalú összehasonlítás nem készült. Az "
    "implementáció a `src/naive_rag/global_search.py` modulban van (paraméterezett "
    "riport- és kérdésfájl-útvonalakkal, nem függ pilot-scriptektől)."
)
lines.append("")

lines.append("## Kérdésenkénti összevetés")
lines.append("")
for qid in ["Q09", "Q10", "Q11", "Q12", "Q13"]:
    q = per_q[qid]
    lines.append(f"### {qid}")
    lines.append("")
    lines.append(f"**Eredeti kérdés:** {q['text']}")
    lines.append("")
    lines.append(f"**Map-eredmények:** {q['positive_count']} pozitív pontszámú, {q['zero_count']} nulla pontszámú (37-ből).")
    lines.append("")
    lines.append(f"**Alapválasz (A, csak pozitív pontszámúak, hivatkozott közösségek: {q['cited_a'] or '-'}):**")
    lines.append(f"> {q['answer_a']}")
    lines.append("")
    lines.append(f"**Nulla pontszámúakat is beengedő válasz (B, hivatkozott közösségek: {q['cited_b'] or '-'}):**")
    lines.append(f"> {q['answer_b']}")
    lines.append("")
    lines.append(f"**Mi változott:** {CHANGE_NOTES[qid]}")
    lines.append("")

lines.append("## Mérés, összesítve")
lines.append("")
lines.append(
    f"- Tényleges hívásszám: {totals['map_calls']} map + {totals['reduce_calls']} reduce "
    f"= **{totals['map_calls'] + totals['reduce_calls']}** (engedélyezett felső korlát: 195 = 5x37 + 5x2)."
)
lines.append(f"- `usage.prompt_tokens` összesen: **{totals['prompt_tokens']}**")
lines.append(f"- `usage.completion_tokens` összesen: **{totals['completion_tokens']}**")
lines.append(f"- Mért futási idő összesen: **{totals['duration_seconds']:.1f} s**")
lines.append(f"- Mért költség (0,15/0,60 USD per 1M token): **${totals['cost_usd']:.4f}**")
lines.append("")
lines.append(
    "10 db reduce-hívás (2 × 5 kérdés) mindegyike valódi modellhívás volt -- egyetlen "
    "kérdésnél sem egyezett a nulla pontszámúakat is beengedő (B) bemenet a csak-pozitív "
    "(A) bemenettel, ezért a B-ág sosem hivatkozott A mentett eredményére. Teljes "
    "elutasítás modellhívás nélkül sem fordult elő -- minden kérdéshez volt legalább egy "
    "pozitív pontszámú részválasz."
)
lines.append("")

lines.append("## Hibák / blokkolók")
lines.append("")
lines.append("Egyik lépés sem hibázott, nem csonkolt (`finish_reason=length` sehol), nem hivatkozott ismeretlen azonosítóra. A futás a mind az 5 kérdésre lefutott, megállás nélkül.")
lines.append("")

lines.append("## Korlátok")
lines.append("")
lines.append(
    "- Ez **nem teljes körű tartalmi audit** -- a fenti \"mi változott\" megjegyzések "
    "mentett válaszok puszta átolvasásán alapulnak, külön értékelő modellhívás nélkül."
)
lines.append(
    "- A formai hivatkozás-ellenőrzés (érvényes `evidence_ids`/`cited_statement_ids`/"
    "`cited_partial_answer_ids`) **nem bizonyítja** egyik válasz tartalmi helyességét sem."
)
lines.append(
    "- A **tagsági lefedettség** (a Phase 2/3 auditált 1909 nem izolált kanonikus tag) "
    "**nem azonos** a globális keresés tényleges válasz-lefedettségével: több kérdésnél "
    "(Q10, Q11) a gold válaszhoz képest hiányos a végeredmény, annak ellenére, hogy az "
    "adott tények valahol a 37 riport valamelyikében elvileg jelen lehetnek -- a "
    "riportok szelektív/rövidített bemenete és a map-pontszámozás szűrhetett ki releváns, "
    "de a modell által alacsonyra pontozott információt."
)
lines.append("- Nem állítok globális keresési fölényt pusztán attól, hogy mindkét ág választ adott.")
lines.append("")

lines.append("## Fájlok")
lines.append("")
lines.append("- `src/naive_rag/global_search.py` (az implementáció), `tests/test_global_search.py` (25 offline teszt)")
lines.append("- `diagnostics/2026-11-10-phase4-global-search/results/map-result-<Qxx>-<path>.json`, `map-raw-...json` (185+185 db)")
lines.append("- `diagnostics/2026-11-10-phase4-global-search/results/reduce-result-<Qxx>-{A,B}.json`, `reduce-raw-...json`")
lines.append("- `diagnostics/2026-11-10-phase4-global-search/results/ledger.json` (folytathatósági nyilvántartás, 195 bejegyzés)")
lines.append("- `diagnostics/2026-11-10-phase4-global-search/results/phase4-aggregate.json` (ez az összegzés nyers adata)")
lines.append("- `docs/week4-globalis-kereses-phase4.md` (ez a dokumentum)")
lines.append("")
lines.append("**Futtatási parancs:**")
lines.append("```")
lines.append(
    "PYTHONPATH=src uv run python -m naive_rag.global_search \\\n"
    "  --collection diagnostics/2026-11-10-phase3-measurement/results/week4-report-v3-collection.jsonl \\\n"
    "  --questions questions.md \\\n"
    "  --out-dir diagnostics/2026-11-10-phase4-global-search/results \\\n"
    "  --ledger diagnostics/2026-11-10-phase4-global-search/results/ledger.json"
)
lines.append("```")

out_path = ROOT / "docs" / "week4-globalis-kereses-phase4.md"
out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", out_path)
