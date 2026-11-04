"""Offline checks for the extraction pilot. No network."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag.extract_pilot import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    InputError,
    ReuseError,
    ServiceStop,
    failure_kind,
    input_hash,
    pilot_output_paths,
    run_extraction,
    safe_stem,
)
from naive_rag.extraction_models import (
    REL_SPECS,
    Entity,
    EntityType,
    ExtractionResult,
    ExtractionValidationError,
    RelType,
    validate_extraction,
)


def _entity(local_id: str, name: str, kind: EntityType) -> Entity:
    return Entity(local_id=local_id, name=name, entity_type=kind,
                  description=f"{name} as stated in the text.")


def _drove_for(**years) -> ExtractionResult:
    return ExtractionResult(
        entities=[
            _entity("e1", "Lewis Hamilton", EntityType.Driver),
            _entity("e2", "Ferrari", EntityType.Team),
        ],
        relationships=[{
            "source_id": "e1",
            "target_id": "e2",
            "relationship_type": RelType.DROVE_FOR,
            "description": "The text says he drives for the team.",
            "from_year": years.get("from_year"),
            "to_year": years.get("to_year"),
            "role": years.get("role"),
        }],
    )


class ValidateExtractionTest(unittest.TestCase):
    def test_empty_is_valid(self) -> None:
        validate_extraction(ExtractionResult())

    def test_drove_for_unknown_start_year(self) -> None:
        validate_extraction(_drove_for(from_year=None, to_year=None))

    def test_missing_endpoint(self) -> None:
        result = _drove_for()
        result.relationships[0].target_id = "e9"
        with self.assertRaises(ExtractionValidationError):
            validate_extraction(result)

    def test_duplicate_local_id(self) -> None:
        result = _drove_for()
        result.entities.append(_entity("e1", "Someone", EntityType.Driver))
        with self.assertRaises(ExtractionValidationError):
            validate_extraction(result)

    def test_disallowed_pair(self) -> None:
        result = ExtractionResult(
            entities=[
                _entity("e1", "Lewis Hamilton", EntityType.Driver),
                _entity("e2", "Ron Dennis", EntityType.Driver),
            ],
            relationships=[{
                "source_id": "e1",
                "target_id": "e2",
                "relationship_type": RelType.DROVE_FOR,
                "description": "Not a team endpoint.",
            }],
        )
        with self.assertRaises(ExtractionValidationError):
            validate_extraction(result)

    def test_bad_year_interval(self) -> None:
        with self.assertRaises(ExtractionValidationError):
            validate_extraction(_drove_for(from_year=2021, to_year=2020))

    def test_time_fields_rejected_on_non_temporal_edge(self) -> None:
        result = ExtractionResult(
            entities=[
                _entity("e1", "Ferrari", EntityType.Team),
                _entity("e2", "2021 title", EntityType.Title),
            ],
            relationships=[{
                "source_id": "e1",
                "target_id": "e2",
                "relationship_type": RelType.WON,
                "description": "Won the title.",
                "from_year": 2021,
            }],
        )
        with self.assertRaises(ExtractionValidationError):
            validate_extraction(result)

    def test_schema_lists_are_the_prompt_source(self) -> None:
        self.assertEqual(set(REL_SPECS), set(RelType))
        for kind in EntityType:
            self.assertIn(kind.value, SYSTEM_PROMPT)
        for rel in RelType:
            self.assertIn(rel.value, SYSTEM_PROMPT)
        self.assertNotIn("CONTAINS", {rel.value for rel in RelType})
        for phrase in (
            "young-driver programme",
            "seven titles",
            "Do not pick the nearest",
            "does not prove an unbroken interval",
            "no Title and no AWARDED_IN",
            "Do not emit WON or AWARDED_IN for that aggregate",
            "Driver -WON-> Title -AWARDED_IN-> Season",
            "Season even with no relationship",
            "does not prove a win",
            "ten wins",
            "Zero schema hits",
            "2013–2016",
            "Second winless year",
            "Do not add facts from background knowledge",
            "emit that relationship as an edge",
            "a driver or team won a specific championship title",
            "a specific championship title belongs to a season",
            "Formula One racing spell",
            "a specific Grand Prix is a round of a season",
        ):
            self.assertIn(phrase, SYSTEM_PROMPT)
        for spec in REL_SPECS.values():
            self.assertIn(spec.meaning, SYSTEM_PROMPT)


class RunExtractionTest(unittest.TestCase):
    def _paths(self, root: Path) -> dict:
        chunks = root / "chunks.jsonl"
        metadata = root / "metadata.json"
        out = root / "extraction"
        summary = root / "extraction-summary.md"
        metadata.write_text(json.dumps([{
            "doc_id": "d1", "title": "2021 Season Page", "file": "s.pdf",
        }]), encoding="utf-8")
        row = {
            "chunk_id": "d1#0",
            "doc_id": "d1",
            "section": None,
            "page": 1,
            "source": "https://example.test/s",
            "text": "Max Verstappen won the championship.",
        }
        chunks.write_text(json.dumps(row) + "\n", encoding="utf-8")
        return {"chunks_path": chunks, "metadata_path": metadata,
                "out_dir": out, "summary_path": summary}

    def test_title_is_attached_and_not_sent_as_provenance(self) -> None:
        seen = []

        def caller(payload):
            seen.append(payload)
            return ExtractionResult()

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
        self.assertEqual(code, 0)
        self.assertEqual(seen[0]["document_title"], "2021 Season Page")
        self.assertNotIn("chunk_id", seen[0])
        self.assertNotIn("source", seen[0])

    def test_dry_run_does_not_call_or_write(self) -> None:
        def caller(_payload):
            raise AssertionError("model was called")

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=False, overwrite=False,
                                  caller=caller, model="test-model")
            self.assertEqual(code, 0)
            self.assertFalse(paths["out_dir"].exists())
            self.assertFalse(paths["summary_path"].exists())

    def test_matching_success_is_not_called_again(self) -> None:
        def caller(_payload):
            raise AssertionError("model was called")

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            digest = input_hash(model="test-model",
                                document_title="2021 Season Page",
                                section=None,
                                text="Max Verstappen won the championship.")
            saved = paths["out_dir"] / f"{safe_stem('d1#0')}.json"
            saved.parent.mkdir(parents=True)
            saved.write_text(json.dumps({
                "chunk_id": "d1#0",
                "status": "ok",
                "model": "test-model",
                "prompt_version": PROMPT_VERSION,
                "input_hash": digest,
                "result": {"entities": [], "relationships": []},
            }), encoding="utf-8")
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            self.assertEqual(code, 0)

    def test_changed_input_is_not_reused(self) -> None:
        def caller(_payload):
            raise AssertionError("model was called")

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            saved = paths["out_dir"] / f"{safe_stem('d1#0')}.json"
            saved.parent.mkdir(parents=True)
            saved.write_text(json.dumps({
                "chunk_id": "d1#0",
                "status": "ok",
                "model": "other-model",
                "prompt_version": PROMPT_VERSION,
                "input_hash": "stale",
                "result": {"entities": [], "relationships": []},
            }), encoding="utf-8")
            with self.assertRaises(ReuseError):
                run_extraction(**paths, run=True, overwrite=False,
                               caller=caller, model="test-model")

    def test_model_error_is_not_an_empty_success(self) -> None:
        def caller(_payload):
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            self.assertEqual(code, 1)
            saved = json.loads(
                (paths["out_dir"] / f"{safe_stem('d1#0')}.json")
                .read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "error")
        self.assertNotIn("result", saved)
        self.assertNotIn("candidate_result", saved)
        self.assertIn("boom", saved["error"])

    def test_invalid_result_is_not_saved_as_success(self) -> None:
        def caller(_payload):
            result = _drove_for()
            result.relationships[0].target_id = "missing"
            return result

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            saved = json.loads(
                (paths["out_dir"] / f"{safe_stem('d1#0')}.json")
                .read_text(encoding="utf-8"))
            summary = paths["summary_path"].read_text(encoding="utf-8")
        self.assertEqual(code, 1)
        self.assertEqual(saved["status"], "error")
        self.assertNotIn("result", saved)
        self.assertEqual(
            saved["candidate_result"]["relationships"][0]["target_id"],
            "missing")
        self.assertIn("| `d1#0` | hiba |", summary)
        self.assertNotIn("| `d1#0` | siker |", summary)

    def test_error_record_is_not_reused_as_success(self) -> None:
        calls = []

        def caller(payload):
            calls.append(payload)
            return ExtractionResult()

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            digest = input_hash(model="test-model",
                                document_title="2021 Season Page",
                                section=None,
                                text="Max Verstappen won the championship.")
            saved_path = paths["out_dir"] / f"{safe_stem('d1#0')}.json"
            saved_path.parent.mkdir(parents=True)
            saved_path.write_text(json.dumps({
                "chunk_id": "d1#0",
                "status": "error",
                "model": "test-model",
                "prompt_version": PROMPT_VERSION,
                "input_hash": digest,
                "error": "old",
                "candidate_result": {"entities": [], "relationships": []},
            }), encoding="utf-8")
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertEqual(saved["status"], "error")
        self.assertEqual(saved["error"], "old")

    def test_retry_errors_reprocesses_a_matching_error(self) -> None:
        calls = []

        def caller(_payload):
            calls.append(_payload)
            return ExtractionResult()

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            digest = input_hash(model="test-model",
                                document_title="2021 Season Page",
                                section=None,
                                text="Max Verstappen won the championship.")
            saved_path = paths["out_dir"] / f"{safe_stem('d1#0')}.json"
            saved_path.parent.mkdir(parents=True)
            saved_path.write_text(json.dumps({
                "chunk_id": "d1#0",
                "status": "error",
                "model": "test-model",
                "prompt_version": PROMPT_VERSION,
                "input_hash": digest,
                "error": "old",
            }), encoding="utf-8")
            code = run_extraction(**paths, run=True, overwrite=False,
                                  retry_errors=True, caller=caller,
                                  model="test-model")
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(saved["status"], "ok")
        self.assertNotIn("candidate_result", saved)

    def test_changed_error_input_is_not_overwritten(self) -> None:
        def caller(_payload):
            raise AssertionError("model was called")

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            saved_path = paths["out_dir"] / f"{safe_stem('d1#0')}.json"
            saved_path.parent.mkdir(parents=True)
            saved_path.write_text(json.dumps({
                "chunk_id": "d1#0",
                "status": "error",
                "model": "test-model",
                "prompt_version": PROMPT_VERSION,
                "input_hash": "stale",
                "error": "old",
            }), encoding="utf-8")
            with self.assertRaises(ReuseError):
                run_extraction(**paths, run=True, overwrite=False,
                               retry_errors=True, caller=caller,
                               model="test-model")
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["input_hash"], "stale")

    def test_limit_processes_only_the_first_chunk(self) -> None:
        calls = []

        def caller(_payload):
            calls.append(_payload["text"])
            return ExtractionResult()

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            second = {
                "chunk_id": "d1#1",
                "doc_id": "d1",
                "section": None,
                "page": 1,
                "source": "https://example.test/s",
                "text": "A second chunk that must stay uncalled.",
            }
            with paths["chunks_path"].open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(second) + "\n")
            code = run_extraction(**paths, run=True, overwrite=False,
                                  limit=1, caller=caller, model="test-model")
            self.assertFalse((paths["out_dir"] / f"{safe_stem('d1#1')}.json").exists())
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["Max Verstappen won the championship."])

    def test_limited_dry_run_makes_no_call(self) -> None:
        def caller(_payload):
            raise AssertionError("model was called")

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=False, overwrite=False,
                                  limit=1, caller=caller, model="test-model")
            self.assertEqual(code, 0)
            self.assertFalse(paths["out_dir"].exists())

    def test_v3_output_is_separate_from_earlier_runs(self) -> None:
        out_dir, summary = pilot_output_paths()
        self.assertEqual(out_dir.name, "extraction-v3")
        self.assertEqual(summary.name, "extraction-summary-v3.md")
        self.assertNotIn(out_dir.name, {"extraction", "extraction-v2"})

    def test_reuse_dir_is_read_and_not_written(self) -> None:
        def caller(_payload):
            raise AssertionError("model was called")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root)
            digest = input_hash(model="test-model",
                                document_title="2021 Season Page",
                                section=None,
                                text="Max Verstappen won the championship.")
            reuse = root / "reuse"
            saved = reuse / f"{safe_stem('d1#0')}.json"
            saved.parent.mkdir()
            saved.write_text(json.dumps({
                "chunk_id": "d1#0",
                "status": "ok",
                "model": "test-model",
                "prompt_version": PROMPT_VERSION,
                "input_hash": digest,
                "result": {"entities": [], "relationships": []},
            }), encoding="utf-8")
            before = saved.read_bytes()
            code = run_extraction(**paths, run=True, overwrite=False,
                                  reuse_dirs=(reuse,), caller=caller,
                                  model="test-model")
            copied = paths["out_dir"] / saved.name
            self.assertEqual(code, 0)
            self.assertEqual(saved.read_bytes(), before)
            self.assertEqual(copied.read_bytes(), before)

    def test_doc_id_filter_excludes_other_documents(self) -> None:
        def caller(_payload):
            raise AssertionError("model was called")

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  doc_ids={"other-doc"}, caller=caller,
                                  model="test-model")
            self.assertEqual(code, 0)

    def test_authentication_stops_without_saving_or_calling_again(self) -> None:
        class AuthError(Exception):
            status_code = 401

        calls = []

        def caller(_payload):
            calls.append(1)
            raise AuthError("incorrect api key")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root)
            extra = {
                "chunk_id": "d1#1",
                "doc_id": "d1",
                "section": None,
                "page": 2,
                "source": "https://example.test/s",
                "text": "Another sentence about the championship.",
            }
            with paths["chunks_path"].open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(extra) + "\n")
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            self.assertEqual(code, 2)
            self.assertEqual(calls, [1])
            self.assertEqual(list(paths["out_dir"].glob("*.json")), [])
        self.assertEqual(failure_kind(AuthError("incorrect api key")),
                         "authentication")

    def test_repeated_service_failure_stops(self) -> None:
        class Down(Exception):
            status_code = 503

        calls = []

        def caller(_payload):
            calls.append(1)
            raise Down("unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = self._paths(root)
            lines = [
                json.dumps({
                    "chunk_id": f"d1#{index}",
                    "doc_id": "d1",
                    "section": None,
                    "page": index,
                    "source": "https://example.test/s",
                    "text": f"Sentence {index} about the championship.",
                })
                for index in range(4)
            ]
            paths["chunks_path"].write_text("\n".join(lines) + "\n",
                                            encoding="utf-8")
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            self.assertEqual(code, 2)
            self.assertEqual(len(calls), 3)
            self.assertEqual(list(paths["out_dir"].glob("*.json")), [])

    def test_ambiguous_manifest_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            paths["metadata_path"].write_text(json.dumps([
                {"doc_id": "d1", "title": "One", "file": "a"},
                {"doc_id": "d1", "title": "Two", "file": "b"},
            ]), encoding="utf-8")
            with self.assertRaises(InputError):
                run_extraction(**paths, run=True, overwrite=False,
                               caller=lambda _p: ExtractionResult(),
                               model="test-model")


if __name__ == "__main__":
    unittest.main()
