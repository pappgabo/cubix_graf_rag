"""Hash reuse transfers a saved extraction onto a new chunk id. No network."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from naive_rag.extract_pilot import (
    PROMPT_VERSION,
    ReuseError,
    input_hash,
    main,
    run_extraction,
    safe_stem,
)
from naive_rag.extraction_load import plan_validated_raw

TEXT = "Max Verstappen won the championship."
TITLE = "Doc"


def _digest(text: str = TEXT, section: str | None = "Karrier") -> str:
    return input_hash(model="test-model", document_title=TITLE,
                      section=section, text=text)


def _row(chunk_id: str, text: str = TEXT, source: str = "https://example.test/new") -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": "d1",
        "section": "Karrier",
        "page": 3,
        "source": source,
        "text": text,
    }


def _success(chunk_id: str, digest: str, result: dict, **extra) -> dict:
    body = {
        "chunk_id": chunk_id,
        "doc_id": "d1",
        "document_title": TITLE,
        "section": "Karrier",
        "page": 1,
        "source": "https://example.test/old",
        "model": "test-model",
        "prompt_version": PROMPT_VERSION,
        "input_hash": digest,
        "status": "ok",
        "result": result,
    }
    body.update(extra)
    return body


def _write(directory: Path, name: str, body: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _paths(root: Path, rows: list[dict]) -> dict:
    chunks = root / "chunks.jsonl"
    metadata = root / "metadata.json"
    metadata.write_text(json.dumps([{
        "doc_id": "d1", "title": TITLE, "file": "d.txt",
    }]), encoding="utf-8")
    chunks.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return {
        "chunks_path": chunks,
        "metadata_path": metadata,
        "out_dir": root / "out",
        "summary_path": root / "summary.md",
    }


class HashReuseTest(unittest.TestCase):
    def _run(self, root: Path, rows: list[dict], reuse: Path, **extra):
        caller = extra.pop("caller", None)
        code = run_extraction(
            **_paths(root, rows), run=extra.pop("run", True),
            overwrite=False, reuse_dirs=(reuse,), model="test-model",
            caller=caller, **extra)
        return code

    def test_different_chunk_id_with_the_same_hash_is_reused(self) -> None:
        result = {
            "entities": [{
                "local_id": "e1",
                "name": "Max Verstappen",
                "entity_type": "Driver",
                "description": "The text says Max Verstappen won.",
            }, {
                "local_id": "e2",
                "name": "null",
                "entity_type": "Driver",
                "description": "A placeholder that is not an identity.",
            }],
            "relationships": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reuse = root / "reuse"
            saved = _write(reuse, "old_7.json", _success(
                "d1#1", _digest(), result,
                source_chunk_ids=["d1#1", "kept"],
            ))
            before = saved.read_bytes()

            def caller(_payload):
                raise AssertionError("model was called")

            code = self._run(root, [_row("d1#7")], reuse, caller=caller)
            record = json.loads(
                (root / "out" / f"{safe_stem('d1#7')}.json")
                .read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(saved.read_bytes(), before)
        self.assertEqual(record["chunk_id"], "d1#7")
        self.assertEqual(record["page"], 3)
        self.assertEqual(record["source"], "https://example.test/new")
        self.assertEqual(record["source_chunk_ids"], ["d1#7", "kept"])
        self.assertEqual(record["reused_from"], {
            "chunk_id": "d1#1",
            "file": "old_7.json",
        })
        self.assertEqual(record["candidate_result"], result)
        names = [item["name"] for item in record["result"]["entities"]]
        self.assertEqual(names, ["Max Verstappen"])
        self.assertEqual(
            record["result"]["entities"][0]["description"],
            "The text says Max Verstappen won.")
        plan = plan_validated_raw(record, accept_validated_raw=True)
        self.assertEqual(plan.chunk_id, "d1#7")
        self.assertEqual(plan.entities[0].name, "Max Verstappen")

    def test_empty_success_is_reused(self) -> None:
        empty = {"entities": [], "relationships": []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reuse = root / "reuse"
            _write(reuse, "other.json", _success("d1#4", _digest(), empty))

            def caller(_payload):
                raise AssertionError("model was called")

            code = self._run(root, [_row("d1#8")], reuse, caller=caller)
            record = json.loads(
                (root / "out" / f"{safe_stem('d1#8')}.json")
                .read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["result"], empty)
        self.assertEqual(record["chunk_id"], "d1#8")

    def test_same_chunk_id_with_a_different_hash_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reuse = root / "reuse"
            _write(reuse, f"{safe_stem('d1#0')}.json", _success(
                "d1#0", "stale", {"entities": [], "relationships": []}))
            code = self._run(root, [_row("d1#0")], reuse, reuse_only=True,
                             run=False)
            self.assertEqual(code, 0)
            self.assertFalse((root / "out").exists())

    def test_wrong_filename_does_not_hide_the_hash_match(self) -> None:
        empty = {"entities": [], "relationships": []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reuse = root / "reuse"
            _write(reuse, f"{safe_stem('d1#7')}.json", {
                "chunk_id": "d1#7",
                "status": "error",
                "model": "test-model",
                "prompt_version": PROMPT_VERSION,
                "input_hash": _digest(),
                "error": "old failure",
            })
            _write(reuse, "elsewhere.json", _success("d1#2", _digest(), empty))
            code = self._run(root, [_row("d1#7")], reuse, reuse_only=True,
                             run=False)
            record = json.loads(
                (root / "out" / f"{safe_stem('d1#7')}.json")
                .read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(record["reused_from"]["file"], "elsewhere.json")
        self.assertEqual(record["reused_from"]["chunk_id"], "d1#2")

    def test_error_record_is_not_a_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reuse = root / "reuse"
            _write(reuse, "bad.json", {
                "chunk_id": "d1#1",
                "status": "error",
                "model": "test-model",
                "prompt_version": PROMPT_VERSION,
                "input_hash": _digest(),
                "error": "failed",
                "candidate_result": {"entities": [], "relationships": []},
            })
            code = self._run(root, [_row("d1#7")], reuse, reuse_only=True,
                             run=False)
        self.assertEqual(code, 0)
        self.assertFalse((root / "out").exists())

    def test_conflicting_results_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reuse = root / "reuse"
            digest = _digest()
            _write(reuse, "a.json", _success(
                "d1#1", digest, {"entities": [], "relationships": []}))
            _write(reuse, "b.json", _success("d1#2", digest, {
                "entities": [{
                    "local_id": "e1",
                    "name": "Max Verstappen",
                    "entity_type": "Driver",
                    "description": "The text says he won.",
                }],
                "relationships": [],
            }))
            with self.assertRaises(ReuseError) as caught:
                self._run(root, [_row("d1#7")], reuse, reuse_only=True,
                          run=False)
        self.assertIn("conflicting", str(caught.exception))
        self.assertFalse((root / "out").exists())

    def test_different_target_hash_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reuse = root / "reuse"
            out = root / "out"
            _write(reuse, "match.json", _success(
                "d1#1", _digest(), {"entities": [], "relationships": []}))
            target = _write(out, f"{safe_stem('d1#7')}.json", _success(
                "d1#7", "other-hash", {"entities": [], "relationships": []}))
            before = target.read_bytes()
            with self.assertRaises(ReuseError):
                self._run(root, [_row("d1#7")], reuse, reuse_only=True,
                          run=False)
            self.assertEqual(target.read_bytes(), before)

    def test_second_run_does_not_change_the_transferred_record(self) -> None:
        empty = {"entities": [], "relationships": []}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reuse = root / "reuse"
            _write(reuse, "old.json", _success("d1#1", _digest(), empty))
            self._run(root, [_row("d1#7")], reuse, reuse_only=True, run=False)
            target = root / "out" / f"{safe_stem('d1#7')}.json"
            first = target.read_bytes()
            code = self._run(root, [_row("d1#7")], reuse, reuse_only=True,
                             run=False)
            self.assertEqual(code, 0)
            self.assertEqual(target.read_bytes(), first)

    def test_cli_passes_reuse_only_to_the_extraction_entry(self) -> None:
        with patch("naive_rag.extract_pilot.run_extraction",
                   return_value=0) as run:
            code = main(["--reuse-only", "--reuse-from", "saved"])
        self.assertEqual(code, 0)
        self.assertTrue(run.call_args.kwargs["reuse_only"])
        self.assertEqual(run.call_args.kwargs["reuse_dirs"], (Path("saved"),))
