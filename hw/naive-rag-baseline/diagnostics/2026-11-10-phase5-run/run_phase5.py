"""Phase 5 run: naiv baseline indexing + naiv/lokalis/globalis/router on
Q01-Q13, under a hard $0.15 total API cost cap (embedding + generative),
with mandatory per-call budget checks, full request logging via the
Phase 5 logging adapters, and no retries anywhere.

Reuses, never reimplements:
  - naive_search_logging.make_logged_chat_call, local_search_logging.make_logged_answer_fn,
    global_search_logging.make_logged_call_fn, search_router.route_one
    (all from Phase 5/1-2, unchanged);
  - naive_rag.rag.{PROMPT, source_of, format_context, NaiveRAG} (unchanged
    except the already-approved chat_call injection point);
  - naive_rag.local_search / neo4j_local_search (unchanged, injected
    embed_query/answer_fn/query_fn);
  - naive_rag.global_search (unchanged, injected call_fn).

Price sources (documented, not guessed):
  - gpt-4o-mini input/output: given directly by the user (0.15 / 0.60 USD
    per 1M tokens).
  - text-embedding-3-small: $0.02 / 1M input tokens, confirmed via web
    search against developers.openai.com and several independent 2026
    pricing aggregators (activepieces, cloudzero, nops, economize,
    openrouter) -- not previously verified, now confirmed.

Embeddings go through the raw `openai` client directly (not
langchain_openai.OpenAIEmbeddings), specifically so the real
`usage.total_tokens` is available for exact cost accounting -- langchain's
embed_documents()/embed_query() do not expose usage at all. The resulting
vectors are used exactly as langchain's wrapper would use them (same
model, same 1536-dim output), so the retrieval behaviour is identical to
the project's existing naive/local search; only the *measurement* path
differs.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
LOG_DIR = HERE / "logs"

CAP_USD = 0.15
INPUT_PRICE_PER_MTOK = 0.15
OUTPUT_PRICE_PER_MTOK = 0.60
EMBEDDING_PRICE_PER_MTOK = 0.02
PRICE_SOURCE = (
    "gpt-4o-mini 0.15/0.60 USD per 1M tokens: given by the user. "
    "text-embedding-3-small 0.02 USD per 1M input tokens: confirmed via "
    "web search against developers.openai.com and independent 2026 "
    "pricing aggregators on 2026-11-10."
)

NEW_COLLECTION = "week4_naive_baseline_1200_23"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
CHAT_MODEL = "gpt-4o-mini"
GENERATIVE_MAX_TOKENS = 900  # global_search.REDUCE_MAX_TOKENS, reused for naiv/lokalis/global-reduce
TOP_K = 4
INDEX_BATCH_SIZE = 200  # finer-grained than the 1000 assumed in the Phase 5/1 plan, for closer budget checks


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4) if text else 0


class BudgetExceeded(RuntimeError):
    """A call was not issued because it would exceed the $0.15 cap."""


class PreflightFailed(RuntimeError):
    pass


@dataclass
class Budget:
    cap_usd: float = CAP_USD
    spent_usd: float = 0.0
    generative_calls: int = 0
    embedding_calls: int = 0

    def check_generative(self, input_tokens: int, max_output_tokens: int, label: str) -> float:
        upper = input_tokens / 1_000_000 * INPUT_PRICE_PER_MTOK + max_output_tokens / 1_000_000 * OUTPUT_PRICE_PER_MTOK
        if self.spent_usd + upper > self.cap_usd:
            raise BudgetExceeded(
                f"{label}: spent={self.spent_usd:.6f} + upper_bound={upper:.6f} "
                f"would exceed cap={self.cap_usd}"
            )
        return upper

    def check_embedding(self, tokens: int, label: str) -> float:
        upper = tokens / 1_000_000 * EMBEDDING_PRICE_PER_MTOK
        if self.spent_usd + upper > self.cap_usd:
            raise BudgetExceeded(
                f"{label}: spent={self.spent_usd:.6f} + upper_bound={upper:.6f} "
                f"would exceed cap={self.cap_usd}"
            )
        return upper

    def record_generative(self, actual_usage_prompt: Any, actual_usage_completion: Any, upper_bound: float) -> float:
        if isinstance(actual_usage_prompt, int) and isinstance(actual_usage_completion, int):
            cost = (actual_usage_prompt / 1_000_000 * INPUT_PRICE_PER_MTOK
                    + actual_usage_completion / 1_000_000 * OUTPUT_PRICE_PER_MTOK)
        else:
            cost = upper_bound  # usage unknown -- book the conservative upper bound, never zero
        self.spent_usd += cost
        self.generative_calls += 1
        return cost

    def record_embedding(self, actual_tokens: Any, upper_bound: float) -> float:
        if isinstance(actual_tokens, int):
            cost = actual_tokens / 1_000_000 * EMBEDDING_PRICE_PER_MTOK
        else:
            cost = upper_bound
        self.spent_usd += cost
        self.embedding_calls += 1
        return cost


# --------------------------------------------------------------------------
# Ledger (persistent, append-only, new run directory -- never overwrites)
# --------------------------------------------------------------------------


@dataclass
class Ledger:
    run_id: str
    path: Path
    entries: list[dict] = field(default_factory=list)

    def add(self, **fields: Any) -> dict:
        entry = {"run_id": self.run_id, "timestamp": time.time(), **fields}
        self.entries.append(entry)
        self.path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=1), encoding="utf-8")
        return entry


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# A. Offline preflight checks (no model/DB call besides read-only queries)
# --------------------------------------------------------------------------


def preflight_model_and_temperature() -> dict:
    """1. Confirm naiv and lokalis use the same model/temperature as
    required (gpt-4o-mini, temperature=0) -- via naive_rag.models.get_chat_model,
    which both rag.py and local_search.py's main() call."""
    from naive_rag.config import get_settings

    settings = get_settings()
    result = {
        "chat_model_setting": settings.chat_model,
        "temperature_in_get_chat_model": 0,  # models.py:28, hardcoded, read not changed
        "naiv_uses": "models.get_chat_model() (rag.py:17,82)",
        "lokalis_uses": "models.get_chat_model() (local_search.py:1199, via local_search.main())",
        "globalis_uses": "global_search.MODEL = 'gpt-4o-mini', temperature=0 (global_search.py)",
        "router_uses": "search_router.MODEL = 'gpt-4o-mini', temperature=0 (search_router.py)",
    }
    if settings.chat_model != CHAT_MODEL:
        raise PreflightFailed(f"configured chat_model {settings.chat_model!r} != {CHAT_MODEL!r}")
    return result


def preflight_community_layer_isolation() -> dict:
    """3. Read-only Neo4j check: the local-search Cypher paths cannot reach
    :Community/:CommunityRun. Both a static (file-referenced) and a live
    empirical check."""
    from naive_rag.graph import query

    overlap = query(
        "MATCH (n) WHERE n:Extracted AND (n:Community OR n:CommunityRun) RETURN count(n) AS n"
    )[0]["n"]
    hop_hits = query(
        "MATCH (anchor:Extracted)-[hop]-(near:Extracted) "
        "WHERE hop.origin = 'extracted' AND (near:Community OR near:CommunityRun) "
        "RETURN count(*) AS n"
    )[0]["n"]
    edge_hits = query(
        "MATCH (source:Extracted)-[rel]->(target:Extracted) "
        "WHERE rel.origin = 'extracted' "
        "AND (source:Community OR target:Community OR source:CommunityRun OR target:CommunityRun) "
        "RETURN count(*) AS n"
    )[0]["n"]
    result = {
        "extracted_and_community_label_overlap": overlap,
        "neighborhood_query_pattern_hits_on_community": hop_hits,
        "edge_expansion_pattern_hits_on_community": edge_hits,
        "file_reference": "src/naive_rag/neo4j_local_search.py:33-81 "
                          "(NEIGHBORHOOD_QUERY, NODE_QUERY, MENTIONS_QUERY, CHUNK_TEXT_QUERY "
                          "-- all explicitly scoped to :Extracted/:Chunk labels)",
    }
    if overlap != 0 or hop_hits != 0 or edge_hits != 0:
        raise PreflightFailed(f"community layer IS reachable from local search: {result}")
    return result


def preflight_collection_absent() -> dict:
    """6. Read-only: the new collection must not already exist."""
    from naive_rag.vectorstore import _client

    client = _client(register_close=False)
    try:
        exists = client.collection_exists(NEW_COLLECTION)
        f1_exists = client.collection_exists("f1_naive_rag")
    finally:
        client.close()
    if exists:
        raise PreflightFailed(f"{NEW_COLLECTION} already exists -- refusing to overwrite")
    return {"new_collection_exists": exists, "f1_naive_rag_exists": f1_exists}


def preflight_vector_index_ready() -> dict:
    from naive_rag.local_search import configured_query, require_neo4j_settings, require_vector_index
    from naive_rag.config import get_settings

    settings = get_settings()
    require_neo4j_settings(settings)
    require_vector_index(configured_query)
    return {"vector_index": "ONLINE (require_vector_index passed)"}


def run_all_preflight() -> dict:
    return {
        "model_and_temperature": preflight_model_and_temperature(),
        "community_layer_isolation": preflight_community_layer_isolation(),
        "collection_absent": preflight_collection_absent(),
        "vector_index": preflight_vector_index_ready(),
    }


# --------------------------------------------------------------------------
# Embedding (raw openai client, exact usage, budget-gated)
# --------------------------------------------------------------------------


def embed_texts(
    texts: list[str], ids: list[str], budget: Budget, ledger: Ledger, *, label: str, openai_client=None,
) -> list[list[float]]:
    """One raw embeddings.create call. ids are local metadata only (never
    sent as content -- OpenAI embeddings input is the texts themselves)."""
    est_tokens = sum(estimate_tokens(t) for t in texts)
    upper = budget.check_embedding(est_tokens, label)
    started = time.monotonic()
    error = None
    actual_tokens: Any = "unknown"
    vectors: list[list[float]] = []
    try:
        if openai_client is None:
            from naive_rag.config import get_settings
            from openai import OpenAI

            openai_client = OpenAI(api_key=get_settings().openai_api_key)
        response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
        vectors = [item.embedding for item in response.data]
        actual_tokens = getattr(response.usage, "total_tokens", "unknown")
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.monotonic() - started
    cost = budget.record_embedding(actual_tokens, upper) if error is None else 0.0
    ledger.add(
        step="embedding", label=label, ids=ids, model=EMBEDDING_MODEL,
        estimated_tokens=est_tokens, actual_tokens=actual_tokens,
        cost_usd=cost, duration_seconds=round(elapsed, 3), error=error,
        status="error" if error else "success",
    )
    if error:
        raise RuntimeError(error)
    return vectors


# --------------------------------------------------------------------------
# C.1 Index the new naiv baseline collection
# --------------------------------------------------------------------------


def index_naive_baseline(budget: Budget, ledger: Ledger) -> dict:
    from qdrant_client.models import Distance, PointStruct, VectorParams

    from naive_rag.vectorstore import _client

    chunks_path = ROOT / "graph" / "corpus" / "chunks-section-1200-23" / "chunks.jsonl"
    rows = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    texts = [row["text"] for row in rows]
    chunk_ids = [row["chunk_id"] for row in rows]

    client = _client()
    client.create_collection(
        NEW_COLLECTION,
        vectors_config=VectorParams(size=EMBEDDING_DIMENSIONS, distance=Distance.COSINE),
    )

    total_points = 0
    for start in range(0, len(texts), INDEX_BATCH_SIZE):
        batch_texts = texts[start:start + INDEX_BATCH_SIZE]
        batch_ids = chunk_ids[start:start + INDEX_BATCH_SIZE]
        vectors = embed_texts(batch_texts, batch_ids, budget, ledger, label=f"index-batch-{start}")
        points = [
            PointStruct(
                id=start + i, vector=vector,
                payload={**rows[start + i], "chunk_id": batch_ids[i]},
            )
            for i, vector in enumerate(vectors)
        ]
        client.upsert(NEW_COLLECTION, points=points)
        total_points += len(points)

    count = client.count(NEW_COLLECTION, exact=True).count
    client.close()

    unique_ids = len(set(chunk_ids))
    result = {
        "collection": NEW_COLLECTION,
        "chunks_in_source": len(rows),
        "points_indexed": total_points,
        "qdrant_reported_count": count,
        "unique_chunk_ids": unique_ids,
    }
    if count != len(rows) or unique_ids != len(rows):
        raise RuntimeError(f"index mismatch: {result}")
    return result


# --------------------------------------------------------------------------
# C.2 Naiv search
# --------------------------------------------------------------------------


def run_naiv(
    question_id: str, question_text: str, budget: Budget, ledger: Ledger, *,
    qdrant_client=None, chat_client=None, openai_client=None, search_fn=None,
    prompt_variant: str = "baseline",
    actual_context_override: str | None = None,
) -> dict:
    """``qdrant_client``/``chat_client``/``openai_client``/``search_fn`` are
    injection points for offline testing (fakes); None builds the real
    ones, exactly as the approved production path does.

    Uses the raw qdrant_client ``query_points`` call directly (not
    ``QdrantVectorStore``) so a precomputed vector can be searched without
    requiring a langchain ``Embeddings`` object -- that object's sole job
    would be to embed the query, which has already been done above via the
    raw OpenAI client for exact usage accounting."""
    from types import SimpleNamespace

    from naive_rag.models import get_chat_model
    from naive_rag.rag import format_context, prompt_for, source_of
    from naive_rag.naive_search_logging import make_logged_chat_call

    prompt = prompt_for(prompt_variant)

    if actual_context_override is None:
        vector = embed_texts([question_text], [f"naiv-query-{question_id}"], budget, ledger,
                            label=f"naiv-query-{question_id}", openai_client=openai_client)[0]

        if search_fn is None:
            from naive_rag.vectorstore import _client as qdrant_client_factory

            client = qdrant_client or qdrant_client_factory()

            def search_fn(v):
                response = client.query_points(NEW_COLLECTION, query=v, limit=TOP_K, with_payload=True)
                return [
                    (SimpleNamespace(page_content=point.payload.get("text", ""), metadata=point.payload), point.score)
                    for point in response.points
                ]
        hits = search_fn(vector)
        sources = [source_of(d, i, sc) for i, (d, sc) in enumerate(hits, 1)]
        context = format_context(sources)
    else:
        sources = []
        context = actual_context_override
    messages = prompt.format_messages(context=context, question=question_text)

    input_text = "".join(m.content for m in messages)
    upper = budget.check_generative(estimate_tokens(input_text), GENERATIVE_MAX_TOKENS, f"naiv-{question_id}")

    chat_client = chat_client or get_chat_model(max_retries=0, max_tokens=GENERATIVE_MAX_TOKENS)
    chat_call = make_logged_chat_call(chat_client, log_dir=LOG_DIR, question_id=f"naiv-{question_id}")

    started = time.monotonic()
    error = None
    answer = None
    try:
        answer = chat_call(messages)
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    elapsed = time.monotonic() - started

    log_path = LOG_DIR / f"naive-log-naiv-{question_id}.json"
    saved = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    cost = budget.record_generative(saved.get("usage_prompt_tokens"), saved.get("usage_completion_tokens"), upper)

    entry = ledger.add(
        step="answer", mode="naiv", question_id=question_id, log_file=str(log_path),
        request_hash=saved.get("messages_sha256"), usage_prompt_tokens=saved.get("usage_prompt_tokens"),
        usage_completion_tokens=saved.get("usage_completion_tokens"), cost_usd=cost,
        duration_seconds=round(elapsed, 3), status="error" if error else "success", error=error,
    )
    result = {"question_id": question_id, "answer": answer, "sources": sources, "error": error, "ledger_entry": entry}
    if actual_context_override is not None:
        result["context_source"] = "saved_context_replay"
        result["actual_context"] = actual_context_override
    return result


# --------------------------------------------------------------------------
# C.3 Lokalis search
# --------------------------------------------------------------------------


def run_lokalis(
    question_id: str, question_text: str, budget: Budget, ledger: Ledger, *,
    chat_client=None, openai_client=None, query_fn=None,
) -> dict:
    """``chat_client``/``openai_client``/``query_fn`` are injection points
    for offline testing; None builds the real ones."""
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
        return embed_texts([q], [f"lokalis-query-{question_id}"], budget, ledger,
                          label=f"lokalis-query-{question_id}", openai_client=openai_client)[0]

    chat_client = chat_client or get_chat_model(max_retries=0, max_tokens=GENERATIVE_MAX_TOKENS)
    plain_answer_fn = make_logged_answer_fn(chat_client, log_dir=LOG_DIR, question_id=f"lokalis-{question_id}")

    def gated_answer_fn(prompt: str) -> str:
        upper = budget.check_generative(estimate_tokens(prompt), GENERATIVE_MAX_TOKENS, f"lokalis-{question_id}")
        answer = plain_answer_fn(prompt)
        log_path = LOG_DIR / f"local-log-lokalis-{question_id}.json"
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

    log_path = LOG_DIR / f"local-log-lokalis-{question_id}.json"
    saved = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    entry = ledger.add(
        step="answer", mode="lokalis", question_id=question_id,
        log_file=str(log_path) if log_path.exists() else None,
        request_hash=saved.get("messages_sha256"), model_called=found.model_called if found else None,
        refused=found.refused if found else None,
        duration_seconds=round(elapsed, 3), status="error" if error else "success", error=error,
    )
    return {
        "question_id": question_id,
        "answer": found.answer if found else None,
        "refused": found.refused if found else None,
        "model_called": found.model_called if found else None,
        "context_budget": found.context_budget if found else None,
        "error": error, "ledger_entry": entry,
    }


# --------------------------------------------------------------------------
# C.4 Globalis -- Q09-Q13 rerun, A branch only
# --------------------------------------------------------------------------


def run_globalis_rerun(
    budget: Budget, ledger: Ledger, *, client_factory=None, reports=None, questions=None,
) -> dict:
    """``client_factory``/``reports``/``questions`` are injection points for
    offline testing; None builds the real ones (the actual v3 report
    collection and the real OpenAI client)."""
    from naive_rag.config import get_settings
    from naive_rag.global_search import load_questions, load_reports, questions_by_label
    from naive_rag.global_search_logging import make_logged_call_fn

    settings = get_settings()
    if reports is None:
        collection_path = ROOT / "diagnostics" / "2026-11-10-phase3-measurement" / "results" / "week4-report-v3-collection.jsonl"
        reports = load_reports(collection_path, expected_run_id="week4-leiden-elokeszitett-6f05327d7d88ebf0")
    if questions is None:
        questions = questions_by_label(load_questions(ROOT / "questions.md"), "global")

    call_log_dir = LOG_DIR / "global-rerun"
    call_log_dir.mkdir(parents=True, exist_ok=True)

    def budget_checked_call_fn(system_prompt: str, user_message: str, max_tokens: int):
        upper = budget.check_generative(
            estimate_tokens(system_prompt) + estimate_tokens(user_message), max_tokens, "globalis-rerun",
        )
        response = raw_call_fn(system_prompt, user_message, max_tokens)
        budget.record_generative(response.usage_prompt_tokens, response.usage_completion_tokens, upper)
        return response

    raw_call_fn = make_logged_call_fn(settings, log_dir=call_log_dir, prefix="global-rerun", client_factory=client_factory)

    results = {}
    for question in questions:
        outcome = gs_run_question_a_only(question, reports, budget_checked_call_fn)
        results[question.question_id] = outcome
        entry = ledger.add(
            step="globalis-rerun", question_id=question.question_id,
            halted_reason=outcome.get("halted_reason"),
            map_calls=len(outcome.get("map_results", [])),
            status="error" if outcome.get("halted_reason") else "success",
        )
        if outcome.get("halted_reason"):
            break
    return results


def gs_run_question_a_only(question, reports, call_fn) -> dict:
    """Mirrors global_search.run_question but reduce-A only (no B branch),
    since this rerun is explicitly A-only (no comparison branch wanted)."""
    from naive_rag.global_search import (
        MapResult, deterministic_refusal_record, process_one_map, process_one_reduce,
        resolve_citation_chain, select_basis, RunPaths, load_ledger, save_ledger,
    )

    call_log_dir = LOG_DIR / "global-rerun-paths"
    call_log_dir.mkdir(parents=True, exist_ok=True)
    paths = RunPaths(call_log_dir)
    internal_ledger_path = call_log_dir / "ledger.json"
    internal_ledger = load_ledger(internal_ledger_path)

    map_results = []
    for report in reports:
        record = process_one_map(question, report, call_fn, paths, internal_ledger, internal_ledger_path)
        if record.get("error") or not record.get("validation", {}).get("valid_structure"):
            return {"question_id": question.question_id,
                    "halted_reason": f"map failed for {report.path}: {record}", "map_results": map_results}
        map_results.append(MapResult(
            path=report.path, question_id=question.question_id,
            partial_answer=record["partial_answer"], usefulness_score=record["usefulness_score"],
            cited_statement_ids=tuple(record["cited_statement_ids"]),
        ))

    basis_a = select_basis(map_results, include_zero=False)
    if basis_a:
        reduce_a = process_one_reduce(question, "A", basis_a, call_fn, paths, internal_ledger, internal_ledger_path)
    else:
        reduce_a = deterministic_refusal_record(question, "A")
    if reduce_a.get("error") or not reduce_a.get("validation", {}).get("valid_structure"):
        return {"question_id": question.question_id, "halted_reason": f"reduce A failed: {reduce_a}",
                "map_results": map_results, "reduce_a": reduce_a}

    reports_by_path = {r.path: r for r in reports}
    map_by_path = {r.path: r for r in map_results}
    reduce_a["citation_chain"] = resolve_citation_chain(
        reduce_a.get("cited_partial_answer_ids", []), map_by_path, reports_by_path
    )
    return {"question_id": question.question_id, "halted_reason": None, "map_results": map_results, "reduce_a": reduce_a}


# --------------------------------------------------------------------------
# C.5 Router
# --------------------------------------------------------------------------


def run_router_all(
    questions: list[tuple[str, str]], budget: Budget, ledger: Ledger, *, raw_caller=None,
) -> list[dict]:
    """``raw_caller`` is an injection point for offline testing; None
    builds the real one."""
    from naive_rag.config import get_settings
    from naive_rag.search_router import MAX_TOKENS as ROUTER_MAX_TOKENS, route_one

    settings = get_settings()

    if raw_caller is None:
        def raw_caller(messages, params):
            from naive_rag.call_logging import make_langchain_raw_caller
            from langchain_openai import ChatOpenAI

            def factory(p):
                return ChatOpenAI(
                    model=p.model, temperature=p.temperature, max_retries=p.max_retries,
                    max_tokens=p.max_tokens, api_key=settings.openai_api_key,
                    model_kwargs={"response_format": p.response_format},
                )
            return make_langchain_raw_caller(factory)(messages, params)

    records = []
    for question_id, question_text in questions:
        upper = budget.check_generative(
            estimate_tokens(question_text) + 400, ROUTER_MAX_TOKENS, f"router-{question_id}",
        )
        record = route_one(question_id, question_text, raw_caller, log_path=LOG_DIR / f"router-log-{question_id}.json")
        budget.record_generative(record.get("usage_prompt_tokens"), record.get("usage_completion_tokens"), upper)
        ledger.add(step="router", question_id=question_id, mode=record.get("mode"),
                  reasoning=record.get("reasoning"), status="error" if record.get("error") else "success",
                  error=record.get("error"))
        records.append(record)
        if record.get("error"):
            break
    return records


if __name__ == "__main__":
    print("This module is meant to be driven by its test suite first, then "
          "invoked explicitly for the approved real run -- see the Phase 5 report.")
