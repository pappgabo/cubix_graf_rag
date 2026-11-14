"""Mode wrappers that call the KEPT-UNCHANGED Phase 5 code path
(``diagnostics/2026-11-10-phase5-run/run_phase5.py``) for one question at
a time, and capture the chunk ids/actual context that call already
produced -- no second retrieval, no reindexing, no prompt/budget/model
change.

Same model, prompt, collection, top_k, context budget, output budget,
global filtering and A-branch as Phase 5 (``run_phase5.py`` is imported,
not copied, except for the lokalis wrapper below, which must duplicate a
small amount of ``run_lokalis`` because that function discards the
``LocalAnswer`` object -- and with it the post-budget sources and the
rendered prompt -- before returning. The duplicated code changes nothing
about the model, budget, or k; it only keeps more of the same call's
return value.

``run_phase5.LOG_DIR`` is monkey-patched (module attribute, not file
content) to our own logs directory so new log files never land inside
the preserved Phase 5 folder.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401
import run_phase5 as phase5

HERE = Path(__file__).resolve().parent
LOG_DIR = HERE / "logs"
phase5.LOG_DIR = LOG_DIR  # redirect all of run_phase5's log writes here


def run_naiv_capture(
    question_id: str, question_text: str, budget, ledger, *, run_phase: str, **inject,
) -> dict[str, Any]:
    """One real retrieval + one real generation call via
    ``run_phase5.run_naiv`` (unchanged). The sources it already computed
    (with ``chunk_id``) are reused for both the actual-context
    reconstruction and the retrieval record -- never re-retrieved."""
    from naive_rag.rag import format_context

    started = time.monotonic()
    result = phase5.run_naiv(question_id, question_text, budget, ledger, **inject)
    elapsed = time.monotonic() - started
    sources = result.get("sources") or []
    chunk_ids = [s["chunk_id"] for s in sources if s.get("chunk_id")]
    actual_context = format_context(sources) if sources else ""
    return {
        "question_id": question_id, "mode": "naiv", "run_phase": run_phase,
        "answer": result.get("answer"), "refused": None, "model_called": result.get("error") is None,
        "actual_context": actual_context, "actual_chunk_ids": chunk_ids, "chunk_ids_traceable": True,
        "is_proxy_retrieval": False,
        "error": result.get("error"), "duration_seconds": round(elapsed, 3),
        "ledger_entry": result.get("ledger_entry"),
        "raw": {"sources": sources},
    }


def run_lokalis_capture(
    question_id: str, question_text: str, budget, ledger, *,
    run_phase: str, chat_client=None, openai_client=None, query_fn=None,
) -> dict[str, Any]:
    """Mirrors ``run_phase5.run_lokalis`` exactly (same model, same budget,
    same k=3, same gating/logging), but also returns the post-budget
    ``LocalAnswer.subgraph['sources']`` and the literal rendered prompt,
    which the original function computes but does not return."""
    from naive_rag.config import get_settings
    from naive_rag.models import get_chat_model
    from naive_rag.neo4j_entity_index import configured_embedding_model
    from naive_rag.neo4j_local_search import neo4j_local_search
    from naive_rag.local_search import configured_query, context_budget_from_settings
    from naive_rag.local_search_logging import make_logged_answer_fn

    settings = get_settings()
    query_fn = query_fn or configured_query
    model_name = configured_embedding_model(settings) if query_fn is configured_query else "offline-test-model"

    def gated_embed_query(q: str) -> list[float]:
        return phase5.embed_texts(
            [q], [f"lokalis-query-{question_id}"], budget, ledger,
            label=f"lokalis-query-{question_id}", openai_client=openai_client,
        )[0]

    chat_client = chat_client or get_chat_model(max_retries=0, max_tokens=phase5.GENERATIVE_MAX_TOKENS)
    plain_answer_fn = make_logged_answer_fn(chat_client, log_dir=LOG_DIR, question_id=f"lokalis-{question_id}")

    def gated_answer_fn(prompt: str) -> str:
        upper = budget.check_generative(
            phase5.estimate_tokens(prompt), phase5.GENERATIVE_MAX_TOKENS, f"lokalis-{question_id}")
        answer = plain_answer_fn(prompt)
        log_path = LOG_DIR / f"local-log-lokalis-{question_id}.json"
        import json
        saved = json.loads(log_path.read_text(encoding="utf-8"))
        budget.record_generative(saved.get("usage_prompt_tokens"), saved.get("usage_completion_tokens"), upper)
        return answer

    error = None
    found = None
    started = time.monotonic()
    try:
        found = neo4j_local_search(
            question_text, embed_query=gated_embed_query, answer_fn=gated_answer_fn,
            query_fn=query_fn, model=model_name, k=3,
            budget=context_budget_from_settings(settings),
        )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    elapsed = time.monotonic() - started

    sources = (found.subgraph.get("sources") or []) if found else []
    chunk_ids = [s["chunk_id"] for s in sources if s.get("chunk_id") and s.get("text_found")]
    return {
        "question_id": question_id, "mode": "lokalis", "run_phase": run_phase,
        "answer": found.answer if found else None,
        "refused": found.refused if found else None,
        "model_called": found.model_called if found else None,
        "actual_context": found.prompt if found else "",
        "actual_chunk_ids": chunk_ids, "chunk_ids_traceable": found is not None,
        "is_proxy_retrieval": False,
        "error": error, "duration_seconds": round(elapsed, 3),
        "raw": {"context_budget": found.context_budget if found else None, "subgraph_sources": sources},
    }


def run_global_capture(
    question_id: str, question_text: str, budget, ledger, reports, *,
    run_phase: str, client_factory=None,
) -> dict[str, Any]:
    """Runs exactly one question through ``run_phase5.run_globalis_rerun``
    (unchanged code path: same model, same map/reduce prompts, same A-only
    branch), by scoping its ``questions`` list to this one question.

    The retrieval-proxy chunk ids and the actual reduce-input context come
    from the basis the reduce step was actually given (``reduce_a.basis_paths``
    + each basis map result's ``cited_statement_ids``), never from the
    final answer's ``citation_chain`` -- the jóváhagyási jegyzet's
    retrieval_bridge-style distinction between "what was fed in" and "what
    the final answer happened to cite" is preserved."""
    from naive_rag.global_search import GLOBAL_REFUSAL, Question as GSQuestion, reduce_user_message

    question = GSQuestion(question_id=question_id, label="global", text=question_text)
    started = time.monotonic()
    results = phase5.run_globalis_rerun(
        budget, ledger, client_factory=client_factory, reports=reports, questions=[question],
    )
    elapsed = time.monotonic() - started
    outcome = results.get(question_id, {})

    reduce_a = outcome.get("reduce_a") or {}
    map_results = outcome.get("map_results") or []
    map_by_path = {r.path: r for r in map_results}
    reports_by_path = {r.path: r for r in reports}
    basis_paths = reduce_a.get("basis_paths") or []
    basis = [map_by_path[p] for p in basis_paths if p in map_by_path]

    actual_context = reduce_user_message(question_text, basis) if basis else ""
    chunk_ids: list[str] = []
    for map_result in basis:
        report = reports_by_path.get(map_result.path)
        if report is None:
            continue
        statements_by_id = {s.statement_id: s for s in report.statements}
        for statement_id in map_result.cited_statement_ids:
            statement = statements_by_id.get(statement_id)
            if statement is None:
                continue
            for chunk_id in statement.candidate_source_chunk_ids:
                if chunk_id not in chunk_ids:
                    chunk_ids.append(chunk_id)

    return {
        "question_id": question_id, "mode": "globalis", "run_phase": run_phase,
        "answer": reduce_a.get("answer"),
        "refused": (reduce_a.get("answer") == GLOBAL_REFUSAL) if "answer" in reduce_a else None,
        "model_called": not reduce_a.get("no_model_call", False),
        "actual_context": actual_context, "actual_chunk_ids": chunk_ids,
        "chunk_ids_traceable": True, "is_proxy_retrieval": True,
        "proxy_note": "candidate_source_chunk_ids from the reduce step's actual basis "
                      "(basis_paths), not the final answer's citation_chain -- a "
                      "retrieval proxy, not verified per-chunk coverage",
        "error": outcome.get("halted_reason"), "duration_seconds": round(elapsed, 3),
        "raw": {"basis_paths": basis_paths, "map_result_count": len(map_results), "reduce_a": reduce_a},
    }
