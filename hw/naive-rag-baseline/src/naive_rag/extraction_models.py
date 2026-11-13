"""Structured extraction schema for the F1 pilot. No database writes.

Entity and relationship types follow `docs/graph-schema.md` and the edges
`graph_seed.py` actually creates. Document-graph edges (CONTAINS, NEXT_CHUNK,
HAS_DOCUMENT, HAS_SECTION) are not extraction relations.

`from_year`, `to_year` and `role` belong only to DROVE_FOR, the one edge the
schema stores those properties on. Validation here is structural. It does not
prove that an extracted fact is true in the source text.
"""

from __future__ import annotations

import re
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
    # Description and years are not part of the identity. A missing
    # description stays empty; it does not reject the entity.
    description: str = ""

    @field_validator("description", mode="before")
    @classmethod
    def _description(cls, value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("description must be a string")
        return value.strip()

    @field_validator("local_id", "name")
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


def load_saved_extraction(
        result: ExtractionResult,
) -> tuple[ExtractionResult, tuple[str, ...]]:
    """Drop self-loops from a saved result, then validate what remains.

    One bad edge does not reject the record. ``validate_extraction`` still
    raises for every other structural defect, and new extraction calls that
    function directly.
    """
    reasons: list[str] = []
    kept: list[Relationship] = []
    for rel in result.relationships:
        if rel.source_id == rel.target_id:
            reasons.append(f"{rel.relationship_type.value}: {SELF_LOOP_REASON}")
            continue
        kept.append(rel)
    accepted = ExtractionResult(
        entities=list(result.entities), relationships=kept)
    validate_extraction(accepted)
    return accepted, tuple(reasons)


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
        if rel.source_id == rel.target_id:
            raise ExtractionValidationError(
                f"{rel.relationship_type.value}: {SELF_LOOP_REASON}")
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


PARTIAL_VALIDATION_VERSION = "partial-1"
SELF_LOOP_REASON = "source_id equals target_id"


class FilterRejection(NamedTuple):
    """One dropped element. `index` is its position in the original list."""

    element: str
    index: int
    reason: str


def _endpoint_reason(role: str, local_id: str, accepted: dict[str, EntityType],
                     duplicated: set[str],
                     rejected_identity: dict[str, str] | None = None) -> str | None:
    if local_id in accepted:
        return None
    if rejected_identity and local_id in rejected_identity:
        return (f"{role} {local_id!r} rejected: "
                f"{rejected_identity[local_id]}")
    if local_id in duplicated:
        return f"{role} {local_id!r} rejected: duplicate local_id"
    return f"unknown {role} {local_id!r}"


def _relationship_reason(rel: Relationship, accepted: dict[str, EntityType],
                         duplicated: set[str],
                         rejected_identity: dict[str, str] | None = None,
                         ) -> str | None:
    """The first structural defect, or None when the relationship may stay.

    The text matches `validate_extraction`. Nothing is rewritten.
    """
    for role, local_id in (("source_id", rel.source_id),
                           ("target_id", rel.target_id)):
        reason = _endpoint_reason(
            role, local_id, accepted, duplicated, rejected_identity)
        if reason is not None:
            return f"{rel.relationship_type.value}: {reason}"
    if rel.source_id == rel.target_id:
        return f"{rel.relationship_type.value}: {SELF_LOOP_REASON}"
    spec = REL_SPECS[rel.relationship_type]
    pair = (accepted[rel.source_id], accepted[rel.target_id])
    if pair[0] not in spec.sources or pair[1] not in spec.targets:
        return (f"{rel.relationship_type.value} does not allow "
                f"{pair[0].value} -> {pair[1].value}")
    if (rel.from_year is not None and rel.to_year is not None
            and rel.from_year > rel.to_year):
        return (f"{rel.relationship_type.value}: from_year {rel.from_year} "
                f"> to_year {rel.to_year}")
    timed = (rel.from_year, rel.to_year, rel.role)
    if not spec.temporal and any(value is not None for value in timed):
        return (f"{rel.relationship_type.value} is not temporal; "
                "from_year, to_year and role must be null")
    return None


def read_extraction_candidate(
        raw: object,
) -> tuple[ExtractionResult, list[FilterRejection]]:
    """Parse one model object element by element.

    One invalid entity or relationship is rejected. The other elements stay.
    A response that is not an object with two lists is still unreadable.
    """
    if not isinstance(raw, dict):
        raise ExtractionValidationError("extraction result is not an object")
    entities = raw.get("entities", [])
    relationships = raw.get("relationships", [])
    if not isinstance(entities, list) or not isinstance(relationships, list):
        raise ExtractionValidationError(
            "entities and relationships must be lists")
    from pydantic import ValidationError

    rejections: list[FilterRejection] = []
    kept_entities: list[Entity] = []
    for index, item in enumerate(entities):
        try:
            kept_entities.append(Entity.model_validate(item))
        except ValidationError as exc:
            loc = ".".join(str(part) for part in exc.errors()[0].get("loc", ()))
            rejections.append(FilterRejection(
                "entity", index,
                f"invalid entity: {loc or 'value'} {exc.errors()[0].get('type')}"))
    kept_relationships: list[Relationship] = []
    for index, item in enumerate(relationships):
        try:
            kept_relationships.append(Relationship.model_validate(item))
        except ValidationError as exc:
            loc = ".".join(str(part) for part in exc.errors()[0].get("loc", ()))
            rejections.append(FilterRejection(
                "relationship", index,
                f"invalid relationship: {loc or 'value'} "
                f"{exc.errors()[0].get('type')}"))
    return (
        ExtractionResult(entities=kept_entities, relationships=kept_relationships),
        rejections,
    )


def filter_extraction(
        result: ExtractionResult,
) -> tuple[ExtractionResult, list[FilterRejection]]:
    """Drop broken elements. Keep every other entity and relationship.

    A duplicate `local_id` rejects every entity with that id and every
    relationship that uses it. The returned result passes
    `validate_extraction`.
    """
    rejections: list[FilterRejection] = []
    counts: dict[str, int] = {}
    for entity in result.entities:
        counts[entity.local_id] = counts.get(entity.local_id, 0) + 1
    duplicated = {local_id for local_id, count in counts.items() if count > 1}

    from .extraction_identity import identity_rejection

    accepted_types: dict[str, EntityType] = {}
    rejected_identity: dict[str, str] = {}
    kept_entities: list[Entity] = []
    for index, entity in enumerate(result.entities):
        if entity.local_id in duplicated:
            rejections.append(FilterRejection(
                "entity", index,
                f"duplicate local_id {entity.local_id!r}"))
            continue
        reason = identity_rejection(entity.name)
        if reason is not None:
            rejections.append(FilterRejection("entity", index, reason))
            rejected_identity[entity.local_id] = reason
            continue
        kept_entities.append(entity)
        accepted_types[entity.local_id] = entity.entity_type

    kept_relationships: list[Relationship] = []
    for index, rel in enumerate(result.relationships):
        reason = _relationship_reason(
            rel, accepted_types, duplicated, rejected_identity)
        if reason is not None:
            rejections.append(FilterRejection("relationship", index, reason))
            continue
        kept_relationships.append(rel)

    accepted = ExtractionResult(
        entities=kept_entities, relationships=kept_relationships)
    validate_extraction(accepted)
    return accepted, rejections


class Alignment(NamedTuple):
    """One representation change. `index` is the original relationship."""

    index: int
    action: str
    detail: str


_NAMED_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _named_year(name: str) -> int | None:
    found = {int(match) for match in _NAMED_YEAR.findall(name)}
    if len(found) == 1:
        return found.pop()
    return None


def _single_year(rel: Relationship) -> int | None:
    years = {year for year in (rel.from_year, rel.to_year) if year is not None}
    if rel.role is None and len(years) == 1:
        return years.pop()
    return None


def _has_time(rel: Relationship) -> bool:
    return any(value is not None
               for value in (rel.from_year, rel.to_year, rel.role))


def _time_text(rel: Relationship) -> str:
    return (f"from_year={rel.from_year}, to_year={rel.to_year}, "
            f"role={rel.role}")


def _fresh_id(used: set[str], prefix: str) -> str:
    number = 1
    while f"{prefix}{number}" in used:
        number += 1
    local_id = f"{prefix}{number}"
    used.add(local_id)
    return local_id


def _types_of(entities: list[Entity]) -> dict[str, EntityType] | None:
    types: dict[str, EntityType] = {}
    for entity in entities:
        if entity.local_id in types:
            return None
        types[entity.local_id] = entity.entity_type
    return types


def _legal_pair(rel: Relationship, types: dict[str, EntityType]) -> bool:
    source = types.get(rel.source_id)
    target = types.get(rel.target_id)
    if source is None or target is None:
        return False
    spec = REL_SPECS[rel.relationship_type]
    return source in spec.sources and target in spec.targets


def _season_id(rel: Relationship, types: dict[str, EntityType]) -> str | None:
    spec = REL_SPECS[rel.relationship_type]
    if (EntityType.Season in spec.targets
            and types.get(rel.target_id) == EntityType.Season):
        return rel.target_id
    if (EntityType.Season in spec.sources
            and types.get(rel.source_id) == EntityType.Season):
        return rel.source_id
    return None


def align_extraction(
        result: ExtractionResult,
) -> tuple[ExtractionResult, list[FilterRejection], list[Alignment]]:
    """Map unambiguous extraction shapes onto the stored schema.

    `filter_extraction` still decides what is kept. A candidate that would
    need a new fact, title, or endpoint stays unchanged so the filter can
    reject it. Duplicate local ids are left untouched.
    """
    types = _types_of(result.entities)
    if types is None:
        return result, [], []

    entities = list(result.entities)
    used = set(types)
    kept: list[Relationship] = []
    refusals: list[FilterRejection] = []
    alignments: list[Alignment] = []

    def entity_named(local_id: str) -> Entity:
        return next(entity for entity in entities if entity.local_id == local_id)

    for index, rel in enumerate(result.relationships):
        source = types.get(rel.source_id)
        target = types.get(rel.target_id)
        if (rel.relationship_type == RelType.ACHIEVED
                and source == EntityType.Driver
                and target == EntityType.GrandPrix):
            if _has_time(rel):
                refusals.append(FilterRejection(
                    "relationship", index,
                    "ACHIEVED Driver -> GrandPrix has "
                    f"{_time_text(rel)}; the year or role cannot be stored "
                    "on the reified result"))
                continue
            result_id = _fresh_id(used, "rr")
            driver = entity_named(rel.source_id)
            race = entity_named(rel.target_id)
            entities.append(Entity(
                local_id=result_id,
                name=f"{driver.name} at {race.name}",
                entity_type=EntityType.RaceResult,
                description=rel.description,
            ))
            types[result_id] = EntityType.RaceResult
            kept.append(rel.model_copy(update={"target_id": result_id}))
            kept.append(Relationship(
                source_id=result_id,
                target_id=rel.target_id,
                relationship_type=RelType.AT_RACE,
                description=rel.description,
            ))
            alignments.append(Alignment(
                index, "reify_race_result",
                "ACHIEVED Driver -> GrandPrix stored as "
                f"RaceResult {result_id} -AT_RACE-> {rel.target_id}; "
                "description kept"))
            continue

        if (rel.relationship_type == RelType.WON
                and source in {EntityType.Driver, EntityType.Team}
                and target == EntityType.Title):
            year = _single_year(rel)
            if year is not None:
                moved = _move_title_year(
                    rel, index, year, entities, types, used, kept,
                    result.relationships, alignments)
                if moved:
                    continue

        if _legal_pair(rel, types) and not REL_SPECS[
                rel.relationship_type].temporal and _has_time(rel):
            season = _season_id(rel, types)
            named = _named_year(entity_named(season).name) if season else None
            years = {value for value in (rel.from_year, rel.to_year)
                     if value is not None}
            if (rel.role is None and season is not None and named is not None
                    and years == {named}):
                kept.append(rel.model_copy(update={
                    "from_year": None, "to_year": None}))
                alignments.append(Alignment(
                    index, "clear_redundant_season_year",
                    f"{rel.relationship_type.value} year {named} already "
                    f"named by Season {season!r}; from_year and to_year "
                    "cleared"))
                continue
            refusals.append(FilterRejection(
                "relationship", index,
                f"{rel.relationship_type.value} is not temporal; "
                f"{_time_text(rel)} cannot be stored without dropping them"))
            continue

        kept.append(rel)

    aligned = ExtractionResult(entities=entities, relationships=kept)
    return aligned, refusals, alignments


def _move_title_year(rel: Relationship, index: int, year: int,
                     entities: list[Entity], types: dict[str, EntityType],
                     used: set[str], kept: list[Relationship],
                     original: list[Relationship],
                     alignments: list[Alignment]) -> bool:
    """Move one title-win year onto AWARDED_IN. Return False if ambiguous."""
    seasons = [
        entity for entity in entities
        if entity.entity_type == EntityType.Season
        and _named_year(entity.name) == year
    ]
    if len(seasons) > 1:
        return False
    awarded = [
        other.target_id for other in [*original, *kept]
        if other.relationship_type == RelType.AWARDED_IN
        and other.source_id == rel.target_id
    ]
    season_id = seasons[0].local_id if seasons else None
    if any(target != season_id for target in awarded):
        return False
    if season_id is None:
        season_id = _fresh_id(used, f"season{year}-")
        entities.append(Entity(
            local_id=season_id,
            name=str(year),
            entity_type=EntityType.Season,
            description=str(year),
        ))
        types[season_id] = EntityType.Season
    kept.append(rel.model_copy(update={"from_year": None, "to_year": None}))
    if season_id not in awarded:
        kept.append(Relationship(
            source_id=rel.target_id,
            target_id=season_id,
            relationship_type=RelType.AWARDED_IN,
            description=rel.description,
        ))
    alignments.append(Alignment(
        index, "move_won_year",
        f"WON year {year} stored as {rel.target_id} -AWARDED_IN-> "
        f"{season_id}; from_year and to_year cleared; description kept"))
    return True
