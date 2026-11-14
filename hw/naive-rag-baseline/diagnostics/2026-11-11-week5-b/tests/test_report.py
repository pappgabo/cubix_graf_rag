import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import report


def _row(question_id, mode, qtype, status, ratio=None, is_proxy=False, label="helyes",
        faithfulness=None, cost=None, duration=None, run_phase="smoke") -> dict:
    return {
        "question_id": question_id, "mode": mode, "question_type": qtype, "question_status": status,
        "run_phase": run_phase,
        "retrieval": {"ratio": ratio, "is_proxy": is_proxy, "status": "scored" if ratio is not None else "untraceable"},
        "correctness": {"label": label},
        "faithfulness": {"score": faithfulness} if faithfulness is not None else None,
        "cost_usd": cost, "duration_seconds": duration,
    }


class ReportTests(unittest.TestCase):
    def test_write_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.jsonl"
            rows = [_row("Q01", "naiv", "simple", "frozen_w4", ratio=1.0)]
            report.write_results(path, rows)
            loaded = report.load_results(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["question_id"], "Q01")

    def test_write_results_overwrites_not_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.jsonl"
            report.write_results(path, [_row("Q01", "naiv", "simple", "frozen_w4")])
            report.write_results(path, [_row("Q02", "naiv", "simple", "frozen_w4")])
            loaded = report.load_results(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["question_id"], "Q02")

    def test_proxy_and_real_retrieval_reported_separately(self) -> None:
        rows = [
            _row("Q01", "naiv", "global", "frozen_w4", ratio=1.0, is_proxy=False),
            _row("Q09", "globalis", "global", "frozen_w4", ratio=0.5, is_proxy=True),
        ]
        cell_naiv = report._cell([rows[0]])
        cell_global = report._cell([rows[1]])
        self.assertIn("retrieval_avg", cell_naiv)
        self.assertNotIn("retrieval_proxy_avg", cell_naiv)
        self.assertIn("retrieval_proxy_avg", cell_global)
        self.assertNotIn("retrieval_avg=", cell_global)

    def test_missing_cost_is_distinct_from_zero(self) -> None:
        rows = [_row("Q01", "naiv", "simple", "frozen_w4", cost=None), _row("Q02", "naiv", "simple", "frozen_w4", cost=0.01)]
        summary = report.cost_latency_summary(rows)
        self.assertEqual(summary["cases_missing_cost"], 1)
        self.assertEqual(summary["cases_with_known_cost"], 1)

    def test_comparison_table_has_all_modes_and_types(self) -> None:
        rows = [_row("Q01", "naiv", "simple", "frozen_w4", ratio=1.0)]
        table = report.comparison_table_markdown(rows)
        for mode in ("naiv", "lokalis", "globalis"):
            self.assertIn(mode, table)
        for qtype in ("simple", "multi-hop", "global"):
            self.assertIn(qtype, table)

    def test_empty_cell_reports_zero_cases_not_blank(self) -> None:
        cell = report._cell([])
        self.assertIn("0 eset", cell)


if __name__ == "__main__":
    unittest.main()
