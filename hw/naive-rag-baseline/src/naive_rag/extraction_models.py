"""Structured extraction schema for the F1 pilot. No database writes.

Entity and relationship types follow `docs/graph-schema.md` and the edges
`graph_seed.py` actually creates. Document-graph edges (CONTAINS, NEXT_CHUNK,
HAS_DOCUMENT, HAS_SECTION) are not extraction relations.

`from_year`, `to_year` and `role` belong only to DROVE_FOR, the one edge the
schema stores those properties on. Validation here is structural. It does not
prove that an extracted fact is true in the source text.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple

from pydantic import BaseModel, Field, field_validator


class EntityType(str, Enum):
    Driver = "Driver"
    Team = "Team"
    Season = "Season"
    GrandPrix = "GrandPrix"
    Circuit = "Circuit"
    Car = "Car"
    PowerUnit = "PowerUnit"
    Title = "Title"
    RaceResult = "RaceResult"


class RelType(str, Enum):
    DROVE_FOR = "DROVE_FOR"
    TEAMMATE_OF = "TEAMMATE_OF"
    FIELDED = "FIELDED"
    POWERED_BY = "POWERED_BY"
    RACED_IN = "RACED_IN"
    ENTERED = "ENTERED"
    ROUND_OF = "ROUND_OF"
    HELD_AT = "HELD_AT"
    ACHIEVED = "ACHIEVED"
    AT_RACE = "AT_RACE"
    FOR_TEAM = "FOR_TEAM"
    WON = "WON"
    AWARDED_IN = "AWARDED_IN"


class RelEnds(NamedTuple):
    sources: frozenset[EntityType]
    targets: frozenset[EntityType]
    temporal: bool
    meaning: str


# Directed pairs as stored in the schema. TEAMMATE_OF is semantically
# symmetric, but the seed still stores Driver -> Driver.
# `meaning` is the prompt text. Endpoints are unchanged from pilot 1.
REL_SPECS: dict[RelType, RelEnds] = {
    RelType.DROVE_FOR: RelEnds(
        frozenset({EntityType.Driver}), frozenset({EntityType.Team}), True,
        "a driver's Formula One racing spell with a team; not ownership, "
        "sponsorship, management, engine supply, or young-driver programme "
        "membership"),
    RelType.TEAMMATE_OF: RelEnds(
        frozenset({EntityType.Driver}), frozenset({EntityType.Driver}), False,
        "two drivers were teammates, only when the text states it"),
    RelType.FIELDED: RelEnds(
        frozenset({EntityType.Team}), frozenset({EntityType.Car}), False,
        "a team entered a car"),
    RelType.POWERED_BY: RelEnds(
        frozenset({EntityType.Car}), frozenset({EntityType.PowerUnit}), False,
        "a car uses a power unit"),
    RelType.RACED_IN: RelEnds(
        frozenset({EntityType.Car}), frozenset({EntityType.Season}), False,
        "a car took part in a season"),
    RelType.ENTERED: RelEnds(
        frozenset({EntityType.Team}), frozenset({EntityType.Season}), False,
        "a team took part in a season, only when the text states it"),
    RelType.ROUND_OF: RelEnds(
        frozenset({EntityType.GrandPrix}), frozenset({EntityType.Season}),
        False, "a specific Grand Prix is a round of a season"),
    RelType.HELD_AT: RelEnds(
        frozenset({EntityType.GrandPrix}), frozenset({EntityType.Circuit}),
        False, "a Grand Prix is held at a circuit"),
    RelType.ACHIEVED: RelEnds(
        frozenset({EntityType.Driver}), frozenset({EntityType.RaceResult}),
        False, "a driver recorded a result in a race"),
    RelType.AT_RACE: RelEnds(
        frozenset({EntityType.RaceResult}), frozenset({EntityType.GrandPrix}),
        False, "a race result belongs to one Grand Prix"),
    RelType.FOR_TEAM: RelEnds(
        frozenset({EntityType.RaceResult}), frozenset({EntityType.Team}),
        False, "a race result was scored for a team"),
    RelType.WON: RelEnds(
        frozenset({EntityType.Driver, EntityType.Team}),
        frozenset({EntityType.Title}), False,
        "a driver or team won a specific championship title"),
    RelType.AWARDED_IN: RelEnds(
        frozenset({EntityType.Title}), frozenset({EntityType.Season}), False,
        "a specific championship title belongs to a season"),
}

ENTITY_BLURBS: dict[EntityType, str] = {
    EntityType.Driver: "A person who races in Formula One. Not a principal, "
                       "engineer, mentor, or programme boss unless the text "
                       "says they themselves race.",
    EntityType.Team: "A Formula 1 team that enters cars. Not an automotive "
                     "brand, engine brand, title sponsor, owner, parent "
                     "company, or shareholder.",
    EntityType.Season: "A championship year named in the text. Include it "
                       "even when it has no relationship. Do not invent years "
                       "the text does not name.",
    EntityType.GrandPrix: "One named race event, not a count of wins.",
    EntityType.Circuit: "A racing venue.",
    EntityType.Car: "A chassis or car model a team fields.",
    EntityType.PowerUnit: "An engine or power unit.",
    EntityType.Title: "One championship title for one stated season. An "
                      "aggregate count of titles is not one Title, and it "
                      "gets no WON or AWARDED_IN. Keep that count in the "
                      "driver description. The document title or section may "
                      "supply the year only when the chunk text states that "
                      "win. The title alone does not prove a win.",
    EntityType.RaceResult: "One driver's result in one named race. A count of "
                           "wins is not that many RaceResult entities.",
}

if set(REL_SPECS) != set(RelType):
    raise RuntimeError("REL_SPECS and RelType have drifted apart.")
if set(ENTITY_BLURBS) != set(EntityType):
    raise RuntimeError("ENTITY_BLURBS and EntityType have drifted apart.")


class ExtractionValidationError(ValueError):
    """The model returned JSON the schema does not allow."""


def _blank_to_none(value: object) -> object:
    if value == "":
        return None
    return value


class Entity(BaseModel):
    local_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    entity_type: EntityType
    description: str = Field(min_length=1)

    @field_validator("local_id", "name", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("blank")
        return stripped


class Relationship(BaseModel):
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relationship_type: RelType
    description: str = Field(min_length=1)
    from_year: int | None = None
    to_year: int | None = None
    role: str | None = None

    @field_validator("from_year", "to_year", "role", mode="before")
    @classmethod
    def _empty(cls, value: object) -> object:
        return _blank_to_none(value)

    @field_validator("source_id", "target_id", "description")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("blank")
        return stripped

    @field_validator("role")
    @classmethod
    def _strip_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ExtractionResult(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


def validate_extraction(result: ExtractionResult) -> None:
    """Raise ExtractionValidationError on structural schema breaks.

    Does not check whether the description is actually supported by the text.
    """
    seen: dict[str, EntityType] = {}
    for entity in result.entities:
        if entity.local_id in seen:
            raise ExtractionValidationError(
                f"duplicate local_id {entity.local_id!r}")
        seen[entity.local_id] = entity.entity_type

    for rel in result.relationships:
        if rel.source_id not in seen:
            raise ExtractionValidationError(
                f"{rel.relationship_type.value}: unknown source_id "
                f"{rel.source_id!r}")
        if rel.target_id not in seen:
            raise ExtractionValidationError(
                f"{rel.relationship_type.value}: unknown target_id "
                f"{rel.target_id!r}")
        spec = REL_SPECS[rel.relationship_type]
        pair = (seen[rel.source_id], seen[rel.target_id])
        if pair[0] not in spec.sources or pair[1] not in spec.targets:
            raise ExtractionValidationError(
                f"{rel.relationship_type.value} does not allow "
                f"{pair[0].value} -> {pair[1].value}")
        if (rel.from_year is not None and rel.to_year is not None
                and rel.from_year > rel.to_year):
            raise ExtractionValidationError(
                f"{rel.relationship_type.value}: from_year {rel.from_year} "
                f"> to_year {rel.to_year}")
        timed = (rel.from_year, rel.to_year, rel.role)
        if not spec.temporal and any(value is not None for value in timed):
            raise ExtractionValidationError(
                f"{rel.relationship_type.value} is not temporal; "
                "from_year, to_year and role must be null")
