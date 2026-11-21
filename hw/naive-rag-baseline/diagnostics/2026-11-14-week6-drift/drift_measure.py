"""Week 6 — one CLI command for drift-only measurement over the SAME
approved 15-question golden set and the SAME correctness/faithfulness
judges as week5-b, with its own smoke/full state and case store.

    python drift_measure.py run --smoke   # Q01, Q07, Q10 x drift = 3 cases
    python drift_measure.py run --full    # all 15 questions x drift = 15 cases

The old three modes (naiv/lokalis/globalis) are NOT re-run here --
``diagnostics/2026-11-11-week5-b``'s code, golden set, state, results and
ledger are untouched. DRIFT is the fourth mode; no further mode is
introduced.

The per-case step machine (``process_case``) and its ``CaseContext``
contract are imported UNCHANGED from week5-b's ``measure.py`` -- they are
already mode-parameterized (``gen_fns`` is a ``{mode: callable}`` dict,
every step branch takes ``mode`` as a plain argument). Only the OUTER loop
over ``MODES`` in week5-b's own ``run_cases`` is week5-specific (a
module-level 3-mode tuple); ``run_drift_cases`` below is the thin,
single-mode replacement for exactly that loop -- everything inside it is
the same imported, unmodified ``process_case``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import week6_bootstrap  # noqa: F401
import drift_runner
import report as report_mod  # week5-b, unchanged
import report_week6
import state_store
import measure as week5measure  # week5-b, unchanged
from golden_set import (
    GoldenQuestion, golden_set_sha256, load_golden_set, verify_corpus_matches_disk,
    verify_single_corpus_snapshot,
)

from naive_rag.drift_search import (
    CHAT_MODEL,
    DEFAULT_REPORT_K,
    DEFAULT_SYNTHESIS_CHAR_BUDGET,
    EMBEDDING_MODEL,
    GENERATIVE_MAX_TOKENS,
    MAX_RETRIES,
    MAX_SUBQUESTIONS,
    TEMPERATURE,
    ReportIndexCacheError,
    load_report_index,
    reports_content_hash,
)
from naive_rag.global_search import load_reports

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
RESULTS_DIR = HERE / "results"
STATE_DIR = HERE / "state"
CASES_DIR = RESULTS_DIR / "cases"

# Unchanged from week5-b -- the approved golden set is not touched here.
DEFAULT_GOLDEN_PATH = PROJECT_ROOT / "golden" / "week5-golden-set-v1-approval-draft.jsonl"
SMOKE_QUESTION_IDS = ("Q01", "Q07", "Q10")
MODE = "drift"

# CODE_VERSION: bumped after the first real smoke run (PRIMER_PROMPT_VERSION
# v2 in naive_rag.drift_search -- an empty "subquestions" list is now a
# primer_invalid status, not a silent report-only answer; see
# docs/week6-atadas.md's C-phase diagnosis). Only the smoke/full STATE,
# CASE and RESULTS paths are versioned -- the report-index cache and the
# cost ledger stay at their unversioned, shared paths on purpose (same
# valid cache, same cumulative ledger; no new index embedding). The old
# v1 smoke files under these same unversioned names are left on disk,
# untouched.
CODE_VERSION = "v2"

GLOBAL_REPORT_COLLECTION = (
    "diagnostics/2026-11-10-phase3-measurement/results/week4-report-v3-collection.jsonl"
)
GLOBAL_REPORTING_LEVEL = 0
REPORT_INDEX_CACHE_PATH = RESULTS_DIR / "report-index-cache.json"
INDEX_COST_SUMMARY_PATH = RESULTS_DIR / "week6-index-cost.json"
LEDGER_PATH = RESULTS_DIR / "week6-cost-ledger.json"


class ReportIndexNotReady(RuntimeError):
    """The report-index cache is missing, or was built from a different
    report set / embedding model than this run expects.

    Raised BEFORE any paid call -- there is no automatic rebuild. The
    caller must run ``build_index.py`` explicitly first (see README.md)."""


def load_project_env() -> None:
    week5measure.load_project_env()


def ensure_langfuse_configured() -> None:
    week5measure.ensure_langfuse_configured()


LangfuseConfigError = week5measure.LangfuseConfigError
MeasurementHalted = week5measure.MeasurementHalted


def detect_report_run_id(collection_path: Path) -> str:
    return drift_runner.detect_report_run_id(collection_path)


def require_report_index(reports, cache_path: Path):
    content_hash = reports_content_hash(reports)
    try:
        return load_report_index(
            cache_path, expected_reports_hash=content_hash, expected_embedding_model=EMBEDDING_MODEL)
    except ReportIndexCacheError as exc:
        raise ReportIndexNotReady(
            f"{exc} -- run build_index.py explicitly first (see README.md); "
            "no automatic rebuild is performed here"
        ) from exc


def effective_config(*, global_run_id: str, reports_hash: str) -> dict[str, Any]:
    import correctness_judge
    import faithfulness_judge
    from naive_rag.drift_search import MIN_SUBQUESTIONS, PRIMER_PROMPT_VERSION

    return {
        "mode": MODE,
        "code_version": CODE_VERSION,
        "chat_model": CHAT_MODEL,
        "temperature": TEMPERATURE,
        "max_retries": MAX_RETRIES,
        "generative_max_output_tokens": GENERATIVE_MAX_TOKENS,
        "embedding_model": EMBEDDING_MODEL,
        "report_k": DEFAULT_REPORT_K,
        "max_subquestions": MAX_SUBQUESTIONS,
        "min_subquestions": MIN_SUBQUESTIONS,
        "primer_prompt_version": PRIMER_PROMPT_VERSION,
        "synthesis_char_budget": DEFAULT_SYNTHESIS_CHAR_BUDGET,
        "local_entity_index_path": "graph/corpus/entity-index.json",
        "local_extraction_dir": "graph/corpus/extraction",
        "global_run_id": global_run_id,
        "global_reporting_level": GLOBAL_REPORTING_LEVEL,
        "global_report_collection": GLOBAL_REPORT_COLLECTION,
        "report_index_reports_content_hash": reports_hash,
        "report_index_cache_path": "diagnostics/2026-11-14-week6-drift/results/report-index-cache.json",
        "correctness_judge_prompt_version": correctness_judge.PROMPT_VERSION,
        "faithfulness_judge_prompt_version": faithfulness_judge.PROMPT_VERSION,
        "drift_search_code_version": "week6-drift-search-v2",
        "shared_cost_cap_usd": 0.50,
    }


def build_run_signature(run_kind: str, golden_path: Path, *, global_run_id: str,
                        reports_hash: str) -> state_store.RunSignature:
    return state_store.RunSignature(
        run_kind=run_kind,
        config_sha256=state_store.config_hash(effective_config(
            global_run_id=global_run_id, reports_hash=reports_hash)),
        golden_set_sha256=golden_set_sha256(golden_path),
    )


def select_questions(all_questions: tuple[GoldenQuestion, ...], run_kind: str) -> list[GoldenQuestion]:
    if run_kind == "smoke":
        chosen = [q for q in all_questions if q.id in SMOKE_QUESTION_IDS]
        found_ids = {q.id for q in chosen}
        for qid in SMOKE_QUESTION_IDS:
            if qid not in found_ids:
                raise ValueError(f"smoke question {qid} not found in golden set")
        return chosen
    return list(all_questions)


def run_drift_cases(
    questions: list[GoldenQuestion], store: state_store.StateStore, ctx: "week5measure.CaseContext",
) -> list[dict[str, Any]]:
    """Single-mode replacement for week5-b's ``run_cases``'s outer loop
    (``for mode in MODES``) -- the only week5-specific thing in that
    function. Everything per-case is the UNCHANGED, imported
    ``process_case``: when a case is already fully done (resume), calling
    it once more with ``next_step() is None`` costs nothing -- it only
    re-reads the saved row from disk (see week5-b's ``process_case``,
    first lines)."""
    rows = []
    for question in questions:
        case = store.get_or_create(question.id, MODE)
        while case.next_step() is not None:
            week5measure.process_case(question, MODE, case, ctx)
            store.save()
        rows.append(week5measure.process_case(question, MODE, case, ctx))
    return rows


def build_real_langfuse_sync_fn(
    run_phase: str, expected_question_ids: tuple[str, ...], case_store_dir: Path,
    config_metadata: dict[str, Any],
) -> Callable[[dict], None] | None:
    """Week6-named equivalent of week5-b's ``build_real_langfuse_sync_fn``
    (same structure: re-reads every expected case from disk, syncs once
    the whole (run_phase, drift) group has both judge scores on every
    case) -- but using ``langfuse_week6.sync_drift_group_once`` (week6
    experiment/run names) instead of ``langfuse_sync.sync_mode_group_once``
    (hardcoded to the ``"week5-b-"`` prefix), and this run's OWN config
    metadata, not week5-b's."""
    try:
        import langfuse  # noqa: F401
    except ImportError:
        return None
    load_project_env()
    ensure_langfuse_configured()
    from langfuse import Langfuse
    import langfuse_sync as ls
    import langfuse_week6 as lw6

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
        marker_path = marker_dir / f"{run_phase}-{MODE}.json"
        lw6.sync_drift_group_once(
            client, marker_path, run_phase=run_phase, records=records, config_metadata=config_metadata)

    return sync_one


def run_measurement(run_kind: str, *, golden_path: Path = DEFAULT_GOLDEN_PATH,
                    sync_langfuse: bool = True) -> dict[str, Any]:
    if sync_langfuse:
        load_project_env()
        ensure_langfuse_configured()

    all_questions = load_golden_set(golden_path)
    corpus_sha256 = verify_single_corpus_snapshot(all_questions)
    chunks_path = PROJECT_ROOT / all_questions[0].corpus_chunks_file
    verify_corpus_matches_disk(corpus_sha256, chunks_path)

    questions = select_questions(all_questions, run_kind)

    collection_path = PROJECT_ROOT / GLOBAL_REPORT_COLLECTION
    global_run_id = detect_report_run_id(collection_path)
    reports = load_reports(
        collection_path, expected_run_id=global_run_id, expected_reporting_level=GLOBAL_REPORTING_LEVEL)
    reports_hash = reports_content_hash(reports)

    # Fails fast, before the ledger, the local-search fixtures, or any
    # paid call are built -- no automatic rebuild (see ReportIndexNotReady).
    report_index = require_report_index(reports, REPORT_INDEX_CACHE_PATH)

    signature = build_run_signature(run_kind, golden_path, global_run_id=global_run_id, reports_hash=reports_hash)
    state_path = STATE_DIR / f"week6-drift-state-{run_kind}-{CODE_VERSION}.json"
    store = state_store.StateStore.load_or_create(state_path, signature)

    import cost_guard
    ledger = cost_guard.SharedCostLedger.load(LEDGER_PATH)

    graph, local_index, chunk_texts = drift_runner.build_local_search_fixtures()

    judge_log_dir = RESULTS_DIR.parent / "logs" / "judges"
    correctness_call_fn_factory = week5measure.build_real_judge_call_fn_factory(
        ledger, None, f"correctness-drift-{run_kind}", judge_log_dir)
    faithfulness_call_fn_factory = week5measure.build_real_judge_call_fn_factory(
        ledger, None, f"faithfulness-drift-{run_kind}", judge_log_dir)
    case_store_dir = CASES_DIR / CODE_VERSION / run_kind
    config_metadata = effective_config(global_run_id=global_run_id, reports_hash=reports_hash)
    langfuse_sync_fn = (
        build_real_langfuse_sync_fn(run_kind, tuple(q.id for q in questions), case_store_dir, config_metadata)
        if sync_langfuse else None
    )

    def drift_fn(question: GoldenQuestion) -> dict:
        return drift_runner.run_drift_capture(
            question.id, question.question, ledger, run_phase=run_kind,
            reports=reports, report_index=report_index, graph=graph,
            local_index=local_index, chunk_texts=chunk_texts,
        )

    ctx = week5measure.CaseContext(
        run_phase=run_kind, budget=ledger, ledger=None, gen_fns={MODE: drift_fn},
        correctness_call_fn_factory=correctness_call_fn_factory,
        faithfulness_call_fn_factory=faithfulness_call_fn_factory,
        langfuse_sync_fn=langfuse_sync_fn, case_store_dir=case_store_dir,
    )

    rows = run_drift_cases(questions, store, ctx)

    results_path = RESULTS_DIR / f"results-{CODE_VERSION}.jsonl"
    all_rows = report_mod.load_results(results_path)
    by_key = {(r["question_id"], r["mode"], r["run_phase"]): r for r in all_rows}
    for row in rows:
        by_key[(row["question_id"], row["mode"], row["run_phase"])] = row
    report_mod.write_results(results_path, by_key.values())

    index_cost_summary = (
        json.loads(INDEX_COST_SUMMARY_PATH.read_text(encoding="utf-8"))
        if INDEX_COST_SUMMARY_PATH.exists() else None
    )
    report_md = report_week6.build_drift_report_markdown(
        list(by_key.values()), run_phase=run_kind, index_cost_summary=index_cost_summary,
        ledger_cumulative_spent_usd=ledger.spent_usd, ledger_cumulative_remaining_usd=ledger.remaining_usd(),
    )
    (RESULTS_DIR / f"week6-drift-report-{CODE_VERSION}-{run_kind}.md").write_text(report_md, encoding="utf-8")

    return {
        "run_kind": run_kind, "case_count": len(rows), "state_summary": store.summary(),
        "ledger_cumulative_spent_usd": ledger.spent_usd, "ledger_cumulative_remaining_usd": ledger.remaining_usd(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="drift_measure.py")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run (or resume) the drift smoke or full measurement")
    group = run_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--smoke", action="store_const", dest="run_kind", const="smoke")
    group.add_argument("--full", action="store_const", dest="run_kind", const="full")
    run_p.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    run_p.add_argument("--no-langfuse", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "run":
        try:
            outcome = run_measurement(args.run_kind, golden_path=args.golden, sync_langfuse=not args.no_langfuse)
        except LangfuseConfigError as exc:
            print(f"LANGFUSE CONFIG ERROR (no paid call was made): {exc}", file=sys.stderr)
            return 2
        except ReportIndexNotReady as exc:
            print(f"REPORT INDEX NOT READY (no paid call was made): {exc}", file=sys.stderr)
            return 3
        except MeasurementHalted as exc:
            print(f"HALTED: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(outcome, ensure_ascii=False, indent=1, default=str))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
