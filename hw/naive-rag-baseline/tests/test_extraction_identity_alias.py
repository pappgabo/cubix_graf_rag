"""Offline checks for canonical entity names. No model and no database."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag.extract_pilot import refilter_record, run_extraction, safe_stem
from naive_rag.extraction_identity import (
    ALIAS_MAP,
    canonical_identity,
    canonicalize_result,
)
from naive_rag.extraction_load import _build_plan
from naive_rag.extraction_models import (
    EntityType,
    ExtractionResult,
    RelType,
    validate_extraction,
)
from naive_rag.graph_merge import merged_graph


MERCEDES = "Mercedes-AMG Petronas Formula One Team"
MERCEDES_KEY = "Team:mercedes-amg petronas formula one team"


def _entity(local_id: str, name: str, kind: EntityType,
            description: str | None = None) -> dict:
    return {
        "local_id": local_id,
        "name": name,
        "entity_type": kind.value,
        "description": description or f"{name} as stated in the text.",
    }


def _drove(source: str, target: str, **extra) -> dict:
    body = {
        "source_id": source,
        "target_id": target,
        "relationship_type": RelType.DROVE_FOR.value,
        "description": extra.pop("description", "The text states this spell."),
        "from_year": None,
        "to_year": None,
        "role": None,
    }
    body.update(extra)
    return body


def _result(*entities: dict, relationships: list[dict] | None = None):
    return ExtractionResult.model_validate({
        "entities": list(entities),
        "relationships": relationships or [],
    })


class ExistingAliasTests(unittest.TestCase):
    def test_hamilton_ferrari_and_red_bull_stay_canonical(self) -> None:
        self.assertEqual(
            canonical_identity(EntityType.Driver, "Hamilton"),
            ("Driver:lewis hamilton", "Lewis Hamilton", "lewis hamilton"))
        self.assertEqual(
            canonical_identity(EntityType.Team, "Ferrari"),
            ("Team:scuderia ferrari", "Scuderia Ferrari", "scuderia ferrari"))
        self.assertEqual(
            canonical_identity(EntityType.Team, "Red Bull"),
            ("Team:red bull racing", "Red Bull Racing", "red bull racing"))
        self.assertEqual(ALIAS_MAP["Driver:hamilton"], "Driver:lewis hamilton")
        self.assertEqual(ALIAS_MAP["Team:ferrari"], "Team:scuderia ferrari")
        self.assertEqual(ALIAS_MAP["Team:red bull"], "Team:red bull racing")


class MercedesAliasTests(unittest.TestCase):
    def test_team_name_variants_share_one_identity(self) -> None:
        for name in (
            "Mercedes",
            "Mercedes GP",
            "Mercedes AMG",
            "Mercedes GP Petronas Formula One Team",
            "Mercedes F1",
            "Mercedes F1 Team",
            MERCEDES,
        ):
            key, display, name_norm = canonical_identity(EntityType.Team, name)
            self.assertEqual(key, MERCEDES_KEY, name)
            self.assertEqual(display, MERCEDES)
            self.assertEqual(name_norm, "mercedes-amg petronas formula one team")

    def test_endpoints_descriptions_and_years_survive_the_merge(self) -> None:
        result = _result(
            _entity("e1", "Lewis Hamilton", EntityType.Driver,
                    "Hamilton drove for the team."),
            _entity("e2", "Mercedes", EntityType.Team,
                    "The works Formula 1 team."),
            _entity("e3", "Mercedes GP", EntityType.Team,
                    "The 2010 name of the same team."),
            relationships=[
                _drove("e1", "e2", from_year=2013, to_year=2020,
                       description="Hamilton's later spell."),
                _drove("e1", "e3", from_year=2010, to_year=2012,
                       description="Schumacher's earlier spell."),
                _drove("e1", "e2", from_year=2013, to_year=2020,
                       description="The same spell stated again."),
            ],
        )
        once = canonicalize_result(result)
        twice = canonicalize_result(once)
        validate_extraction(once)
        self.assertEqual(once.model_dump(), twice.model_dump())
        self.assertEqual(
            [entity.name for entity in once.entities],
            ["Lewis Hamilton", MERCEDES])
        self.assertEqual(once.entities[1].local_id, "e2")
        self.assertIn("works Formula 1 team", once.entities[1].description)
        self.assertIn("2010 name", once.entities[1].description)
        years = {(rel.from_year, rel.to_year, rel.target_id, rel.description)
                 for rel in once.relationships}
        self.assertEqual(years, {
            (2013, 2020, "e2",
             "Hamilton's later spell.\nThe same spell stated again."),
            (2010, 2012, "e2", "Schumacher's earlier spell."),
        })

    def test_loader_and_merge_use_the_same_team_key(self) -> None:
        result = _result(
            _entity("e1", "Lewis Hamilton", EntityType.Driver),
            _entity("e2", "Mercedes F1 Team", EntityType.Team),
            relationships=[_drove("e1", "e2", from_year=2017, role="race driver",
                                  description="The Mercedes spell.")],
        )
        plan = _build_plan(result, "driver-lewis-hamilton#0")
        graph = merged_graph([{
            "chunk_id": "driver-lewis-hamilton#0",
            "status": "ok",
            "result": result.model_dump(mode="json"),
        }])
        self.assertEqual(plan.entities[1].entity_key, MERCEDES_KEY)
        self.assertEqual(plan.entities[1].name, MERCEDES)
        self.assertEqual(plan.relationships[0].target_key, MERCEDES_KEY)
        self.assertEqual(plan.relationships[0].from_year, 2017)
        self.assertEqual(plan.relationships[0].role, "race driver")
        self.assertEqual(plan.relationships[0].description, "The Mercedes spell.")
        self.assertEqual(plan.chunk_id, "driver-lewis-hamilton#0")
        edge = graph.edges[0]
        self.assertEqual(edge.target_id, MERCEDES_KEY)
        self.assertEqual(edge.source_chunk_ids, ("driver-lewis-hamilton#0",))
        self.assertEqual(edge.from_year, 2017)
        self.assertEqual(edge.role, "race driver")

    def test_ambiguous_names_stay_separate(self) -> None:
        pairs = [
            (EntityType.Driver, "Rosberg", "Driver:rosberg"),
            (EntityType.Driver, "Nico Rosberg", "Driver:nico rosberg"),
            (EntityType.Driver, "Keke Rosberg", "Driver:keke rosberg"),
            (EntityType.Team, "Mercedes-Benz", "Team:mercedes-benz"),
            (EntityType.PowerUnit, "Mercedes", "PowerUnit:mercedes"),
            (EntityType.Team, "Mercedes AMG High Performance Powertrains",
             "Team:mercedes amg high performance powertrains"),
            (EntityType.Team, "McLaren-Mercedes", "Team:mclaren-mercedes"),
            (EntityType.Car, "Mercedes F1 W03", "Car:mercedes f1 w03"),
        ]
        keys = []
        for kind, name, expected in pairs:
            key, display, _norm = canonical_identity(kind, name)
            self.assertEqual(key, expected, name)
            self.assertEqual(display, name)
            keys.append(key)
        self.assertEqual(len(keys), len(set(keys)))
        result = _result(
            _entity("e1", "Rosberg", EntityType.Driver, "A driver in 2010."),
            _entity("e2", "Nico Rosberg", EntityType.Driver, "The 2016 champion."),
            _entity("e3", "Mercedes", EntityType.Team, "The works team."),
            _entity("e4", "Mercedes", EntityType.PowerUnit, "An engine supplier."),
        )
        kept = canonicalize_result(result)
        self.assertEqual(
            [(entity.entity_type, entity.name) for entity in kept.entities],
            [
                (EntityType.Driver, "Rosberg"),
                (EntityType.Driver, "Nico Rosberg"),
                (EntityType.Team, MERCEDES),
                (EntityType.PowerUnit, "Mercedes"),
            ])


class CanonicalPathTests(unittest.TestCase):
    def test_extraction_and_refilter_agree(self) -> None:
        def caller(_payload):
            return _result(
                _entity("e1", "Lewis Hamilton", EntityType.Driver,
                        "Hamilton drove for Mercedes."),
                _entity("e2", "Mercedes", EntityType.Team, "The works team."),
                _entity("e3", "Mercedes GP", EntityType.Team, "The earlier name."),
                relationships=[
                    _drove("e1", "e2", from_year=2013,
                           description="The later spell."),
                    _drove("e1", "e3", from_year=2010,
                           description="The earlier spell."),
                ],
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = root / "metadata.json"
            chunks = root / "chunks.jsonl"
            out = root / "extraction"
            summary = root / "summary.md"
            metadata.write_text(json.dumps([{
                "doc_id": "d1", "title": "Mercedes page", "file": "m.html",
            }]), encoding="utf-8")
            chunks.write_text(json.dumps({
                "chunk_id": "d1#0",
                "doc_id": "d1",
                "section": None,
                "page": 4,
                "source": "https://example.test/mercedes",
                "text": "Hamilton drove for Mercedes.",
            }) + "\n", encoding="utf-8")
            code = run_extraction(
                chunks_path=chunks, metadata_path=metadata, out_dir=out,
                summary_path=summary, run=True, overwrite=False,
                caller=caller, model="test-model")
            saved = json.loads(
                (out / f"{safe_stem('d1#0')}.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(saved["chunk_id"], "d1#0")
        self.assertEqual(saved["source"], "https://example.test/mercedes")
        self.assertEqual(saved["page"], 4)
        names = [entity["name"] for entity in saved["result"]["entities"]]
        self.assertEqual(names, ["Lewis Hamilton", MERCEDES])
        self.assertEqual(
            [(rel["target_id"], rel["from_year"], rel["description"])
             for rel in saved["result"]["relationships"]],
            [("e2", 2013, "The later spell."),
             ("e2", 2010, "The earlier spell.")])
        again = refilter_record(saved)
        self.assertEqual(again["result"], saved["result"])
        self.assertEqual(again["chunk_id"], saved["chunk_id"])
        self.assertEqual(again["source"], saved["source"])
        self.assertEqual(again["input_hash"], saved["input_hash"])
