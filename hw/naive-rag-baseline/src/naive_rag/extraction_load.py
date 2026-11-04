"""Load one approved extraction into the extracted graph layer.

Importing this module does not connect to Neo4j, does not create a
constraint, and does not write a node or a relationship.

`graph.query()` commits each call. This loader therefore does not use it.
A sample is written in one explicit transaction opened by the caller. The
live opener is `open_neo4j_transaction`; tests pass a double instead.
Calling the live opener is a database connection and is not part of the
offline tests.

Seed nodes stay `:Driver:Seed` / `:Team:Seed` and keep `driver_id` /
`team_id`. This loader matches `:Driver:Extracted` or `:Team:Extracted`
together with `entity_key`. It does not copy seed identifiers onto
extracted nodes, and it does not match on `name` alone.

Q6 in `graph/cypher/queries.cypher` still matches
`(d:Driver {name: $driver})` with no `:Seed` or `:Extracted` filter.
A bare `:Driver` match can see both layers. This module does not change
that query.

`raw_input_hash` compared here is the string stored on the raw record.
See `RAW_INPUT_HASH_SCOPE`. Equality of that string is not a checksum of
the raw file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import ValidationError

from .config import PROJECT_ROOT
from .extraction_identity import (
    EmptyNameError,
    make_entity_key,
    make_rel_key,
    merge_descriptions,
    merge_source_ids,
    normalize_name,
)
from .extraction_models import (
    EntityType,
    ExtractionResult,
    ExtractionValidationError,
    RelType,
    validate_extraction,
)

APPROVED = "approved"
ORIGIN_EXTRACTED = "extracted"

RAW_INPUT_HASH_SCOPE = (
    "extract_pilot.input_hash is the sha256 hex digest of the UTF-8 bytes of "
    "json.dumps(payload, ensure_ascii=False, sort_keys=True). The payload "
    "keys are model, prompt_version, prompt (the full SYSTEM_PROMPT), "
    "document_title, section, and text. It is not a hash of the raw JSON "
    "file. The load gate compares the review field raw_input_hash to the "
    "raw record's stored input_hash string, and compares chunk_id. That "
    "comparison does not recompute the hash and does not checksum the raw "
    "file bytes."
)

Q6_LAYER_NOTE = (
    "graph/cypher/queries.cypher Q6 matches (d:Driver {name: $driver}) "
    "with no :Seed or :Extracted filter. A bare :Driver match can see both "
    "layers. This loader does not change that query."
)

# Read-back of mentions. Not executed by the loader.
MENTIONS_REVERSE_QUERY = """
MATCH (c:Chunk)-[:MENTIONS]->(e:Driver:Extracted {entity_key: $entity_key})
RETURN c.chunk_id AS chunk_id
""".strip()

_LABELS = {item.value for item in EntityType}
_REL_TYPES = {item.value for item in RelType}

MATCH_CHUNK = """
MATCH (c:Chunk {chunk_id: $chunk_id})
RETURN c.chunk_id AS chunk_id
""".strip()

def entity_merge_cypher(label: str) -> str:
    _check_name(label, _LABELS, "entity label")
    return (
        f"MERGE (e:{label}:Extracted {{entity_key: $entity_key}})\n"
        "SET e.name = $name, e.name_norm = $name_norm\n"
        "RETURN e.description AS description"
    )


def mentions_cypher(label: str) -> str:
    _check_name(label, _LABELS, "entity label")
    return (
        f"MATCH (c:Chunk {{chunk_id: $chunk_id}})\n"
        f"MATCH (e:{label}:Extracted {{entity_key: $entity_key}})\n"
        "MERGE (c)-[:MENTIONS]->(e)"
    )


SET_DESCRIPTION = """
MATCH (e:Extracted {entity_key: $entity_key})
SET e.description = $description
""".strip()

MERGE_DROVE_FOR = """
MATCH (d:Driver:Extracted {entity_key: $driver_key})
MATCH (t:Team:Extracted {entity_key: $team_key})
MERGE (d)-[r:DROVE_FOR {rel_key: $rel_key}]->(t)
ON CREATE SET
    r.origin = $origin,
    r.from_year = $from_year,
    r.to_year = $to_year,
    r.role = $role,
    r.description = $description,
    r.source_chunk_ids = $source_chunk_ids
RETURN r.source_chunk_ids AS source_chunk_ids
""".strip()

SET_SOURCES = """
MATCH (d:Driver:Extracted {entity_key: $driver_key})
MATCH (t:Team:Extracted {entity_key: $team_key})
MATCH (d)-[r:DROVE_FOR {rel_key: $rel_key}]->(t)
SET r.source_chunk_ids = $source_chunk_ids
""".strip()


def relationship_merge_cypher(source_label: str, rel_type: str,
                              target_label: str) -> str:
    """DROVE_FOR keeps the original statement. Other types use the same shape."""
    _check_name(source_label, _LABELS, "entity label")
    _check_name(target_label, _LABELS, "entity label")
    _check_name(rel_type, _REL_TYPES, "relationship type")
    if (source_label, rel_type, target_label) == ("Driver", "DROVE_FOR", "Team"):
        return MERGE_DROVE_FOR
    return (
        f"MATCH (s:{source_label}:Extracted {{entity_key: $source_key}})\n"
        f"MATCH (t:{target_label}:Extracted {{entity_key: $target_key}})\n"
        f"MERGE (s)-[r:{rel_type} {{rel_key: $rel_key}}]->(t)\n"
        "ON CREATE SET\n"
        "    r.origin = $origin,\n"
        "    r.from_year = $from_year,\n"
        "    r.to_year = $to_year,\n"
        "    r.role = $role,\n"
        "    r.description = $description,\n"
        "    r.source_chunk_ids = $source_chunk_ids\n"
        "RETURN r.source_chunk_ids AS source_chunk_ids"
    )


def set_sources_cypher(rel_type: str) -> str:
    _check_name(rel_type, _REL_TYPES, "relationship type")
    if rel_type == "DROVE_FOR":
        return SET_SOURCES
    return (
        f"MATCH ()-[r:{rel_type} {{rel_key: $rel_key}}]-()\n"
        "SET r.source_chunk_ids = $source_chunk_ids"
    )


def _check_name(value: str, allowed: set[str], label: str) -> None:
    if value not in allowed:
        raise ResultRejected(f"Unsupported {label}: {value!r}")

# Neo4j 5.7 added relationship-property uniqueness. The compose image is
# neo4j:5.26-community; the running server is still checked when, and only
# when, apply_extracted_constraints is called. Seed DROVE_FOR edges have no
# rel_key. This statement is not a change to the seed MERGE.
_MIN_RELATIONSHIP_UNIQUENESS = (5, 7)

VERSION_QUERY = """
CALL dbms.components() YIELD name, versions, edition
WHERE name = 'Neo4j Kernel'
RETURN versions, edition
""".strip()

EXTRACTED_ENTITY_KEY_CONSTRAINT = """
CREATE CONSTRAINT extracted_entity_key IF NOT EXISTS
FOR (n:Extracted) REQUIRE n.entity_key IS UNIQUE
""".strip()

DROVE_FOR_REL_KEY_CONSTRAINT = """
CREATE CONSTRAINT drove_for_rel_key IF NOT EXISTS
FOR ()-[r:DROVE_FOR]-() REQUIRE r.rel_key IS UNIQUE
""".strip()


class LoadRejected(Exception):
    """The sample stopped before a transaction was opened."""


class ApprovalRejected(LoadRejected):
    """approval_status is not exactly 'approved'."""


class ResultRejected(LoadRejected):
    """The review result is not a valid pilot ExtractionResult."""


class SourceRejected(LoadRejected):
    """chunk_id or the stored raw input_hash does not match."""


class MissingChunk(Exception):
    """The chunk is not in the graph. Raised inside the write transaction."""


class ConstraintUnsupported(Exception):
    """The server version was not accepted. No constraint statement was sent."""


class GraphTx(Protocol):
    def run(self, cypher: str,
            parameters: dict[str, Any]) -> list[dict[str, Any]]:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...


Opener = Callable[[], GraphTx]
Query = Callable[[str, dict[str, Any]], list[dict[str, Any]]]


@dataclass(frozen=True)
class EntityWrite:
    label: str
    name: str
    name_norm: str
    entity_key: str
    description: str


@dataclass(frozen=True)
class RelationshipWrite:
    source_key: str
    target_key: str
    source_label: str
    target_label: str
    rel_type: str
    rel_key: str
    from_year: int | None
    to_year: int | None
    role: str | None
    description: str
    origin: str


@dataclass(frozen=True)
class LoadPlan:
    chunk_id: str
    entities: tuple[EntityWrite, ...]
    relationships: tuple[RelationshipWrite, ...]


def require_approved(review: dict[str, Any]) -> None:
    """Step 1. A raw record's status field is not an approval."""
    status = review.get("approval_status")
    if status != APPROVED:
        raise ApprovalRejected(
            "approval_status must be exactly 'approved' "
            f"(got {status!r}). pending_review is not approval, "
            "and a raw extraction status is not approval."
        )


def plan_validated_raw(record: dict[str, Any], *,
                       accept_validated_raw: bool = False) -> LoadPlan:
    """Plan one structurally valid raw record. This is not human approval.

    The flag is the batch gate for a later, explicitly authorized load.
    Leaving it false rejects the record before a transaction. The function
    does not write ``approved`` onto the record.
    """
    if accept_validated_raw is not True:
        raise ApprovalRejected(
            "A raw extraction record is not human approval. "
            "accept_validated_raw was not set."
        )
    if record.get("status") != "ok":
        raise SourceRejected("The raw record status is not 'ok'.")
    try:
        result = ExtractionResult.model_validate(record["result"])
        validate_extraction(result)
    except KeyError as exc:
        raise ResultRejected("raw result is missing.") from exc
    except (ValidationError, ExtractionValidationError) as exc:
        raise ResultRejected(str(exc)) from exc
    return _build_plan(result, record.get("chunk_id"))


def plan_approved_load(review: dict[str, Any],
                       raw: dict[str, Any]) -> LoadPlan:
    """Steps 1-3. Returns a plan and does not open a transaction.

    The plan is built from the review record's result. A documented
    corrections list records how that result was edited. The loader does
    not apply the list again, and a non-empty list is not a rejection.
    Step 3 compares chunk_id and the stored input_hash string. It does not
    hash the raw file and does not require the two result bodies to be equal.
    """
    require_approved(review)
    result = _validated_result(review)
    plan = _build_plan(result, review.get("chunk_id"))
    _require_raw_reference(review, raw)
    return plan


def load_approved_records(review: dict[str, Any], raw: dict[str, Any],
                          open_tx: Opener) -> LoadPlan:
    """Plan the load, then write it in the single transaction of `open_tx`.

    A rejection in the plan happens before `open_tx` is called.
    """
    plan = plan_approved_load(review, raw)
    load_approved_plan(plan, open_tx)
    return plan


def load_approved_plan(plan: LoadPlan, open_tx: Opener) -> None:
    """Write one already accepted plan in one transaction."""
    run_unit_of_work(open_tx, lambda tx: write_plan(tx, plan))


def load_review_file(path: Path, open_tx: Opener) -> LoadPlan:
    """Read a review file and the raw file it names, then load.

    The pending Hamilton sample fails `require_approved` before the raw
    file is read and before `open_tx` is called.
    """
    review = json.loads(Path(path).read_text(encoding="utf-8"))
    require_approved(review)
    raw_path = resolve_raw_path(str(review.get("raw_result_path", "")))
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    return load_approved_records(review, raw, open_tx)


def resolve_raw_path(raw_result_path: str) -> Path:
    path = Path(raw_result_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def run_unit_of_work(open_tx: Opener, work: Callable[[GraphTx], None]) -> None:
    """Open one transaction, run `work`, commit, or roll back after an error.

    This is the application boundary. A unit test can observe `rollback` on
    a double. That observation is not a Neo4j rollback.
    """
    tx = open_tx()
    try:
        work(tx)
    except Exception:
        tx.rollback()
        raise
    else:
        tx.commit()


def write_plan(tx: GraphTx, plan: LoadPlan) -> None:
    """Match the chunk, then write extracted entities, MENTIONS, and edges.

    The chunk MATCH is the first statement. An empty result raises
    `MissingChunk` before any MERGE. No statement creates a `:Chunk`.
    MENTIONS is a MERGE, so a repeated load does not add a second edge.
    Entity descriptions are stored and merged by line. Relationship years,
    role, origin, and description are set on create. A later load only
    updates `source_chunk_ids` through `merge_source_ids`.
    """
    found = tx.run(MATCH_CHUNK, {"chunk_id": plan.chunk_id})
    if not found:
        raise MissingChunk(
            f"No :Chunk with chunk_id {plan.chunk_id!r}. Nothing is written."
        )
    for entity in plan.entities:
        rows = tx.run(entity_merge_cypher(entity.label), {
            "entity_key": entity.entity_key,
            "name": entity.name,
            "name_norm": entity.name_norm,
        })
        current = rows[0].get("description") if rows else None
        tx.run(SET_DESCRIPTION, {
            "entity_key": entity.entity_key,
            "description": merge_descriptions(
                current if isinstance(current, str) else None,
                entity.description,
            ),
        })
        tx.run(mentions_cypher(entity.label), {
            "chunk_id": plan.chunk_id,
            "entity_key": entity.entity_key,
        })
    for rel in plan.relationships:
        statement = relationship_merge_cypher(
            rel.source_label, rel.rel_type, rel.target_label)
        params: dict[str, Any] = {
            "rel_key": rel.rel_key,
            "origin": rel.origin,
            "from_year": rel.from_year,
            "to_year": rel.to_year,
            "role": rel.role,
            "description": rel.description,
            "source_chunk_ids": [plan.chunk_id],
        }
        if statement == MERGE_DROVE_FOR:
            params["driver_key"] = rel.source_key
            params["team_key"] = rel.target_key
        else:
            params["source_key"] = rel.source_key
            params["target_key"] = rel.target_key
        created = tx.run(statement, params)
        if not created:
            raise RuntimeError(
                f"{rel.rel_type} merge returned no row, so sources were not set."
            )
        current_sources = created[0].get("source_chunk_ids")
        merged = merge_source_ids(current_sources, plan.chunk_id)
        source_params: dict[str, Any] = {
            "rel_key": rel.rel_key,
            "source_chunk_ids": merged,
        }
        if rel.rel_type == "DROVE_FOR":
            source_params["driver_key"] = rel.source_key
            source_params["team_key"] = rel.target_key
        tx.run(set_sources_cypher(rel.rel_type), source_params)


def extracted_constraint_statements() -> tuple[str, ...]:
    """Statements for a later, explicit schema step. Not executed here."""
    return (EXTRACTED_ENTITY_KEY_CONSTRAINT, DROVE_FOR_REL_KEY_CONSTRAINT)


def relationship_uniqueness_supported(version: str) -> bool:
    """True when `version` is Neo4j 5.7 or newer."""
    return _version_tuple(version) >= _MIN_RELATIONSHIP_UNIQUENESS


def apply_extracted_constraints(query: Query) -> str:
    """Create the extracted uniqueness constraints. Explicit command only.

    Not called on import, not called by the loader, and not called by test
    discovery. The version is read first. An unreadable or older server
    raises `ConstraintUnsupported` and no CREATE CONSTRAINT is sent. This
    does not switch the data model. The running database is unchanged until
    a caller invokes this function against that database.
    """
    try:
        rows = query(VERSION_QUERY, {})
        version = _version_from_components(rows)
    except ConstraintUnsupported:
        raise
    except Exception as exc:
        raise ConstraintUnsupported(
            "Neo4j version could not be read; no constraint was created."
        ) from exc
    if not relationship_uniqueness_supported(version):
        raise ConstraintUnsupported(
            f"Neo4j {version} has no relationship-property uniqueness; "
            "no constraint was created and the data model was not changed."
        )
    for statement in extracted_constraint_statements():
        query(statement, {})
    return version


def open_neo4j_transaction() -> GraphTx:
    """Open one write transaction on the configured Neo4j database.

    This connects. Offline tests must not call it. `get_driver` is imported
    here so importing the loader does not connect.
    """
    from .config import get_settings
    from .graph import get_driver

    settings = get_settings()
    session = get_driver().session(database=settings.neo4j_database)
    return _Neo4jTransaction(session, session.begin_transaction())


class _Neo4jTransaction:
    def __init__(self, session: Any, tx: Any) -> None:
        self._session = session
        self._tx = tx
        self._closed = False

    def run(self, cypher: str,
            parameters: dict[str, Any]) -> list[dict[str, Any]]:
        result = self._tx.run(cypher, parameters)
        return [record.data() for record in result]

    def commit(self) -> None:
        try:
            self._tx.commit()
        finally:
            self._close()

    def rollback(self) -> None:
        try:
            self._tx.rollback()
        finally:
            self._close()

    def _close(self) -> None:
        if not self._closed:
            self._session.close()
            self._closed = True


def _validated_result(review: dict[str, Any]) -> ExtractionResult:
    try:
        result = ExtractionResult.model_validate(review["result"])
        validate_extraction(result)
    except KeyError as exc:
        raise ResultRejected("review result is missing.") from exc
    except (ValidationError, ExtractionValidationError) as exc:
        raise ResultRejected(str(exc)) from exc
    return result


def _build_plan(result: ExtractionResult, chunk_id: object) -> LoadPlan:
    if not isinstance(chunk_id, str) or chunk_id == "":
        raise SourceRejected("chunk_id must be a non-empty string.")
    by_local: dict[str, tuple[EntityType, str]] = {}
    entities: list[EntityWrite] = []
    for entity in result.entities:
        try:
            name_norm = normalize_name(entity.name)
            key = make_entity_key(entity.entity_type, entity.name)
        except EmptyNameError as exc:
            raise ResultRejected(str(exc)) from exc
        if key == "":
            raise ResultRejected("entity_key is empty.")
        by_local[entity.local_id] = (entity.entity_type, key)
        entities.append(EntityWrite(
            label=entity.entity_type.value,
            name=entity.name,
            name_norm=name_norm,
            entity_key=key,
            description=entity.description or "",
        ))
    relationships: list[RelationshipWrite] = []
    for rel in result.relationships:
        source_type, source_key = by_local[rel.source_id]
        target_type, target_key = by_local[rel.target_id]
        rel_key = make_rel_key(
            source_key,
            rel.relationship_type.value,
            target_key,
            rel.from_year,
            rel.to_year,
            rel.role,
        )
        if rel_key == "":
            raise ResultRejected("rel_key is empty.")
        relationships.append(RelationshipWrite(
            source_key=source_key,
            target_key=target_key,
            source_label=source_type.value,
            target_label=target_type.value,
            rel_type=rel.relationship_type.value,
            rel_key=rel_key,
            from_year=rel.from_year,
            to_year=rel.to_year,
            role=rel.role,
            description=rel.description,
            origin=ORIGIN_EXTRACTED,
        ))
    return LoadPlan(
        chunk_id=chunk_id,
        entities=tuple(entities),
        relationships=tuple(relationships),
    )


def _require_raw_reference(review: dict[str, Any], raw: dict[str, Any]) -> None:
    if raw.get("status") != "ok":
        raise SourceRejected("The raw record status is not 'ok'.")
    if review.get("chunk_id") != raw.get("chunk_id"):
        raise SourceRejected(
            "chunk_id does not match the chunk_id stored on the raw record."
        )
    if review.get("raw_input_hash") != raw.get("input_hash"):
        raise SourceRejected(
            "raw_input_hash does not match the input_hash stored on the "
            "raw record. This comparison is not a checksum of the raw file."
        )


def _version_from_components(rows: list[dict[str, Any]]) -> str:
    if not rows:
        raise ConstraintUnsupported(
            "Neo4j version was not returned; no constraint was created."
        )
    versions = rows[0].get("versions")
    if isinstance(versions, str) and versions:
        return versions
    if isinstance(versions, list) and versions and isinstance(versions[0], str):
        return versions[0]
    raise ConstraintUnsupported(
        "Neo4j version was not readable; no constraint was created."
    )


def _version_tuple(version: str) -> tuple[int, int]:
    numbers: list[int] = []
    for part in version.split(".")[:2]:
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            else:
                break
        if digits == "":
            break
        numbers.append(int(digits))
    while len(numbers) < 2:
        numbers.append(0)
    return numbers[0], numbers[1]
