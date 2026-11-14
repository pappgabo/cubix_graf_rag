"""Offline tests for measure.py's real Langfuse wiring
(build_real_langfuse_sync_fn): it must read each mode's expected cases
from disk, stay silent until the whole group is complete, then call the
grouped sync exactly once -- never once per (question, mode).

Monkeypatches ``langfuse.Langfuse`` with a fake (no network, no model
call) for the duration of each test.
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure
import langfuse_sync as ls


class FakeLangfuseClient:
    instances: list["FakeLangfuseClient"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[dict] = []
        FakeLangfuseClient.instances.append(self)

    @staticmethod
    def create_trace_id(*, seed=None) -> str:
        # Same deterministic-hash shape as the real Langfuse.create_trace_id;
        # only used so langfuse_sync.deterministic_experiment_id resolves
        # offline against this fake module.
        return hashlib.sha256((seed or "").encode("utf-8")).digest()[:16].hex()

    def run_experiment(self, *, name, run_name, data, task, evaluators,
                       experiment_id=None, metadata=None, **kwargs):
        for item in data:
            task(item=item)  # proves no model call is needed to produce output
        self.calls.append({"run_name": run_name, "experiment_id": experiment_id, "item_count": len(data)})
        return {"results": []}


def _write_case(case_dir: Path, question_id: str, mode: str, *, scored: bool) -> None:
    row = {
        "question_id": question_id, "mode": mode, "question_text": "Q?", "answer": "A.",
        "expected_answer": "A.", "question_type": "simple", "question_status": "frozen_w4",
        "retrieval": {"ratio": 1.0, "is_proxy": False},
        "correctness": {"label": "helyes"} if scored else None,
        "faithfulness": {"score": 1.0} if scored else None,
    }
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / f"{question_id}-{mode}.json").write_text(json.dumps(row), encoding="utf-8")


class BuildRealLangfuseSyncFnTests(unittest.TestCase):
    def setUp(self) -> None:
        import langfuse as real_langfuse  # the real, installed SDK -- only its Evaluation class is reused

        self._orig_langfuse_module = sys.modules.get("langfuse")
        fake_module = type(sys)("langfuse")
        fake_module.Langfuse = FakeLangfuseClient
        fake_module.Evaluation = real_langfuse.Evaluation
        sys.modules["langfuse"] = fake_module
        FakeLangfuseClient.instances = []

    def tearDown(self) -> None:
        if self._orig_langfuse_module is not None:
            sys.modules["langfuse"] = self._orig_langfuse_module
        else:
            sys.modules.pop("langfuse", None)

    def test_silent_while_group_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "cases"
            sync_fn = measure.build_real_langfuse_sync_fn("smoke", ("Q01", "Q07", "Q11"), case_dir)
            _write_case(case_dir, "Q01", "naiv", scored=True)
            row = json.loads((case_dir / "Q01-naiv.json").read_text(encoding="utf-8"))
            sync_fn(row)  # only 1 of 3 expected cases exists -> must not call run_experiment
            client = FakeLangfuseClient.instances[-1]
            self.assertEqual(client.calls, [])

    def test_fires_once_when_group_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "cases"
            sync_fn = measure.build_real_langfuse_sync_fn("smoke", ("Q01", "Q07", "Q11"), case_dir)
            for qid in ("Q01", "Q07", "Q11"):
                _write_case(case_dir, qid, "naiv", scored=True)
            row = json.loads((case_dir / "Q11-naiv.json").read_text(encoding="utf-8"))
            sync_fn(row)
            client = FakeLangfuseClient.instances[-1]
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(client.calls[0]["item_count"], 3)  # all 3 questions in ONE call

    def test_repeated_invocation_after_completion_does_not_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "cases"
            sync_fn = measure.build_real_langfuse_sync_fn("smoke", ("Q01", "Q07", "Q11"), case_dir)
            for qid in ("Q01", "Q07", "Q11"):
                _write_case(case_dir, qid, "naiv", scored=True)
            row = json.loads((case_dir / "Q11-naiv.json").read_text(encoding="utf-8"))
            sync_fn(row)
            sync_fn(row)  # called again (e.g. a later resume re-reaching this case's step)
            client = FakeLangfuseClient.instances[-1]
            self.assertEqual(len(client.calls), 1)  # still just one run_experiment call

    def test_different_modes_sync_independently_one_call_each(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "cases"
            sync_fn = measure.build_real_langfuse_sync_fn("smoke", ("Q01", "Q07", "Q11"), case_dir)
            for mode in ("naiv", "lokalis"):
                for qid in ("Q01", "Q07", "Q11"):
                    _write_case(case_dir, qid, mode, scored=True)
            sync_fn(json.loads((case_dir / "Q11-naiv.json").read_text(encoding="utf-8")))
            sync_fn(json.loads((case_dir / "Q11-lokalis.json").read_text(encoding="utf-8")))
            client = FakeLangfuseClient.instances[-1]
            self.assertEqual(len(client.calls), 2)
            run_names = {c["run_name"] for c in client.calls}
            self.assertEqual(run_names, {"week5-b-smoke-naiv", "week5-b-smoke-lokalis"})


if __name__ == "__main__":
    unittest.main()
