"""Week 5 B — one CLI command for naiv/lokalis/globalis measurement over
the approved 15-question golden set, with Langfuse sync, local JSONL
persistence, and a per-step resumable state.

    python measure.py run --smoke   # Q01, Q07, Q11 x 3 modes = 9 cases
    python measure.py run --full    # all 15 questions x 3 modes = 45 cases

Resuming is automatic: re-running the same command with the same
configuration and the same golden-set file only executes the steps that
are still missing (see state_store.py). A different configuration or a
different golden-set file is refused as a resume (StateError) rather than
silently mixed in.

This module wires the real generation/judge/Langfuse calls; the
orchestration logic itself (``process_case``, ``run_cases``) is
dependency-injected and is what ``tests/test_measure_orchestration.py``
exercises offline with fakes -- no real call is made by the test suite.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import _bootstrap  # noqa: F401
import correctness_judge
import faithfulness_judge
import retrieval_eval
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

DEFAULT_GOLDEN_PATH = PROJECT_ROOT / "golden" / "week5-golden-set-v1-approval-draft.jsonl"
SMOKE_QUESTION_IDS = ("Q01", "Q07", "Q11")
HELD_OUT_IDS = ("Q14", "Q15")
MODES = ("naiv", "lokalis", "globalis")

CONFIG = {
    "chat_model": "gpt-4o-mini",
    "temperature": 0,
    "naiv_top_k": 4,
    "naiv_collection": "week4_naive_baseline_1200_23",
    "lokalis_k": 3,
    "lokalis_context_model_window": 8192,
    "lokalis_context_answer_reserve": 1024,
    "lokalis_context_graph_share": 0.5,
    "global_run_id": "week4-leiden-elokeszitett-6f05327d7d88ebf0",
    "global_reporting_level": 0,
    "global_report_collection": "diagnostics/2026-11-10-phase3-measurement/results/week4-report-v3-collection.jsonl",
    "correctness_judge_prompt_version": correctness_judge.PROMPT_VERSION,
    "faithfulness_judge_prompt_version": faithfulness_judge.PROMPT_VERSION,
    "shared_cost_cap_usd": 0.50,
}


class MeasurementHalted(RuntimeError):
    """A step failed; the run stops (no new paid call, no auto-retry)."""


class LangfuseConfigError(RuntimeError):
    """A required Langfuse credential is missing from the environment.

    Raised BEFORE any generation or judge call is built -- the run must
    stop here with a clear error, not continue with the Langfuse SDK's own
    silently-disabled client (which only logs a warning and no-ops every
    subsequent call)."""


REQUIRED_LANGFUSE_ENV_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")


def load_project_env() -> None:
    """Loads naive-rag-baseline/.env into ``os.environ`` via python-dotenv
    (an existing project dependency), using the exact same file
    ``naive_rag.config.Settings`` already reads (``PROJECT_ROOT / ".env"``).

    ``naive_rag.config.get_settings()`` parses that file for its own
    pydantic fields only and never exports it to ``os.environ`` -- so a
    non-pydantic consumer that reads plain env vars directly, like the
    Langfuse SDK's ``Langfuse()`` constructor, never sees it unless
    something does this. Never prints or logs the file's contents or any
    key value."""
    from dotenv import load_dotenv
    from naive_rag.config import PROJECT_ROOT as NAIVE_RAG_PROJECT_ROOT

    load_dotenv(NAIVE_RAG_PROJECT_ROOT / ".env")


def ensure_langfuse_configured() -> None:
    """Raises LangfuseConfigError (variable NAMES only, never values) if a
    required Langfuse credential is still missing after
    ``load_project_env()``. Call this before building any paid
    generation/judge function, so a missing credential halts the run
    before it can incur any cost."""
    import os

    missing = [name for name in REQUIRED_LANGFUSE_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise LangfuseConfigError(
            "missing required Langfuse environment variable(s): " + ", ".join(missing)
            + " -- set them in naive-rag-baseline/.env before running with Langfuse "
              "sync enabled, or pass --no-langfuse to skip syncing for this run"
        )


@dataclass
class CaseContext:
    run_phase: str  # "smoke" | "full"
    budget: Any  # exposes .spent_usd (cost_guard.SharedCostLedger); may be None in tests that don't track cost
    ledger: Any
    gen_fns: dict[str, Callable]  # mode -> callable(question) -> generation record dict
    # Factories, not pre-built callables: (question_id, mode, step) -> call_fn.
    # A fresh call_fn per (case, step, attempt) is what makes the judge log
    # filename unique (see build_real_judge_call_fn_factory) without
    # touching the shared call_logging/global_search_logging code.
    correctness_call_fn_factory: Callable[[str, str, str], Callable] | None
    faithfulness_call_fn_factory: Callable[[str, str, str], Callable] | None
    langfuse_sync_fn: Callable[[dict], None] | None
    case_store_dir: Path


def _case_path(ctx: CaseContext, question_id: str, mode: str) -> Path:
    return ctx.case_store_dir / f"{question_id}-{mode}.json"


def _load_case_row(ctx: CaseContext, question_id: str, mode: str) -> dict[str, Any]:
    path = _case_path(ctx, question_id, mode)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"question_id": question_id, "mode": mode, "run_phase": ctx.run_phase}


def _save_case_row(ctx: CaseContext, question_id: str, mode: str, row: dict[str, Any]) -> None:
    """Takes the file's identity from the caller's own ``question_id``/
    ``mode`` (the loop variables ``process_case`` is actually iterating
    over), never from ``row``'s own ``question_id``/``mode`` fields -- a
    generation function's returned dict merged into ``row`` via
    ``row.update(generation)`` must never be able to redirect a save to a
    different case's file."""
    path = _case_path(ctx, question_id, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")


def _spent_usd(ctx: CaseContext) -> float | None:
    """``None`` when no cost-tracking budget is wired (some offline test
    fixtures pass ``budget=None``) -- never 0.0 as a stand-in for unknown."""
    return ctx.budget.spent_usd if ctx.budget is not None else None


def _cost_delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round(after - before, 6)


def _recompute_total_cost(row: dict[str, Any]) -> None:
    """``cost_usd`` = sum of the three step costs, ONLY when all three are
    known -- a partially-known cost is never reported as if it were the
    whole case's cost. Old rows saved before this field existed simply
    don't have the three sub-fields, so this correctly leaves ``cost_usd``
    unset (null), not zero."""
    parts = [row.get("cost_usd_generation"), row.get("cost_usd_correctness_judge"),
            row.get("cost_usd_faithfulness_judge")]
    if all(isinstance(p, (int, float)) for p in parts):
        row["cost_usd"] = round(sum(parts), 6)
        row["cost_source"] = "ledger_delta"


def process_case(
    question: GoldenQuestion, mode: str, case: state_store.CaseState, ctx: CaseContext,
) -> dict[str, Any]:
    """Executes exactly the next missing step for this case, persists the
    row, updates and returns the case state. Raises MeasurementHalted on
    any step failure -- the caller must stop the whole run, not continue
    to the next case.

    Each of the three paid steps (generation, correctness judge,
    faithfulness judge) is timed and cost-measured individually here, via
    the shared cost ledger's own running total taken immediately before
    and immediately after that one step's call (this only attributes cost
    correctly because the run is sequential, never concurrent). The
    resulting per-step cost/duration fields are saved alongside the rest
    of the row by the SAME ``_save_case_row`` call each step already made,
    so a step already marked done on a resume is never re-run just to
    backfill a cost figure it never got."""
    row = _load_case_row(ctx, question.id, mode)
    # Authoritative identity, from the caller's own loop variables -- never
    # trust whatever a generation function's returned dict might carry in
    # these same key names once row.update(generation) runs below.
    row["question_id"] = question.id
    row["mode"] = mode
    row.setdefault("question_type", question.type)
    row.setdefault("question_status", question.status)
    row.setdefault("question_text", question.question)
    row.setdefault("expected_answer", question.expected_answer)
    row.setdefault("golden_set_version", question.golden_set_version)

    step = case.next_step()
    if step is None:
        return row

    if step == "answer_saved":
        gen_fn = ctx.gen_fns[mode]
        cost_before = _spent_usd(ctx)
        started = time.monotonic()
        try:
            generation = gen_fn(question)
        except Exception as exc:  # noqa: BLE001
            row["duration_seconds_generation"] = round(time.monotonic() - started, 3)
            row["cost_usd_generation"] = _cost_delta(cost_before, _spent_usd(ctx))
            _recompute_total_cost(row)
            case.last_error = {"step": step, "error": f"{type(exc).__name__}: {exc}"}
            _save_case_row(ctx, question.id, mode, row)
            raise MeasurementHalted(f"{question.id}/{mode}: generation failed: {exc}") from exc
        elapsed = round(time.monotonic() - started, 3)
        cost_delta = _cost_delta(cost_before, _spent_usd(ctx))
        if generation.get("error"):
            case.last_error = {"step": step, "error": generation["error"]}
            row.update(generation)
            row["question_id"], row["mode"] = question.id, mode
            row["duration_seconds_generation"] = elapsed
            row["cost_usd_generation"] = cost_delta
            _recompute_total_cost(row)
            _save_case_row(ctx, question.id, mode, row)
            raise MeasurementHalted(f"{question.id}/{mode}: generation error: {generation['error']}")
        row.update(generation)
        row["question_id"], row["mode"] = question.id, mode
        row["duration_seconds_generation"] = elapsed
        row["cost_usd_generation"] = cost_delta
        retrieval = retrieval_eval.evaluate_retrieval(
            question,
            frozenset(generation["actual_chunk_ids"]) if generation.get("chunk_ids_traceable") else None,
            is_proxy=generation.get("is_proxy_retrieval", False),
            proxy_note=generation.get("proxy_note"),
        )
        row["retrieval"] = retrieval_eval.result_to_dict(retrieval)
        _recompute_total_cost(row)
        case.answer_saved = True
        _save_case_row(ctx, question.id, mode, row)
        return row

    if step == "criteria_scored":
        if ctx.correctness_call_fn_factory is None:
            raise MeasurementHalted(f"{question.id}/{mode}: no correctness_call_fn configured")
        call_fn = ctx.correctness_call_fn_factory(question.id, mode, step)
        cost_before = _spent_usd(ctx)
        started = time.monotonic()
        record = correctness_judge.judge_one(question, row.get("answer") or "", call_fn)
        row["duration_seconds_correctness_judge"] = round(time.monotonic() - started, 3)
        row["cost_usd_correctness_judge"] = _cost_delta(cost_before, _spent_usd(ctx))
        if record["status"] == "error":
            case.last_error = {"step": step, "error": record["error"]}
            row["correctness"] = {"status": "error", "error": record["error"]}
            _recompute_total_cost(row)
            _save_case_row(ctx, question.id, mode, row)
            raise MeasurementHalted(f"{question.id}/{mode}: correctness judge error: {record['error']}")
        row["correctness"] = {
            "status": "scored", "label": record["label"], "parsed": record["parsed"],
            "usage_prompt_tokens": record.get("usage_prompt_tokens"),
            "usage_completion_tokens": record.get("usage_completion_tokens"),
        }
        _recompute_total_cost(row)
        case.criteria_scored = True
        _save_case_row(ctx, question.id, mode, row)
        return row

    if step == "faithfulness_scored":
        if ctx.faithfulness_call_fn_factory is None:
            raise MeasurementHalted(f"{question.id}/{mode}: no faithfulness_call_fn configured")
        call_fn = ctx.faithfulness_call_fn_factory(question.id, mode, step)
        cost_before = _spent_usd(ctx)
        started = time.monotonic()
        record = faithfulness_judge.judge_one(
            question.id, question.question, row.get("answer") or "",
            row.get("actual_context") or "", call_fn,
        )
        row["duration_seconds_faithfulness_judge"] = round(time.monotonic() - started, 3)
        row["cost_usd_faithfulness_judge"] = _cost_delta(cost_before, _spent_usd(ctx))
        if record["status"] == "error":
            case.last_error = {"step": step, "error": record["error"]}
            row["faithfulness"] = {"status": "error", "error": record["error"]}
            _recompute_total_cost(row)
            _save_case_row(ctx, question.id, mode, row)
            raise MeasurementHalted(f"{question.id}/{mode}: faithfulness judge error: {record['error']}")
        row["faithfulness"] = {
            "status": "scored", "score": record["scoring"]["score"],
            "supported_count": record["scoring"]["supported_count"],
            "unsupported_count": record["scoring"]["unsupported_count"],
            "unclear_count": record["scoring"]["unclear_count"],
        }
        _recompute_total_cost(row)
        case.faithfulness_scored = True
        _save_case_row(ctx, question.id, mode, row)
        return row

    if step == "langfuse_synced":
        if ctx.langfuse_sync_fn is not None:
            try:
                ctx.langfuse_sync_fn(row)
            except Exception as exc:  # noqa: BLE001
                case.last_error = {"step": step, "error": f"{type(exc).__name__}: {exc}"}
                _save_case_row(ctx, question.id, mode, row)
                raise MeasurementHalted(f"{question.id}/{mode}: langfuse sync failed: {exc}") from exc
        case.langfuse_synced = True
        _save_case_row(ctx, question.id, mode, row)
        return row

    raise AssertionError(f"unknown step {step!r}")


def run_cases(
    questions: list[GoldenQuestion], store: state_store.StateStore, ctx: CaseContext,
) -> list[dict[str, Any]]:
    """Runs every (question, mode) case through its remaining steps, in a
    fixed deterministic order, stopping the WHOLE run at the first
    MeasurementHalted (no case after the failure is attempted).

    A case already fully complete from a prior run (``case.next_step()``
    is ``None`` from the start, e.g. on a resume) never enters the
    ``while`` body, so its row is read back from the saved case file
    instead of relying on ``process_case``'s return value -- no completed
    step (generation, judge, or sync) is re-run to produce it."""
    rows = []
    for question in questions:
        for mode in MODES:
            case = store.get_or_create(question.id, mode)
            while case.next_step() is not None:
                process_case(question, mode, case, ctx)
                store.save()
            rows.append(_load_case_row(ctx, question.id, mode))
    return rows


def effective_config() -> dict[str, Any]:
    return dict(CONFIG)


def build_run_signature(run_kind: str, golden_path: Path) -> state_store.RunSignature:
    return state_store.RunSignature(
        run_kind=run_kind,
        config_sha256=state_store.config_hash(effective_config()),
        golden_set_sha256=golden_set_sha256(golden_path),
    )


def select_questions(all_questions: tuple[GoldenQuestion, ...], run_kind: str) -> list[GoldenQuestion]:
    if run_kind == "smoke":
        chosen = [q for q in all_questions if q.id in SMOKE_QUESTION_IDS]
        for qid in SMOKE_QUESTION_IDS:
            if qid not in {q.id for q in chosen}:
                raise ValueError(f"smoke question {qid} not found in golden set")
        for qid in HELD_OUT_IDS:
            if qid in SMOKE_QUESTION_IDS:
                raise ValueError("held-out question leaked into the smoke set")
        return chosen
    return list(all_questions)


@contextlib.contextmanager
def shared_qdrant_client() -> Iterator[Any]:
    """One Qdrant client for every naiv case in a single ``run_measurement``
    call, always closed on the way out -- success or error alike.

    Root cause this fixes: local, on-disk Qdrant storage (``.qdrant/``)
    takes an exclusive lock per open client. ``run_phase5.run_naiv``
    (``diagnostics/2026-11-10-phase5-run/run_phase5.py``, inside
    ``run_naiv``) only builds its own fresh client when none is supplied
    (``client = qdrant_client or qdrant_client_factory()``) and never
    closes it -- by design, since that function is also used standalone.
    If each naiv case in this measurement built its own client via that
    default path, the previous case's client would still be holding the
    lock when the next case's client tried to open the same path, which
    is exactly the reported crash (``Storage folder ... is already
    accessed by another instance of Qdrant client``). Passing this single
    shared client into every naiv case (see ``build_real_gen_fns``) avoids
    that; this context manager is what guarantees it is released exactly
    once, including when ``run_cases`` raises ``MeasurementHalted``."""
    from naive_rag.vectorstore import _client as qdrant_client_factory

    client = qdrant_client_factory(register_close=False)
    try:
        yield client
    finally:
        client.close()


def build_real_gen_fns(
    budget, ledger, reports, run_phase: str, *, qdrant_client: Any = None,
) -> dict[str, Callable]:
    """``qdrant_client`` is a single, long-lived client shared across every
    naiv case in this run (see ``run_measurement``'s ``finally`` block for
    where it is closed). Local on-disk Qdrant storage takes an exclusive
    file lock per open client -- ``run_phase5.run_naiv`` builds its own
    fresh client only when none is supplied (``diagnostics/2026-11-10-phase5-run/run_phase5.py``,
    ``run_naiv``'s ``client = qdrant_client or qdrant_client_factory()``),
    and never closes it, so letting every naiv case build its own would
    leave the previous call's client still holding the lock when the next
    one tries to open the same path."""
    import generation_runner as gr

    def naiv_fn(question: GoldenQuestion) -> dict:
        return gr.run_naiv_capture(
            question.id, question.question, budget, ledger, run_phase=run_phase, qdrant_client=qdrant_client)

    def lokalis_fn(question: GoldenQuestion) -> dict:
        return gr.run_lokalis_capture(question.id, question.question, budget, ledger, run_phase=run_phase)

    def global_fn(question: GoldenQuestion) -> dict:
        return gr.run_global_capture(question.id, question.question, budget, ledger, reports, run_phase=run_phase)

    return {"naiv": naiv_fn, "lokalis": lokalis_fn, "globalis": global_fn}


def build_real_judge_call_fn_factory(
    budget, ledger, base_label: str, log_dir: Path, *, client_factory: Callable | None = None,
) -> Callable[[str, str, str], Callable]:
    """Returns a factory ``(question_id, mode, step) -> call_fn``, built
    fresh on every call -- NOT a single shared callable -- specifically so
    the judge's log file name can embed the question id, mode and step,
    and a retried attempt after a halt never overwrites the previous
    attempt's log.

    ``make_logged_call_fn`` (``naive_rag.global_search_logging``, shared/
    unmodified) names its own log files from its ``prefix`` plus an
    internal per-closure counter starting at 1
    (``global_search_logging.py``'s ``make_logged_call_fn`` docstring).
    Giving every call its own closure with an already-unique ``prefix``
    (question id + mode + step + a nanosecond timestamp) turns that
    counter-based naming into a de-facto globally unique filename, without
    touching call_logging.py or global_search_logging.py -- the fix lives
    entirely in this measurement integration.

    Model/temperature/JSON-mode shape mirrors
    ``global_search.make_openai_caller`` (reused, not a new model config).

    ``client_factory`` is forwarded to ``make_logged_call_fn`` unchanged
    (that parameter already exists there for test injection); ``None``
    keeps the real default (a genuine ``ChatOpenAI``)."""
    import _bootstrap  # noqa: F401
    import run_phase5 as phase5
    from naive_rag.config import get_settings
    from naive_rag.global_search_logging import make_logged_call_fn

    settings = get_settings()

    def factory(question_id: str, mode: str, step: str) -> Callable:
        prefix = f"{base_label}-{question_id}-{mode}-{step}-{time.time_ns()}"
        raw_call_fn = make_logged_call_fn(
            settings, log_dir=log_dir, prefix=prefix, client_factory=client_factory)

        def gated(system_prompt: str, user_message: str, max_tokens: int):
            upper = budget.check_generative(
                phase5.estimate_tokens(system_prompt) + phase5.estimate_tokens(user_message),
                max_tokens, prefix,
            )
            response = raw_call_fn(system_prompt, user_message, max_tokens)
            budget.record_generative(response.usage_prompt_tokens, response.usage_completion_tokens, upper)
            return response

        return gated

    return factory


def _row_to_local_record(row: dict[str, Any]) -> Any:
    import langfuse_sync as ls

    return ls.LocalRecord(
        question_id=row["question_id"], mode=row["mode"], question_text=row["question_text"],
        answer=row.get("answer"), expected_answer=row.get("expected_answer", ""),
        metadata={
            "correctness_label": (row.get("correctness") or {}).get("label"),
            "faithfulness_score": (row.get("faithfulness") or {}).get("score"),
            "retrieval_ratio": (row.get("retrieval") or {}).get("ratio"),
            "retrieval_is_proxy": (row.get("retrieval") or {}).get("is_proxy", False),
            "question_type": row.get("question_type"),
            "question_status": row.get("question_status"),
        },
    )


def build_real_langfuse_sync_fn(
    run_phase: str, expected_question_ids: tuple[str, ...], case_store_dir: Path,
) -> Callable[[dict], None] | None:
    """Returns a per-case callable (so ``process_case``/``run_cases`` stay
    completely unchanged), but the callable itself only ever reaches
    Langfuse ONCE per (run_phase, mode): on every invocation it re-reads
    ALL of that mode's expected cases from disk (not from in-memory
    accumulation, so this survives a process restart mid-run), and only
    calls ``langfuse_sync.sync_mode_group_once`` -- which itself is a
    no-op if that exact group was already synced -- once every expected
    case for the mode has both a correctness and a faithfulness score on
    disk. While the group is incomplete, this is a silent no-op (the
    case's own ``langfuse_synced`` flag still advances, since from the
    per-case step machine's point of view the case's data is simply
    queued for the next group-complete sync).

    Loads the project's .env and verifies the required Langfuse
    credentials BEFORE constructing the client -- ``run_measurement``
    already does this once at startup, but this function repeats the
    check (cheap, idempotent) so it never silently builds a
    disabled client if ever called on its own."""
    try:
        import langfuse  # noqa: F401
    except ImportError:
        return None
    load_project_env()
    ensure_langfuse_configured()
    from langfuse import Langfuse
    import langfuse_sync as ls

    client = Langfuse()
    marker_dir = case_store_dir.parent / "langfuse-markers"

    def sync_one(row: dict[str, Any]) -> None:
        mode = row["mode"]
        disk_rows = []
        for question_id in expected_question_ids:
            case_path = case_store_dir / f"{question_id}-{mode}.json"
            if not case_path.exists():
                return  # group not complete yet -- nothing to sync now
            data = json.loads(case_path.read_text(encoding="utf-8"))
            if data.get("correctness") is None or data.get("faithfulness") is None:
                return  # group not complete yet
            disk_rows.append(data)
        records = [_row_to_local_record(r) for r in disk_rows]
        marker_path = marker_dir / f"{run_phase}-{mode}.json"
        ls.sync_mode_group_once(
            client, marker_path, run_phase=run_phase, mode=mode,
            records=records, config_metadata=effective_config(),
        )

    return sync_one


def run_measurement(run_kind: str, *, golden_path: Path = DEFAULT_GOLDEN_PATH, sync_langfuse: bool = True) -> dict:
    # Fail fast, before any paid call is built: load the project's .env
    # (the existing naive_rag.config solution only parses it for its own
    # pydantic fields and never exports to os.environ) and verify the
    # Langfuse credentials are actually present. A missing credential must
    # stop the run here, not continue with Langfuse's own silently
    # disabled client.
    if sync_langfuse:
        load_project_env()
        ensure_langfuse_configured()

    from naive_rag.global_search import load_reports

    all_questions = load_golden_set(golden_path)
    corpus_sha256 = verify_single_corpus_snapshot(all_questions)
    chunks_path = PROJECT_ROOT / all_questions[0].corpus_chunks_file
    verify_corpus_matches_disk(corpus_sha256, chunks_path)

    questions = select_questions(all_questions, run_kind)
    signature = build_run_signature(run_kind, golden_path)
    state_path = STATE_DIR / f"week5-b-state-{run_kind}.json"
    store = state_store.StateStore.load_or_create(state_path, signature)

    import cost_guard
    ledger_path = RESULTS_DIR / "week5-b-cost-ledger.json"
    budget = cost_guard.SharedCostLedger.load(ledger_path)

    import run_phase5 as phase5
    phase_ledger = phase5.Ledger(run_id=f"week5-b-{run_kind}-{int(time.time())}",
                                 path=RESULTS_DIR / f"week5-b-ledger-{run_kind}.json")

    reports = load_reports(
        PROJECT_ROOT / CONFIG["global_report_collection"],
        expected_run_id=CONFIG["global_run_id"], expected_reporting_level=CONFIG["global_reporting_level"],
    )

    with shared_qdrant_client() as qdrant_client:
        gen_fns = build_real_gen_fns(
            budget, phase_ledger, reports, run_kind, qdrant_client=qdrant_client)
        judge_log_dir = RESULTS_DIR.parent / "logs" / "judges"
        correctness_call_fn_factory = build_real_judge_call_fn_factory(
            budget, phase_ledger, f"correctness-{run_kind}", judge_log_dir)
        faithfulness_call_fn_factory = build_real_judge_call_fn_factory(
            budget, phase_ledger, f"faithfulness-{run_kind}", judge_log_dir)
        case_store_dir = CASES_DIR / run_kind
        langfuse_sync_fn = (
            build_real_langfuse_sync_fn(run_kind, tuple(q.id for q in questions), case_store_dir)
            if sync_langfuse else None
        )

        ctx = CaseContext(
            run_phase=run_kind, budget=budget, ledger=phase_ledger, gen_fns=gen_fns,
            correctness_call_fn_factory=correctness_call_fn_factory,
            faithfulness_call_fn_factory=faithfulness_call_fn_factory,
            langfuse_sync_fn=langfuse_sync_fn, case_store_dir=case_store_dir,
        )

        rows = run_cases(questions, store, ctx)

    import report as report_mod
    results_path = RESULTS_DIR / "results.jsonl"
    all_rows = report_mod.load_results(results_path)
    by_key = {(r["question_id"], r["mode"], r["run_phase"]): r for r in all_rows}
    for row in rows:
        by_key[(row["question_id"], row["mode"], row["run_phase"])] = row
    report_mod.write_results(results_path, by_key.values())

    report_md = report_mod.build_report_markdown(list(by_key.values()), run_phase=run_kind)
    (RESULTS_DIR / f"week5-b-report-{run_kind}.md").write_text(report_md, encoding="utf-8")

    return {"run_kind": run_kind, "case_count": len(rows), "state_summary": store.summary(),
           "remaining_budget_usd": budget.remaining_usd()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="measure.py")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run (or resume) the smoke or full measurement")
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
        except MeasurementHalted as exc:
            print(f"HALTED: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(outcome, ensure_ascii=False, indent=1, default=str))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
