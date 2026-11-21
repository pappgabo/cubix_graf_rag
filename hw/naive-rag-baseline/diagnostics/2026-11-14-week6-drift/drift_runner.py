"""Real-call wiring for the drift mode, mirroring
``diagnostics/2026-11-11-week5-b/generation_runner.py``'s pattern (call the
KEPT-UNCHANGED code path for one question at a time, capture what it
already computed) -- except the "kept-unchanged code path" here is the
week6 B-phase `naive_rag.drift_search.drift_search`, not Phase 5.

No model/embedding client is constructed at import time. `max_retries=0`
everywhere, same as every other wrapper in this project.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import week6_bootstrap  # noqa: F401

from naive_rag.call_logging import CallParams, logged_call, make_langchain_raw_caller, save_log_entry
from naive_rag.drift_search import (
    CHAT_MODEL,
    MAX_RETRIES,
    REFUSAL,
    TEMPERATURE,
    DriftAnswer,
    StepUsage,
    drift_search,
)
from naive_rag.entity_index import EntityIndex, load_index as load_entity_index
from naive_rag.global_search import CommunityReport
from naive_rag.graph_merge import DomainGraph, merged_graph
from naive_rag.ingest import load_and_chunk
from naive_rag.quality_report import load_records

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
LOG_DIR = HERE / "logs"

# Pre-embedded, historical artifacts -- loading them makes no new embedding
# call (see docs/extrakcio-es-lokalis-kereses.md: "A 401 összevont entitás
# embeddingje elkészült"). The extraction-record -> merged-graph step is a
# pure, offline data transform (no model call).
EXTRACTION_DIR = PROJECT_ROOT / "graph" / "corpus" / "extraction"
ENTITY_INDEX_PATH = PROJECT_ROOT / "graph" / "corpus" / "entity-index.json"


def detect_report_run_id(collection_path: Path) -> str:
    """Reads the actual ``run_id`` from the report collection file itself
    -- never a hardcoded assumption. Uses the first non-empty line only;
    ``global_search.load_reports`` is what actually validates every line
    shares the same run_id."""
    with collection_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            run_id = row.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                raise ValueError(f"{collection_path}: first report row has no run_id")
            return run_id
    raise ValueError(f"{collection_path}: no report rows found")


def build_local_search_fixtures() -> tuple[DomainGraph, EntityIndex, dict[str, str]]:
    """The merged domain graph, the pre-built entity index, and the chunk
    text lookup `local_search.local_search` needs for sub-question
    answering -- all offline, no model call (same artifacts/functions
    `naive_rag.local_search.main()` and `naive_rag.entity_index.main()`
    already use)."""
    graph = merged_graph(load_records(EXTRACTION_DIR))
    local_index = load_entity_index(ENTITY_INDEX_PATH)
    _sources, chunks = load_and_chunk()
    chunk_texts = {chunk.metadata.get("chunk_id"): chunk.page_content for chunk in chunks}
    return graph, local_index, chunk_texts


def build_real_call_chat(*, log_dir: Path, label_prefix: str):
    """`call_chat(prompt, label, max_output_tokens) -> (text, usage)`, the
    exact contract `drift_search.drift_search` expects. Reuses
    `call_logging.logged_call`/`make_langchain_raw_caller` unchanged --
    every call is logged (exact messages, usage, duration) before this
    function ever looks at the result."""
    from naive_rag.models import get_chat_model

    def client_factory(params: CallParams):
        return get_chat_model(max_retries=params.max_retries, max_tokens=params.max_tokens)

    raw_caller = make_langchain_raw_caller(client_factory)

    def call_chat(prompt: str, label: str, max_output_tokens: int) -> tuple[str, dict]:
        params = CallParams(
            model=CHAT_MODEL, temperature=TEMPERATURE, max_tokens=max_output_tokens,
            response_format=None, max_retries=MAX_RETRIES,
        )
        messages = [{"role": "user", "content": prompt}]
        entry = logged_call(messages, params, raw_caller)
        save_log_entry(log_dir / f"{label_prefix}-{label}-{time.time_ns()}.json", entry)
        if entry.error:
            raise RuntimeError(entry.error)
        return entry.raw_response or "", {
            "prompt_tokens": entry.usage_prompt_tokens,
            "completion_tokens": entry.usage_completion_tokens,
        }

    return call_chat


def build_real_call_embed():
    """`call_embed(texts, label) -> (vectors, total_tokens)`. The installed
    langchain embeddings client does not expose token usage, so
    `total_tokens` is `"unknown"` -- `drift_search`'s cost-guard wrapper
    already books the pre-call upper bound for that case, never zero."""
    from naive_rag.models import get_embeddings

    embeddings = get_embeddings()

    def call_embed(texts: list[str], label: str) -> tuple[list[list[float]], Any]:
        vectors = embeddings.embed_documents(texts)
        return vectors, "unknown"

    return call_embed


def _serialize_step(step: StepUsage) -> dict:
    return {
        "step": step.step, "kind": step.kind,
        "input_tokens_estimate": step.input_tokens_estimate,
        "max_output_tokens": step.max_output_tokens,
        "upper_bound_cost_usd": step.upper_bound_cost_usd,
        "actual_cost_usd": step.actual_cost_usd,
        "usage_known": step.usage_known,
        "prompt_tokens": step.prompt_tokens, "completion_tokens": step.completion_tokens,
    }


def run_drift_capture(
    question_id: str, question_text: str, cost_guard, *,
    run_phase: str, reports: tuple[CommunityReport, ...], report_index,
    graph: DomainGraph, local_index: EntityIndex, chunk_texts: dict[str, str],
    local_budget: dict | None = None,
) -> dict[str, Any]:
    """One real drift-search call for one question. Mirrors
    `generation_runner.run_lokalis_capture`'s shape: a flat dict with the
    keys `measure.process_case` reads (`answer`, `error`,
    `actual_chunk_ids`, `chunk_ids_traceable`, `is_proxy_retrieval`,
    `actual_context`), plus drift-specific extras kept distinct.

    Three local-retrieval concepts never get merged into one number:
    - `local_candidate_chunk_ids` -- every chunk id touching the selected
      sub-question subgraph (`subgraph["chunk_ids"]`), most of which were
      NEVER shown to the model (local_search.subgraph_payload's full
      candidate pool, not budget-fitted).
    - `actual_chunk_ids` -- chunk ids whose TEXT was actually placed in
      the local-search prompt (`subgraph["sources"]`, post-`fit_context`
      budget fitting, `text_found` chunks only -- the retrieval signal
      `measure.process_case`'s `retrieval_eval` reads). This measures
      context inclusion, NOT provable use in the final synthesis answer:
      `synthesis_context`/the faithfulness judge's input are unaffected by
      this field and are not derived from it.
    - the model's own prose may cite only a subset of `actual_chunk_ids`,
      or none explicitly -- that citation-level signal is not computed
      here at all (no `unsupported_claims`-style parsing is added).

    A report's candidate chunk id (`report_candidate_chunk_ids`, from the
    primer's selected reports' `candidate_source_chunk_ids`) is a fourth,
    separate axis -- riport-level, not local-search-level -- and is never
    merged into any of the three above either."""
    call_chat = build_real_call_chat(log_dir=LOG_DIR, label_prefix=f"drift-{run_phase}-{question_id}")
    call_embed = build_real_call_embed()

    started = time.monotonic()
    result: DriftAnswer = drift_search(
        question_text, report_index=report_index, reports=reports,
        graph=graph, local_index=local_index,
        call_chat=call_chat, call_embed=call_embed, cost_guard=cost_guard,
        chunk_texts=chunk_texts, local_budget=local_budget,
    )
    elapsed = time.monotonic() - started

    local_candidate_chunk_ids: list[str] = []
    local_context_chunk_ids: list[str] = []
    for sub in result.subquestion_results:
        subgraph = sub.local_answer.subgraph
        for chunk_id in subgraph.get("chunk_ids") or []:
            if chunk_id not in local_candidate_chunk_ids:
                local_candidate_chunk_ids.append(chunk_id)
        for source in subgraph.get("sources") or []:
            chunk_id = source.get("chunk_id")
            # Same convention as generation_runner.run_lokalis_capture:
            # only a source whose text was actually found/placed counts.
            if chunk_id and source.get("text_found") and chunk_id not in local_context_chunk_ids:
                local_context_chunk_ids.append(chunk_id)
    report_candidate_chunk_ids: list[str] = []
    reports_by_path = {report.path: report for report in reports}
    for report_id in result.report_ids:
        report = reports_by_path.get(report_id)
        if report is None:
            continue
        for statement in report.statements:
            for chunk_id in statement.candidate_source_chunk_ids:
                if chunk_id not in report_candidate_chunk_ids:
                    report_candidate_chunk_ids.append(chunk_id)

    error = None if result.status == "ok" else f"{result.status}: {result.error or result.status}"
    return {
        "question_id": question_id, "mode": "drift", "run_phase": run_phase,
        "answer": result.answer if result.status == "ok" else None,
        "refused": (result.answer == REFUSAL) if result.status == "ok" else None,
        "model_called": result.generative_call_count > 0,
        "actual_context": result.synthesis_context,
        "actual_chunk_ids": local_context_chunk_ids, "chunk_ids_traceable": True,
        "is_proxy_retrieval": False,
        "local_candidate_chunk_ids": local_candidate_chunk_ids,
        "report_ids": list(result.report_ids),
        "report_candidate_chunk_ids": report_candidate_chunk_ids,
        "drift_status": result.status,
        "subquestions": list(result.subquestions),
        "synthesis_truncated": (
            result.synthesis_context_truncation.truncated
            if result.synthesis_context_truncation is not None else None),
        "drift_steps": [_serialize_step(step) for step in result.steps],
        "error": error, "duration_seconds": round(elapsed, 3),
    }
