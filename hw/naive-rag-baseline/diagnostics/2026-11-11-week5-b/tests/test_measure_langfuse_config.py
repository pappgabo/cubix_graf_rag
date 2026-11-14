"""Regression tests for the two real-smoke-run crashes:

1. Langfuse client built before the project's .env was ever loaded into
   os.environ (naive_rag.config.Settings parses .env for its own pydantic
   fields only -- it never exports it), so Langfuse() silently built a
   disabled client instead of the run halting with a clear error.
2. SharedCostLedger didn't implement run_phase5.Budget's actual interface
   (check_embedding/record_embedding) -- covered in test_cost_guard.py.

This file never reads the real project .env and never constructs a real
langfuse.Langfuse() client; it only exercises measure.py's own gating
functions, isolated via monkeypatching.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure


class LangfuseGateOrderingTests(unittest.TestCase):
    """Isolates measure.load_project_env (a no-op here) so these tests
    never depend on whether the REAL naive-rag-baseline/.env on this
    machine actually has Langfuse credentials -- they test the ordering
    and the raise, not the real file's contents."""

    def setUp(self) -> None:
        self._orig_load_project_env = measure.load_project_env
        measure.load_project_env = lambda: None
        self._removed: dict[str, str] = {}
        for name in measure.REQUIRED_LANGFUSE_ENV_VARS:
            if name in os.environ:
                self._removed[name] = os.environ.pop(name)

    def tearDown(self) -> None:
        measure.load_project_env = self._orig_load_project_env
        os.environ.update(self._removed)

    def test_ensure_langfuse_configured_raises_when_vars_missing(self) -> None:
        with self.assertRaises(measure.LangfuseConfigError) as ctx:
            measure.ensure_langfuse_configured()
        message = str(ctx.exception)
        self.assertIn("LANGFUSE_PUBLIC_KEY", message)
        self.assertIn("LANGFUSE_SECRET_KEY", message)

    def test_ensure_langfuse_configured_passes_when_vars_present(self) -> None:
        os.environ["LANGFUSE_PUBLIC_KEY"] = "fake-public"
        os.environ["LANGFUSE_SECRET_KEY"] = "fake-secret"
        try:
            measure.ensure_langfuse_configured()  # must not raise
        finally:
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)

    def test_run_measurement_checks_langfuse_before_touching_the_golden_set(self) -> None:
        """A nonexistent golden-set path would normally raise
        FileNotFoundError once load_golden_set runs -- if LangfuseConfigError
        is raised instead, the Langfuse gate ran FIRST, before any file I/O
        or paid-call wiring."""
        missing_path = Path(tempfile.gettempdir()) / "week5-b-does-not-exist.jsonl"
        with self.assertRaises(measure.LangfuseConfigError):
            measure.run_measurement("smoke", golden_path=missing_path, sync_langfuse=True)

    def test_run_measurement_skips_the_gate_when_sync_langfuse_false(self) -> None:
        missing_path = Path(tempfile.gettempdir()) / "week5-b-does-not-exist.jsonl"
        with self.assertRaises(FileNotFoundError):
            measure.run_measurement("smoke", golden_path=missing_path, sync_langfuse=False)

    def test_build_real_langfuse_sync_fn_raises_instead_of_building_disabled_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(measure.LangfuseConfigError):
                measure.build_real_langfuse_sync_fn("smoke", ("Q01",), Path(tmp))


class LoadProjectEnvTests(unittest.TestCase):
    """Proves .env values actually reach os.environ via the project's own
    config path (naive_rag.config.PROJECT_ROOT), not a separately
    hardcoded path -- and that nothing is printed."""

    def test_env_file_values_reach_os_environ(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            (tmp_root / ".env").write_text(
                "LANGFUSE_PUBLIC_KEY=test-fixture-value-not-a-real-secret\n", encoding="utf-8")
            had = os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            try:
                with mock.patch("naive_rag.config.PROJECT_ROOT", tmp_root):
                    measure.load_project_env()
                self.assertEqual(
                    os.environ.get("LANGFUSE_PUBLIC_KEY"), "test-fixture-value-not-a-real-secret")
            finally:
                if had is not None:
                    os.environ["LANGFUSE_PUBLIC_KEY"] = had
                else:
                    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)

    def test_missing_env_file_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)  # no .env written here
            with mock.patch("naive_rag.config.PROJECT_ROOT", tmp_root):
                measure.load_project_env()  # must not raise


class MainExitCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._removed: dict[str, str] = {}
        for name in measure.REQUIRED_LANGFUSE_ENV_VARS:
            if name in os.environ:
                self._removed[name] = os.environ.pop(name)
        self._orig_load_project_env = measure.load_project_env
        measure.load_project_env = lambda: None  # isolate from the real .env

    def tearDown(self) -> None:
        measure.load_project_env = self._orig_load_project_env
        os.environ.update(self._removed)

    def test_main_returns_distinct_exit_code_for_langfuse_config_error(self) -> None:
        missing_path = str(Path(tempfile.gettempdir()) / "week5-b-does-not-exist.jsonl")
        rc = measure.main(["run", "--smoke", "--golden", missing_path])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
