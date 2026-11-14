"""results.jsonl persistence and the comparison report (Markdown table +
frozen_w4/held_out breakdown + cost/latency summary).

One JSONL row per (question_id, mode) case -- this file, not Langfuse, is
the archive of record and the resumability basis.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

CORRECTNESS_LABELS = ("helyes", "hiányos", "elutasított", "téves", "error")


def append_result(path: Path, row: dict[str, Any]) -> None:
    """Appends one case row. Existing rows for the same (question_id,
    mode, run_phase) are not deduplicated here -- callers (measure.py)
    rewrite the whole file from the state store on each save instead, so
    this is only used by the initial per-case write path in tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_results(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Rewrites the whole file from the given rows (keyed by
    (question_id, mode, run_phase) by the caller) -- avoids duplicate
    lines across resumed runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _cell(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "n/a (0 eset)"
    label_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        label = (row.get("correctness") or {}).get("label") or "n/a"
        label_counts[label] += 1
    retrieval_ratios = [
        row["retrieval"]["ratio"] for row in rows
        if row.get("retrieval") and row["retrieval"].get("ratio") is not None
        and not row["retrieval"].get("is_proxy")
    ]
    proxy_ratios = [
        row["retrieval"]["ratio"] for row in rows
        if row.get("retrieval") and row["retrieval"].get("ratio") is not None
        and row["retrieval"].get("is_proxy")
    ]
    faithfulness_scores = [
        row["faithfulness"]["score"] for row in rows
        if row.get("faithfulness") and isinstance(row["faithfulness"].get("score"), (int, float))
    ]
    label_str = ", ".join(f"{k}={v}" for k, v in sorted(label_counts.items()))
    parts = [f"n={len(rows)}", label_str]
    if retrieval_ratios:
        parts.append(f"retrieval_avg={_avg(retrieval_ratios):.2f}")
    if proxy_ratios:
        parts.append(f"retrieval_proxy_avg={_avg(proxy_ratios):.2f} (proxy, n/a valódi lefedettség)")
    if faithfulness_scores:
        parts.append(f"faithfulness_avg={_avg(faithfulness_scores):.2f}")
    return "<br>".join(parts)


def comparison_table_markdown(rows: list[dict[str, Any]]) -> str:
    modes = ("naiv", "lokalis", "globalis")
    types = ("simple", "multi-hop", "global")
    by_type_mode: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_type_mode[(row.get("question_type"), row.get("mode"))].append(row)

    lines = ["| Kérdéstípus | " + " | ".join(modes) + " |",
             "|---|" + "---|" * len(modes)]
    for qtype in types:
        cells = [_cell(by_type_mode.get((qtype, mode), [])) for mode in modes]
        lines.append(f"| {qtype} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def status_breakdown_markdown(rows: list[dict[str, Any]]) -> str:
    modes = ("naiv", "lokalis", "globalis")
    statuses = ("frozen_w4", "held_out")
    by_status_mode: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_status_mode[(row.get("question_status"), row.get("mode"))].append(row)

    lines = ["| frozen_w4 / held_out | " + " | ".join(modes) + " |",
             "|---|" + "---|" * len(modes)]
    for status in statuses:
        cells = [_cell(by_status_mode.get((status, mode), [])) for mode in modes]
        lines.append(f"| {status} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _cost_bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Full cost (``cost_usd``) is only ever set when all three step costs
    are known (see measure.py's ``_recompute_total_cost``) -- so counting
    it here never mistakes a partial cost for the whole case's cost. A row
    with at least one known step cost but not a full ``cost_usd`` is
    counted as ``partial_count``, kept distinct from ``unknown_count``
    (no step cost known at all -- not the same as zero spend)."""
    full_known = [row["cost_usd"] for row in rows if isinstance(row.get("cost_usd"), (int, float))]
    partial = 0
    unknown = 0
    for row in rows:
        if isinstance(row.get("cost_usd"), (int, float)):
            continue
        subs = (row.get("cost_usd_generation"), row.get("cost_usd_correctness_judge"),
               row.get("cost_usd_faithfulness_judge"))
        if any(isinstance(s, (int, float)) for s in subs):
            partial += 1
        else:
            unknown += 1
    return {
        "case_count": len(rows),
        "full_known_count": len(full_known),
        "full_known_sum": round(sum(full_known), 6) if full_known else None,
        "partial_count": partial,
        "unknown_count": unknown,
    }


def cost_by_mode(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_mode: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_mode[row.get("mode")].append(row)
    return {mode: _cost_bucket(group) for mode, group in by_mode.items()}


def cost_by_question_type(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_type[row.get("question_type")].append(row)
    return {qtype: _cost_bucket(group) for qtype, group in by_type.items()}


_EMPTY_COST_BUCKET = {"case_count": 0, "full_known_count": 0, "full_known_sum": None,
                      "partial_count": 0, "unknown_count": 0}


def cost_breakdown_markdown(rows: list[dict[str, Any]]) -> str:
    modes = ("naiv", "lokalis", "globalis")
    types = ("simple", "multi-hop", "global")
    by_mode = cost_by_mode(rows)
    by_type = cost_by_question_type(rows)

    def _rows(labels: tuple[str, ...], buckets: dict[str, dict]) -> list[str]:
        out = []
        for label in labels:
            b = buckets.get(label, _EMPTY_COST_BUCKET)
            out.append(
                f"| {label} | {b['full_known_count']} / {b['case_count']} | "
                f"{b['full_known_sum']} | {b['partial_count']} | {b['unknown_count']} |")
        return out

    header = ["| | teljes költségű esetek | ismert összeg (USD) | részleges | ismeretlen |",
             "|---|---|---|---|---|"]
    lines = ["### Módonként", "", *header, *_rows(modes, by_mode), "",
             "### Kérdéstípusonként", "", *header, *_rows(types, by_type)]
    return "\n".join(lines)


def cost_latency_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    known_cost = [row["cost_usd"] for row in rows if isinstance(row.get("cost_usd"), (int, float))]
    durations = [row["duration_seconds"] for row in rows if isinstance(row.get("duration_seconds"), (int, float))]
    return {
        "case_count": len(rows),
        "cost_usd_known_sum": round(sum(known_cost), 6) if known_cost else None,
        "cases_with_known_cost": len(known_cost),
        "cases_missing_cost": len(rows) - len(known_cost),
        "avg_duration_seconds": round(_avg(durations), 3) if durations else None,
    }


def evaluable_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total_cases": len(rows),
        "answer_saved": sum(1 for r in rows if r.get("answer") is not None or r.get("error")),
        "criteria_scored": sum(1 for r in rows if r.get("correctness") is not None),
        "faithfulness_scored": sum(1 for r in rows if r.get("faithfulness") is not None),
        "retrieval_untraceable": sum(
            1 for r in rows if r.get("retrieval") and r["retrieval"].get("status") == "untraceable"),
        "retrieval_proxy": sum(
            1 for r in rows if r.get("retrieval") and r["retrieval"].get("is_proxy")),
    }


def build_report_markdown(rows: list[dict[str, Any]], *, run_phase: str) -> str:
    phase_rows = [r for r in rows if r.get("run_phase") == run_phase]
    counts = evaluable_counts(phase_rows)
    cost = cost_latency_summary(phase_rows)
    lines = [
        f"# Week 5 B — mérési jelentés ({run_phase})",
        "",
        "## Elemszámok",
        f"- összes eset: {counts['total_cases']}",
        f"- válasz mentve: {counts['answer_saved']}",
        f"- helyességi kritérium pontozva: {counts['criteria_scored']}",
        f"- faithfulness pontozva: {counts['faithfulness_scored']}",
        f"- retrieval nem visszavezethető (untraceable, nem nulla): {counts['retrieval_untraceable']}",
        f"- retrieval proxy (globális): {counts['retrieval_proxy']}",
        "",
        "## Három mód × kérdéstípus",
        "",
        comparison_table_markdown(phase_rows),
        "",
        "## frozen_w4 / held_out bontás",
        "",
        status_breakdown_markdown(phase_rows),
        "",
        "## Költség és késleltetés",
        f"- teljes (mindhárom szakasz ismert) költségű esetek: {cost['cases_with_known_cost']} / {cost['case_count']}",
        f"- ismert teljes költség összege: {cost['cost_usd_known_sum']}",
        f"- hiányzó költségű esetek: {cost['cases_missing_cost']} "
        "(a keretnyilvántartás ilyenkor becsléssel számol, nem nulla fogyasztással)",
        f"- átlagos futásidő (s): {cost['avg_duration_seconds']}",
        "",
        "A részleges (nem mindhárom szakaszra ismert) költség nem szerepel "
        "teljes esetköltségként -- a lenti bontás külön jelzi.",
        "",
        cost_breakdown_markdown(phase_rows),
        "",
        "## Megjegyzés a proxy/n-a jelölésekről",
        "A globális mód `retrieval_proxy_avg` értéke a reduce-nak ténylegesen átadott "
        "részválaszok candidate_source_chunk_ids kapcsolataiból képzett arány, nem "
        "valódi, soronként ellenőrzött bizonyíték-lefedettség -- nem átlagolható "
        "össze a naiv/lokalis `retrieval_avg` értékekkel.",
    ]
    return "\n".join(lines)
