"""Offline checks for FULL run-id isolation. No model, database, or measurement."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "diagnostics" / "2026-11-21-week78-j2-naive-measure"))
sys.path.insert(0, str(ROOT / "src"))

import j2_naive_measure as j2  # noqa: E402
import state_store  # noqa: E402
from naive_rag.rag import prompt_for  # noqa: E402


def _golden(path: Path) -> None:
    path.write_text(
        '{"id":"Q01","type":"simple","status":"frozen_w4","question":"Q?",'
        '"expected_answer":"A.","criteria":[{"id":"Q01-c1","text":"t",'
        '"expected_content":["a"],"required":true}],'
        '"evidence_groups":[{"id":"Q01-e1","criterion":"Q01-c1","any_of_chunk_ids":["c0"]}],'
        '"gold_docs":["doc"],"notes":"n","golden_set_version":"test",'
        '"corpus":{"chunks_file":"x","chunks_sha256":"abc","chunk_count":1}}\n',
        encoding="utf-8",
    )


class FullRunIsolationTests(unittest.TestCase):
    def test_run_ids_separate_paths_and_share_the_existing_ledger(self):
        base = j2.pair_paths("baseline", "j3cmp-baseline")
        j3 = j2.pair_paths("baseline", "j3cmp-j3")
        historical = j2.pair_paths("baseline")
        self.assertNotEqual(base["results"], j3["results"])
        self.assertNotEqual(base["state"], j3["state"])
        self.assertNotEqual(base["logs"], j3["logs"])
        self.assertEqual(base["cost_ledger"], j2.PAIR_LEDGER)
        self.assertEqual(j3["cost_ledger"], j2.PAIR_LEDGER)
        self.assertNotEqual(base["results"], historical["results"])
        self.assertNotIn(str(base["cost_ledger"]), str(base["results"]))

    def test_existing_target_stops_and_prompt_identity_blocks_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "results": root / "results",
                "state": root / "state.json",
                "logs": root / "logs",
            }
            paths["results"].mkdir()
            with self.assertRaises(j2.J2MeasureHalt):
                j2.refuse_existing_run(paths)
            self.assertFalse(paths["state"].exists())
            golden = root / "golden.jsonl"
            _golden(golden)
            baseline = j2.pair_signature("baseline", golden, "idx", "baseline", "j3cmp-baseline")
            other = j2.pair_signature("baseline", golden, "idx", "j3", "j3cmp-baseline")
            self.assertNotEqual(baseline.config_sha256, other.config_sha256)
            state_store.StateStore.load_or_create(paths["state"], baseline).save()
            with self.assertRaises(state_store.StateError):
                state_store.StateStore.load_or_create(paths["state"], other)
        base_cfg = j2.pair_config("baseline", "idx", "baseline", "j3cmp-baseline")
        j3_cfg = j2.pair_config("baseline", "idx", "j3", "j3cmp-j3")
        self.assertEqual(base_cfg["prompt_variant"], "baseline")
        self.assertEqual(j3_cfg["prompt_variant"], "j3")
        self.assertFalse(base_cfg["j2_enabled"])
        self.assertFalse(j3_cfg["j2_enabled"])
        self.assertEqual(
            base_cfg["generation_prompt_sha256"],
            hashlib.sha256(prompt_for("baseline").messages[0].prompt.template.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            j3_cfg["generation_prompt_sha256"],
            hashlib.sha256(prompt_for("j3").messages[0].prompt.template.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(base_cfg["generation_prompt_sha256"], j3_cfg["generation_prompt_sha256"])
        self.assertIsNone(j2.run_pair.__kwdefaults__["actual_context_override"])
        self.assertEqual(j2.main(["run", "--variant", "baseline", "--full"]), 1)


if __name__ == "__main__":
    unittest.main()
