"""Offline checks for the drift-only report: smoke/full cost separation,
the one-column comparison table, and the index-cost summary line being
reported once, not per question type."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import week6_bootstrap  # noqa: F401,E402
import report_week6  # noqa: E402


def _row(question_id, run_phase, qtype, status, *, cost_usd=None, correctness="helyes"):
    return {
        "question_id": question_id, "mode": "drift", "run_phase": run_phase,
        "question_type": qtype, "question_status": status,
        "correctness": {"status": "scored", "label": correctness},
        "faithfulness": {"score": 1.0},
        "retrieval": {"status": "scored", "ratio": 1.0, "is_proxy": False},
        "report_candidate_chunk_ids": ["rc#0"],
        "cost_usd": cost_usd, "duration_seconds": 1.0,
    }


class ComparisonTableTests(unittest.TestCase):
    def test_table_has_one_drift_column_and_every_type_row(self) -> None:
        rows = [_row("Q01", "smoke", "simple", "frozen_w4")]
        table = report_week6.drift_comparison_table_markdown(rows)
        self.assertIn("| Kérdéstípus | drift |", table)
        for qtype in ("simple", "multi-hop", "global"):
            self.assertIn(f"| {qtype} |", table)


class SmokeFullCostSeparationTests(unittest.TestCase):
    def test_full_report_cost_excludes_smoke_rows(self) -> None:
        rows = [
            _row("Q01", "smoke", "simple", "frozen_w4", cost_usd=0.01),
            _row("Q01", "full", "simple", "frozen_w4", cost_usd=0.02),
            _row("Q02", "full", "simple", "frozen_w4", cost_usd=0.03),
        ]
        full_md = report_week6.build_drift_report_markdown(rows, run_phase="full")
        smoke_md = report_week6.build_drift_report_markdown(rows, run_phase="smoke")
        self.assertIn("0.05", full_md)  # 0.02 + 0.03, not 0.08
        self.assertNotIn("0.08", full_md)
        self.assertIn("0.01", smoke_md)
        self.assertNotIn("0.05", smoke_md)

    def test_index_cost_appears_once_not_per_type(self) -> None:
        rows = [_row("Q01", "full", "simple", "frozen_w4", cost_usd=0.01)]
        summary = {"cost_usd": 0.0537, "report_count": 37, "ledger_path": "x.json"}
        md = report_week6.build_drift_report_markdown(rows, run_phase="full", index_cost_summary=summary)
        self.assertEqual(md.count("0.0537"), 1)
        self.assertIn("EGYSZERI", md)

    def test_missing_index_cost_summary_is_reported_not_silently_zero(self) -> None:
        rows = [_row("Q01", "full", "simple", "frozen_w4", cost_usd=0.01)]
        md = report_week6.build_drift_report_markdown(rows, run_phase="full", index_cost_summary=None)
        self.assertIn("nincs rögzítve", md)

    def test_cumulative_ledger_total_is_shown_separately_from_per_run_cost(self) -> None:
        rows = [_row("Q01", "full", "simple", "frozen_w4", cost_usd=0.01)]
        md = report_week6.build_drift_report_markdown(
            rows, run_phase="full", ledger_cumulative_spent_usd=0.1234, ledger_cumulative_remaining_usd=0.3766)
        self.assertIn("0.1234", md)
        self.assertIn("0.3766", md)


class ReportProxySeparationTests(unittest.TestCase):
    def test_report_candidate_chunks_are_reported_separately_from_retrieval_avg(self) -> None:
        rows = [_row("Q01", "full", "simple", "frozen_w4")]
        md = report_week6.build_drift_report_markdown(rows, run_phase="full")
        self.assertIn("jelölt", md)
        self.assertIn("nem keverendő", md)


if __name__ == "__main__":
    unittest.main()
