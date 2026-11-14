"""Regression tests for report.py's mode/question-type cost breakdown:
full vs. partial vs. unknown cost must stay distinct, and a partial cost
must never be reported as if it were the case's full cost.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import report


def _row(question_id, mode, qtype, *, cost_usd=None, cost_gen=None,
        cost_corr=None, cost_faith=None) -> dict:
    row = {"question_id": question_id, "mode": mode, "question_type": qtype,
          "question_status": "frozen_w4", "run_phase": "smoke"}
    if cost_usd is not None:
        row["cost_usd"] = cost_usd
    if cost_gen is not None:
        row["cost_usd_generation"] = cost_gen
    if cost_corr is not None:
        row["cost_usd_correctness_judge"] = cost_corr
    if cost_faith is not None:
        row["cost_usd_faithfulness_judge"] = cost_faith
    return row


class CostBucketTests(unittest.TestCase):
    def test_full_cost_counted_and_summed(self) -> None:
        rows = [_row("Q01", "naiv", "simple", cost_usd=0.01, cost_gen=0.005,
                     cost_corr=0.003, cost_faith=0.002)]
        bucket = report._cost_bucket(rows)
        self.assertEqual(bucket["full_known_count"], 1)
        self.assertAlmostEqual(bucket["full_known_sum"], 0.01)
        self.assertEqual(bucket["partial_count"], 0)
        self.assertEqual(bucket["unknown_count"], 0)

    def test_partial_cost_not_counted_as_full_and_not_summed(self) -> None:
        rows = [_row("Q07", "naiv", "multi-hop", cost_gen=0.005)]  # judges missing
        bucket = report._cost_bucket(rows)
        self.assertEqual(bucket["full_known_count"], 0)
        self.assertIsNone(bucket["full_known_sum"])
        self.assertEqual(bucket["partial_count"], 1)
        self.assertEqual(bucket["unknown_count"], 0)

    def test_fully_unknown_cost_is_not_zero(self) -> None:
        rows = [_row("Q11", "globalis", "global")]  # no cost field at all
        bucket = report._cost_bucket(rows)
        self.assertEqual(bucket["unknown_count"], 1)
        self.assertEqual(bucket["partial_count"], 0)
        self.assertIsNone(bucket["full_known_sum"])

    def test_mixed_group_reports_each_bucket_independently(self) -> None:
        rows = [
            _row("Q01", "naiv", "simple", cost_usd=0.01, cost_gen=0.005, cost_corr=0.003, cost_faith=0.002),
            _row("Q07", "naiv", "multi-hop", cost_gen=0.004),
            _row("Q11", "naiv", "global"),
        ]
        bucket = report._cost_bucket(rows)
        self.assertEqual(bucket["case_count"], 3)
        self.assertEqual(bucket["full_known_count"], 1)
        self.assertEqual(bucket["partial_count"], 1)
        self.assertEqual(bucket["unknown_count"], 1)
        self.assertAlmostEqual(bucket["full_known_sum"], 0.01)  # only the fully-known case


class CostByModeAndTypeTests(unittest.TestCase):
    def test_cost_by_mode_separates_naiv_and_lokalis(self) -> None:
        rows = [
            _row("Q01", "naiv", "simple", cost_usd=0.01, cost_gen=0.005, cost_corr=0.003, cost_faith=0.002),
            _row("Q01", "lokalis", "simple", cost_gen=0.002),  # partial: only generation known
        ]
        by_mode = report.cost_by_mode(rows)
        self.assertEqual(by_mode["naiv"]["full_known_count"], 1)
        self.assertEqual(by_mode["lokalis"]["full_known_count"], 0)
        self.assertEqual(by_mode["lokalis"]["partial_count"], 1)

    def test_cost_by_question_type_groups_correctly(self) -> None:
        rows = [
            _row("Q01", "naiv", "simple", cost_usd=0.01, cost_gen=0.005, cost_corr=0.003, cost_faith=0.002),
            _row("Q07", "lokalis", "multi-hop", cost_gen=0.004),
        ]
        by_type = report.cost_by_question_type(rows)
        self.assertEqual(by_type["simple"]["full_known_count"], 1)
        self.assertEqual(by_type["multi-hop"]["partial_count"], 1)

    def test_breakdown_markdown_contains_both_sections(self) -> None:
        rows = [_row("Q01", "naiv", "simple", cost_usd=0.01, cost_gen=0.005, cost_corr=0.003, cost_faith=0.002)]
        md = report.cost_breakdown_markdown(rows)
        self.assertIn("Módonként", md)
        self.assertIn("Kérdéstípusonként", md)
        self.assertIn("naiv", md)
        self.assertIn("simple", md)

    def test_missing_mode_or_type_renders_empty_bucket_not_crash(self) -> None:
        md = report.cost_breakdown_markdown([])
        self.assertIn("0 / 0", md)


class FullReportIncludesCostBreakdownTests(unittest.TestCase):
    def test_build_report_markdown_includes_breakdown_section(self) -> None:
        rows = [_row("Q01", "naiv", "simple", cost_usd=0.01, cost_gen=0.005, cost_corr=0.003, cost_faith=0.002)]
        for row in rows:
            row["duration_seconds"] = 1.0
            row["correctness"] = {"label": "helyes"}
        md = report.build_report_markdown(rows, run_phase="smoke")
        self.assertIn("Módonként", md)
        self.assertIn("részleges", md.lower())


if __name__ == "__main__":
    unittest.main()
