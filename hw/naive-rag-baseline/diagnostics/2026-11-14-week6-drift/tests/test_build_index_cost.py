"""Offline checks for build_index.py's cost accounting and cache reuse --
no real embedding call (a fake `embeddings` stand-in is injected)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import week6_bootstrap  # noqa: F401,E402
import build_index  # noqa: E402
import cost_guard  # noqa: E402

from naive_rag.drift_search import build_report_index, reports_content_hash, save_report_index
from naive_rag.global_search import CommunityReport, ReportStatement


def _reports() -> tuple[CommunityReport, ...]:
    return (
        CommunityReport(path="1", community_id="c1", run_id="r", reporting_level=0,
                        summary="Summary one.", statements=(ReportStatement("1#1", "s1", (), ()),)),
        CommunityReport(path="2", community_id="c2", run_id="r", reporting_level=0,
                        summary="Summary two.", statements=(ReportStatement("2#1", "s2", (), ()),)),
    )


class LedgerTrackedEmbedTests(unittest.TestCase):
    def test_cost_is_checked_before_and_recorded_after_the_embed_call(self) -> None:
        calls: list[str] = []

        class FakeEmbeddings:
            def embed_documents(self, texts):
                calls.append("embed")
                return [[1.0, 0.0] for _ in texts]

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "ledger.json"
            ledger = cost_guard.SharedCostLedger.load(ledger_path)
            long_text = "word " * 5000
            vectors = build_index.ledger_tracked_embed_documents(
                FakeEmbeddings(), ledger, [long_text, long_text], "drift-report-index-build")
            self.assertEqual(len(vectors), 2)
            self.assertEqual(calls, ["embed"])
            self.assertEqual(len(ledger.entries), 1)
            self.assertFalse(ledger.entries[0]["usage_known"])  # langchain exposes no token usage
            self.assertGreater(ledger.entries[0]["cost_usd"], 0.0)  # upper bound, never zero


class BuildIndexMainTests(unittest.TestCase):
    def _write_collection(self, tmp: Path, reports: tuple[CommunityReport, ...]) -> Path:
        path = tmp / "collection.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for report in reports:
                handle.write(json.dumps({
                    "run_id": report.run_id, "reporting_level": report.reporting_level,
                    "path": report.path, "community_id": report.community_id,
                    "summary": report.summary,
                    "key_statements": [
                        {"statement": s.text, "evidence_ids": list(s.evidence_ids),
                         "candidate_source_chunk_ids": list(s.candidate_source_chunk_ids)}
                        for s in report.statements
                    ],
                    "validation": {"valid_structure": True},
                }) + "\n")
        return path

    def test_missing_cache_builds_and_records_index_cost_summary(self) -> None:
        reports = _reports()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            collection_path = self._write_collection(tmp_path, reports)
            out_path = tmp_path / "cache.json"
            ledger_path = tmp_path / "ledger.json"
            summary_path = tmp_path / "index-cost.json"

            import unittest.mock as mock

            class FakeEmbeddings:
                def embed_documents(self, texts):
                    return [[1.0, 0.0] for _ in texts]

            with mock.patch("naive_rag.models.get_embeddings", return_value=FakeEmbeddings()):
                rc = build_index.main([
                    "--build", "--collection-path", str(collection_path), "--expected-run-id", "r",
                    "--out", str(out_path), "--ledger-path", str(ledger_path),
                    "--index-cost-summary-path", str(summary_path),
                ])
            self.assertEqual(rc, 0)
            self.assertTrue(out_path.exists())
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["report_count"], 2)
            self.assertEqual(summary["entry_count"], 1)
            self.assertGreaterEqual(summary["cost_usd"], 0.0)
            ledger = cost_guard.SharedCostLedger.load(ledger_path)
            self.assertAlmostEqual(ledger.spent_usd, summary["cost_usd"])
            self.assertFalse(ledger.entries[0]["usage_known"])  # never silently booked as a real 0

    def test_already_valid_cache_makes_no_embedding_call(self) -> None:
        reports = _reports()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            collection_path = self._write_collection(tmp_path, reports)
            out_path = tmp_path / "cache.json"
            ledger_path = tmp_path / "ledger.json"
            summary_path = tmp_path / "index-cost.json"

            index = build_report_index(reports, lambda texts: [[1.0, 0.0] for _ in texts])
            save_report_index(
                index, out_path, reports_hash=reports_content_hash(reports),
                embedding_model=build_index.EMBEDDING_MODEL)

            embed_calls: list[str] = []

            class ExplodingEmbeddings:
                def embed_documents(self, texts):
                    embed_calls.append("embed")
                    raise AssertionError("should never be called for a valid cache")

            import unittest.mock as mock
            with mock.patch("naive_rag.models.get_embeddings", return_value=ExplodingEmbeddings()):
                rc = build_index.main([
                    "--build", "--collection-path", str(collection_path), "--expected-run-id", "r",
                    "--out", str(out_path), "--ledger-path", str(ledger_path),
                    "--index-cost-summary-path", str(summary_path),
                ])
            self.assertEqual(rc, 0)
            self.assertEqual(embed_calls, [])
            self.assertFalse(summary_path.exists())  # no new build -> no new cost summary
            self.assertFalse(ledger_path.exists())  # the ledger was never even opened


if __name__ == "__main__":
    unittest.main()
