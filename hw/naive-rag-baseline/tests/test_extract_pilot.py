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
    Relationship,
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

    def test_self_loop_is_rejected(self) -> None:
        result = ExtractionResult(
            entities=[_entity("e1", "Nico Rosberg", EntityType.Driver)],
            relationships=[{
                "source_id": "e1",
                "target_id": "e1",
                "relationship_type": RelType.TEAMMATE_OF,
                "description": (
                    "Nico Rosberg was teammates with Lewis Hamilton "
                    "from 2013 to 2016."
                ),
            }],
        )
        with self.assertRaises(ExtractionValidationError) as caught:
            validate_extraction(result)
        self.assertEqual(
            str(caught.exception),
            "TEAMMATE_OF: source_id equals target_id",
        )

    def test_two_drivers_are_not_a_self_loop(self) -> None:
        result = ExtractionResult(
            entities=[
                _entity("e1", "Nico Rosberg", EntityType.Driver),
                _entity("e2", "Lewis Hamilton", EntityType.Driver),
            ],
            relationships=[{
                "source_id": "e1",
                "target_id": "e2",
                "relationship_type": RelType.TEAMMATE_OF,
                "description": (
                    "Nico Rosberg was teammates with Lewis Hamilton "
                    "from 2013 to 2016."
                ),
            }],
        )
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

    def test_one_bad_relationship_keeps_the_rest_of_the_extraction(self) -> None:
        def caller(_payload):
            result = _drove_for()
            result.entities.append(
                _entity("e3", "Mercedes", EntityType.Team))
            result.relationships.append(Relationship(
                source_id="e1", target_id="missing",
                relationship_type=RelType.DROVE_FOR,
                description="This endpoint is not in the extraction.",
            ))
            result.relationships.append(Relationship(
                source_id="e1", target_id="e3",
                relationship_type=RelType.DROVE_FOR,
                description="The text states the Mercedes spell.",
                from_year=2007, to_year=2012,
            ))
            return result

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            saved = json.loads(
                (paths["out_dir"] / f"{safe_stem('d1#0')}.json")
                .read_text(encoding="utf-8"))
            summary = paths["summary_path"].read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(saved["status"], "ok")
        self.assertEqual(saved["chunk_id"], "d1#0")
        self.assertEqual(saved["document_title"], "2021 Season Page")
        self.assertEqual(saved["source"], "https://example.test/s")
        self.assertEqual(saved["page"], 1)
        self.assertEqual(saved["model"], "test-model")
        self.assertEqual(saved["prompt_version"], PROMPT_VERSION)
        self.assertTrue(saved["input_hash"])
        kept = saved["result"]["relationships"]
        self.assertEqual(
            [(item["source_id"], item["target_id"], item["from_year"])
             for item in kept],
            [("e1", "e2", None), ("e1", "e3", 2007)],
        )
        self.assertEqual(kept[1]["description"],
                         "The text states the Mercedes spell.")
        self.assertEqual(saved["relationship_candidates"], 3)
        self.assertEqual(saved["relationships_accepted"], 2)
        self.assertEqual(saved["relationships_rejected"], 1)
        self.assertEqual(saved["rejections"][0]["index"], 1)
        self.assertIn("unknown target_id", saved["rejections"][0]["reason"])
        self.assertNotIn("candidate_result", saved)
        self.assertIn("| `d1#0` | siker |", summary)
        self.assertIn("elutasított: 1", summary)
        self.assertNotIn("| `d1#0` | hiba |", summary)

    def test_every_relationship_valid_is_saved(self) -> None:
        def caller(_payload):
            return _drove_for(from_year=2014, to_year=2016)

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            saved = json.loads(
                (paths["out_dir"] / f"{safe_stem('d1#0')}.json")
                .read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(saved["relationship_candidates"], 1)
        self.assertEqual(saved["relationships_accepted"], 1)
        self.assertEqual(saved["relationships_rejected"], 0)
        self.assertEqual(saved["rejections"], [])
        self.assertEqual(saved["result"]["relationships"][0]["from_year"], 2014)

    def test_every_relationship_rejected_keeps_entities(self) -> None:
        def caller(_payload):
            result = _drove_for()
            result.relationships[0].target_id = "missing"
            result.relationships.append(Relationship(
                source_id="e2", target_id="e1",
                relationship_type=RelType.DROVE_FOR,
                description="The direction is not allowed.",
            ))
            return result

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            saved = json.loads(
                (paths["out_dir"] / f"{safe_stem('d1#0')}.json")
                .read_text(encoding="utf-8"))
            summary = paths["summary_path"].read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(saved["status"], "ok")
        self.assertEqual(saved["result"]["relationships"], [])
        self.assertEqual(len(saved["result"]["entities"]), 2)
        self.assertEqual(saved["relationship_candidates"], 2)
        self.assertEqual(saved["relationships_accepted"], 0)
        self.assertEqual(saved["relationships_rejected"], 2)
        self.assertIn("unknown target_id", saved["rejections"][0]["reason"])
        self.assertIn("does not allow", saved["rejections"][1]["reason"])
        self.assertIn("elutasított: 2", summary)

    def test_empty_relationship_list_is_success(self) -> None:
        def caller(_payload):
            return ExtractionResult(
                entities=[_entity("e1", "Lewis Hamilton", EntityType.Driver)])

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            saved = json.loads(
                (paths["out_dir"] / f"{safe_stem('d1#0')}.json")
                .read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(saved["status"], "ok")
        self.assertEqual(saved["result"]["relationships"], [])
        self.assertEqual(saved["relationship_candidates"], 0)
        self.assertEqual(saved["relationships_rejected"], 0)

    def test_unreadable_response_is_not_a_successful_extraction(self) -> None:
        def caller(_payload):
            return {"entities": "not a list"}

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
        self.assertNotIn("candidate_result", saved)
        self.assertNotIn("relationships_accepted", saved)
        self.assertIn("| `d1#0` | hiba |", summary)
        self.assertNotIn("| `d1#0` | siker |", summary)

    def test_entry_point_aligns_a_mocked_response(self) -> None:
        def caller(_payload):
            return ExtractionResult(
                entities=[
                    _entity("e1", "Lewis Hamilton", EntityType.Driver),
                    _entity("e2", "Mercedes", EntityType.Team),
                    _entity("e3", "British Grand Prix", EntityType.GrandPrix),
                    _entity("e4", "2014", EntityType.Season),
                    _entity("e5", "World Drivers' Championship", EntityType.Title),
                ],
                relationships=[
                    Relationship(
                        source_id="e1", target_id="e2",
                        relationship_type=RelType.DROVE_FOR,
                        description="Hamilton drove for Mercedes.",
                        from_year=2013, to_year=2024,
                    ),
                    Relationship(
                        source_id="e1", target_id="e3",
                        relationship_type=RelType.ACHIEVED,
                        description="Hamilton won the British Grand Prix.",
                    ),
                    Relationship(
                        source_id="e1", target_id="e5",
                        relationship_type=RelType.WON,
                        description="Hamilton won the world title in 2014.",
                        from_year=2014,
                    ),
                    Relationship(
                        source_id="e1", target_id="e4",
                        relationship_type=RelType.WON,
                        description="The season edge does not name a title.",
                    ),
                ],
            )

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            saved = json.loads(
                (paths["out_dir"] / f"{safe_stem('d1#0')}.json")
                .read_text(encoding="utf-8"))
            summary = paths["summary_path"].read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(saved["status"], "ok")
        self.assertEqual(saved["chunk_id"], "d1#0")
        self.assertEqual(saved["source"], "https://example.test/s")
        self.assertEqual(saved["page"], 1)
        self.assertEqual(saved["document_title"], "2021 Season Page")
        self.assertTrue(saved["input_hash"])
        kinds = [item["relationship_type"]
                 for item in saved["result"]["relationships"]]
        self.assertEqual(
            kinds, ["DROVE_FOR", "ACHIEVED", "AT_RACE", "WON", "AWARDED_IN"])
        self.assertEqual(
            saved["result"]["relationships"][4]["target_id"], "e4")
        self.assertEqual(
            saved["result"]["relationships"][4]["description"],
            "Hamilton won the world title in 2014.")
        drove = saved["result"]["relationships"][0]
        self.assertEqual(drove["from_year"], 2013)
        self.assertEqual(drove["to_year"], 2024)
        self.assertEqual(drove["description"], "Hamilton drove for Mercedes.")
        self.assertEqual(saved["relationship_candidates"], 4)
        self.assertEqual(saved["relationships_rejected"], 1)
        self.assertIn("does not allow Driver -> Season",
                      saved["rejections"][0]["reason"])
        actions = [item["action"] for item in saved["alignments"]]
        self.assertEqual(actions, ["reify_race_result", "move_won_year"])
        self.assertIn("Átalakítva", summary)
        self.assertIn("elutasított: 1", summary)

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
            record = json.loads(copied.read_text(encoding="utf-8"))
            self.assertEqual(record["chunk_id"], "d1#0")
            self.assertEqual(record["status"], "ok")
            self.assertEqual(record["result"],
                             {"entities": [], "relationships": []})
            self.assertNotEqual(copied.read_bytes(), before)

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

    def test_entry_point_rejects_null_names_and_keeps_the_rest(self) -> None:
        def caller(_payload):
            return {
                "entities": [
                    {
                        "local_id": "e1",
                        "name": "Lewis Hamilton",
                        "entity_type": "Driver",
                        "description": "British racing driver.",
                    },
                    {
                        "local_id": "e2",
                        "name": "null",
                        "entity_type": "Season",
                        "description": "No specific season year mentioned.",
                    },
                    {
                        "local_id": "e3",
                        "name": "2016",
                        "entity_type": "Season",
                        "description": "The 2016 season.",
                    },
                    {
                        "local_id": "e4",
                        "name": "Williams",
                        "entity_type": "Team",
                        "description": "A team named in the text.",
                    },
                ],
                "relationships": [
                    {
                        "source_id": "e1",
                        "target_id": "e4",
                        "relationship_type": "DROVE_FOR",
                        "description": "The text states the spell.",
                        "from_year": None,
                        "to_year": None,
                        "role": None,
                    },
                    {
                        "source_id": "e4",
                        "target_id": "e2",
                        "relationship_type": "ENTERED",
                        "description": "No year was stored on this edge.",
                        "from_year": None,
                        "to_year": None,
                        "role": None,
                    },
                    {
                        "source_id": "e4",
                        "target_id": "e3",
                        "relationship_type": "ENTERED",
                        "description": "Williams entered the 2016 season.",
                        "from_year": None,
                        "to_year": None,
                        "role": None,
                    },
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            saved = json.loads(
                (paths["out_dir"] / f"{safe_stem('d1#0')}.json")
                .read_text(encoding="utf-8"))
            summary = paths["summary_path"].read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertEqual(saved["status"], "ok")
        self.assertEqual(saved["chunk_id"], "d1#0")
        self.assertEqual(saved["input_hash"] != "", True)
        names = [item["name"] for item in saved["result"]["entities"]]
        self.assertEqual(names, ["Lewis Hamilton", "2016", "Williams"])
        kept = [(item["source_id"], item["target_id"])
                for item in saved["result"]["relationships"]]
        self.assertEqual(kept, [("e1", "e4"), ("e4", "e3")])
        self.assertEqual(saved["entity_candidates"], 4)
        self.assertEqual(saved["entities_rejected"], 1)
        self.assertEqual(saved["relationships_rejected"], 1)
        self.assertIn("placeholder", saved["rejections"][0]["reason"])
        self.assertIn("Entitásjelöltek", summary)
        self.assertIn("elutasított: 1", summary)
        self.assertNotIn("Season:null", json.dumps(saved["result"]))

    def test_entry_point_with_only_bad_entities_stays_a_successful_record(self) -> None:
        def caller(_payload):
            return {
                "entities": [{
                    "local_id": "e1",
                    "name": None,
                    "entity_type": "Season",
                    "description": "No year.",
                }],
                "relationships": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            code = run_extraction(**paths, run=True, overwrite=False,
                                  caller=caller, model="test-model")
            saved = json.loads(
                (paths["out_dir"] / f"{safe_stem('d1#0')}.json")
                .read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(saved["status"], "ok")
        self.assertEqual(saved["result"]["entities"], [])
        self.assertEqual(saved["entities_rejected"], 1)
        self.assertIn("invalid entity", saved["rejections"][0]["reason"])
        self.assertNotIn("candidate_result", saved)


if __name__ == "__main__":
    unittest.main()
