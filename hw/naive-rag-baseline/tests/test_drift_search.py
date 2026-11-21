"""Offline, model-free and database-free checks for the limited DRIFT
adaptation (`naive_rag.drift_search`). No real API call, no embedding
call, no database connection anywhere in this file -- every model and
embedding call is a fake injected by the test.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag import drift_search as ds
from naive_rag.entity_index import EntityIndex, IndexedEntity
from naive_rag.global_search import CommunityReport, ReportStatement
from naive_rag.graph_merge import DomainEdge, DomainGraph, DomainNode

DRIVER_A = "Driver:a"
DRIVER_B = "Driver:b"


def _graph() -> DomainGraph:
    nodes = (
        DomainNode(node_id="n1", entity_key=DRIVER_A, label="Driver",
                   name="Driver A", description="Driver A description.",
                   source_chunk_ids=("c1",)),
        DomainNode(node_id="n2", entity_key=DRIVER_B, label="Driver",
                   name="Driver B", description="Driver B description.",
                   source_chunk_ids=("c2",)),
    )
    edges = (
        DomainEdge(edge_id="e1", rel_key="a|b", rel_type="RACED_WITH",
                   source_id=DRIVER_A, target_id=DRIVER_B,
                   from_year=2007, to_year=2007, role=None,
                   description="Raced together in 2007.",
                   source_chunk_ids=("c1", "c2")),
    )
    return DomainGraph(kind="merged", nodes=nodes, edges=edges)


def _local_index() -> EntityIndex:
    return EntityIndex((
        IndexedEntity(entity_key=DRIVER_A, label="Driver", name="Driver A",
                      description="Driver A description.", text="Driver A\nDriver A description.",
                      vector=(1.0, 0.0)),
        IndexedEntity(entity_key=DRIVER_B, label="Driver", name="Driver B",
                      description="Driver B description.", text="Driver B\nDriver B description.",
                      vector=(0.0, 1.0)),
    ))


_CHUNK_TEXTS = {
    "c1": "Driver A raced for Team X in 2007.",
    "c2": "Driver B raced for Team Y in 2007.",
}


def _report(path: str, community_id: str, summary: str, statements: tuple[str, ...]) -> CommunityReport:
    return CommunityReport(
        path=path, community_id=community_id, run_id="test-run", reporting_level=0,
        summary=summary,
        statements=tuple(
            ReportStatement(statement_id=f"{path}#{i}", text=text, evidence_ids=(), candidate_source_chunk_ids=())
            for i, text in enumerate(statements, start=1)
        ),
    )


def _reports() -> tuple[CommunityReport, ...]:
    return (
        _report("1", "c1", "Community 1 summary.", ("Statement one.",)),
        _report("2", "c2", "Community 2 summary.", ("Statement two.",)),
        _report("3", "c3", "Community 3 summary.", ("Statement three.",)),
        _report("4", "c4", "Community 4 summary.", ("Statement four.",)),
    )


def _report_index() -> ds.ReportIndex:
    # r1 matches the test query vector exactly, r2 is close, r3/r4 are
    # orthogonal and tie on score -- ties break by path, so top-3 is
    # deterministic: 1, 2, 3.
    vectors = {
        "1": (1.0, 0.0, 0.0, 0.0),
        "2": (0.9, 0.1, 0.0, 0.0),
        "3": (0.0, 1.0, 0.0, 0.0),
        "4": (0.0, 0.0, 1.0, 0.0),
    }
    indexed = tuple(
        ds.IndexedReport(path=path, community_id=f"c{path}",
                         text=ds.report_index_text(report), vector=vector)
        for report, (path, vector) in zip(_reports(), vectors.items())
    )
    return ds.ReportIndex(indexed)


class FakeCostGuard:
    """Records check/record calls in order so tests can assert that a
    check always happens before the matching call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def check_generative(self, input_tokens, max_output_tokens, label):
        self.calls.append(("check_generative", label))
        return 0.001

    def check_embedding(self, tokens, label):
        self.calls.append(("check_embedding", label))
        return 0.0002

    def record_generative(self, actual_prompt, actual_completion, upper):
        self.calls.append(("record_generative", actual_prompt, actual_completion))
        return upper if not isinstance(actual_prompt, int) else 0.0009

    def record_embedding(self, actual_tokens, upper):
        self.calls.append(("record_embedding", actual_tokens))
        return upper if not isinstance(actual_tokens, int) else 0.0001


def _primer_response(initial_answer: str, subquestions: list[str]) -> str:
    return json.dumps({"initial_answer": initial_answer, "subquestions": subquestions})


class _Caller:
    """Deterministic fake call_chat/call_embed pair. `chat_by_label` maps a
    label prefix to a plain response string; `embed_by_label` maps a label
    to the vector to return for any text."""

    def __init__(self, chat_by_label: dict[str, str], embed_by_label: dict[str, tuple[float, ...]]):
        self.chat_by_label = chat_by_label
        self.embed_by_label = embed_by_label
        self.call_log: list[tuple] = []

    def call_chat(self, prompt: str, label: str, max_output_tokens: int):
        self.call_log.append(("chat", label))
        if label not in self.chat_by_label:
            raise AssertionError(f"unexpected chat label {label!r}")
        return self.chat_by_label[label], {"prompt_tokens": 10, "completion_tokens": 5}

    def call_embed(self, texts: list[str], label: str):
        self.call_log.append(("embed", label))
        if label not in self.embed_by_label:
            raise AssertionError(f"unexpected embed label {label!r}")
        vector = self.embed_by_label[label]
        return [list(vector) for _ in texts], 7


class DriftSearchOrchestrationTests(unittest.TestCase):
    def _run(self, *, chat_by_label, embed_by_label, **kwargs):
        caller = _Caller(chat_by_label, embed_by_label)
        guard = FakeCostGuard()
        result = ds.drift_search(
            "Who raced with whom in 2007?",
            report_index=_report_index(), reports=_reports(),
            graph=_graph(), local_index=_local_index(),
            call_chat=caller.call_chat, call_embed=caller.call_embed,
            cost_guard=guard, chunk_texts=_CHUNK_TEXTS,
            local_budget={"model_window": 8192, "answer_reserve": 1024, "graph_share": 0.5},
            **kwargs,
        )
        return result, caller, guard

    def test_top_3_reports_are_selected_deterministically(self):
        result, _caller, _guard = self._run(
            chat_by_label={
                "drift-primer": _primer_response("initial", ["about a"]),
                "drift-subq-gen-1": "Driver A fact.",
                "drift-synthesis": "final answer",
            },
            embed_by_label={
                "drift-report-embed": (1.0, 0.0, 0.0, 0.0),
                "drift-subq-embed-1": (1.0, 0.0),
            },
        )
        self.assertEqual(result.report_ids, ("1", "2", "3"))
        self.assertEqual(result.status, "ok")

    def test_at_most_two_subquestions_each_trigger_one_local_search(self):
        result, caller, guard = self._run(
            chat_by_label={
                "drift-primer": _primer_response("initial", ["about a", "about b"]),
                "drift-subq-gen-1": "Driver A fact.",
                "drift-subq-gen-2": "Driver B fact.",
                "drift-synthesis": "final combining both",
            },
            embed_by_label={
                "drift-report-embed": (1.0, 0.0, 0.0, 0.0),
                "drift-subq-embed-1": (1.0, 0.0),
                "drift-subq-embed-2": (0.0, 1.0),
            },
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.subquestion_results), 2)
        self.assertEqual(result.subquestion_results[0].local_answer.answer, "Driver A fact.")
        self.assertEqual(result.subquestion_results[1].local_answer.answer, "Driver B fact.")
        self.assertTrue(result.subquestion_results[0].local_answer.model_called)
        self.assertEqual(result.answer, "final combining both")
        self.assertLessEqual(result.generative_call_count, 4)
        self.assertLessEqual(result.embedding_call_count, 3)
        self.assertEqual(result.generative_call_count, 4)  # primer + 2 local + synthesis
        self.assertEqual(result.embedding_call_count, 3)  # report + 2 subquestion

    def test_empty_subquestion_list_is_now_a_clear_invalid_status(self):
        """PRIMER_PROMPT_VERSION v2 (tightened after the first real smoke
        run, see docs/week6-atadas.md's C-phase diagnosis): an empty
        "subquestions" list used to be accepted and silently produced a
        report-only answer -- this is deliberately no longer allowed."""
        result, _caller, _guard = self._run(
            chat_by_label={
                "drift-primer": _primer_response("only the primer matters", []),
            },
            embed_by_label={"drift-report-embed": (1.0, 0.0, 0.0, 0.0)},
        )
        self.assertEqual(result.status, "primer_invalid")
        self.assertIn("fewer than", result.error)
        self.assertEqual(result.subquestion_results, ())
        self.assertEqual(result.generative_call_count, 1)  # primer only, no synthesis call wasted

    def test_more_than_two_subquestions_is_a_clear_invalid_status(self):
        result, _caller, _guard = self._run(
            chat_by_label={
                "drift-primer": _primer_response("x", ["q1", "q2", "q3"]),
            },
            embed_by_label={"drift-report-embed": (1.0, 0.0, 0.0, 0.0)},
        )
        self.assertEqual(result.status, "primer_invalid")
        self.assertIn("subquestions has more than", result.error)
        self.assertEqual(result.subquestion_results, ())

    def test_invalid_primer_json_is_a_clear_status_not_an_exception(self):
        result, _caller, _guard = self._run(
            chat_by_label={"drift-primer": "not json at all"},
            embed_by_label={"drift-report-embed": (1.0, 0.0, 0.0, 0.0)},
        )
        self.assertEqual(result.status, "primer_invalid")
        self.assertIn("invalid JSON", result.error)

    def test_primer_call_exception_is_reported_not_raised(self):
        caller = _Caller({}, {"drift-report-embed": (1.0, 0.0, 0.0, 0.0)})

        def failing_call_chat(prompt, label, max_output_tokens):
            raise RuntimeError("simulated primer failure")

        guard = FakeCostGuard()
        result = ds.drift_search(
            "q?", report_index=_report_index(), reports=_reports(),
            graph=_graph(), local_index=_local_index(),
            call_chat=failing_call_chat, call_embed=caller.call_embed,
            cost_guard=guard,
        )
        self.assertEqual(result.status, "primer_error")
        self.assertIn("simulated primer failure", result.error)

    def test_cost_guard_is_checked_before_every_paid_call(self):
        _result, caller, guard = self._run(
            chat_by_label={
                "drift-primer": _primer_response("initial", ["about a"]),
                "drift-subq-gen-1": "Driver A fact.",
                "drift-synthesis": "final",
            },
            embed_by_label={
                "drift-report-embed": (1.0, 0.0, 0.0, 0.0),
                "drift-subq-embed-1": (1.0, 0.0),
            },
        )
        checks = [c for c in guard.calls if c[0].startswith("check_")]
        self.assertEqual(len(checks), len(caller.call_log))
        for (kind, label), (call_kind, call_label) in zip(checks, caller.call_log):
            self.assertEqual(call_label, label)
            expected_kind = "check_embedding" if call_kind == "embed" else "check_generative"
            self.assertEqual(kind, expected_kind)

    def test_report_and_local_chunk_evidence_stay_separate(self):
        result, _caller, _guard = self._run(
            chat_by_label={
                "drift-primer": _primer_response("initial", ["about a"]),
                "drift-subq-gen-1": "Driver A fact.",
                "drift-synthesis": "final",
            },
            embed_by_label={
                "drift-report-embed": (1.0, 0.0, 0.0, 0.0),
                "drift-subq-embed-1": (1.0, 0.0),
            },
        )
        # report_ids never contain chunk ids, and the local subgraph's
        # chunk ids never contain a report path.
        local_chunk_ids = result.subquestion_results[0].local_answer.subgraph["chunk_ids"]
        self.assertEqual(set(result.report_ids) & set(local_chunk_ids), set())
        self.assertIn("c1", local_chunk_ids)


class SynthesisContextTruncationTests(unittest.TestCase):
    def test_small_budget_drops_whole_subquestion_blocks_not_text(self):
        local_index = _local_index()
        graph = _graph()
        from naive_rag.local_search import LocalAnswer

        long_answer = ds.SubQuestionResult(
            question="about a",
            local_answer=LocalAnswer(
                question="about a", answer="A" * 500, refused=False, model_called=True,
                subgraph={"nodes": [], "edges": [], "sources": [], "chunk_ids": []},
            ),
        )
        context, truncation = ds.build_synthesis_context(
            "short primer answer", ("1", "2", "3"), (long_answer,), char_budget=50)
        self.assertTrue(truncation.truncated)
        self.assertEqual(truncation.dropped_item_ids, ("subq:1",))
        self.assertNotIn("A" * 500, context)
        self.assertIn("short primer answer", context)
        self.assertEqual(truncation.char_budget, 50)
        self.assertLessEqual(truncation.final_chars, truncation.original_chars)

    def test_generous_budget_keeps_everything(self):
        from naive_rag.local_search import LocalAnswer

        item = ds.SubQuestionResult(
            question="about a",
            local_answer=LocalAnswer(
                question="about a", answer="short", refused=False, model_called=True,
                subgraph={"nodes": [], "edges": [], "sources": [], "chunk_ids": []},
            ),
        )
        context, truncation = ds.build_synthesis_context(
            "primer answer", ("1",), (item,), char_budget=24000)
        self.assertFalse(truncation.truncated)
        self.assertEqual(truncation.dropped_item_ids, ())
        self.assertIn("short", context)


class ReportIndexCacheTests(unittest.TestCase):
    def test_build_report_index_covers_every_report_once(self):
        reports = _reports()
        calls = []

        def fake_embed_texts(texts):
            calls.append(list(texts))
            return [[float(index), 0.0] for index, _ in enumerate(texts)]

        index = ds.build_report_index(reports, fake_embed_texts)
        self.assertEqual(len(index.reports), 4)
        self.assertEqual(calls, [[ds.report_index_text(r) for r in sorted(reports, key=lambda r: r.path)]])

    def test_save_and_load_round_trip_with_matching_hash(self):
        reports = _reports()
        index = ds.build_report_index(reports, lambda texts: [[1.0, 0.0] for _ in texts])
        content_hash = ds.reports_content_hash(reports)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report-index.json"
            ds.save_report_index(index, path, reports_hash=content_hash, embedding_model=ds.EMBEDDING_MODEL)
            loaded = ds.load_report_index(
                path, expected_reports_hash=content_hash,
                expected_embedding_model=ds.EMBEDDING_MODEL, expected_embedding_dimension=2)
            self.assertEqual(loaded.by_path.keys(), index.by_path.keys())

    def test_missing_cache_raises_a_clear_error_not_an_automatic_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            with self.assertRaises(ds.ReportIndexCacheError):
                ds.load_report_index(path, expected_reports_hash="deadbeef")

    def test_content_mismatch_is_rejected(self):
        reports = _reports()
        index = ds.build_report_index(reports, lambda texts: [[1.0, 0.0] for _ in texts])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report-index.json"
            ds.save_report_index(
                index, path, reports_hash=ds.reports_content_hash(reports), embedding_model=ds.EMBEDDING_MODEL)
            with self.assertRaises(ds.ReportIndexCacheError):
                ds.load_report_index(path, expected_reports_hash="not-the-real-hash")

    def test_embedding_model_mismatch_is_rejected(self):
        reports = _reports()
        index = ds.build_report_index(reports, lambda texts: [[1.0, 0.0] for _ in texts])
        content_hash = ds.reports_content_hash(reports)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report-index.json"
            ds.save_report_index(index, path, reports_hash=content_hash, embedding_model="some-other-model")
            with self.assertRaises(ds.ReportIndexCacheError):
                ds.load_report_index(path, expected_reports_hash=content_hash, expected_embedding_model=ds.EMBEDDING_MODEL)

    def test_embedding_dimension_mismatch_is_rejected(self):
        reports = _reports()
        index = ds.build_report_index(reports, lambda texts: [[1.0, 0.0] for _ in texts])
        content_hash = ds.reports_content_hash(reports)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report-index.json"
            ds.save_report_index(index, path, reports_hash=content_hash, embedding_model=ds.EMBEDDING_MODEL)
            with self.assertRaises(ds.ReportIndexCacheError):
                ds.load_report_index(
                    path, expected_reports_hash=content_hash,
                    expected_embedding_model=ds.EMBEDDING_MODEL, expected_embedding_dimension=1536)


class ModelConfigTests(unittest.TestCase):
    def test_model_settings_match_the_actual_week5_configuration(self):
        self.assertEqual(ds.CHAT_MODEL, "gpt-4o-mini")
        self.assertEqual(ds.TEMPERATURE, 0)
        self.assertEqual(ds.MAX_RETRIES, 0)
        self.assertEqual(ds.GENERATIVE_MAX_TOKENS, 900)
        self.assertEqual(ds.EMBEDDING_MODEL, "text-embedding-3-small")

    def test_primer_prompt_version_v2_requires_at_least_one_subquestion(self):
        self.assertEqual(ds.PRIMER_PROMPT_VERSION, "drift-primer-prompt-v2")
        self.assertEqual(ds.MIN_SUBQUESTIONS, 1)
        empty = ds.validate_primer_response({"initial_answer": "x", "subquestions": []})
        self.assertFalse(empty.valid_structure)
        self.assertTrue(any("fewer than" in problem for problem in empty.problems))
        one = ds.validate_primer_response({"initial_answer": "x", "subquestions": ["q1"]})
        self.assertTrue(one.valid_structure)

    def test_generative_max_tokens_is_passed_to_every_chat_call(self):
        seen_max_tokens = []

        def call_chat(prompt, label, max_output_tokens):
            seen_max_tokens.append(max_output_tokens)
            return _primer_response("x", ["about a"]) if label == "drift-primer" else "final", \
                {"prompt_tokens": 1, "completion_tokens": 1}

        def call_embed(texts, label):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts], 1

        ds.drift_search(
            "q?", report_index=_report_index(), reports=_reports(),
            graph=_graph(), local_index=_local_index(),
            call_chat=call_chat, call_embed=call_embed, cost_guard=FakeCostGuard(),
        )
        self.assertTrue(all(value == ds.GENERATIVE_MAX_TOKENS for value in seen_max_tokens))


if __name__ == "__main__":
    unittest.main()
