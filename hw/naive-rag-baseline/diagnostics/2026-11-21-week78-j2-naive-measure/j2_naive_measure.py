"""J2 naiv measurement entry. Reuses week5-b's case machine and run_naiv.

Only retrieval changes: ``retrieve_naive_hits(..., j2_enabled=True)``.
Generation, prompt, model, judges, and metrics stay on the existing path.
Pilot (Q04) is the default. FULL is opt-in. Neither writes week5-b files.

    python j2_naive_measure.py run
    python j2_naive_measure.py run --full
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import j2_measure_bootstrap  # noqa: F401
import measure as week5measure
import state_store
from golden_set import (
    GoldenQuestion, golden_set_sha256, load_golden_set, verify_corpus_matches_disk,
    verify_single_corpus_snapshot,
)
from naive_rag.naive_year_rerank import (
    CANDIDATE_K,
    FINAL_K,
    distinct_question_years,
    retrieve_naive_hits,
)

HERE = Path(__file__).resolve().parent
MODE = "naiv"
PILOT_QUESTION_ID = "Q04"


class J2MeasureHalt(RuntimeError):
    """Raised before a paid call when the run identity or the question
    selection does not match this entry point."""


def paths_for(run_kind: str) -> dict[str, Path]:
    root = HERE / "results" / run_kind
    return {
        "results": root,
        "cases": root / "cases",
        "state": HERE / "state" / f"j2-naive-state-{run_kind}.json",
        "cost_ledger": root / "j2-naive-cost-ledger.json",
        "request_log": root / "j2-naive-request-log.json",
        "logs": HERE / "logs" / run_kind,
        "judge_logs": HERE / "logs" / run_kind / "judges",
        "report": root / f"j2-naive-report-{run_kind}.md",
        "results_jsonl": root / "results.jsonl",
    }


def effective_config() -> dict[str, Any]:
    """Naive baseline settings, read from the week5 measurement config,
    plus the J2 retrieval settings that make this run a different identity."""
    base = week5measure.effective_config()
    return {
        "chat_model": base["chat_model"],
        "temperature": base["temperature"],
        "naiv_top_k": base["naiv_top_k"],
        "naiv_collection": base["naiv_collection"],
        "correctness_judge_prompt_version": base["correctness_judge_prompt_version"],
        "faithfulness_judge_prompt_version": base["faithfulness_judge_prompt_version"],
        "shared_cost_cap_usd": base["shared_cost_cap_usd"],
        "j2_enabled": True,
        "j2_candidate_k": CANDIDATE_K,
        "j2_final_k": FINAL_K,
        "j2_retrieval": "naive_rag.naive_year_rerank.retrieve_naive_hits",
    }


def build_run_signature(run_kind: str, golden_path: Path) -> state_store.RunSignature:
    return state_store.RunSignature(
        run_kind=run_kind,
        config_sha256=state_store.config_hash(effective_config()),
        golden_set_sha256=golden_set_sha256(golden_path),
    )


def select_questions(questions: list[GoldenQuestion], run_kind: str) -> list[GoldenQuestion]:
    if run_kind == "pilot":
        chosen = [question for question in questions if question.id == PILOT_QUESTION_ID]
        if len(chosen) != 1:
            raise J2MeasureHalt(f"pilot requires exactly one {PILOT_QUESTION_ID} in the golden set")
        return chosen
    if run_kind == "full":
        return list(questions)
    raise J2MeasureHalt(f"unknown run kind {run_kind!r}")


def _year_match(question: str, text: str) -> bool:
    years = distinct_question_years(question)
    if len(years) != 1:
        return False
    year = next(iter(years))
    return re.compile(rf"(?<!\d){re.escape(year)}(?!\d)").search(text or "") is not None


def _candidate_row(hit, rank: int, question: str) -> dict[str, Any]:
    document, score = hit
    metadata = getattr(document, "metadata", None) or {}
    text = getattr(document, "page_content", "") or ""
    return {
        "chunk_id": metadata.get("chunk_id"),
        "text": text,
        "score": score,
        "rank": rank,
        "year_match": _year_match(question, text),
    }


def build_j2_search(
    question_text: str, query_points: Callable[[list, int], list], *, j2_enabled: bool = True,
):
    """``query_points(vector, limit)`` is the single vector search.

    The returned ``search_fn`` is what ``run_phase5.run_naiv`` calls after
    it has embedded the question. Retrieval itself is only
    ``retrieve_naive_hits``. ``j2_enabled=False`` keeps the original top-4.
    """
    trace: dict[str, Any] = {}

    def search_fn(vector):
        def search(limit: int):
            points = list(query_points(vector, limit))
            hits = []
            for point in points:
                payload = dict(getattr(point, "payload", None) or {})
                hits.append((
                    SimpleNamespace(page_content=payload.get("text", ""), metadata=payload),
                    point.score,
                ))
            trace["search_limit"] = limit
            trace["candidates"] = [
                _candidate_row(hit, rank, question_text) for rank, hit in enumerate(hits, 1)
            ]
            return hits

        final = retrieve_naive_hits(question_text, search, j2_enabled=j2_enabled)
        trace["j2_enabled"] = j2_enabled
        trace["final_order"] = [
            (getattr(hit[0], "metadata", None) or {}).get("chunk_id") for hit in final
        ]
        return final

    return search_fn, trace


def build_j2_naiv_fn(
    budget, ledger, run_phase: str, *, log_dir: Path, query_points: Callable[[list, int], list],
    j2_enabled: bool = True, prompt_variant: str = "baseline",
    actual_context_override: str | None = None,
):
    """One naiv case: existing ``run_naiv_capture``, J2 search injected."""
    import generation_runner as gr
    import run_phase5 as phase5

    def naiv_fn(question: GoldenQuestion) -> dict:
        search_fn, trace = build_j2_search(
            question.question, query_points, j2_enabled=j2_enabled,
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        previous = phase5.LOG_DIR
        phase5.LOG_DIR = log_dir
        try:
            record = gr.run_naiv_capture(
                question.id, question.question, budget, ledger,
                run_phase=run_phase, search_fn=search_fn,
                prompt_variant=prompt_variant,
                actual_context_override=actual_context_override,
            )
        finally:
            phase5.LOG_DIR = previous
        record["j2_retrieval"] = {
            "j2_enabled": j2_enabled,
            "candidates": trace.get("candidates", []),
            "final_order": trace.get("final_order", []),
            "actual_chunk_ids": list(record.get("actual_chunk_ids") or []),
        }
        return record

    return naiv_fn


def real_query_points(client):
    import run_phase5 as phase5

    def query_points(vector, limit: int):
        response = client.query_points(
            phase5.NEW_COLLECTION, query=vector, limit=limit, with_payload=True,
        )
        return response.points

    return query_points


def run_j2_cases(questions, store, ctx) -> list[dict]:
    rows = []
    for question in questions:
        case = store.get_or_create(question.id, MODE)
        while case.next_step() is not None:
            week5measure.process_case(question, MODE, case, ctx)
            store.save()
        rows.append(week5measure._load_case_row(ctx, question.id, MODE))
    return rows


def execute_j2(
    run_kind: str,
    questions: list[GoldenQuestion],
    golden_path: Path,
    paths: dict[str, Path],
    *,
    gen_fn,
    budget,
    ledger,
    correctness_call_fn_factory,
    faithfulness_call_fn_factory,
    langfuse_sync_fn=None,
    signature: state_store.RunSignature | None = None,
) -> list[dict]:
    signature = signature or build_run_signature(run_kind, golden_path)
    store = state_store.StateStore.load_or_create(paths["state"], signature)
    ctx = week5measure.CaseContext(
        run_phase=run_kind, budget=budget, ledger=ledger,
        gen_fns={MODE: gen_fn},
        correctness_call_fn_factory=correctness_call_fn_factory,
        faithfulness_call_fn_factory=faithfulness_call_fn_factory,
        langfuse_sync_fn=langfuse_sync_fn,
        case_store_dir=paths["cases"],
    )
    rows = run_j2_cases(questions, store, ctx)
    import report as report_mod
    report_mod.write_results(paths["results_jsonl"], rows)
    paths["report"].write_text(
        report_mod.build_report_markdown(rows, run_phase=run_kind), encoding="utf-8",
    )
    return rows


def run_j2(
    run_kind: str, *, golden_path: Path, sync_langfuse: bool, prompt_variant: str = "baseline",
    actual_context_override: str | None = None,
) -> dict:
    from naive_rag.rag import prompt_for
    prompt_for(prompt_variant)
    if sync_langfuse:
        week5measure.load_project_env()
        week5measure.ensure_langfuse_configured()

    all_questions = load_golden_set(golden_path)
    corpus_sha256 = verify_single_corpus_snapshot(all_questions)
    chunks_path = week5measure.PROJECT_ROOT / all_questions[0].corpus_chunks_file
    verify_corpus_matches_disk(corpus_sha256, chunks_path)
    questions = select_questions(list(all_questions), run_kind)
    paths = paths_for(run_kind)

    import cost_guard
    import run_phase5 as phase5
    budget = cost_guard.SharedCostLedger.load(paths["cost_ledger"])
    ledger = phase5.Ledger(
        run_id=f"j2-naive-{run_kind}", path=paths["request_log"],
    )
    with week5measure.shared_qdrant_client() as client:
        gen_fn = build_j2_naiv_fn(
            budget, ledger, run_kind, log_dir=paths["logs"],
            query_points=real_query_points(client), prompt_variant=prompt_variant,
            actual_context_override=actual_context_override,
        )
        correctness = week5measure.build_real_judge_call_fn_factory(
            budget, ledger, f"correctness-j2-{run_kind}", paths["judge_logs"],
        )
        faithfulness = week5measure.build_real_judge_call_fn_factory(
            budget, ledger, f"faithfulness-j2-{run_kind}", paths["judge_logs"],
        )
        langfuse_sync_fn = (
            week5measure.build_real_langfuse_sync_fn(
                run_kind, tuple(question.id for question in questions), paths["cases"],
            )
            if sync_langfuse else None
        )
        rows = execute_j2(
            run_kind, questions, golden_path, paths,
            gen_fn=gen_fn, budget=budget, ledger=ledger,
            correctness_call_fn_factory=correctness,
            faithfulness_call_fn_factory=faithfulness,
            langfuse_sync_fn=langfuse_sync_fn,
        )
    return {"run_kind": run_kind, "case_count": len(rows), "results": str(paths["results"])}


PAIR_VARIANTS = ("baseline", "j2")
PAIR_LEDGER = HERE / "results" / "pair-shared" / "j2-pair-cost-ledger.json"
PAIR_FINGERPRINT = HERE / "results" / "pair-shared" / "index-fingerprint.json"
CHUNKS_FILE = week5measure.PROJECT_ROOT / "graph" / "corpus" / "chunks-section-1200-23" / "chunks.jsonl"


def pair_paths(variant: str, run_id: str | None = None) -> dict[str, Path]:
    if run_id is None:
        root = HERE / "results" / f"pair-{variant}-full"
        state = HERE / "state" / f"j2-pair-state-{variant}-full.json"
        logs = HERE / "logs" / f"pair-{variant}-full"
        request_log = root / "j2-pair-request-log.json"
    else:
        root = HERE / "results" / run_id
        state = HERE / "state" / f"{run_id}.json"
        logs = HERE / "logs" / run_id
        request_log = root / "request-log.json"
    return {
        "results": root,
        "cases": root / "cases",
        "state": state,
        "request_log": request_log,
        "logs": logs,
        "judge_logs": logs / "judges",
        "report": root / "report.md",
        "results_jsonl": root / "results.jsonl",
        "cost_ledger": PAIR_LEDGER,
        "fingerprint": PAIR_FINGERPRINT,
    }


def refuse_existing_run(paths: dict[str, Path]) -> None:
    occupied = [key for key in ("results", "state", "logs") if paths[key].exists()]
    if occupied:
        listed = ", ".join(f"{key}={paths[key]}" for key in occupied)
        raise J2MeasureHalt(f"run target already exists; not overwriting or resuming: {listed}")


def ensure_pair_output_dirs(paths: dict[str, Path]) -> None:
    """Create this variant's output directories before the request log or any paid call."""
    for key in ("results", "cases", "logs", "judge_logs"):
        paths[key].mkdir(parents=True, exist_ok=True)
    for key in ("state", "request_log", "report", "results_jsonl", "cost_ledger", "fingerprint"):
        paths[key].parent.mkdir(parents=True, exist_ok=True)


def shared_pair_config(index_sha256: str) -> dict[str, Any]:
    """Settings shared by the fresh baseline and J2 runs. The switch is not here."""
    import run_phase5 as phase5
    from naive_rag.rag import PROMPT
    import correctness_judge
    import faithfulness_judge

    base = week5measure.effective_config()
    system = PROMPT.messages[0].prompt.template
    return {
        "chat_model": base["chat_model"],
        "temperature": base["temperature"],
        "embedding_model": phase5.EMBEDDING_MODEL,
        "naiv_collection": phase5.NEW_COLLECTION,
        "final_k": FINAL_K,
        "candidate_k": CANDIDATE_K,
        "correctness_judge_prompt_version": correctness_judge.PROMPT_VERSION,
        "faithfulness_judge_prompt_version": faithfulness_judge.PROMPT_VERSION,
        "generation_prompt_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
        "correctness_prompt_sha256": hashlib.sha256(correctness_judge.SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "faithfulness_prompt_sha256": hashlib.sha256(faithfulness_judge.SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        "index_sha256": index_sha256,
        "shared_cost_cap_usd": cost_cap_usd(),
    }


def pair_config(
    variant: str, index_sha256: str, prompt_variant: str = "baseline", run_id: str | None = None,
) -> dict[str, Any]:
    if variant not in PAIR_VARIANTS:
        raise J2MeasureHalt(f"unknown pair variant {variant!r}")
    from naive_rag.rag import prompt_for

    config = shared_pair_config(index_sha256)
    system = prompt_for(prompt_variant).messages[0].prompt.template
    config["prompt_variant"] = prompt_variant
    config["generation_prompt_sha256"] = hashlib.sha256(system.encode("utf-8")).hexdigest()
    config["variant"] = variant
    config["j2_enabled"] = variant == "j2"
    if run_id is not None:
        config["run_id"] = run_id
    return config


def cost_cap_usd() -> float:
    import cost_guard
    return cost_guard.CAP_USD_PER_WEEK


class RunTaggedBudget:
    """Prefixes the existing ledger label with the run id. The cap stays shared."""

    def __init__(self, inner, run_id: str):
        self._inner = inner
        self._run_id = run_id

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def check_generative(self, input_tokens: int, max_output_tokens: int, label: str) -> float:
        return self._inner.check_generative(input_tokens, max_output_tokens, f"{self._run_id}|{label}")

    def check_embedding(self, tokens: int, label: str) -> float:
        return self._inner.check_embedding(tokens, f"{self._run_id}|{label}")


def _vector_params(info) -> tuple[int, str]:
    vectors = info.config.params.vectors
    if isinstance(vectors, dict):
        vectors = next(iter(vectors.values()))
    distance = getattr(vectors.distance, "name", None) or str(vectors.distance)
    return int(vectors.size), str(distance)


def read_chunks(path: Path = CHUNKS_FILE) -> tuple[str, dict[str, str]]:
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if len(rows) != 1651:
        raise J2MeasureHalt(f"{path} has {len(rows)} chunks, expected 1651")
    by_id = {}
    for row in rows:
        chunk_id = row["chunk_id"]
        if chunk_id in by_id:
            raise J2MeasureHalt(f"duplicate chunk_id in {path}: {chunk_id}")
        by_id[chunk_id] = row["text"]
    return hashlib.sha256(raw).hexdigest(), by_id


def read_live_index(client) -> dict[str, Any]:
    """Read-only collection metadata and payloads. No vector search and no upsert."""
    import run_phase5 as phase5

    name = phase5.NEW_COLLECTION
    if not client.collection_exists(name):
        raise J2MeasureHalt(f"collection missing: {name}")
    size, distance = _vector_params(client.get_collection(name))
    if size != phase5.EMBEDDING_DIMENSIONS or distance.upper() != "COSINE":
        raise J2MeasureHalt(
            f"{name} vector_size={size} distance={distance}, "
            f"expected {phase5.EMBEDDING_DIMENSIONS} COSINE"
        )
    payloads: dict[str, str] = {}
    offset = None
    while True:
        batch, offset = client.scroll(
            collection_name=name, limit=256, offset=offset,
            with_payload=True, with_vectors=False,
        )
        for point in batch:
            payload = point.payload or {}
            chunk_id = payload.get("chunk_id")
            if chunk_id in payloads:
                raise J2MeasureHalt(f"duplicate chunk_id in {name}: {chunk_id}")
            payloads[chunk_id] = payload.get("text", "")
        if offset is None:
            break
    file_sha, expected = read_chunks()
    if set(payloads) != set(expected):
        missing = sorted(set(expected) - set(payloads))[:5]
        extra = sorted(set(payloads) - set(expected))[:5]
        raise J2MeasureHalt(
            f"{name} chunk_id set differs from {CHUNKS_FILE.name}: "
            f"missing={missing}, extra={extra}"
        )
    mismatched = [chunk_id for chunk_id, text in expected.items() if payloads[chunk_id] != text]
    if mismatched:
        raise J2MeasureHalt(f"{name} text differs for {mismatched[0]} ({len(mismatched)} chunks)")
    body = "\n".join(f"{chunk_id}\t{expected[chunk_id]}" for chunk_id in sorted(expected))
    return {
        "collection": name,
        "vector_size": size,
        "distance": distance,
        "point_count": len(payloads),
        "chunks_sha256": file_sha,
        "payload_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def assert_same_index(live: dict[str, Any], recorded: dict[str, Any]) -> None:
    if live != recorded:
        raise J2MeasureHalt(f"index fingerprint mismatch: live={live} recorded={recorded}")


def load_recorded_index(path: Path = PAIR_FINGERPRINT) -> dict[str, Any]:
    if not path.exists():
        raise J2MeasureHalt(f"index fingerprint missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))["index"]


def pair_signature(
    variant: str, golden_path: Path, index_sha256: str,
    prompt_variant: str = "baseline", run_id: str | None = None,
) -> state_store.RunSignature:
    run_kind = f"pair-{variant}-full" if run_id is None else f"pair-{variant}-{run_id}"
    return state_store.RunSignature(
        run_kind=run_kind,
        config_sha256=state_store.config_hash(
            pair_config(variant, index_sha256, prompt_variant, run_id),
        ),
        golden_set_sha256=golden_set_sha256(golden_path),
    )


def run_pair(
    variant: str, *, run_id: str, golden_path: Path, sync_langfuse: bool, index_reader=None,
    prompt_variant: str = "baseline",
    actual_context_override: str | None = None,
) -> dict:
    import cost_guard
    import run_phase5 as phase5

    from naive_rag.rag import prompt_for
    if actual_context_override is not None:
        raise J2MeasureHalt("FULL replay is forbidden; actual_context_override must be None")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", run_id):
        raise J2MeasureHalt(f"invalid run id {run_id!r}")
    prompt_for(prompt_variant)
    paths = pair_paths(variant, run_id)
    refuse_existing_run(paths)
    recorded = load_recorded_index(paths["fingerprint"])
    if index_reader is None:
        with week5measure.shared_qdrant_client() as client:
            live = read_live_index(client)
    else:
        live = index_reader()
    assert_same_index(live, recorded)
    all_questions = load_golden_set(golden_path)
    corpus_sha256 = verify_single_corpus_snapshot(all_questions)
    if corpus_sha256 != recorded["chunks_sha256"]:
        raise J2MeasureHalt(
            f"golden corpus sha256 {corpus_sha256} != index fingerprint {recorded['chunks_sha256']}"
        )
    chunks_path = week5measure.PROJECT_ROOT / all_questions[0].corpus_chunks_file
    verify_corpus_matches_disk(corpus_sha256, chunks_path)
    questions = list(all_questions)
    signature = pair_signature(
        variant, golden_path, recorded["payload_sha256"], prompt_variant, run_id,
    )
    ensure_pair_output_dirs(paths)
    if sync_langfuse:
        week5measure.load_project_env()
        week5measure.ensure_langfuse_configured()
    inner = cost_guard.SharedCostLedger.load(paths["cost_ledger"], cap_usd=cost_cap_usd())
    if inner.cap_usd != cost_cap_usd():
        raise J2MeasureHalt(f"shared ledger cap {inner.cap_usd} != {cost_cap_usd()}")
    budget = RunTaggedBudget(inner, run_id)
    request_ledger = phase5.Ledger(run_id=run_id, path=paths["request_log"])
    j2_enabled = variant == "j2"
    with week5measure.shared_qdrant_client() as client:
        gen_fn = build_j2_naiv_fn(
            budget, request_ledger, run_id, log_dir=paths["logs"],
            query_points=real_query_points(client), j2_enabled=j2_enabled,
            prompt_variant=prompt_variant,
            actual_context_override=actual_context_override,
        )
        rows = execute_j2(
            run_id, questions, golden_path, paths,
            gen_fn=gen_fn, budget=budget, ledger=request_ledger, signature=signature,
            correctness_call_fn_factory=week5measure.build_real_judge_call_fn_factory(
                budget, request_ledger, f"correctness-{run_id}", paths["judge_logs"],
            ),
            faithfulness_call_fn_factory=week5measure.build_real_judge_call_fn_factory(
                budget, request_ledger, f"faithfulness-{run_id}", paths["judge_logs"],
            ),
            langfuse_sync_fn=(
                week5measure.build_real_langfuse_sync_fn(
                    run_id, tuple(question.id for question in questions), paths["cases"],
                )
                if sync_langfuse else None
            ),
        )
    return {"variant": variant, "case_count": len(rows), "results": str(paths["results"])}


def write_verified_fingerprint() -> dict[str, Any]:
    """Read-only check, then store the shared fingerprint. Does not index."""
    with week5measure.shared_qdrant_client() as client:
        live = read_live_index(client)
    if PAIR_FINGERPRINT.exists():
        assert_same_index(live, load_recorded_index(PAIR_FINGERPRINT))
        return live
    PAIR_FINGERPRINT.parent.mkdir(parents=True, exist_ok=True)
    PAIR_FINGERPRINT.write_text(
        json.dumps({"index": live}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
    )
    return live


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="j2_naive_measure.py")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Q04 pilot, or a fresh pair FULL with --variant")
    run_p.add_argument("--full", action="store_true")
    run_p.add_argument("--variant", choices=list(PAIR_VARIANTS))
    run_p.add_argument("--golden", type=Path, default=week5measure.DEFAULT_GOLDEN_PATH)
    run_p.add_argument("--no-langfuse", action="store_true")
    run_p.add_argument("--prompt-variant", default="baseline", choices=["baseline", "j3"])
    run_p.add_argument("--run-id", default=None)
    sub.add_parser("check-index", help="Read-only collection check; writes the shared fingerprint")
    args = parser.parse_args(argv)
    try:
        if args.command == "check-index":
            outcome = write_verified_fingerprint()
        elif args.command == "run" and args.variant:
            if not args.full:
                raise J2MeasureHalt("--variant requires --full")
            if not args.run_id:
                raise J2MeasureHalt("FULL requires --run-id")
            outcome = run_pair(
                args.variant, run_id=args.run_id, golden_path=args.golden,
                sync_langfuse=not args.no_langfuse, prompt_variant=args.prompt_variant,
            )
        elif args.command == "run":
            if args.full:
                raise J2MeasureHalt("FULL requires --variant baseline or --variant j2")
            outcome = run_j2(
                "pilot", golden_path=args.golden, sync_langfuse=not args.no_langfuse,
                prompt_variant=args.prompt_variant,
            )
        else:
            return 1
    except week5measure.LangfuseConfigError as exc:
        print(f"LANGFUSE CONFIG ERROR (no paid call was made): {exc}", file=sys.stderr)
        return 2
    except (week5measure.MeasurementHalted, J2MeasureHalt, state_store.StateError) as exc:
        print(f"HALTED: {exc}", file=sys.stderr)
        return 1
    print(outcome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
