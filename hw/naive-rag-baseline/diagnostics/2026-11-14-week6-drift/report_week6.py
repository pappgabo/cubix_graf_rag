"""Drift-only report: reuses week5-b's ``report.py`` generic, mode-agnostic
helpers (``load_results``/``write_results``/``evaluable_counts``/
``cost_latency_summary``/the per-group ``_cell`` formatter) unchanged.

``report.py``'s own ``comparison_table_markdown``/``status_breakdown_markdown``/
``cost_breakdown_markdown`` hardcode the three week5 modes
(``("naiv", "lokalis", "globalis")``) -- not reusable for a single new
mode without rewriting them, which is explicitly out of scope ("a régi
táblát ne írd át"). This module's one-column tables use the SAME type
names and the SAME correctness-category cell format
(``report._cell``, reused directly), so a later four-mode table can be
built straight from the same saved ``results.jsonl`` rows, without this
module's cooperation and without touching ``report.py``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import week6_bootstrap  # noqa: F401
import report as report_mod  # week5-b, unchanged

TYPES = ("simple", "multi-hop", "global")
STATUSES = ("frozen_w4", "held_out")


def drift_comparison_table_markdown(rows: list[dict[str, Any]]) -> str:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_type[row.get("question_type")].append(row)
    lines = ["| Kérdéstípus | drift |", "|---|---|"]
    for qtype in TYPES:
        lines.append(f"| {qtype} | {report_mod._cell(by_type.get(qtype, []))} |")
    return "\n".join(lines)


def drift_status_breakdown_markdown(rows: list[dict[str, Any]]) -> str:
    by_status: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_status[row.get("question_status")].append(row)
    lines = ["| frozen_w4 / held_out | drift |", "|---|---|"]
    for status in STATUSES:
        lines.append(f"| {status} | {report_mod._cell(by_status.get(status, []))} |")
    return "\n".join(lines)


def _drift_candidate_retrieval_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The report-candidate chunk id proxy, kept fully separate from the
    genuine local-search `retrieval` ratio report.py already computes
    (never averaged together -- "a riportforrásokból képzett mutató csak
    jelölt/proxy lehet")."""
    counts = [len(row.get("report_candidate_chunk_ids") or []) for row in rows]
    return {
        "cases": len(rows),
        "cases_with_candidate_chunks": sum(1 for c in counts if c > 0),
        "avg_candidate_chunk_count": round(sum(counts) / len(counts), 2) if counts else None,
    }


def index_cost_line(index_cost_summary: dict[str, Any] | None) -> str:
    if index_cost_summary is None:
        return ("- riportindex-embedding költsége: nincs rögzítve (a cache már létezett, vagy "
               "még nem futott le a build_index.py)")
    return (
        f"- riportindex-embedding költsége (EGYSZERI, nem kérdéstípusonkénti sor): "
        f"{index_cost_summary['cost_usd']} USD, {index_cost_summary['report_count']} riport, "
        f"forrás: {index_cost_summary['ledger_path']}"
    )


def build_drift_report_markdown(
    rows: list[dict[str, Any]], *, run_phase: str,
    index_cost_summary: dict[str, Any] | None = None,
    ledger_cumulative_spent_usd: float | None = None,
    ledger_cumulative_remaining_usd: float | None = None,
) -> str:
    phase_rows = [r for r in rows if r.get("run_phase") == run_phase]
    counts = report_mod.evaluable_counts(phase_rows)
    cost = report_mod.cost_latency_summary(phase_rows)
    candidate_summary = _drift_candidate_retrieval_summary(phase_rows)
    lines = [
        f"# Week 6 — DRIFT mérési jelentés ({run_phase})",
        "",
        "## Elemszámok",
        f"- összes eset: {counts['total_cases']}",
        f"- válasz mentve: {counts['answer_saved']}",
        f"- helyességi kritérium pontozva: {counts['criteria_scored']}",
        f"- faithfulness pontozva: {counts['faithfulness_scored']}",
        f"- retrieval nem visszavezethető (untraceable, nem nulla): {counts['retrieval_untraceable']}",
        "",
        "## DRIFT × kérdéstípus (a 3-mód táblába illeszthető formátum, egy oszloppal)",
        "",
        drift_comparison_table_markdown(phase_rows),
        "",
        "## frozen_w4 / held_out bontás",
        "",
        drift_status_breakdown_markdown(phase_rows),
        "",
        "## Költség és késleltetés -- ennek a futásnak (" + run_phase + ") a fogyasztása, "
        "a másik run_phase fogyasztását NEM tartalmazza",
        f"- teljes (generálás + mindkét bíró ismert) költségű esetek: "
        f"{cost['cases_with_known_cost']} / {cost['case_count']}",
        f"- ismert teljes költség összege ({run_phase}): {cost['cost_usd_known_sum']}",
        f"- hiányzó költségű esetek: {cost['cases_missing_cost']} "
        "(a keretnyilvántartás ilyenkor becsléssel számol, nem nulla fogyasztással)",
        f"- átlagos futásidő (s): {cost['avg_duration_seconds']}",
        "",
        index_cost_line(index_cost_summary),
        f"- kumulatív week6 ledger-fogyasztás (indexépítés + smoke + full együtt, "
        f"folytatások között is összegződik): "
        f"{ledger_cumulative_spent_usd if ledger_cumulative_spent_usd is not None else 'n/a'} USD",
        f"- kumulatív hátralévő keret: "
        f"{ledger_cumulative_remaining_usd if ledger_cumulative_remaining_usd is not None else 'n/a'} USD "
        "(ez csak az eddigi fogyasztást ellenőrzi az adott hívás előtt -- nem garantálja, hogy a "
        "teljes futás végig a kereten belül marad, mert az upper-bound becslés a válasz "
        "megérkezése előtt történik)",
        "",
        "## Retrieval-proxy a riportforrásokból (jelölt, nem ellenőrzött bizonyíték)",
        f"- esetek jelölt riport-chunk kapcsolattal: {candidate_summary['cases_with_candidate_chunks']} / "
        f"{candidate_summary['cases']}",
        f"- átlagos jelölt chunk-szám esetenként: {candidate_summary['avg_candidate_chunk_count']}",
        "Ez a mutató a primer által kiválasztott riportok key_statements."
        "candidate_source_chunk_ids kapcsolataiból képzett arány -- jelölt/proxy, nem a "
        "local_search által ténylegesen visszahozott és citált chunk. A fenti DRIFT × "
        "kérdéstípus táblában szereplő `retrieval_avg` kizárólag a lokális keresésben "
        "ténylegesen visszahozott chunkokból számol, a kettő nem keverendő össze.",
        "",
        "## Megjegyzés a primer/lokális résztől a tényszerűségig",
        "A primer riport-alapú kezdeti válasza és egy-egy lokális részválasz önmagában nem "
        "igazolja a végső szintézis minden állításának tényszerűségét -- a faithfulness-bíró "
        "a szintézisnek ténylegesen átadott, már korlátozott (`actual_context`, a "
        "`synthesis_context_truncation` szerint esetleg levágott) kontextust kapja, nem a "
        "levágás előtti teljes riport- és lokális anyagot.",
    ]
    return "\n".join(lines)
