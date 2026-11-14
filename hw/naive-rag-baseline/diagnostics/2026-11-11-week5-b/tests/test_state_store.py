import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import state_store as ss


class CaseStateTests(unittest.TestCase):
    def test_next_step_order(self) -> None:
        case = ss.CaseState(question_id="Q01", mode="naiv")
        self.assertEqual(case.next_step(), "answer_saved")
        case.answer_saved = True
        self.assertEqual(case.next_step(), "criteria_scored")
        case.criteria_scored = True
        self.assertEqual(case.next_step(), "faithfulness_scored")
        case.faithfulness_scored = True
        self.assertEqual(case.next_step(), "langfuse_synced")
        case.langfuse_synced = True
        self.assertIsNone(case.next_step())

    def test_roundtrip_dict(self) -> None:
        case = ss.CaseState(question_id="Q01", mode="naiv", answer_saved=True)
        restored = ss.CaseState.from_dict(case.as_dict())
        self.assertEqual(restored.answer_saved, True)
        self.assertEqual(restored.criteria_scored, False)


class StateStoreTests(unittest.TestCase):
    def _sig(self, config="c1", golden="g1") -> ss.RunSignature:
        return ss.RunSignature(run_kind="smoke", config_sha256=config, golden_set_sha256=golden)

    def test_save_and_reload_preserves_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            sig = self._sig()
            store = ss.StateStore.load_or_create(path, sig)
            case = store.get_or_create("Q01", "naiv")
            case.answer_saved = True
            store.save()

            reloaded = ss.StateStore.load_or_create(path, sig)
            case2 = reloaded.get_or_create("Q01", "naiv")
            self.assertTrue(case2.answer_saved)
            self.assertFalse(case2.criteria_scored)

    def test_different_config_hash_refuses_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            ss.StateStore.load_or_create(path, self._sig(config="c1")).save()
            with self.assertRaises(ss.StateError):
                ss.StateStore.load_or_create(path, self._sig(config="c2"))

    def test_different_golden_hash_refuses_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            ss.StateStore.load_or_create(path, self._sig(golden="g1")).save()
            with self.assertRaises(ss.StateError):
                ss.StateStore.load_or_create(path, self._sig(golden="g2"))

    def test_summary_counts_completed_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store = ss.StateStore.load_or_create(path, self._sig())
            c1 = store.get_or_create("Q01", "naiv")
            c1.answer_saved = True
            c1.criteria_scored = True
            store.get_or_create("Q02", "naiv")
            summary = store.summary()
            self.assertEqual(summary["answer_saved"], 1)
            self.assertEqual(summary["criteria_scored"], 1)
            self.assertEqual(summary["faithfulness_scored"], 0)

    def test_config_hash_is_order_independent(self) -> None:
        h1 = ss.config_hash({"a": 1, "b": 2})
        h2 = ss.config_hash({"b": 2, "a": 1})
        self.assertEqual(h1, h2)

    def test_config_hash_changes_with_value(self) -> None:
        h1 = ss.config_hash({"a": 1})
        h2 = ss.config_hash({"a": 2})
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
