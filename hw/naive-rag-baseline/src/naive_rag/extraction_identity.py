"""Name, entity, and DROVE_FOR identity for the extraction pilot.

Pure functions. Importing this module does not open a database connection
and does not read or write the graph.

`name_norm` is not an alias list. The same normalized name and type is the
pilot's match rule, not a decision that two real entities are the same person
or team. `ALIAS_MAP` is the only extra list, and it is applied after
`make_entity_key`.
"""

from __future__ import annotations

import json
import re
import unicodedata

from .extraction_models import EntityType, ExtractionResult

_WHITESPACE = re.compile(r"\s+")


class EmptyNameError(ValueError):
    """The normalized name is empty, so no entity_key may be built."""


# Missing-value tokens only. This is not a list of unusual real names.
# Comparison uses normalize_name, so "NULL" and "None" match.
PLACEHOLDER_NAMES = frozenset({"null", "none", "nil", "undefined"})


def identity_rejection(name: object) -> str | None:
    """Return why this name cannot be stored, or None when it can.

    A missing description or year is not a reason. No name is inferred.
    """
    if not isinstance(name, str):
        return "name is missing"
    try:
        normalized = normalize_name(name)
    except EmptyNameError:
        return "name is empty"
    if normalized in PLACEHOLDER_NAMES:
        return f"name {normalized!r} is a placeholder, not an entity identity"
    return None


def normalize_name(name: str) -> str:
    """NFKC, casefold, NFKC, then outer strip and collapsed internal space.

    Accents and punctuation stay. The second NFKC runs on the casefold
    result: casefold can expand a character, and NFKC folds that expansion
    back (U+01F0 is the covered example). Internal whitespace, including
    non-breaking and ideographic spaces, becomes one U+0020 space.
    """
    text = unicodedata.normalize("NFKC", name)
    text = text.casefold()
    text = unicodedata.normalize("NFKC", text)
    text = _WHITESPACE.sub(" ", text).strip()
    if text == "":
        raise EmptyNameError("name_norm is empty.")
    return text


# entity_key -> canonical entity_key. Only reviewed pairs belong here.
_MERCEDES_TEAM = "Team:mercedes-amg petronas formula one team"

ALIAS_MAP: dict[str, str] = {
    "Driver:hamilton": "Driver:lewis hamilton",
    "Team:ferrari": "Team:scuderia ferrari",
    "Team:red bull": "Team:red bull racing",
    "Team:mercedes": _MERCEDES_TEAM,
    "Team:mercedes gp": _MERCEDES_TEAM,
    "Team:mercedes amg": _MERCEDES_TEAM,
    "Team:mercedes gp petronas formula one team": _MERCEDES_TEAM,
    "Team:mercedes f1": _MERCEDES_TEAM,
    "Team:mercedes f1 team": _MERCEDES_TEAM,
}

# Display name for a canonical key. First-seen text is not used for these.
CANONICAL_NAMES: dict[str, str] = {
    "Driver:lewis hamilton": "Lewis Hamilton",
    "Team:scuderia ferrari": "Scuderia Ferrari",
    "Team:red bull racing": "Red Bull Racing",
    _MERCEDES_TEAM: "Mercedes-AMG Petronas Formula One Team",
}


def canonical_key(entity_key: str) -> str:
    """Follow ``ALIAS_MAP`` to the canonical key. Other keys stay as they are."""
    seen = set()
    current = entity_key
    while current in ALIAS_MAP and current not in seen:
        seen.add(current)
        current = ALIAS_MAP[current]
    return current


def canonical_identity(entity_type: EntityType, name: str) -> tuple[str, str, str]:
    """Canonical key, display name, and the name_norm of that display name.

    ``make_entity_key`` and ``normalize_name`` are unchanged. An alias is
    applied to the key afterwards. A listed canonical node uses
    ``CANONICAL_NAMES``; every other node keeps the given name.
    """
    key = canonical_key(make_entity_key(entity_type, name))
    display = CANONICAL_NAMES.get(key)
    if display is None:
        return key, name, normalize_name(name)
    return key, display, normalize_name(display)


def canonicalize_result(result: ExtractionResult) -> ExtractionResult:
    """Use one local entity per canonical key and point edges at it.

    The same ``canonical_identity`` drives the name and both endpoints.
    Descriptions of the same entity or the same relationship are kept.
    A repeated call returns the same result. Duplicate ``local_id`` values
    are left for the partial validator.
    """
    if len({entity.local_id for entity in result.entities}) != len(
            result.entities):
        return result
    groups: dict[str, list] = {}
    order: list[str] = []
    displays: dict[str, str] = {}
    for entity in result.entities:
        key, display, _name_norm = canonical_identity(
            entity.entity_type, entity.name)
        if key not in groups:
            groups[key] = []
            order.append(key)
            displays[key] = display
        groups[key].append(entity)
    survivor: dict[str, str] = {}
    entities = []
    for key in order:
        members = groups[key]
        description = None
        for entity in members:
            description = merge_descriptions(description, entity.description)
        kept = members[0].model_copy(update={
            "name": displays[key],
            "description": description or members[0].description,
        })
        entities.append(kept)
        for entity in members:
            survivor[entity.local_id] = kept.local_id
    relationships = []
    seen: dict[tuple, int] = {}
    for rel in result.relationships:
        rewritten = rel.model_copy(update={
            "source_id": survivor[rel.source_id],
            "target_id": survivor[rel.target_id],
        })
        identity = (
            rewritten.source_id,
            rewritten.relationship_type,
            rewritten.target_id,
            rewritten.from_year,
            rewritten.to_year,
            rewritten.role,
        )
        previous = seen.get(identity)
        if previous is None:
            seen[identity] = len(relationships)
            relationships.append(rewritten)
            continue
        current = relationships[previous]
        relationships[previous] = current.model_copy(update={
            "description": merge_descriptions(
                current.description, rewritten.description),
        })
    return ExtractionResult(entities=entities, relationships=relationships)


def make_entity_key(entity_type: EntityType, name: str) -> str:
    """`entity_type.value + ':' + name_norm`.

    The key is built from the fields. Nothing in this module parses a key
    back into a type and a name.
    """
    if not isinstance(entity_type, EntityType):
        raise TypeError("entity_type must be EntityType.")
    normalized = normalize_name(name)
    return f"{entity_type.value}:{normalized}"


def make_rel_key(
    source_key: str,
    relationship_type: str,
    target_key: str,
    from_year: int | None,
    to_year: int | None,
    role: str | None,
) -> str:
    """JSON text of the six-element relationship identity.

    The serialized text is the value stored as `rel_key`. It is not a Neo4j
    array property. `description`, `origin`, and `source_chunk_ids` are not
    part of the identity. JSON null is used for a missing year or role; the
    string ``null`` is a different role. Different years or roles stay
    different keys.
    """
    payload = [
        _required_text(source_key, "source_key"),
        _required_text(relationship_type, "relationship_type"),
        _required_text(target_key, "target_key"),
        _optional_year(from_year, "from_year"),
        _optional_year(to_year, "to_year"),
        _optional_role(role),
    ]
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def drove_for_rel_key(
    driver_key: str,
    team_key: str,
    from_year: int | None,
    to_year: int | None,
    role: str | None,
) -> str:
    """DROVE_FOR identity. Same text as `make_rel_key` with that type."""
    return make_rel_key(
        driver_key, "DROVE_FOR", team_key, from_year, to_year, role)


def merge_descriptions(existing: str | None, description: str | None) -> str:
    """Keep unique description lines in first-seen order."""
    kept: list[str] = []
    for block in (existing, description):
        if not block:
            continue
        for line in str(block).split("\n"):
            if line and line not in kept:
                kept.append(line)
    return "\n".join(kept)


def merge_source_ids(existing: list[str] | None, chunk_id: str) -> list[str]:
    """Append `chunk_id` when it is absent. Keep the existing order.

    A new relationship starts from no sources. A repeat of a source already
    in the list leaves the list as it is, including a list that already has
    other chunks before it.
    """
    source = _required_text(chunk_id, "chunk_id")
    if existing is None:
        current: list[str] = []
    else:
        current = [str(item) for item in existing]
    if source in current:
        return current
    return current + [source]


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{label} must be a non-empty string.")
    return value


def _optional_year(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an int or null.")
    return value


def _optional_role(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value.strip() == "":
        raise TypeError("role must be a non-empty string or null.")
    return value
