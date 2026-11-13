"""Offline checks for partial extraction filtering. No model and no corpus."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag.extract_pilot import refilter_record, refilter_saved
from naive_rag.extraction_identity import (
    canonical_identity,
    canonicalize_result,
    identity_rejection,
)
from naive_rag.extraction_models import (
    PARTIAL_VALIDATION_VERSION,
    Entity,
    EntityType,
    ExtractionResult,
    ExtractionValidationError,
    RelType,
    align_extraction,
    filter_extraction,
    read_extraction_candidate,
    validate_extraction,
)


def _entity(local_id: str, name: str, kind: EntityType) -> dict:
    return {
        "local_id": local_id,
        "name": name,
        "entity_type": kind.value,
        "description": f"{name} as stated in the text.",
    }


def _edge(source: str, target: str, kind: RelType, **extra) -> dict:
    body = {
        "source_id": source,
        "target_id": target,
        "relationship_type": kind.value,
        "description": "The text states this relationship.",
        "from_year": None,
        "to_year": None,
        "role": None,
    }
    body.update(extra)
    return body


def _result(*entities: dict, relationships: list[dict] | None = None,
            ) -> ExtractionResult:
    return ExtractionResult.model_validate({
        "entities": list(entities),
        "relationships": relationships or [],
    })


class FilterExtractionTests(unittest.TestCase):
    def test_self_loop_is_dropped_and_the_other_edge_stays(self) -> None:
        description = (
            "Nico Rosberg was teammates with Lewis Hamilton "
            "from 2013 to 2016."
        )
        result = _result(
            _entity("e1", "Nico Rosberg", EntityType.Driver),
            _entity("e2", "Lewis Hamilton", EntityType.Driver),
            relationships=[
                _edge("e1", "e1", RelType.TEAMMATE_OF, description=description),
                _edge("e1", "e2", RelType.TEAMMATE_OF, description=description),
            ],
        )
        accepted, rejections = filter_extraction(result)
        self.assertEqual(
            [item.reason for item in rejections],
            ["TEAMMATE_OF: source_id equals target_id"],
        )
        self.assertEqual(len(accepted.relationships), 1)
        self.assertEqual(accepted.relationships[0].target_id, "e2")
        validate_extraction(accepted)

    def test_valid_result_is_unchanged(self) -> None:
        result = _result(
            _entity("e1", "Lewis Hamilton", EntityType.Driver),
            _entity("e2", "Ferrari", EntityType.Team),
            relationships=[_edge("e1", "e2", RelType.DROVE_FOR, from_year=2010)],
        )
        accepted, rejections = filter_extraction(result)
        self.assertEqual(rejections, [])
        self.assertEqual(accepted.model_dump(), result.model_dump())
        validate_extraction(accepted)

    def test_bad_edge_does_not_drop_a_good_edge(self) -> None:
        result = _result(
            _entity("e1", "Lewis Hamilton", EntityType.Driver),
            _entity("e2", "Ferrari", EntityType.Team),
            _entity("e3", "McLaren", EntityType.Team),
            relationships=[
                _edge("e1", "e2", RelType.DROVE_FOR),
                _edge("e1", "missing", RelType.DROVE_FOR),
                _edge("e1", "e3", RelType.DROVE_FOR, from_year=2007),
            ],
        )
        accepted, rejections = filter_extraction(result)
        self.assertEqual([item.index for item in rejections], [1])
        self.assertEqual(
            [(rel.source_id, rel.target_id) for rel in accepted.relationships],
            [("e1", "e2"), ("e1", "e3")],
        )
        validate_extraction(accepted)

    def test_unknown_endpoint_is_dropped(self) -> None:
        result = _result(
            _entity("e1", "Lewis Hamilton", EntityType.Driver),
            _entity("e2", "Ferrari", EntityType.Team),
            relationships=[_edge("e1", "e9", RelType.DROVE_FOR)],
        )
        accepted, rejections = filter_extraction(result)
        self.assertEqual(len(accepted.entities), 2)
        self.assertEqual(accepted.relationships, [])
        self.assertEqual(rejections[0].element, "relationship")
        self.assertEqual(rejections[0].index, 0)
        self.assertIn("unknown target_id", rejections[0].reason)
        validate_extraction(accepted)

    def test_duplicate_local_id_rejects_every_use(self) -> None:
        result = _result(
            _entity("e1", "Lewis Hamilton", EntityType.Driver),
            _entity("e1", "Someone else", EntityType.Team),
            _entity("e2", "Ferrari", EntityType.Team),
            _entity("e3", "Nico Rosberg", EntityType.Driver),
            relationships=[
                _edge("e1", "e2", RelType.DROVE_FOR),
                _edge("e3", "e2", RelType.DROVE_FOR),
            ],
        )
        accepted, rejections = filter_extraction(result)
        self.assertEqual(
            [entity.local_id for entity in accepted.entities], ["e2", "e3"])
        self.assertEqual(accepted.relationships[0].source_id, "e3")
        entity_hits = [item for item in rejections if item.element == "entity"]
        self.assertEqual([item.index for item in entity_hits], [0, 1])
        dropped = next(item for item in rejections
                       if item.element == "relationship")
        self.assertEqual(dropped.index, 0)
        self.assertIn("duplicate local_id", dropped.reason)
        validate_extraction(accepted)

    def test_bad_interval_and_forbidden_time_are_dropped(self) -> None:
        result = _result(
            _entity("e1", "Lewis Hamilton", EntityType.Driver),
            _entity("e2", "Ferrari", EntityType.Team),
            _entity("e3", "Nico Rosberg", EntityType.Driver),
            relationships=[
                _edge("e1", "e2", RelType.DROVE_FOR,
                      from_year=2021, to_year=2020),
                _edge("e1", "e3", RelType.TEAMMATE_OF, from_year=2013),
                _edge("e1", "e2", RelType.DROVE_FOR, from_year=2010,
                      to_year=2012),
            ],
        )
        accepted, rejections = filter_extraction(result)
        self.assertEqual([item.index for item in rejections], [0, 1])
        self.assertIn("from_year", rejections[0].reason)
        self.assertIn("not temporal", rejections[1].reason)
        self.assertEqual(accepted.relationships[0].from_year, 2010)
        validate_extraction(accepted)

    def test_empty_extraction_is_accepted(self) -> None:
        accepted, rejections = filter_extraction(ExtractionResult())
        self.assertEqual(rejections, [])
        self.assertEqual(accepted.entities, [])
        self.assertEqual(accepted.relationships, [])
        validate_extraction(accepted)


class RefilterCommandTests(unittest.TestCase):
    def test_saved_records_are_copied_without_changing_the_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "in"
            output = Path(tmp) / "out"
            source.mkdir()
            ok_path = source / "ok.json"
            missing_path = source / "missing.json"
            ok_path.write_text(json.dumps({
                "chunk_id": "driver-lewis-hamilton#0",
                "doc_id": "driver-lewis-hamilton",
                "document_title": "Lewis Hamilton",
                "section": None,
                "page": 1,
                "source": "https://example.test/hamilton",
                "model": "gpt-4o-mini",
                "prompt_version": "f1-pilot-3",
                "input_hash": "abc123",
                "status": "ok",
                "result": {
                    "entities": [
                        _entity("e1", "Lewis Hamilton", EntityType.Driver),
                        _entity("e2", "Ferrari", EntityType.Team),
                    ],
                    "relationships": [
                        _edge("e1", "e2", RelType.DROVE_FOR),
                        _edge("e1", "e9", RelType.DROVE_FOR),
                    ],
                },
            }, ensure_ascii=False), encoding="utf-8")
            missing_path.write_text(json.dumps({
                "chunk_id": "season-2021#1",
                "input_hash": "def456",
                "status": "error",
                "error": "ExtractionValidationError: unknown target_id",
            }, ensure_ascii=False), encoding="utf-8")
            before = ok_path.read_bytes()
            code = refilter_saved(source, output)
            self.assertEqual(code, 0)
            self.assertEqual(ok_path.read_bytes(), before)

            saved = json.loads((output / "ok.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["input_hash"], "abc123")
            self.assertEqual(saved["source"], "https://example.test/hamilton")
            self.assertEqual(saved["validation_version"],
                             PARTIAL_VALIDATION_VERSION)
            self.assertEqual(saved["status"], "ok")
            self.assertEqual(len(saved["result"]["relationships"]), 1)
            self.assertEqual(saved["rejections"][0]["index"], 1)
            validate_extraction(ExtractionResult.model_validate(saved["result"]))

            missing = json.loads(
                (output / "missing.json").read_text(encoding="utf-8"))
            self.assertEqual(missing["status"], "unprocessable")
            self.assertNotIn("result", missing)
            self.assertEqual(missing["input_hash"], "def456")
            self.assertIsNone(missing["rejections"][0]["index"])

            again = refilter_saved(source, output)
            self.assertEqual(again, 1)
            self.assertEqual(ok_path.read_bytes(), before)

    def test_error_record_uses_the_candidate(self) -> None:
        record = {
            "chunk_id": "a#0",
            "input_hash": "hash",
            "status": "error",
            "candidate_result": {
                "entities": [
                    _entity("e1", "Lewis Hamilton", EntityType.Driver),
                    _entity("e2", "Ferrari", EntityType.Team),
                ],
                "relationships": [],
            },
        }
        produced = refilter_record(record)
        self.assertEqual(produced["status"], "ok")
        self.assertEqual(produced["input_hash"], "hash")
        self.assertEqual(produced["result"]["entities"][0]["local_id"], "e1")
        self.assertEqual(record["status"], "error")


class IdentityFilterTests(unittest.TestCase):
    def test_placeholder_rule_is_narrow(self) -> None:
        self.assertIsNone(identity_rejection("2016"))
        self.assertIsNone(identity_rejection("Keke Rosberg"))
        self.assertIsNone(identity_rejection("n/a"))
        self.assertIsNone(identity_rejection("unknown"))
        for name in (None, "", "   ", "\t"):
            self.assertIsNotNone(identity_rejection(name))
        for name in ("null", "NULL", " None ", "nil", "undefined"):
            reason = identity_rejection(name)
            self.assertIn("placeholder", reason or "")

    def test_null_season_is_dropped_and_a_year_stays(self) -> None:
        result = _result(
            _entity("e1", "Keke Rosberg", EntityType.Driver),
            _entity("e2", "null", EntityType.Season),
            _entity("e3", "2016", EntityType.Season),
            _entity("e4", "Williams", EntityType.Team),
            relationships=[
                _edge("e4", "e2", RelType.ENTERED),
                _edge("e1", "e4", RelType.DROVE_FOR, from_year=None),
                _edge("e4", "e3", RelType.ENTERED),
            ],
        )
        accepted, rejections = filter_extraction(result)
        self.assertEqual(
            [entity.name for entity in accepted.entities],
            ["Keke Rosberg", "2016", "Williams"])
        self.assertEqual(
            [(rel.source_id, rel.target_id) for rel in accepted.relationships],
            [("e1", "e4"), ("e4", "e3")])
        self.assertIn("placeholder", rejections[0].reason)
        self.assertIn("e2", rejections[1].reason)
        validate_extraction(accepted)

    def test_missing_description_and_years_do_not_reject_a_name(self) -> None:
        raw = {
            "entities": [{
                "local_id": "e1",
                "name": "Niki Lauda",
                "entity_type": "Driver",
            }],
            "relationships": [],
        }
        candidate, rejections = read_extraction_candidate(raw)
        self.assertEqual(rejections, [])
        self.assertEqual(candidate.entities[0].description, "")
        accepted, filtered = filter_extraction(candidate)
        self.assertEqual(filtered, [])
        self.assertEqual(accepted.entities[0].name, "Niki Lauda")

    def test_description_text_is_not_used_as_a_name(self) -> None:
        result = _result(
            _entity("e1", "2016", EntityType.Season),
        )
        result.entities[0].description = "null"
        accepted, rejections = filter_extraction(result)
        self.assertEqual(rejections, [])
        self.assertEqual(accepted.entities[0].name, "2016")

    def test_only_bad_candidates_leave_an_empty_result(self) -> None:
        raw = {
            "entities": [
                {"local_id": "e1", "name": None, "entity_type": "Season",
                 "description": "Missing year."},
                {"local_id": "e2", "name": "   ", "entity_type": "Team",
                 "description": "Blank."},
                {"local_id": "e3", "name": "null", "entity_type": "Season",
                 "description": "No specific season year mentioned."},
            ],
            "relationships": [_edge("e1", "e3", RelType.ROUND_OF)],
        }
        candidate, parse_rejections = read_extraction_candidate(raw)
        accepted, rejections = filter_extraction(candidate)
        self.assertEqual(accepted.entities, [])
        self.assertEqual(accepted.relationships, [])
        self.assertGreaterEqual(len(parse_rejections) + len(rejections), 3)
        validate_extraction(accepted)

    def test_unreadable_shape_is_still_rejected_as_a_whole(self) -> None:
        with self.assertRaises(ExtractionValidationError):
            read_extraction_candidate({"entities": "not a list"})

    def test_aligned_season_and_aliases_stay(self) -> None:
        result = ExtractionResult.model_validate({
            "entities": [
                _entity("e1", "Hamilton", EntityType.Driver),
                _entity("e2", "Autosport Award", EntityType.Title),
                _entity("e3", "Mercedes", EntityType.Team),
            ],
            "relationships": [
                _edge("e1", "e2", RelType.WON, from_year=2006,
                      description="Hamilton won the 2006 award."),
                _edge("e1", "e3", RelType.DROVE_FOR),
            ],
        })
        aligned, _refusals, alignments = align_extraction(result)
        accepted, rejections = filter_extraction(aligned)
        stored = canonicalize_result(accepted)
        self.assertEqual(alignments[0].action, "move_won_year")
        self.assertEqual(rejections, [])
        names = {entity.name for entity in stored.entities}
        self.assertIn("2006", names)
        self.assertIn("Lewis Hamilton", names)
        self.assertIn("Mercedes-AMG Petronas Formula One Team", names)
        driver_key, _display, _norm = canonical_identity(
            EntityType.Driver, "Hamilton")
        team_key, _display, _norm = canonical_identity(
            EntityType.Team, "Mercedes")
        self.assertEqual(driver_key, "Driver:lewis hamilton")
        self.assertEqual(
            team_key, "Team:mercedes-amg petronas formula one team")

    def test_refilter_keeps_source_ids_and_is_stable(self) -> None:
        record = {
            "chunk_id": "driver-fernando-alonso#24",
            "doc_id": "driver-fernando-alonso",
            "document_title": "Fernando Alonso",
            "section": "Career",
            "page": 2,
            "source": "https://example.test/alonso",
            "model": "test-model",
            "prompt_version": "f1-pilot-3",
            "input_hash": "hash-alonso",
            "status": "ok",
            "result": {
                "entities": [
                    _entity("e1", "Fernando Alonso", EntityType.Driver),
                    _entity("e2", "null", EntityType.Season),
                    _entity("e3", "2010", EntityType.Season),
                ],
                "relationships": [
                    _edge("e4", "e2", RelType.ENTERED),
                    _edge("e4", "e3", RelType.ENTERED),
                ],
            },
        }
        record["result"]["entities"].append(
            _entity("e4", "Ferrari", EntityType.Team))
        first = refilter_record(record)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["chunk_id"], "driver-fernando-alonso#24")
        self.assertEqual(first["input_hash"], "hash-alonso")
        self.assertEqual(first["source"], "https://example.test/alonso")
        names = [item["name"] for item in first["result"]["entities"]]
        self.assertEqual(names, ["Fernando Alonso", "2010", "Scuderia Ferrari"])
        self.assertEqual(first["entities_rejected"], 1)
        self.assertEqual(first["relationships_rejected"], 1)
        self.assertIn("placeholder", first["rejections"][0]["reason"])
        self.assertEqual(record["result"]["entities"][1]["name"], "null")
        second = refilter_record(first)
        self.assertEqual(second["result"], first["result"])
        self.assertEqual(second["chunk_id"], first["chunk_id"])
        self.assertEqual(second["rejections"], [])


if __name__ == "__main__":
    unittest.main()
