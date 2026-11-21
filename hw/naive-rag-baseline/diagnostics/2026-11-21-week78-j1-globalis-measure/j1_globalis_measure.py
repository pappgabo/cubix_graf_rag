"""Globalis-only measurement over an EXPLICIT, different community
report collection (the J1 numeric-fact-preservation prompt variant),
on the SAME, unchanged 15-question golden set.

Reuses, UNCHANGED, week5-b's `measure.py` per-case step machine
(`process_case`, `CaseContext`), its real generation/judge builders
(`build_real_gen_fns`, `build_real_judge_call_fn_factory`), and its
`state_store`/`golden_set`/`report` modules -- exactly the way
`diagnostics/2026-11-14-week6-drift/drift_measure.py` already reused the
same pieces for a different single mode. Only the outer loop
(`run_j1_globalis_cases`, single-mode, mirroring `drift_measure.
run_drift_cases`) and the report-collection source are new.

No globalis search/map/reduce code, prompt, or judge is touched. No
smoke/full split is needed here (this is a single, fixed, 15-question
globalis-only run over a given collection) -- `run_kind` only
distinguishes this measurement's OWN output namespace.

    python j1_globalis_measure.py run --collection <path-to-j1-collection.jsonl>

No real call is made by this module as imported. `run_measurement`'s
real wiring is only exercised by `main()`; offline tests inject fakes
for `build_real_gen_fns`/judge factories/Langfuse client.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import j1_measure_bootstrap  # noqa: F401
import measure as week5measure  # week5-b, unchanged
import state_store
from golden_set import (
    GoldenQuestion, golden_set_sha256, load_golden_set, verify_corpus_matches_disk,
    verify_single_corpus_snapshot,
)

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
RESULTS_DIR = HERE / "results"
STATE_DIR = HERE / "state"
CASES_DIR = RESULTS_DIR / "cases"

DEFAULT_GOLDEN_PATH = week5measure.DEFAULT_GOLDEN_PATH  # unchanged, approved golden set -- not re-chosen
MODE = "globalis"
RUN_KIND = "j1-globalis-full"  # fixed: this measurement is always the full 15-question set

V3_COLLECTION_PATH = (
    PROJECT_ROOT / "diagnostics" / "2026-11-10-phase3-measurement"
    / "results" / "week4-report-v3-collection.jsonl"
)
DEFAULT_J1_COLLECTION_PATH = (
    PROJECT_ROOT / "diagnostics" / "2026-11-21-week78-j1-report-prompt"
    / "results" / "full" / "week4-report-j1-full-collection.jsonl"
)

LEDGER_PATH = RESULTS_DIR / "week78-j1-globalis-cost-ledger.json"
REQUEST_LOG_PATH = RESULTS_DIR / "week78-j1-globalis-request-log.json"
STATE_PATH = STATE_DIR / f"week78-j1-globalis-state-{RUN_KIND}.json"


class J1MeasureHalt(RuntimeError):
    """A prerequisite/identity check failed -- raised before any paid
    call, never a silent continuation from a mismatched or incomplete
    prior state."""


# --------------------------------------------------------------------------
# Collection identity/completeness (read-only; no paid call)
# --------------------------------------------------------------------------


def collection_sha256(path: Path) -> str:
    """Raw-bytes SHA-256 of the whole collection file -- the path alone
    never identifies a collection's content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collection_paths(path: Path) -> list[str]:
    """Every row's `path` field, in file order, duplicates kept (so the
    caller can detect them) -- never deduplicated here."""
    paths: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            paths.append(json.loads(line)["path"])
    return paths


def expected_community_paths() -> frozenset[str]:
    """The canonical, full community-path set, read from the v3 FULL
    collection -- the controlled baseline's own basis. Never hardcoded
    as a literal community count."""
    if not V3_COLLECTION_PATH.exists():
        raise J1MeasureHalt(f"baseline v3 collection not found: {V3_COLLECTION_PATH}")
    return frozenset(collection_paths(V3_COLLECTION_PATH))


def verify_single_prompt_version(path: Path) -> str:
    versions: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            versions.add(json.loads(line).get("prompt_version"))
    if len(versions) != 1:
        raise J1MeasureHalt(f"{path} does not have exactly one prompt_version across all rows: {sorted(versions)}")
    return next(iter(versions))


def verify_collection_completeness(path: Path) -> dict[str, Any]:
    """Raises J1MeasureHalt (before any paid call) if the collection is
    missing, has a duplicate path, or its path set does not EXACTLY match
    `expected_community_paths()` (no missing id, no extra id -- a
    pilot-only collection, which is a strict subset, fails this). Never
    inferred from file existence, size, or line count alone."""
    if not path.exists():
        raise J1MeasureHalt(f"J1 report collection not found: {path}")
    found = collection_paths(path)
    found_set = set(found)
    duplicates = sorted({p for p in found if found.count(p) > 1})
    if duplicates:
        raise J1MeasureHalt(f"{path}: duplicate community path id(s): {duplicates}")
    expected = expected_community_paths()
    missing = sorted(expected - found_set)
    extra = sorted(found_set - expected)
    if missing or extra:
        raise J1MeasureHalt(
            f"{path}: community path set does not match the baseline's {len(expected)} ids "
            f"-- missing={missing}, extra={extra}"
        )
    return {
        "collection_path": str(path),
        "collection_sha256": collection_sha256(path),
        "community_path_count": len(found_set),
    }


# --------------------------------------------------------------------------
# Run configuration / signature
# --------------------------------------------------------------------------


def effective_config(collection_info: dict[str, Any], collection_prompt_version: str) -> dict[str, Any]:
    """Everything the baseline rule requires to be provably identical
    (model, judge prompt versions, global run id/level) is read from
    week5measure.CONFIG, UNCHANGED -- only the report-collection identity
    is this run's own."""
    return {
        "mode": MODE,
        "report_collection_path": collection_info["collection_path"],
        "report_collection_sha256": collection_info["collection_sha256"],
        "report_collection_prompt_version": collection_prompt_version,
        "global_run_id": week5measure.CONFIG["global_run_id"],
        "global_reporting_level": week5measure.CONFIG["global_reporting_level"],
        "chat_model": week5measure.CONFIG["chat_model"],
        "temperature": week5measure.CONFIG["temperature"],
        "correctness_judge_prompt_version": week5measure.CONFIG["correctness_judge_prompt_version"],
        "faithfulness_judge_prompt_version": week5measure.CONFIG["faithfulness_judge_prompt_version"],
    }


def build_run_signature(golden_path: Path, config: dict[str, Any]) -> state_store.RunSignature:
    return state_store.RunSignature(
        run_kind=RUN_KIND,
        config_sha256=state_store.config_hash(config),
        golden_set_sha256=golden_set_sha256(golden_path),
    )


# --------------------------------------------------------------------------
# Single-mode case loop (mirrors drift_measure.run_drift_cases exactly)
# --------------------------------------------------------------------------


def run_j1_globalis_cases(
    questions: list[GoldenQuestion], store: state_store.StateStore, ctx: "week5measure.CaseContext",
) -> list[dict[str, Any]]:
    rows = []
    for question in questions:
        case = store.get_or_create(question.id, MODE)
        while case.next_step() is not None:
            week5measure.process_case(question, MODE, case, ctx)
            store.save()
        rows.append(week5measure.process_case(question, MODE, case, ctx))
    return rows


# --------------------------------------------------------------------------
# Langfuse gating (reuses week5measure's generic record mapper)
# --------------------------------------------------------------------------


def build_real_langfuse_sync_fn(
    expected_question_ids: tuple[str, ...], case_store_dir: Path, config_metadata: dict[str, Any],
) -> Callable[[dict], None] | None:
    """Same structure as week5measure's/week6's own: re-reads every
    expected case from disk, syncs ONCE only when the whole (run_kind,
    globalis) group has both correctness and faithfulness on every one
    of the 15 cases -- a partial J1 run is never submitted as a finished
    experiment."""
    try:
        import langfuse  # noqa: F401
    except ImportError:
        return None
    week5measure.load_project_env()
    week5measure.ensure_langfuse_configured()
    from langfuse import Langfuse
    import langfuse_week78 as lw78

    client = Langfuse()
    marker_dir = case_store_dir.parent / "langfuse-markers"

    def sync_one(row: dict[str, Any]) -> None:
        disk_rows = []
        for question_id in expected_question_ids:
            case_path = case_store_dir / f"{question_id}-{MODE}.json"
            if not case_path.exists():
                return  # group not complete yet
            data = json.loads(case_path.read_text(encoding="utf-8"))
            if data.get("correctness") is None or data.get("faithfulness") is None:
                return  # group not complete yet
            disk_rows.append(data)
        records = [week5measure._row_to_local_record(r) for r in disk_rows]
        marker_path = marker_dir / f"{RUN_KIND}-{MODE}.json"
        lw78.sync_j1_globalis_group_once(
            client, marker_path, run_phase=RUN_KIND, records=records, config_metadata=config_metadata)

    return sync_one


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run_measurement(
    j1_collection_path: Path, *, golden_path: Path = DEFAULT_GOLDEN_PATH, sync_langfuse: bool = True,
    gen_fns_builder: Callable[..., dict[str, Callable]] | None = None,
    judge_call_fn_factory_builder: Callable[..., Callable] | None = None,
) -> dict[str, Any]:
    """`gen_fns_builder(budget, phase_ledger, reports, run_phase, **kw) ->
    {mode: fn}` and `judge_call_fn_factory_builder(budget, phase_ledger,
    base_label, log_dir) -> factory` default to week5measure's real
    builders; offline tests inject fakes with the same signatures so no
    real model client is ever constructed."""
    if sync_langfuse:
        week5measure.load_project_env()
        week5measure.ensure_langfuse_configured()

    collection_info = verify_collection_completeness(j1_collection_path)
    collection_prompt_version = verify_single_prompt_version(j1_collection_path)

    all_questions = load_golden_set(golden_path)
    corpus_sha256 = verify_single_corpus_snapshot(all_questions)
    chunks_path = PROJECT_ROOT / all_questions[0].corpus_chunks_file
    verify_corpus_matches_disk(corpus_sha256, chunks_path)
    questions = list(all_questions)  # always the full, unchanged 15 -- no smoke/full split here

    config = effective_config(collection_info, collection_prompt_version)
    signature = build_run_signature(golden_path, config)
    store = state_store.StateStore.load_or_create(STATE_PATH, signature)  # raises StateError on mismatch

    import cost_guard
    import run_phase5 as phase5

    budget = cost_guard.SharedCostLedger.load(LEDGER_PATH)
    phase_ledger = phase5.Ledger(run_id=f"{RUN_KIND}-{int(time.time())}", path=REQUEST_LOG_PATH)

    from naive_rag.global_search import load_reports
    reports = load_reports(
        j1_collection_path, expected_run_id=config["global_run_id"],
        expected_reporting_level=config["global_reporting_level"],
    )

    builder = gen_fns_builder or week5measure.build_real_gen_fns
    gen_fns = builder(budget, phase_ledger, reports, RUN_KIND)
    global_fn = gen_fns["globalis"]

    judge_builder = judge_call_fn_factory_builder or week5measure.build_real_judge_call_fn_factory
    judge_log_dir = RESULTS_DIR.parent / "logs" / "judges"
    correctness_call_fn_factory = judge_builder(
        budget, phase_ledger, f"correctness-{RUN_KIND}", judge_log_dir)
    faithfulness_call_fn_factory = judge_builder(
        budget, phase_ledger, f"faithfulness-{RUN_KIND}", judge_log_dir)
    case_store_dir = CASES_DIR / RUN_KIND
    langfuse_sync_fn = (
        build_real_langfuse_sync_fn(tuple(q.id for q in questions), case_store_dir, config)
        if sync_langfuse else None
    )

    ctx = week5measure.CaseContext(
        run_phase=RUN_KIND, budget=budget, ledger=phase_ledger, gen_fns={MODE: global_fn},
        correctness_call_fn_factory=correctness_call_fn_factory,
        faithfulness_call_fn_factory=faithfulness_call_fn_factory,
        langfuse_sync_fn=langfuse_sync_fn, case_store_dir=case_store_dir,
    )

    rows = run_j1_globalis_cases(questions, store, ctx)

    import report as report_mod
    results_path = RESULTS_DIR / f"results-{RUN_KIND}.jsonl"  # OWN file -- never week5-b's results.jsonl
    report_mod.write_results(results_path, rows)
    report_md = report_mod.build_report_markdown(rows, run_phase=RUN_KIND)
    (RESULTS_DIR / f"week78-j1-globalis-report-{RUN_KIND}.md").write_text(report_md, encoding="utf-8")

    return {
        "run_kind": RUN_KIND, "case_count": len(rows), "state_summary": store.summary(),
        "remaining_budget_usd": budget.remaining_usd(), "collection_info": collection_info,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python j1_globalis_measure.py")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run (or resume) the J1-globalis full measurement")
    run_p.add_argument("--collection", type=Path, default=DEFAULT_J1_COLLECTION_PATH)
    run_p.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    run_p.add_argument("--no-langfuse", action="store_true")
    args = parser.parse_args(argv)

    outcome = run_measurement(
        args.collection, golden_path=args.golden, sync_langfuse=not args.no_langfuse)
    print(json.dumps(outcome, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
