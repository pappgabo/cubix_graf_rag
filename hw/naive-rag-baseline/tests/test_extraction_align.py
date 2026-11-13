"""Offline checks for extraction-to-storage alignment. No model and no corpus."""

from __future__ import annotations

import unittest

from naive_rag.extraction_models import (
    EntityType,
    ExtractionResult,
    RelType,
    Relationship,
    align_extraction,
    filter_extraction,
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
        "description": extra.pop("description", "The text states this relationship."),
        "from_year": None,
        "to_year": None,
        "role": None,
    }
    body.update(extra)
    return body


def _stored(result: ExtractionResult):
    aligned, refusals, alignments = align_extraction(result)
    accepted, rejections = filter_extraction(aligned)
    validate_extraction(accepted)
    return accepted, [*refusals, *rejections], alignments


class AlignExtractionTests(unittest.TestCase):
    def test_already_stored_relationship_is_unchanged(self) -> None:
        result = ExtractionResult.model_validate({
            "entities": [
                _entity("e1", "Lewis Hamilton", EntityType.Driver),
                _entity("e2", "Ferrari", EntityType.Team),
            ],
            "relationships": [
                _edge("e1", "e2", RelType.DROVE_FOR, from_year=2010,
                      to_year=2014, role="race driver",
                      description="The text says he drives for the team."),
            ],
        })
        accepted, rejections, alignments = _stored(result)
        self.assertEqual(rejections, [])
        self.assertEqual(alignments, [])
        self.assertEqual(accepted.model_dump(), result.model_dump())

    def test_driver_result_at_grand_prix_is_reified(self) -> None:
        result = ExtractionResult.model_validate({
            "entities": [
                _entity("e1", "Lewis Hamilton", EntityType.Driver),
                _entity("e2", "British Grand Prix", EntityType.GrandPrix),
            ],
            "relationships": [_edge(
                "e1", "e2", RelType.ACHIEVED,
                description="Hamilton finished second at the British Grand Prix.",
            )],
        })
        accepted, rejections, alignments = _stored(result)
        self.assertEqual(rejections, [])
        self.assertEqual(alignments[0].action, "reify_race_result")
        achieved = accepted.relationships[0]
        at_race = accepted.relationships[1]
        result_entity = accepted.entities[2]
        self.assertEqual(achieved.relationship_type, RelType.ACHIEVED)
        self.assertEqual(achieved.source_id, "e1")
        self.assertEqual(achieved.target_id, result_entity.local_id)
        self.assertEqual(
            achieved.description,
            "Hamilton finished second at the British Grand Prix.")
        self.assertEqual(result_entity.entity_type, EntityType.RaceResult)
        self.assertEqual(result_entity.description, achieved.description)
        self.assertEqual(at_race.relationship_type, RelType.AT_RACE)
        self.assertEqual(at_race.source_id, result_entity.local_id)
        self.assertEqual(at_race.target_id, "e2")
        self.assertEqual(at_race.description, achieved.description)

    def test_title_win_year_moves_to_awarded_in(self) -> None:
        result = ExtractionResult.model_validate({
            "entities": [
                _entity("e1", "Fernando Alonso", EntityType.Driver),
                _entity("e2", "2005 F1 World Championship", EntityType.Title),
                _entity("e3", "2005 Formula One World Championship",
                        EntityType.Season),
            ],
            "relationships": [_edge(
                "e1", "e2", RelType.WON, from_year=2005,
                description="Alonso won the 2005 F1 World Championship.",
            )],
        })
        accepted, rejections, alignments = _stored(result)
        self.assertEqual(rejections, [])
        self.assertEqual(alignments[0].action, "move_won_year")
        won = accepted.relationships[0]
        awarded = accepted.relationships[1]
        self.assertEqual(won.from_year, None)
        self.assertEqual(won.to_year, None)
        self.assertEqual(won.description,
                         "Alonso won the 2005 F1 World Championship.")
        self.assertEqual(awarded.relationship_type, RelType.AWARDED_IN)
        self.assertEqual(awarded.source_id, "e2")
        self.assertEqual(awarded.target_id, "e3")
        self.assertEqual(awarded.description, won.description)
        self.assertEqual(
            [entity.local_id for entity in accepted.entities],
            ["e1", "e2", "e3"])

    def test_title_win_year_creates_the_missing_season(self) -> None:
        result = ExtractionResult.model_validate({
            "entities": [
                _entity("e1", "Fernando Alonso", EntityType.Driver),
                _entity("e2", "Autosport Award", EntityType.Title),
            ],
            "relationships": [_edge(
                "e1", "e2", RelType.WON, from_year=2006,
                description="Alonso won the 2006 Autosport award.",
            )],
        })
        accepted, rejections, alignments = _stored(result)
        self.assertEqual(rejections, [])
        self.assertEqual(alignments[0].action, "move_won_year")
        season = accepted.entities[2]
        self.assertEqual(season.entity_type, EntityType.Season)
        self.assertEqual(season.name, "2006")
        self.assertEqual(season.description, "2006")
        awarded = accepted.relationships[1]
        self.assertEqual(awarded.target_id, season.local_id)
        self.assertEqual(awarded.description,
                         "Alonso won the 2006 Autosport award.")
        self.assertIsNone(accepted.relationships[0].from_year)

    def test_redundant_season_year_is_cleared(self) -> None:
        result = ExtractionResult.model_validate({
            "entities": [
                _entity("e1", "Ferrari", EntityType.Team),
                _entity("e2", "2014", EntityType.Season),
            ],
            "relationships": [_edge(
                "e1", "e2", RelType.ENTERED, from_year=2014,
                description="Ferrari entered the 2014 season.",
            )],
        })
        accepted, rejections, alignments = _stored(result)
        self.assertEqual(rejections, [])
        self.assertEqual(alignments[0].action, "clear_redundant_season_year")
        entered = accepted.relationships[0]
        self.assertEqual(entered.from_year, None)
        self.assertEqual(entered.to_year, None)
        self.assertEqual(entered.description, "Ferrari entered the 2014 season.")
        self.assertEqual(entered.source_id, "e1")
        self.assertEqual(entered.target_id, "e2")

    def test_won_season_is_not_rewritten_as_a_title(self) -> None:
        result = ExtractionResult.model_validate({
            "entities": [
                _entity("e1", "Nico Rosberg", EntityType.Driver),
                _entity("e2", "1993", EntityType.Season),
            ],
            "relationships": [_edge(
                "e1", "e2", RelType.WON,
                description="Nico Rosberg was the first reigning champion "
                            "to retire since Alain Prost.",
            )],
        })
        accepted, rejections, alignments = _stored(result)
        self.assertEqual(alignments, [])
        self.assertEqual(accepted.relationships, [])
        self.assertEqual(
            [entity.entity_type for entity in accepted.entities],
            [EntityType.Driver, EntityType.Season])
        self.assertIn("does not allow Driver -> Season", rejections[0].reason)

    def test_unmappable_year_and_reversed_participation_stay_rejected(self) -> None:
        result = ExtractionResult.model_validate({
            "entities": [
                _entity("e1", "Lewis Hamilton", EntityType.Driver),
                _entity("e2", "World Drivers' Championship", EntityType.Title),
                _entity("e3", "British Grand Prix", EntityType.GrandPrix),
                _entity("e4", "2014", EntityType.Season),
            ],
            "relationships": [
                _edge("e1", "e2", RelType.WON, from_year=2014, to_year=2020,
                      description="Hamilton won across these years."),
                _edge("e1", "e3", RelType.ACHIEVED, from_year=2021,
                      description="Hamilton finished second in 2021."),
                _edge("e1", "e4", RelType.RACED_IN,
                      description="Hamilton raced in the 2014 season."),
            ],
        })
        accepted, rejections, alignments = _stored(result)
        self.assertEqual(alignments, [])
        self.assertEqual(accepted.relationships, [])
        self.assertEqual(len(rejections), 3)
        self.assertIn("from_year=2014", rejections[0].reason)
        self.assertIn("to_year=2020", rejections[0].reason)
        self.assertIn("from_year=2021", rejections[1].reason)
        self.assertIn("does not allow Driver -> Season", rejections[2].reason)
        self.assertFalse(any(entity.entity_type == EntityType.Car
                             for entity in accepted.entities))
        self.assertFalse(any(entity.entity_type == EntityType.RaceResult
                             for entity in accepted.entities))

    def test_mixed_candidates_keep_the_mappable_edges(self) -> None:
        result = ExtractionResult.model_validate({
            "entities": [
                _entity("e1", "Lewis Hamilton", EntityType.Driver),
                _entity("e2", "Mercedes", EntityType.Team),
                _entity("e3", "British Grand Prix", EntityType.GrandPrix),
                _entity("e4", "2014", EntityType.Season),
            ],
            "relationships": [
                _edge("e1", "e2", RelType.DROVE_FOR, from_year=2013,
                      to_year=2024,
                      description="Hamilton drove for Mercedes."),
                _edge("e1", "e3", RelType.ACHIEVED,
                      description="Hamilton won the British Grand Prix."),
                _edge("e1", "e4", RelType.WON,
                      description="Hamilton won the 2014 season."),
            ],
        })
        accepted, rejections, alignments = _stored(result)
        kinds = [rel.relationship_type for rel in accepted.relationships]
        self.assertEqual(kinds, [RelType.DROVE_FOR, RelType.ACHIEVED,
                                 RelType.AT_RACE])
        self.assertEqual(accepted.relationships[0].from_year, 2013)
        self.assertEqual(accepted.relationships[0].to_year, 2024)
        self.assertEqual(accepted.relationships[0].description,
                         "Hamilton drove for Mercedes.")
        self.assertEqual(alignments[0].action, "reify_race_result")
        self.assertIn("does not allow Driver -> Season", rejections[0].reason)
        self.assertEqual(len(rejections), 1)
