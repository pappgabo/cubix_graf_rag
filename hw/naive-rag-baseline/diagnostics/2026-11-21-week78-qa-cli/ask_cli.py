"""Common question-answering CLI for the four existing search modes
(naiv/lokalis/globalis/drift) and the automatic router, built on the
existing ``naive_rag.answer_question.answer_question`` dispatch entry
point (``src/naive_rag/answer_question.py``, unmodified).

This module only WIRES already-existing real clients/searchers together
-- it does not reimplement or change any search, router, prompt, or
evaluator logic:
  - naiv/lokalis/globalis: ``generation_runner.run_naiv_capture`` /
    ``run_lokalis_capture`` / ``run_global_capture`` (week5-b, unchanged),
    themselves thin wrappers around ``run_phase5.py``'s real-client code.
  - drift: ``drift_runner.run_drift_capture`` (week6, unchanged).
  - auto routing: ``search_router.route_one`` via ``answer_question``,
    with a real raw_caller built the same way ``route_demo.py`` already
    builds one.

Cost is gated through ``cost_guard.SharedCostLedger`` (week5-b's class,
reused unchanged) before every paid call, including the router call --
this CLI's own, separate ledger file (see LEDGER_PATH below), so no
existing week5-b/week6 ledger record is touched or reset.

    uv run python diagnostics\\2026-11-21-week78-qa-cli\\ask_cli.py --mode auto --question "..."
    uv run python diagnostics\\2026-11-21-week78-qa-cli\\ask_cli.py --mode drift --question "..."

No real API/DB call has been made with this module in this round -- see
README.md's CLI section for exact commands and what remains unexercised.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable

import week78_bootstrap  # noqa: F401

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
LEDGER_PATH = RESULTS_DIR / "week78-qa-cli-cost-ledger.json"
REQUEST_LOG_PATH = RESULTS_DIR / "week78-qa-cli-request-log.json"

MODES = ("naiv", "lokalis", "globalis", "drift")

# Same frozen report collection / run id / reporting level as week5-b's
# measure.py CONFIG and week6's drift_measure.py GLOBAL_* constants --
# read here, not re-chosen or re-derived.
GLOBAL_REPORT_COLLECTION = (
    "diagnostics/2026-11-10-phase3-measurement/results/week4-report-v3-collection.jsonl"
)
GLOBAL_RUN_ID = "week4-leiden-elokeszitett-6f05327d7d88ebf0"
GLOBAL_REPORTING_LEVEL = 0


class PrerequisiteMissing(RuntimeError):
    """An existing mode's infrastructure/artifact is not ready. Raised
    before any paid call; this CLI never builds, rebuilds, or repairs
    the missing piece itself."""


# --------------------------------------------------------------------------
# Readiness probes -- read-only, no paid call, no index build, no DB write
# --------------------------------------------------------------------------

def probe_naiv() -> None:
    """The Qdrant collection ``run_phase5.NEW_COLLECTION`` must already
    exist (it is not built by this CLI)."""
    import run_phase5 as phase5
    from naive_rag.vectorstore import _client

    try:
        client = _client(register_close=False)
    except Exception as exc:  # noqa: BLE001
        raise PrerequisiteMissing(f"naiv: Qdrant unreachable ({exc})") from exc
    try:
        exists = client.collection_exists(phase5.NEW_COLLECTION)
    except Exception as exc:  # noqa: BLE001
        raise PrerequisiteMissing(f"naiv: Qdrant unreachable ({exc})") from exc
    finally:
        client.close()
    if not exists:
        raise PrerequisiteMissing(
            f"naiv: Qdrant collection {phase5.NEW_COLLECTION!r} does not exist "
            "-- this CLI does not build it (see docs/week6-eredmenyek.md "
            "'Aktuális és történeti adatok' for how it was indexed)")


def probe_lokalis() -> None:
    """Neo4j settings must be present and the configured vector index must
    be online (both existing, unmodified checks: ``local_search.
    require_neo4j_settings`` / ``require_vector_index``)."""
    from naive_rag.config import get_settings
    from naive_rag.local_search import configured_query, require_neo4j_settings, require_vector_index

    settings = get_settings()
    try:
        require_neo4j_settings(settings)
        require_vector_index(configured_query)
    except Exception as exc:  # noqa: BLE001
        raise PrerequisiteMissing(f"lokalis: {exc}") from exc


def probe_globalis() -> tuple:
    """The community report collection file must exist and parse with the
    expected run id/level (``global_search.load_reports``, unmodified).
    Returns the loaded reports so the mode builder below does not
    re-read the file."""
    from naive_rag.config import PROJECT_ROOT
    from naive_rag.global_search import load_reports

    collection_path = PROJECT_ROOT / GLOBAL_REPORT_COLLECTION
    if not collection_path.exists():
        raise PrerequisiteMissing(f"globalis: report collection not found: {collection_path}")
    try:
        return load_reports(
            collection_path, expected_run_id=GLOBAL_RUN_ID, expected_reporting_level=GLOBAL_REPORTING_LEVEL)
    except Exception as exc:  # noqa: BLE001
        raise PrerequisiteMissing(f"globalis: {exc}") from exc


def probe_drift() -> tuple:
    """The report-index embedding cache must already exist and match the
    current report collection (``drift_measure.require_report_index``,
    unmodified -- no automatic rebuild). Also needs the same report
    collection as globalis. Returns everything ``run_drift_capture``
    needs so it is computed exactly once per CLI invocation."""
    import drift_measure as dm
    import drift_runner

    reports = probe_globalis()
    try:
        report_index = dm.require_report_index(reports, dm.REPORT_INDEX_CACHE_PATH)
    except dm.ReportIndexNotReady as exc:
        raise PrerequisiteMissing(f"drift: {exc}") from exc
    graph, local_index, chunk_texts = drift_runner.build_local_search_fixtures()
    return reports, report_index, graph, local_index, chunk_texts


PROBES: dict[str, Callable[[], Any]] = {
    "naiv": probe_naiv, "lokalis": probe_lokalis, "globalis": probe_globalis, "drift": probe_drift,
}


# --------------------------------------------------------------------------
# Real mode_fn builders -- each wraps an existing, unmodified real-client
# capture function from generation_runner.py (week5-b) or drift_runner.py
# (week6). No search/router/prompt logic is copied here.
# --------------------------------------------------------------------------

def build_naiv_fn(cost_ledger, request_log) -> Callable[[str], dict]:
    import generation_runner as gr

    def fn(question_text: str) -> dict:
        return gr.run_naiv_capture("cli", question_text, cost_ledger, request_log, run_phase="cli")
    return fn


def build_lokalis_fn(cost_ledger, request_log) -> Callable[[str], dict]:
    import generation_runner as gr

    def fn(question_text: str) -> dict:
        return gr.run_lokalis_capture("cli", question_text, cost_ledger, request_log, run_phase="cli")
    return fn


def build_globalis_fn(cost_ledger, request_log, reports) -> Callable[[str], dict]:
    import generation_runner as gr

    def fn(question_text: str) -> dict:
        return gr.run_global_capture("cli", question_text, cost_ledger, request_log, reports, run_phase="cli")
    return fn


def build_drift_fn(cost_ledger, *, reports, report_index, graph, local_index, chunk_texts) -> Callable[[str], dict]:
    import drift_runner

    def fn(question_text: str) -> dict:
        return drift_runner.run_drift_capture(
            "cli", question_text, cost_ledger, run_phase="cli",
            reports=reports, report_index=report_index, graph=graph,
            local_index=local_index, chunk_texts=chunk_texts)
    return fn


_BUILDERS: dict[str, Callable] = {
    "naiv": lambda cl, rl, probe_result: build_naiv_fn(cl, rl),
    "lokalis": lambda cl, rl, probe_result: build_lokalis_fn(cl, rl),
    "globalis": lambda cl, rl, probe_result: build_globalis_fn(cl, rl, probe_result),
    "drift": lambda cl, rl, probe_result: build_drift_fn(cl, **dict(zip(
        ("reports", "report_index", "graph", "local_index", "chunk_texts"), probe_result))),
}


def build_ready_mode_fns(
    cost_ledger, request_log, *, only: set[str] | None = None,
    probes: dict[str, Callable] | None = None, builders: dict[str, Callable] | None = None,
) -> tuple[dict[str, Callable[[str], dict]], dict[str, str]]:
    """Probes each requested mode (read-only) and builds a real mode_fn
    only for the ones that are ready. Returns (mode_fns, unavailable) --
    ``unavailable`` maps mode -> human-readable reason; a mode missing a
    prerequisite is reported, never silently skipped."""
    probes = probes if probes is not None else PROBES
    builders = builders if builders is not None else _BUILDERS
    wanted = only if only is not None else set(MODES)
    mode_fns: dict[str, Callable[[str], dict]] = {}
    unavailable: dict[str, str] = {}
    for mode in MODES:
        if mode not in wanted:
            continue
        try:
            probe_result = probes[mode]()
        except PrerequisiteMissing as exc:
            unavailable[mode] = str(exc)
            continue
        mode_fns[mode] = builders[mode](cost_ledger, request_log, probe_result)
    return mode_fns, unavailable


def build_router_raw_caller(cost_ledger):
    """Same construction as ``route_demo.py``'s
    ``build_real_router_raw_caller``: gpt-4o-mini, temperature=0,
    max_retries=0, JSON response_format, gated through this CLI's own
    cost ledger before the call, exactly like every other paid call
    here."""
    from langchain_openai import ChatOpenAI

    from naive_rag.call_logging import CallParams, make_langchain_raw_caller
    from naive_rag.config import get_settings
    from naive_rag.local_search import estimate_tokens

    settings = get_settings()

    def factory(params: CallParams):
        return ChatOpenAI(
            model=params.model, temperature=params.temperature, max_retries=params.max_retries,
            max_tokens=params.max_tokens, api_key=settings.openai_api_key,
            model_kwargs={"response_format": params.response_format},
        )

    base_caller = make_langchain_raw_caller(factory)

    def gated(messages, params: CallParams):
        input_text = " ".join(message["content"] for message in messages)
        upper = cost_ledger.check_generative(estimate_tokens(input_text), params.max_tokens, "qa-cli-router")
        response = base_caller(messages, params)
        usage = getattr(response, "usage_metadata", None) or {}
        token_usage = (getattr(response, "response_metadata", None) or {}).get("token_usage", {})
        prompt_tokens = usage.get("input_tokens", token_usage.get("prompt_tokens", "unknown"))
        completion_tokens = usage.get("output_tokens", token_usage.get("completion_tokens", "unknown"))
        cost_ledger.record_generative(prompt_tokens, completion_tokens, upper)
        return response

    return gated


# --------------------------------------------------------------------------
# Dispatch (testable with fake probes/builders/raw_caller) and CLI
# --------------------------------------------------------------------------

def dispatch(
    mode: str, question: str, *, cost_ledger, request_log,
    mode_fn_builder: Callable = build_ready_mode_fns,
    router_raw_caller_builder: Callable = build_router_raw_caller,
) -> dict:
    """``mode`` is ``"auto"`` or one of MODES. Explicit modes never call
    the router (``answer_question``'s own guarantee); auto probes/builds
    mode_fns for ALL four modes (the router may pick any of them), while
    an explicit mode only probes/builds that one mode."""
    import cost_guard
    from naive_rag import answer_question as aq

    only = None if mode == "auto" else {mode}
    mode_fns, unavailable = mode_fn_builder(cost_ledger, request_log, only=only)

    entries_before = len(cost_ledger.entries)
    record = None
    error = None
    try:
        if mode == "auto":
            raw_caller = router_raw_caller_builder(cost_ledger)
            record = aq.answer_question("cli", question, mode_fns=mode_fns, raw_caller=raw_caller)
        else:
            if mode not in mode_fns:
                raise PrerequisiteMissing(unavailable.get(mode, f"{mode}: prerequisite missing"))
            record = aq.answer_question("cli", question, mode_fns=mode_fns, mode=mode)
    except cost_guard.BudgetExceeded as exc:
        error = f"cost guard rejected the call before it was made: {exc}"
    except PrerequisiteMissing as exc:
        error = str(exc)

    new_entries = cost_ledger.entries[entries_before:]
    return {
        "requested_mode": mode,
        "unavailable_modes": unavailable,
        "record": record,
        "error": error,
        "new_ledger_entries": new_entries,
        "ledger_cumulative_spent_usd": cost_ledger.spent_usd,
        "ledger_cumulative_remaining_usd": cost_ledger.remaining_usd(),
        "ledger_path": str(LEDGER_PATH),
        "request_log_path": str(REQUEST_LOG_PATH),
    }


def print_result(outcome: dict) -> None:
    print(f"requested mode: {outcome['requested_mode']}")
    if outcome["unavailable_modes"]:
        print("unavailable modes (no real call attempted for these):")
        for mode, reason in outcome["unavailable_modes"].items():
            print(f"  - {mode}: {reason}")
    record = outcome["record"]
    if record is not None:
        print(f"mode source: {record['mode_source']}")
        route_record = record.get("route_record")
        if route_record is not None:
            print(f"router decision: {route_record.get('mode')!r}  reasoning: {route_record.get('reasoning')!r}")
        print(f"executed branch: {record['mode']}")
        if record.get("error"):
            print(f"dispatch error: {record['error']}")
        result = record.get("result") or {}
        if isinstance(result, dict):
            if result.get("error"):
                print(f"branch error: {result['error']}")
            else:
                print(f"answer: {result.get('answer')}")
    if outcome["error"]:
        print(f"error: {outcome['error']}")
    print("cost (new entries from this invocation):")
    if not outcome["new_ledger_entries"]:
        print("  (none -- no paid call was made)")
    for entry in outcome["new_ledger_entries"]:
        cost = entry.get("cost_usd")
        tag = "" if entry.get("usage_known", True) else "  (usage unknown -- upper-bound estimate, not zero)"
        print(f"  - {entry.get('step')}: {cost:.6f} USD{tag}")
    print(f"ledger cumulative: spent={outcome['ledger_cumulative_spent_usd']:.6f} USD, "
          f"remaining={outcome['ledger_cumulative_remaining_usd']:.6f} USD")
    print(f"ledger file: {outcome['ledger_path']}")
    print(f"request log file: {outcome['request_log_path']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python ask_cli.py")
    parser.add_argument("--mode", choices=("auto",) + MODES, default="auto",
                        help="auto uses the router; an explicit mode skips it entirely")
    parser.add_argument("--question", required=True)
    parser.add_argument("--out", type=Path, default=None,
                        help="optional: also save the full JSON outcome here")
    args = parser.parse_args(argv)

    import cost_guard
    import run_phase5 as phase5

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cost_ledger = cost_guard.SharedCostLedger.load(LEDGER_PATH)
    request_log = phase5.Ledger(run_id=f"week78-qa-cli-{int(time.time())}", path=REQUEST_LOG_PATH)

    outcome = dispatch(args.mode, args.question, cost_ledger=cost_ledger, request_log=request_log)
    print_result(outcome)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(outcome, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0 if outcome["error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
