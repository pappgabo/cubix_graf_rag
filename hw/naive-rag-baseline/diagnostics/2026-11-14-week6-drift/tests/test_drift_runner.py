"""Offline checks for `drift_runner.run_drift_capture` -- fake call_chat/
call_embed/graph/index, no real API call. Confirms the dict it returns
carries exactly what `measure.process_case` and the faithfulness judge
need, with report-level and local-chunk-level evidence kept separate."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import week6_bootstrap  # noqa: F401,E402
import drift_runner  # noqa: E402

from naive_rag.entity_index import EntityIndex, IndexedEntity
from naive_rag.global_search import CommunityReport, ReportStatement
from naive_rag.graph_merge import DomainEdge, DomainGraph, DomainNode
import naive_rag.drift_search as ds

DRIVER_A = "Driver:a"


def _graph() -> DomainGraph:
    # "c2" is a candidate (listed as a source_chunk_id) but has no text in
    # chunk_texts below, so local_search's cited_chunks() never puts it in
    # "sources" -- it stays a candidate only, never context.
    nodes = (
        DomainNode(node_id="n1", entity_key=DRIVER_A, label="Driver", name="Driver A",
                   description="Driver A description.", source_chunk_ids=("c1", "c2")),
    )
    return DomainGraph(kind="merged", nodes=nodes, edges=())


def _local_index() -> EntityIndex:
    return EntityIndex((
        IndexedEntity(entity_key=DRIVER_A, label="Driver", name="Driver A",
                      description="Driver A description.", text="Driver A\nDriver A description.",
                      vector=(1.0, 0.0)),
    ))


def _reports() -> tuple[CommunityReport, ...]:
    return (
        CommunityReport(
            path="1", community_id="c1", run_id="r", reporting_level=0,
            summary="Community 1 summary.",
            statements=(ReportStatement("1#1", "Statement one.", (), ("report-chunk#0",)),),
        ),
    )


def _report_index() -> ds.ReportIndex:
    return ds.ReportIndex((
        ds.IndexedReport(path="1", community_id="c1", text="x", vector=(1.0, 0.0, 0.0, 0.0)),
    ))


class FakeCostGuard:
    def __init__(self) -> None:
        self.spent_usd = 0.0

    def check_generative(self, input_tokens, max_output_tokens, label):
        return 0.001

    def check_embedding(self, tokens, label):
        return 0.0002

    def record_generative(self, actual_prompt, actual_completion, upper):
        self.spent_usd += upper
        return upper

    def record_embedding(self, actual_tokens, upper):
        self.spent_usd += upper
        return upper


def _caller(primer_subquestions, answers):
    def call_chat(prompt, label, max_output_tokens):
        if label == "drift-primer":
            return json.dumps({"initial_answer": "initial", "subquestions": primer_subquestions}), \
                {"prompt_tokens": 10, "completion_tokens": 5}
        if label == "drift-synthesis":
            return answers["synthesis"], {"prompt_tokens": 10, "completion_tokens": 5}
        return answers[label], {"prompt_tokens": 10, "completion_tokens": 5}

    def call_embed(texts, label):
        if label == "drift-report-embed":
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts], 5
        return [[1.0, 0.0] for _ in texts], 5

    return call_chat, call_embed


class RunDriftCaptureTests(unittest.TestCase):
    def test_actual_context_is_the_already_truncated_synthesis_context(self) -> None:
        call_chat, call_embed = _caller(["about a"], {
            "drift-subq-gen-1": "local fact", "synthesis": "final synthesis answer",
        })
        import naive_rag.drift_search as ds_mod
        orig = ds_mod.drift_search
        # drive through drift_runner's real call_chat/call_embed wiring by
        # monkeypatching only the injected callables it builds internally
        import unittest.mock as mock
        with mock.patch.object(drift_runner, "build_real_call_chat", return_value=call_chat), \
            mock.patch.object(drift_runner, "build_real_call_embed", return_value=call_embed):
            result = drift_runner.run_drift_capture(
                "Q01", "Who raced?", FakeCostGuard(), run_phase="smoke",
                reports=_reports(), report_index=_report_index(),
                graph=_graph(), local_index=_local_index(), chunk_texts={"c1": "Driver A text."},
            )
        self.assertEqual(result["answer"], "final synthesis answer")
        self.assertIn("initial", result["actual_context"])  # primer content made it into synthesis context
        self.assertEqual(result["drift_status"], "ok")
        self.assertIsNone(result["error"])

    def test_actual_chunk_ids_is_context_included_not_candidate_pool_or_cited_only(self) -> None:
        """"c2" is a candidate (touches the anchored node) but has no text
        in chunk_texts, so it never enters local_search's "sources" --
        actual_chunk_ids must exclude it, while local_candidate_chunk_ids
        must still report it (the two concepts stay separate, neither
        collapsing to the full candidate pool nor to response citations,
        which this function does not parse at all)."""
        call_chat, call_embed = _caller(["about a"], {
            "drift-subq-gen-1": "local fact", "synthesis": "final synthesis answer",
        })
        import unittest.mock as mock
        with mock.patch.object(drift_runner, "build_real_call_chat", return_value=call_chat), \
            mock.patch.object(drift_runner, "build_real_call_embed", return_value=call_embed):
            result = drift_runner.run_drift_capture(
                "Q01", "Who raced?", FakeCostGuard(), run_phase="smoke",
                reports=_reports(), report_index=_report_index(),
                graph=_graph(), local_index=_local_index(), chunk_texts={"c1": "Driver A text."},
            )
        self.assertEqual(result["actual_chunk_ids"], ["c1"])
        self.assertEqual(set(result["local_candidate_chunk_ids"]), {"c1", "c2"})
        self.assertNotIn("c2", result["actual_chunk_ids"])
        self.assertIn("initial", result["actual_context"])  # synthesis context untouched by this fix

    def test_report_candidate_chunks_are_separate_from_local_chunk_ids(self) -> None:
        call_chat, call_embed = _caller([], {"synthesis": "final"})
        import unittest.mock as mock
        with mock.patch.object(drift_runner, "build_real_call_chat", return_value=call_chat), \
            mock.patch.object(drift_runner, "build_real_call_embed", return_value=call_embed):
            result = drift_runner.run_drift_capture(
                "Q01", "Who raced?", FakeCostGuard(), run_phase="smoke",
                reports=_reports(), report_index=_report_index(),
                graph=_graph(), local_index=_local_index(), chunk_texts={},
            )
        self.assertEqual(result["actual_chunk_ids"], [])  # no sub-question ran -> no local chunk
        self.assertEqual(result["report_candidate_chunk_ids"], ["report-chunk#0"])
        self.assertEqual(set(result["actual_chunk_ids"]) & set(result["report_candidate_chunk_ids"]), set())
        self.assertFalse(result["is_proxy_retrieval"])  # actual_chunk_ids is never the proxy signal

    def test_non_ok_status_is_mapped_to_a_halting_error(self) -> None:
        call_chat, call_embed = _caller([], {"synthesis": "final"})

        def failing_call_chat(prompt, label, max_output_tokens):
            raise RuntimeError("simulated primer failure")

        import unittest.mock as mock
        with mock.patch.object(drift_runner, "build_real_call_chat", return_value=failing_call_chat), \
            mock.patch.object(drift_runner, "build_real_call_embed", return_value=call_embed):
            result = drift_runner.run_drift_capture(
                "Q01", "Who raced?", FakeCostGuard(), run_phase="smoke",
                reports=_reports(), report_index=_report_index(),
                graph=_graph(), local_index=_local_index(), chunk_texts={},
            )
        self.assertIsNotNone(result["error"])
        self.assertIn("primer_error", result["error"])
        self.assertIsNone(result["answer"])


class DetectReportRunIdTests(unittest.TestCase):
    def test_reads_the_actual_run_id_not_a_hardcoded_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reports.jsonl"
            path.write_text(json.dumps({"run_id": "actual-run-id-xyz"}) + "\n", encoding="utf-8")
            self.assertEqual(drift_runner.detect_report_run_id(path), "actual-run-id-xyz")


if __name__ == "__main__":
    unittest.main()
