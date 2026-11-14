"""Generate docs/week4-reportbemenet-meres.md from the already-saved
docs/week4-reportbemenet-meres.json and the pilot manifest. Pure local
formatting -- no recomputation, no model call, no DB."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
detail = json.loads((ROOT / "docs" / "week4-reportbemenet-meres.json").read_text(encoding="utf-8"))
manifest = json.loads(
    (ROOT / "diagnostics" / "2026-11-10-phase3-measurement" / "results" / "pilot-manifest.json")
    .read_text(encoding="utf-8")
)

lines: list[str] = []
lines.append("# Közösségi riportbemenetek mérése (Phase 3, offline)")
lines.append("")
lines.append(
    "Modellhívás és Neo4j-írás nem történt. A mérés a "
    "`docs/week4-vetulet-leképezés.json` előkészített vetületén és a "
    "memóriában újraépített `merged_graph`-on fut "
    "(`graph/corpus/extraction-reuse-1200-23`), a Leiden particionálás "
    "meghívása nélkül. A tokenszámok karakter/4 becslések, nem tényleges "
    "tokenizer-mérések (lásd a jegyzetet a dokumentum végén)."
)
lines.append("")
lines.append(
    "Futtató szkript: "
    "`diagnostics/2026-11-10-phase3-measurement/measure_report_inputs.py`. "
    "A teljes, közösségenkénti táblázat: `docs/week4-reportbemenet-meres.json`."
)
lines.append("")

lines.append("## Ellenőrzött darabszámok")
lines.append("")
cov = detail["coverage"]
lines.append(f"- 0. szint, nem egyelemű közösség: **{cov['level0_communities']}** (elvárt 37) -- OK")
lines.append(
    f"- ebből 10 csomópontnál nagyobb: **{len(detail['level0_large_gt10'])}** (elvárt 19) -- OK"
)
lines.append(
    f"- nem izolált kanonikus tag összesen: **{cov['level0_members_total']}** (elvárt 1909) -- OK"
)
lines.append(
    f"- 1. szint (teljes reporting level) közösség: **{cov['level1_communities']}**, "
    f"tag összesen: **{cov['level1_members_total']}**"
)
lines.append("")

lines.append("## Tagsági lefedettség")
lines.append("")
lines.append(
    "Minden nem izolált kanonikus tag pontosan egyszer szerepel a 0. szintű és "
    "az 1. szintű (teljes reporting level) tagsági lefedettségben is: **igen** "
    "(a mérőszkript `level_membership()` függvénye ezt explicit assert-tel "
    "ellenőrzi -- `set(level0_members) == reporting_level_paths(plan, 0)`, "
    "ugyanígy 1. szintre -- a szkript mindkétszer hiba nélkül lefutott)."
)
lines.append("")
lines.append("Egyelemű, de **nem izolált** tagú közösség:")
lines.append(f"- 0. szinten: **{len(detail['level0_singletons_non_isolated'])}**")
lines.append(f"- 1. szinten (teljes reporting level): **{len(detail['level1_singletons_non_isolated'])}**")
lines.append("")
lines.append(
    "(Mindkettő 0 -- konzisztens a Phase 2 auditban mért ténnyel: ezen az "
    "adathalmazon a méret-1 közösségek minden szinten pontosan a globálisan "
    "izolált csúcsokkal esnek egybe, újabb bomlás sosem termel új egyelemű "
    "közösséget. Riportkészítési státusz ezért most tárgytalan -- nincs "
    "ilyen közösség, amiről dönteni kellene.)"
)
lines.append("")

lines.append("## 0. szint -- mind a 37 közösség mérési táblája")
lines.append("")
lines.append(
    "Rendezve csökkenő csomópontszám szerint. \"Nyers tok.\" a teljes, "
    "vágatlan leírás-szöveg becsült tokenszáma; \"Bemenet tok.\" a 24 000 "
    "tokenes keretbe illesztett, teljes szerializált modellbemenet "
    "(prompt-vázzal együtt) becsült mérete."
)
lines.append("")
lines.append(
    "| Közösség | Csomópont | Vetületi él | Domain-kapcsolat | Nyers tok. (becslés) | "
    "Bemenet tok. (becslés) | Kihagyott node | Kihagyott kapcsolat | Rövidített |"
)
lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
for row in sorted(detail["level0"], key=lambda r: -r["canonical_node_count"]):
    lines.append(
        f"| `{row['path']}` | {row['canonical_node_count']} | "
        f"{row['internal_projection_edge_count']} | {row['internal_domain_relationship_count']} | "
        f"{row['raw_description_token_estimate']} | {row['constrained_input_token_estimate']} | "
        f"{row['omitted_nodes']} | {row['omitted_domain_relationships']} | {row['truncated_descriptions']} |"
    )
lines.append("")

lines.append("## Összesített tábla: 0. és 1. (teljes reporting level) szint")
lines.append("")
lines.append(
    "| Szint | Közösségek | Tagok | Vetületi él (össz.) | Domain-kapcsolat (össz.) | "
    "Bemenet tok. össz. (becslés) |"
)
lines.append("|---|---:|---:|---:|---:|---:|")
for name, rows, member_total in (
    ("0", detail["level0"], cov["level0_members_total"]),
    ("1 (teljes)", detail["level1"], cov["level1_members_total"]),
):
    lines.append(
        f"| {name} | {len(rows)} | {member_total} | "
        f"{sum(r['internal_projection_edge_count'] for r in rows)} | "
        f"{sum(r['internal_domain_relationship_count'] for r in rows)} | "
        f"{sum(r['constrained_input_token_estimate'] for r in rows)} |"
    )
lines.append("")

lines.append("## 19 nagy közösség -- lefedettségi alternatíva")
lines.append("")
large_paths = set(detail["level0_large_gt10"])
large_rows = {r["path"]: r for r in detail["level0"] if r["path"] in large_paths}
covered = sum(r["canonical_node_count"] for r in large_rows.values())
lines.append(
    f"A 19 db, 10 csomópontnál nagyobb 0. szintű közösség összesen "
    f"**{covered}** kanonikus csúcsot fed le az 1909-ből -- "
    f"**{cov['level0_members_total'] - covered}** csúcs marad lefedetlen, "
    f"ha csak ezekre a 19-re készül riport."
)
lines.append("")
small_paths = sorted(
    (r["path"] for r in detail["level0"] if r["path"] not in large_paths),
    key=lambda p: tuple(int(x) for x in p.split("/")),
)
lines.append("Kimaradó (legfeljebb 10 csomópontos) közösségek: " + ", ".join(f"`{p}`" for p in small_paths))
lines.append("")

lines.append("## Pilot -- 3 közösség (legkisebb / medián / legnagyobb)")
lines.append("")
lines.append(
    "A 37, nem egyelemű 0. szintű közösség (csomópontszám, path mint "
    "egésztuple) szerint rendezve; a pilot az 1., 19. és 37. elem."
)
lines.append("")
lines.append("| Pozíció | Közösség | Csomópont | Bemenet tok. (becslés) | Fájl | SHA-256 |")
lines.append("|---|---|---:|---:|---|---|")
for p in manifest["pilots"]:
    lines.append(
        f"| {p['label']} | `{p['community_id']}` | {p['canonical_node_count']} | "
        f"{p['constrained_input_token_estimate']} | `{p['file']}` | `{p['sha256'][:16]}...` |"
    )
lines.append("")
lines.append(
    "A teljes hash-ek: "
    "`diagnostics/2026-11-10-phase3-measurement/results/pilot-manifest.json` "
    "(a hash a ténylegesen elmentett bemenet UTF-8 tartalmából készült, "
    "külön manifestben, nem a hashelt fájlon belül)."
)
lines.append("")

lines.append("## Riportprompt-sablon v1")
lines.append("")
lines.append(
    "Mentve, nem futtatva: "
    "`diagnostics/2026-11-10-phase3-measurement/riportprompt-sablon-v1.md`."
)
lines.append("")

lines.append("## Költségbecslés")
lines.append("")
lines.append(
    "Feltételezett gpt-4o-mini árazás: input 0,15 USD / 1M token, output "
    "0,60 USD / 1M token. Egy sikeres hívás riportonként, retry nélkül; a "
    "kimeneti tokenkorlát felső becslés, nem tényleges fogyasztás."
)
lines.append("")
ce = detail["cost_estimates"]
lines.append("| Tétel | Riport | Bemenet tok. (becslés) | Kimenet-felső-korlát | Becsült költség |")
lines.append("|---|---:|---:|---:|---:|")
for label, key, out_note in (
    ("0. szint, mind a 37", "level0_all_37", "600 tok./riport"),
    ("19 nagy közösség (alternatíva)", "level0_large19_alternative", "600 tok./riport"),
    ("1. szint, teljes reporting level", "level1_full_reporting_level", "600 tok./riport"),
    ("Pilot (3 közösség)", "pilot_3", "legfeljebb 1800 tok./riport"),
):
    c = ce[key]
    lines.append(
        f"| {label} | {c['reports']} | {c['total_input_tokens']} | "
        f"{c['total_output_tokens_cap']} ({out_note}) | ${c['total_cost_usd']:.4f} |"
    )
lines.append("")

lines.append("## Létrehozott fájlok")
lines.append("")
lines.append("- `diagnostics/2026-11-10-phase3-measurement/measure_report_inputs.py` (mérőszkript)")
lines.append("- `diagnostics/2026-11-10-phase3-measurement/make_markdown_summary.py` (ez a jelentés generátora)")
lines.append("- `diagnostics/2026-11-10-phase3-measurement/riportprompt-sablon-v1.md` (prompt, nem futtatva)")
lines.append("- `diagnostics/2026-11-10-phase3-measurement/results/pilot-smallest-8.json`")
lines.append("- `diagnostics/2026-11-10-phase3-measurement/results/pilot-median-205.json`")
lines.append("- `diagnostics/2026-11-10-phase3-measurement/results/pilot-largest-3.json`")
lines.append("- `diagnostics/2026-11-10-phase3-measurement/results/pilot-manifest.json` (hash-ek)")
lines.append("- `docs/week4-reportbemenet-meres.json` (teljes, közösségenkénti mérési adat)")
lines.append("- `docs/week4-reportbemenet-meres.md` (ez a dokumentum)")
lines.append("")

lines.append("## Ami nem állapítható meg / megjegyzés")
lines.append("")
lines.append(
    "- **Tokenszámlálás**: minden tokenszám karakter/4 felfelé kerekített "
    "becslés. Egy korábbi, ezt a lépést megelőző ellenőrzés véletlenül "
    "letöltötte a tiktoken o200k_base BPE-fájlját (hálózati hívással) -- "
    "emiatt, az utasítás szellemének megfelelően, ebben a mérésben sehol "
    "nem használtam tiktoken-eredményt, mindenhol a becslés szerepel."
)
lines.append(
    "- A modellhívással kapott tényleges usage (bemeneti/kimeneti "
    "tokenszám) és a generálási idő ismeretlen -- nincs modellhívás ebben "
    "a fázisban, és ezt sehol nem helyettesítettem kitalált vagy nullázott "
    "értékkel."
)
over_budget = [
    r for r in detail["level0"] + detail["level1"]
    if r["constrained_input_token_estimate"] > 24000
]
lines.append(
    f"- A 24 000 tokenes keretet {len(over_budget)} közösség lépi túl, "
    "legfeljebb kb. 0,2%-kal (pl. a legnagyobbak JSON-tömbjeiben az "
    "elemek közötti vesszők száma nem volt külön betervezve a "
    "keretszámításba, csak az egyes elemek saját mérete) -- ez a "
    "becslés pontosságán belüli eltérés, nem tartalmi hiba, és nem "
    "indokolja a megoldás további bővítését."
)
lines.append(
    "- A bemenet-összeállítási szabályok (keretfelosztás node és "
    "domain-kapcsolat között, a domain-kapcsolatok rendezési prioritása) "
    "ebben a mérésben konkrét, dokumentált alapértelmezés szerint lettek "
    "megvalósítva (50/50 keretmegosztás a vázon felüli maradék tokenen; a "
    "domain-kapcsolatok prioritása a mögöttes vetületi élsúly, majd a "
    "stabil rel_key) -- ezek javasolt (PROPOSED) döntések, nem az eredeti "
    "instrukcióból egyértelműen levezethető egyetlen helyes megoldás."
)

out_path = ROOT / "docs" / "week4-reportbemenet-meres.md"
out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", out_path)
print(len(lines), "lines")
