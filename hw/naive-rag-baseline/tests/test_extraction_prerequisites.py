"""Offline checks for the extraction window and corpus identity. No network."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from naive_rag.config import Settings
from naive_rag.extract_pilot import (
    EXTRACTION_TOKEN_ESTIMATE,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    ExtractionBudgetError,
    ReuseError,
    build_jobs,
    check_extraction_prompt,
    default_caller,
    estimate_extraction_tokens,
    input_hash,
    render_extraction_prompt,
    run_extraction,
    safe_stem,
)
from naive_rag.extraction_models import ExtractionResult
from naive_rag.loaders import corpus_inventory


def _row(text: str, chunk_id: str = "d1#0") -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": "d1",
        "section": "Karrier",
        "page": None,
        "source": "local",
        "text": text,
    }


class CorpusIdentityTest(unittest.TestCase):
    def test_manifest_identity_reports_a_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "present.txt").write_text("source", encoding="utf-8")
            (root / "extra.txt").write_text("extra", encoding="utf-8")
            (root / "metadata.json").write_text(json.dumps([
                {"doc_id": "present", "file": "present.txt", "format": "txt",
                 "revision_id": "1"},
                {"doc_id": "missing", "file": "missing.html", "format": "html",
                 "revision_id": "1375968451"},
                {"doc_id": "other", "file": "wrong.txt", "format": "html",
                 "revision_id": "2"},
            ]), encoding="utf-8")
            (root / "wrong.txt").write_text("source", encoding="utf-8")
            report = corpus_inventory(root)
        self.assertEqual(report["manifest_documents"], 3)
        self.assertEqual(report["present_files"], 2)
        self.assertEqual(report["doc_ids"], ["present", "missing", "other"])
        self.assertEqual(report["missing"], [{
            "doc_id": "missing",
            "file": "missing.html",
            "revision_id": "1375968451",
        }])
        self.assertEqual(report["extra"], ["extra.txt"])
        self.assertEqual(report["mismatches"], [
            "wrong.txt: stem 'wrong' != doc_id 'other'",
            "wrong.txt: suffix 'txt' != format 'html'",
        ])


class ExtractionWindowTest(unittest.TestCase):
    def test_window_is_unset_until_both_values_are_given(self) -> None:
        settings = Settings(
            extraction_input_window=None, extraction_output_reserve=None)
        self.assertIsNone(settings.extraction_input_window)
        self.assertIsNone(settings.extraction_output_reserve)
        self.assertEqual(settings.context_model_window, 8192)

    def test_half_set_or_invalid_window_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(extraction_input_window=1000)
        with self.assertRaises(ValidationError):
            Settings(extraction_input_window=100,
                     extraction_output_reserve=100)
        with self.assertRaises(ValidationError):
            Settings(extraction_input_window=True,
                     extraction_output_reserve=10)

    def test_rendered_prompt_keeps_instructions_schema_and_chunk(self) -> None:
        text = "Lewis Hamilton won the title."
        prompt = render_extraction_prompt("Hamilton", "2016", text)
        self.assertIn(SYSTEM_PROMPT, prompt)
        self.assertIn("document_title: Hamilton", prompt)
        self.assertIn("section: 2016", prompt)
        self.assertIn(text, prompt)
        self.assertEqual(
            estimate_extraction_tokens(prompt), (len(prompt) + 2) // 3)
        self.assertEqual(EXTRACTION_TOKEN_ESTIMATE, "ceil_chars_div_3")

    def test_over_budget_is_an_error_and_does_not_cut_the_text(self) -> None:
        text = "Á" * 90
        prompt = render_extraction_prompt("Doc", None, text)
        with self.assertRaises(ExtractionBudgetError) as caught:
            check_extraction_prompt(
                prompt, window=30, reserve=10, label="d1#0")
        self.assertIn("was not truncated", str(caught.exception))
        self.assertIn(text, prompt)

    def test_unset_window_refuses_before_the_model_call(self) -> None:
        class Unset:
            extraction_input_window = None
            extraction_output_reserve = None

        payload = {
            "document_title": "Doc",
            "section": None,
            "text": "short",
        }
        with patch("naive_rag.config.get_settings", return_value=Unset()), \
                patch("naive_rag.models.get_chat_model") as chat:
            with self.assertRaises(ExtractionBudgetError):
                default_caller(payload)
        chat.assert_not_called()
        self.assertEqual(payload["text"], "short")

    def test_output_reserve_is_passed_to_the_model(self) -> None:
        class Configured:
            extraction_input_window = 20000
            extraction_output_reserve = 256

        model = MagicMock()
        structured = MagicMock()
        structured.invoke.return_value = ExtractionResult()
        model.with_structured_output.return_value = structured
        payload = {
            "document_title": "Doc",
            "section": "Karrier",
            "text": "short source",
        }
        with patch("naive_rag.config.get_settings",
                   return_value=Configured()), \
                patch("naive_rag.models.get_chat_model",
                      return_value=model) as chat:
            default_caller(payload)
        chat.assert_called_once_with(max_retries=0, max_tokens=256)

    def test_run_stops_before_a_call_when_the_window_is_unset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chunks = root / "chunks.jsonl"
            metadata = root / "metadata.json"
            out = root / "extraction"
            metadata.write_text(json.dumps([{
                "doc_id": "d1", "title": "Doc", "file": "d.txt",
            }]), encoding="utf-8")
            chunks.write_text(json.dumps(_row("short")) + "\n",
                              encoding="utf-8")

            class Unset:
                extraction_input_window = None
                extraction_output_reserve = None

            with patch("naive_rag.config.get_settings", return_value=Unset()), \
                    self.assertRaises(ExtractionBudgetError):
                run_extraction(
                    chunks_path=chunks, metadata_path=metadata, out_dir=out,
                    summary_path=root / "summary.md", run=True,
                    overwrite=False, model="test-model")
        self.assertFalse(out.exists())

    def test_changed_text_is_not_reused_for_the_same_chunk_id(self) -> None:
        old = "Max Verstappen won the championship."
        new = "Lewis Hamilton won the championship."
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reuse = root / "old"
            reuse.mkdir()
            digest = input_hash(
                model="test-model", document_title="Doc",
                section="Karrier", text=old)
            saved = reuse / f"{safe_stem('d1#0')}.json"
            saved.write_text(json.dumps({
                "chunk_id": "d1#0",
                "status": "ok",
                "model": "test-model",
                "prompt_version": PROMPT_VERSION,
                "input_hash": digest,
                "result": {"entities": [], "relationships": []},
            }), encoding="utf-8")
            jobs = build_jobs(
                [_row(new)], {"d1": "Doc"}, model="test-model",
                out_dir=root / "new", overwrite=False,
                reuse_dirs=(reuse,))
            self.assertEqual(jobs[0].action, "process")
            self.assertIsNone(jobs[0].reused_from)
            (root / "new").mkdir()
            (root / "new" / saved.name).write_bytes(saved.read_bytes())
            with self.assertRaises(ReuseError) as caught:
                build_jobs(
                    [_row(new)], {"d1": "Doc"}, model="test-model",
                    out_dir=root / "new", overwrite=False)
            self.assertIn("input", str(caught.exception))
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))
                             ["input_hash"], digest)
