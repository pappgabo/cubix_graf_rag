"""Read-only demo of `naive_rag.answer_question.answer_question`, wired to
the same real clients/settings `drift_measure.py` builds for the drift
mode (gpt-4o-mini, temperature=0, max_retries=0, the existing report-index
cache), plus the router's own real-call pattern
(`run_phase5.run_router_all`'s raw_caller construction, reused unchanged
in shape).

Only "drift" is wired into `mode_fns` -- this script does not build
naiv/lokalis/globalis clients (that would mean importing and re-wiring
`generation_runner.py`'s whole Qdrant/Neo4j lifecycle, out of scope for a
small demo). If the automatic router call (a) picks a different mode, the
output honestly reports "no search function registered for mode X", not
a fabricated result.

No measurement state, case store, or results.jsonl is touched -- this is
a standalone demo, not part of the smoke/full pipeline. A missing or
mismatched report-index cache stops the script with a clear error (no
silent rebuild), same as `drift_measure.py`.

    uv run python diagnostics\\2026-11-14-week6-drift\\route_demo.py --question "..."
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import week6_bootstrap  # noqa: F401
import drift_measure as dm
import drift_runner
from naive_rag import answer_question as aq
from naive_rag.call_logging import CallParams, make_langchain_raw_caller
from naive_rag.local_search import estimate_tokens

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
OUT_PATH = RESULTS_DIR / "week6-route-demo.json"


def default_question() -> str:
    """Question text only -- no id, no gold answer -- exactly what the
    router is allowed to see (see search_router.router_messages)."""
    from golden_set import load_golden_set

    questions = load_golden_set(dm.DEFAULT_GOLDEN_PATH)
    return next(q for q in questions if q.id == "Q09").question


def build_real_router_raw_caller(ledger):
    """Same construction as `run_phase5.run_router_all`'s real raw_caller
    (diagnostics/2026-11-10-phase5-run/run_phase5.py) -- gpt-4o-mini,
    temperature=0, max_retries=0, JSON response_format -- gated through
    the shared week6 cost ledger before the call, exactly like every
    other paid call in this measurement."""
    from naive_rag.config import get_settings
    from langchain_openai import ChatOpenAI

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
        upper = ledger.check_generative(estimate_tokens(input_text), params.max_tokens, "route-demo-router")
        response = base_caller(messages, params)
        usage = getattr(response, "usage_metadata", None) or {}
        token_usage = (getattr(response, "response_metadata", None) or {}).get("token_usage", {})
        prompt_tokens = usage.get("input_tokens", token_usage.get("prompt_tokens", "unknown"))
        completion_tokens = usage.get("output_tokens", token_usage.get("completion_tokens", "unknown"))
        ledger.record_generative(prompt_tokens, completion_tokens, upper)
        return response

    return gated


def build_drift_mode_fn(ledger, *, reports, report_index, graph, local_index, chunk_texts, label: str):
    def drift_fn(question_text: str) -> dict:
        return drift_runner.run_drift_capture(
            label, question_text, ledger, run_phase="route-demo",
            reports=reports, report_index=report_index, graph=graph,
            local_index=local_index, chunk_texts=chunk_texts,
        )

    return drift_fn


def run(question: str) -> dict[str, Any]:
    import cost_guard

    collection_path = dm.PROJECT_ROOT / dm.GLOBAL_REPORT_COLLECTION
    global_run_id = dm.detect_report_run_id(collection_path)
    reports = dm.load_reports(
        collection_path, expected_run_id=global_run_id, expected_reporting_level=dm.GLOBAL_REPORTING_LEVEL)
    # Fails fast, before the ledger or any paid call, if the cache is
    # missing/stale -- no silent rebuild (same guarantee as drift_measure.py).
    report_index = dm.require_report_index(reports, dm.REPORT_INDEX_CACHE_PATH)

    ledger = cost_guard.SharedCostLedger.load(dm.LEDGER_PATH)
    graph, local_index, chunk_texts = drift_runner.build_local_search_fixtures()

    raw_caller = build_real_router_raw_caller(ledger)
    mode_fns_auto = {"drift": build_drift_mode_fn(
        ledger, reports=reports, report_index=report_index, graph=graph,
        local_index=local_index, chunk_texts=chunk_texts, label="route-demo-auto")}
    mode_fns_explicit = {"drift": build_drift_mode_fn(
        ledger, reports=reports, report_index=report_index, graph=graph,
        local_index=local_index, chunk_texts=chunk_texts, label="route-demo-explicit")}

    started_auto = time.time()
    auto_record = aq.answer_question(
        "route-demo-auto", question, mode_fns=mode_fns_auto, raw_caller=raw_caller)
    auto_record["timestamp"] = started_auto

    started_explicit = time.time()
    explicit_record = aq.answer_question(
        "route-demo-explicit", question, mode_fns=mode_fns_explicit, mode="drift")
    explicit_record["timestamp"] = started_explicit

    return {
        "question": question,
        "auto_route": auto_record,
        "explicit_drift": explicit_record,
        "ledger_path": str(dm.LEDGER_PATH),
        "ledger_cumulative_spent_usd": ledger.spent_usd,
        "ledger_cumulative_remaining_usd": ledger.remaining_usd(),
        "generated_at": time.time(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python route_demo.py")
    parser.add_argument("--question", default=None,
                        help="question text only; default: golden set Q09's question text")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)

    question = args.question or default_question()
    outcome = run(question)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(outcome, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
