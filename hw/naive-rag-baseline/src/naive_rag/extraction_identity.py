"""Name, entity, and DROVE_FOR identity for the extraction pilot.

Pure functions. Importing this module does not open a database connection
and does not read or write the graph.

`name_norm` is not an alias list. The same normalized name and type is the
pilot's match rule, not a decision that two real entities are the same person
or team.
"""

from __future__ import annotations

import json
import re
import unicodedata

from .extraction_models import EntityType

_WHITESPACE = re.compile(r"\s+")


class EmptyNameError(ValueError):
    """The normalized name is empty, so no entity_key may be built."""


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
