"""Offline checks for the evaluation-sheet template builder."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag import evaluation_sheet as es


class TemplateTests(unittest.TestCase):
    def test_builds_one_row_per_question_and_mode(self):
        rows = es.build_template(["Q01", "Q02"])
        self.assertEqual(len(rows), 2 * len(es.MODES))
        self.assertTrue(all(row.status == "előzetes" for row in rows))
        self.assertTrue(all(row.correctness is None for row in rows))

    def test_save_and_reload(self):
        rows = es.build_template(["Q01"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sheet.json"
            es.save_template(path, rows)
            loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(loaded), len(es.MODES))
        self.assertTrue(all(r["status"] == "előzetes" for r in loaded))

    def test_summary_is_zero_when_nothing_filled_in(self):
        rows = es.build_template(["Q01", "Q09"])
        summary = es.summarize_by_type(rows, {"Q01": "simple", "Q09": "global"})
        self.assertEqual(summary["simple"], {v: 0 for v in es.CORRECTNESS_VALUES})
        self.assertEqual(summary["global"], {v: 0 for v in es.CORRECTNESS_VALUES})

    def test_summary_counts_filled_in_values(self):
        rows = es.build_template(["Q01"])
        rows[0].correctness = "helyes"
        summary = es.summarize_by_type(rows, {"Q01": "simple"})
        self.assertEqual(summary["simple"]["helyes"], 1)


if __name__ == "__main__":
    unittest.main()
