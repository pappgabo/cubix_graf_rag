"""Generate docs/week4-kozossegi-riportok-v3.md from the already-saved v3
run summary, per-community reports, and the earlier pilot summaries. Pure
local formatting -- no model call, no recomputation of selection/edges."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "diagnostics" / "2026-11-10-phase3-measurement" / "results"

v3_summary = json.loads((RESULTS / "week4-report-v3-run-summary.json").read_text(encoding="utf-8"))
v1_pilot = json.loads((RESULTS / "week4-pilot-run-summary.json").read_text(encoding="utf-8"))
v2_pilot = json.loads((RESULTS / "week4-pilot-v2-run-summary.json").read_text(encoding="utf-8"))

v3_rows = []
v3_prompt = v3_completion = 0
v3_cost = 0.0
for path in v3_summary["successes"]:
    r = json.loads((RESULTS / f"week4-report-v3-report-{path}.json").read_text(encoding="utf-8"))
    v3_rows.append(r)
    v3_prompt += r["usage_prompt_tokens"]
    v3_completion += r["usage_completion_tokens"]
    v3_cost += r["measured_cost_usd"]
v3_duration = sum(r["duration_seconds"] for r in v3_rows)

v1_prompt = sum(r["usage_prompt_tokens"] for r in v1_pilot["results"])
v1_completion = sum(r["usage_completion_tokens"] for r in v1_pilot["results"])
v1_cost = round(v1_prompt / 1_000_000 * 0.15 + v1_completion / 1_000_000 * 0.60, 6)

v2_prompt = v2_pilot["usage_prompt_tokens"]
v2_completion = v2_pilot["usage_completion_tokens"]
v2_cost = v2_pilot["measured_cost_usd"]

total_calls = len(v1_pilot["results"]) + 1 + len(v3_rows)
total_prompt = v1_prompt + v2_prompt + v3_prompt
total_completion = v1_completion + v2_completion + v3_completion
total_cost = round(v1_cost + v2_cost + v3_cost, 6)

lines: list[str] = []
lines.append("# Közösségi riportok, v3 (rekordazonosítós hivatkozás) -- a 37, 0. szintű közösség")
lines.append("")
lines.append(
    "run_id = `week4-leiden-elokeszitett-6f05327d7d88ebf0`. Neo4j-írás nem történt; a "
    "riportok csak helyi fájlokba kerültek. A globális keresés / router ebben a lépésben "
    "nem készült el."
)
lines.append("")

lines.append("## Eredmény a 37-ből")
lines.append("")
lines.append(
    f"- Sikeres: **{len(v3_summary['successes'])}**\n"
    f"- Hibás/érvénytelen: **{len(v3_summary['invalid'])}**\n"
    f"- API-hiba: **{len(v3_summary['errored'])}**\n"
    f"- Le nem futott: **{len(v3_summary['not_run'])}**"
)
lines.append("")
lines.append(
    "Mind a 37 közösség sikeresen, elsőre érvényes riportot kapott -- egyetlen hívás sem "
    "igényelt újrapróbálkozást (nem is lett volna rá engedély)."
)
lines.append("")

lines.append("## Modellhívások és költség")
lines.append("")
lines.append(
    "| Szakasz | Hívások | `prompt_tokens` | `completion_tokens` | Idő (s) | Mért költség |"
)
lines.append("|---|---:|---:|---:|---:|---:|")
lines.append(f"| v1 pilot (3 közösség, hosszú chunk-id hivatkozás) | 3 | {v1_prompt} | {v1_completion} | -- | ${v1_cost:.4f} |")
lines.append(f"| v2 pilot (1 közösség -- \"largest\", rekordazonosító) | 1 | {v2_prompt} | {v2_completion} | {v2_pilot['duration_seconds']} | ${v2_cost:.4f} |")
lines.append(f"| v3, mind a 37 közösség (rekordazonosító, max_tokens=900) | 37 | {v3_prompt} | {v3_completion} | {v3_duration:.1f} | ${v3_cost:.4f} |")
lines.append(f"| **Phase 3 összesen** | **{total_calls}** | **{total_prompt}** | **{total_completion}** | -- | **${total_cost:.4f}** |")
lines.append("")
lines.append(
    "Az eredeti, karakter/4-becslésen alapuló költségbecslés a mind a 37 riportra "
    "(`docs/week4-reportbemenet-meres.json`, 600 tokenes kimeneti felső korláttal, csak a "
    "JSON-bemenetet számolva) $0.0641 volt. A tényleges, mért v3 költség (900 tokenes "
    "felső korláttal, a rendszerutasítást is beleszámítva, rekordazonosítós bemenettel) "
    f"**${v3_cost:.4f}** -- alacsonyabb, elsősorban azért, mert a tényleges "
    "kimeneti tokenszám (átlag ~{0:.0f} token/riport) jóval a 900-as felső korlát alatt "
    "maradt, és a rekordazonosítós bemenet rövidebb, mint a hosszú chunk-id-listák lettek "
    "volna.".format(v3_completion / len(v3_rows))
)
lines.append("")

lines.append("## A három mintariport ellenőrzése (modellhívás nélkül, nem teljes körű)")
lines.append("")
lines.append(
    "Összeolvastam a v3 kulcsállításokat a hivatkozott rekordok tényleges szövegével "
    "(lásd `results/week4-report-v3-report-{8,205,3}.json`). Nyilvánvalóan nem odaillő "
    "hivatkozást nem találtam; egy helyen (`205` közösség, 2. állítás) két, tartalmilag "
    "majdnem azonos rekord (`E005` és `N007`, ugyanarról a Leclerc-eredményről) került "
    "együtt hivatkozásra -- redundáns, de nem téves."
)
lines.append("")
lines.append(
    "- **`8` (legkisebb):** 1 állítás, a Honda Racing Corporation -> Acura ARX-06 "
    "kapcsolatról, pontosan a hivatkozott rekord szövegét követi."
)
lines.append(
    "- **`205` (medián):** 3 állítás, **több témát** fed le -- a Belga Nagydíj helyszíne "
    "és több győztese (Hamilton, Schumacher, Reutemann), Leclerc vegyes eredményei, "
    "Verstappen kiesése. Ez összhangban van a v3 \"fedje le a fő, egymástól eltérő "
    "témákat\" utasításával."
)
lines.append(
    "- **`3` (legnagyobb, 89 csomópont):** a riport **továbbra is kizárólag Charles "
    "Leclerc-re szűkül** (2021, 2022, 2023, 2024-es szezonjai) -- a v3 explicit "
    "utasítása ellenére sem fedett le más, a bemenetben jelen lévő entitást vagy "
    "témát. Ez dokumentált korlát, nem javítottam újabb modellhívással."
)
lines.append("")

lines.append("## Szintválasztás indoka")
lines.append("")
lines.append(
    "A 0. szint mindössze 37 riporttal lefedi mind az 1909 nem izolált kanonikus tagot "
    "(1 riport/jelentős közösség), szemben az 1. szint teljes reporting level-jével "
    "(191 közösség, 191 riport ugyanazt az 1909 tagot fedné le, lényegesen több "
    "hívással és költséggel, lásd a korábbi mérési jelentést)."
)
lines.append("")

lines.append("## Korlátok")
lines.append("")
lines.append(
    "- A bemenet válogatott és rövidített (24 000 tokenes keret, 80/50 tokenes "
    "leírás-sapka) -- lásd `docs/week4-reportbemenet-meres.md`."
)
lines.append(
    "- A `3` közösség esete mutatja, hogy a válogatás/rövidítés és a modell saját "
    "preferenciája (a leggyakrabban előforduló entitás felé) tematikus "
    "információvesztéshez vezethet, a kifejezett utasítás ellenére is."
)
lines.append(
    "- A mintariport-ellenőrzés **nem teljes körű tartalmi audit** -- csak formai "
    "(rekordazonosító-érvényesség) és egy rövid, 3 közösségre korlátozott, kézi "
    "átolvasás történt."
)
lines.append(
    "- **A tagsági lefedettség (mind az 1909 tag szerepel valamelyik 37 közösségben) "
    "nem azonos a riportok tartalmi lefedettségével** (hogy a riport ténylegesen "
    "megemlíti-e az adott tag szerepét) -- ezt a `3` közösség esete konkrétan is "
    "igazolja: 89 tag van benne, de a riport ezek túlnyomó részét nem említi."
)
lines.append("")

lines.append("## Fájlok")
lines.append("")
lines.append("- `diagnostics/2026-11-10-phase3-measurement/week4-report-v3-prompt-template.md` (v3 sablon, nem futtatva külön)")
lines.append("- `diagnostics/2026-11-10-phase3-measurement/generate_reports_v3.py` (futtató szkript)")
lines.append("- `.../results/week4-report-v3-input-<path>.json`, `week4-report-v3-record-chunk-map-<path>.json` (37 db)")
lines.append("- `.../results/week4-report-v3-raw-<path>.json`, `week4-report-v3-report-<path>.json` (37 db)")
lines.append("- `.../results/week4-report-v3-attempt-ledger.json` (folytathatósági nyilvántartás)")
lines.append("- `.../results/week4-report-v3-collection.jsonl` (mind a 37 sikeres riport, soronként egy JSON, globális kereséshez)")
lines.append("- `.../results/week4-report-v3-run-summary.json` (futási összesítő)")
lines.append("- `docs/week4-kozossegi-riportok-v3.md` (ez a dokumentum)")
lines.append("")

lines.append("## Ami nem állapítható meg")
lines.append("")
lines.append(
    "A hivatkozások formai érvényessége (mindenhol teljesült) nem bizonyítja a "
    "riportok tartalmi helyességét -- ezt sem a kód, sem ez a dokumentum nem állítja. "
    "A globális keresési használhatóság (pl. router, kereszthivatkozás riportok "
    "között) ebben a lépésben nincs vizsgálva -- az nem volt engedélyezve."
)

out_path = ROOT / "docs" / "week4-kozossegi-riportok-v3.md"
out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", out_path)
print("totals: calls=", total_calls, "prompt=", total_prompt, "completion=", total_completion, "cost=", total_cost)
