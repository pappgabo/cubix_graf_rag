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

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import ValidationError

from .config import PROJECT_ROOT
from .extraction_identity import (
    EmptyNameError,
    canonical_identity,
    identity_rejection,
    make_rel_key,
    merge_descriptions,
    merge_source_ids,
)
from .extraction_models import (
    EntityType,
    ExtractionResult,
    ExtractionValidationError,
    RelType,
    load_saved_extraction,
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
        result, _reasons = load_saved_extraction(result)
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
        result, _reasons = load_saved_extraction(result)
    except KeyError as exc:
        raise ResultRejected("review result is missing.") from exc
    except (ValidationError, ExtractionValidationError) as exc:
        raise ResultRejected(str(exc)) from exc
    return result


def _build_plan(result: ExtractionResult, chunk_id: object) -> LoadPlan:
    if not isinstance(chunk_id, str) or chunk_id == "":
        raise SourceRejected("chunk_id must be a non-empty string.")
    by_local: dict[str, tuple[EntityType, str]] = {}
    entities: dict[str, EntityWrite] = {}
    entity_order: list[str] = []
    for entity in result.entities:
        if identity_rejection(entity.name) is not None:
            continue
        try:
            key, display_name, name_norm = canonical_identity(
                entity.entity_type, entity.name)
        except EmptyNameError as exc:
            raise ResultRejected(str(exc)) from exc
        if key == "":
            raise ResultRejected("entity_key is empty.")
        by_local[entity.local_id] = (entity.entity_type, key)
        previous = entities.get(key)
        entities[key] = EntityWrite(
            label=entity.entity_type.value,
            name=display_name,
            name_norm=name_norm,
            entity_key=key,
            description=merge_descriptions(
                previous.description if previous else None,
                entity.description or "",
            ),
        )
        if key not in entity_order:
            entity_order.append(key)
    relationships: dict[str, RelationshipWrite] = {}
    relationship_order: list[str] = []
    for rel in result.relationships:
        if rel.source_id not in by_local or rel.target_id not in by_local:
            continue
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
        previous = relationships.get(rel_key)
        relationships[rel_key] = RelationshipWrite(
            source_key=source_key,
            target_key=target_key,
            source_label=source_type.value,
            target_label=target_type.value,
            rel_type=rel.relationship_type.value,
            rel_key=rel_key,
            from_year=rel.from_year,
            to_year=rel.to_year,
            role=rel.role,
            description=merge_descriptions(
                previous.description if previous else None,
                rel.description,
            ),
            origin=ORIGIN_EXTRACTED,
        )
        if rel_key not in relationship_order:
            relationship_order.append(rel_key)
    return LoadPlan(
        chunk_id=chunk_id,
        entities=tuple(entities[key] for key in entity_order),
        relationships=tuple(relationships[key] for key in relationship_order),
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


@dataclass(frozen=True)
class CorpusPlan:
    """Plans from structurally accepted raw records. Not human approval."""

    plans: tuple[LoadPlan, ...]
    failures: tuple[tuple[str, str], ...]


def plan_validated_corpus(input_dir: Path) -> CorpusPlan:
    """Plan each saved record. Does not open a database or edit the files."""
    if not input_dir.is_dir():
        raise SourceRejected(f"input directory does not exist: {input_dir}")
    plans: list[LoadPlan] = []
    failures: list[tuple[str, str]] = []
    for path in sorted(input_dir.glob("*.json")):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append((path.name, f"invalid JSON: {exc}"))
            continue
        if not isinstance(loaded, dict):
            failures.append((path.name, "record is not an object"))
            continue
        try:
            plans.append(plan_validated_raw(loaded, accept_validated_raw=True))
        except LoadRejected as exc:
            label = loaded.get("chunk_id")
            failures.append((
                str(label) if isinstance(label, str) and label else path.name,
                f"{type(exc).__name__}: {exc}",
            ))
    return CorpusPlan(tuple(plans), tuple(failures))


def load_validated_corpus(input_dir: Path, *, write: bool = False,
                          open_tx: Opener | None = None) -> CorpusPlan:
    """Plan the corpus. Write only when ``write`` is true.

    Writing calls ``load_approved_plan`` once per plan. Dry-run does not
    call ``open_tx`` and does not open Neo4j.
    """
    planned = plan_validated_corpus(input_dir)
    if not write:
        return planned
    opener = open_tx if open_tx is not None else open_neo4j_transaction
    for plan in planned.plans:
        load_approved_plan(plan, opener)
    return planned


BACKUP_FORMAT = "extracted-layer-backup-1"
_PROTECTED_LABELS = ("Seed", "Document", "Chunk", "Section", "Corpus")

MIXED_LABEL_QUERY = """
MATCH (n:Extracted)
WHERE n:Seed OR n:Document OR n:Chunk OR n:Section OR n:Corpus
RETURN labels(n) AS labels, n.entity_key AS entity_key
ORDER BY entity_key
""".strip()

EXTRACTED_NODE_QUERY = """
MATCH (n:Extracted)
RETURN labels(n) AS labels, properties(n) AS properties
ORDER BY n.entity_key
""".strip()

EXTRACTED_EDGE_QUERY = """
MATCH (a)-[r]->(b)
WHERE a:Extracted OR b:Extracted
RETURN type(r) AS type, properties(r) AS properties,
       labels(a) AS source_labels, properties(a) AS source_properties,
       labels(b) AS target_labels, properties(b) AS target_properties
ORDER BY type(r),
         coalesce(a.entity_key, a.chunk_id),
         coalesce(b.entity_key, b.chunk_id),
         coalesce(r.rel_key, "")
""".strip()

EXTRACTED_COUNT_QUERY = """
MATCH (n:Extracted)
RETURN count(n) AS nodes
""".strip()

EXTRACTED_EDGE_COUNT_QUERY = """
MATCH (a)-[r]->(b)
WHERE a:Extracted OR b:Extracted
RETURN count(r) AS edges
""".strip()

# Deletes only nodes that carry :Extracted and none of the protected labels.
# DETACH DELETE removes edges that touch those nodes. It does not match
# :Chunk, :Document, :Section, :Corpus, or :Seed nodes.
DELETE_EXTRACTED_CYPHER = """
MATCH (n:Extracted)
WHERE NOT n:Seed AND NOT n:Document AND NOT n:Chunk
  AND NOT n:Section AND NOT n:Corpus
DETACH DELETE n
""".strip()


class LayerRejected(LoadRejected):
    """The extracted layer cannot be replaced or restored safely."""


class PartialLoad(RuntimeError):
    """The extracted layer was deleted and only some plans were written."""

    def __init__(self, written: int, total: int, backup: Path) -> None:
        self.written = written
        self.total = total
        self.backup = backup
        super().__init__(
            f"partial load: the :Extracted layer was deleted and "
            f"{written} of {total} plans were written. "
            f"Restore from {backup}."
        )


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    raise LayerRejected(f"property value {type(value).__name__} is not JSON")


def _type_label(labels: list[str]) -> str:
    kind = [label for label in labels if label != "Extracted"]
    if len(kind) != 1 or kind[0] not in _LABELS:
        raise LayerRejected(f"extracted node labels are not restorable: {labels}")
    return kind[0]


def _durable_endpoint(labels: list[str], properties: dict) -> dict[str, str]:
    label_list = [str(label) for label in labels]
    if "Extracted" in label_list:
        return {
            "kind": "extracted",
            "label": _type_label(label_list),
            "entity_key": str(properties["entity_key"]),
        }
    if label_list == ["Chunk"]:
        chunk_id = properties.get("chunk_id")
        if not isinstance(chunk_id, str) or chunk_id == "":
            raise LayerRejected("Chunk endpoint has no chunk_id")
        return {"kind": "chunk", "chunk_id": chunk_id}
    raise LayerRejected(
        f"endpoint has no durable key for labels {label_list}")


def build_extracted_backup(node_rows: list[dict],
                           edge_rows: list[dict],
                           mixed_rows: list[dict]) -> dict:
    """Build a restorable snapshot. Endpoints use entity_key or chunk_id."""
    nodes = []
    for row in node_rows:
        labels = [str(label) for label in row["labels"]]
        properties = _json_value(row["properties"])
        if not isinstance(properties, dict) or "entity_key" not in properties:
            raise LayerRejected("extracted node has no entity_key")
        _type_label(labels)
        nodes.append({"labels": labels, "properties": properties})
    edges = []
    for row in edge_rows:
        source_props = _json_value(row["source_properties"])
        target_props = _json_value(row["target_properties"])
        if not isinstance(source_props, dict) or not isinstance(target_props, dict):
            raise LayerRejected("edge endpoint properties are not an object")
        edges.append({
            "type": str(row["type"]),
            "properties": _json_value(row["properties"]),
            "source": _durable_endpoint(list(row["source_labels"]), source_props),
            "target": _durable_endpoint(list(row["target_labels"]), target_props),
        })
    return {
        "format": BACKUP_FORMAT,
        "mixed": [
            {"labels": [str(label) for label in row["labels"]],
             "entity_key": row.get("entity_key")}
            for row in mixed_rows
        ],
        "nodes": nodes,
        "edges": edges,
    }


def read_extracted_backup(path: Path) -> dict:
    """Load a backup and reject a file that cannot be restored."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format") != BACKUP_FORMAT:
        raise LayerRejected(f"{path} is not an extracted-layer backup")
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise LayerRejected(f"{path} has no node and edge lists")
    for node in nodes:
        labels = node.get("labels")
        properties = node.get("properties")
        if not isinstance(labels, list) or not isinstance(properties, dict):
            raise LayerRejected("backup node is incomplete")
        if not isinstance(properties.get("entity_key"), str):
            raise LayerRejected("backup node has no entity_key")
        _type_label([str(label) for label in labels])
    for edge in edges:
        if edge.get("type") not in set(_REL_TYPES) | {"MENTIONS"}:
            raise LayerRejected(f"backup edge type {edge.get('type')!r} is unknown")
        for end in ("source", "target"):
            ref = edge.get(end)
            if not isinstance(ref, dict):
                raise LayerRejected("backup edge has no durable endpoint")
            if ref.get("kind") == "extracted":
                if not isinstance(ref.get("entity_key"), str):
                    raise LayerRejected("backup edge has no entity_key")
                _check_name(str(ref.get("label")), _LABELS, "entity label")
            elif ref.get("kind") == "chunk":
                if not isinstance(ref.get("chunk_id"), str) or ref["chunk_id"] == "":
                    raise LayerRejected("backup edge has no chunk_id")
            else:
                raise LayerRejected("backup edge endpoint is not durable")
        if "element_id" in edge or "elementId" in edge:
            raise LayerRejected("backup edge uses an internal id")
    return payload


def save_extracted_backup(path: Path, query_fn: Query | None = None) -> dict:
    """Read the current :Extracted layer and write a new backup file."""
    if path.exists():
        raise LayerRejected(f"backup already exists: {path}")
    reader = query_fn if query_fn is not None else _read_query
    payload = build_extracted_backup(
        reader(EXTRACTED_NODE_QUERY),
        reader(EXTRACTED_EDGE_QUERY),
        reader(MIXED_LABEL_QUERY),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    read_extracted_backup(path)
    return payload


def _read_query(cypher: str, **params: Any) -> list[dict[str, Any]]:
    from .graph import query

    return query(cypher, **params)


def extracted_scope(query_fn: Query | None = None) -> dict[str, Any]:
    """Read-only counts for the layer a replace would delete."""
    reader = query_fn if query_fn is not None else _read_query
    mixed = reader(MIXED_LABEL_QUERY)
    nodes = reader(EXTRACTED_COUNT_QUERY)[0]["nodes"]
    edges = reader(EXTRACTED_EDGE_COUNT_QUERY)[0]["edges"]
    return {"mixed": mixed, "nodes": nodes, "edges": edges}


def _embedding_params(props: dict) -> dict[str, Any] | None:
    """Return the stored vector fields, or None when the backup has none.

    A present vector is written back with its model, dimension, and text
    hash. An incomplete vector is rejected before the layer is deleted.
    """
    if "embedding" not in props or props.get("embedding") is None:
        return None
    embedding = props.get("embedding")
    if (not isinstance(embedding, list) or not embedding
            or any(isinstance(item, bool) or not isinstance(item, (int, float))
                   for item in embedding)):
        raise LayerRejected("backup embedding is not a numeric vector")
    model = props.get("embedding_model")
    dimensions = props.get("embedding_dimensions")
    digest = props.get("embedding_text_sha256")
    if not isinstance(model, str) or model == "":
        raise LayerRejected("backup embedding has no model")
    if (not isinstance(dimensions, int) or isinstance(dimensions, bool)
            or dimensions != len(embedding)):
        raise LayerRejected("backup embedding dimensions do not match the vector")
    if not isinstance(digest, str) or digest == "":
        raise LayerRejected("backup embedding has no text hash")
    return {
        "embedding": [float(item) for item in embedding],
        "embedding_model": model,
        "embedding_dimensions": dimensions,
        "embedding_text_sha256": digest,
    }


def _restore_node_cypher(label: str, *, with_embedding: bool) -> str:
    _check_name(label, _LABELS, "entity label")
    statement = (
        f"MERGE (e:{label}:Extracted {{entity_key: $entity_key}})\n"
        "SET e.name = $name, e.name_norm = $name_norm, "
        "e.description = $description"
    )
    if with_embedding:
        statement += (
            ",\n    e.embedding = $embedding,\n"
            "    e.embedding_model = $embedding_model,\n"
            "    e.embedding_dimensions = $embedding_dimensions,\n"
            "    e.embedding_text_sha256 = $embedding_text_sha256"
        )
    return statement


def _restore_edge_cypher(edge: dict) -> tuple[str, dict[str, Any]]:
    source = edge["source"]
    target = edge["target"]
    properties = edge.get("properties") or {}
    if edge["type"] == "MENTIONS":
        if source.get("kind") != "chunk" or target.get("kind") != "extracted":
            raise LayerRejected("MENTIONS backup edge is not Chunk -> Extracted")
        label = str(target["label"])
        _check_name(label, _LABELS, "entity label")
        return (
            f"MATCH (c:Chunk {{chunk_id: $chunk_id}})\n"
            f"MATCH (e:{label}:Extracted {{entity_key: $entity_key}})\n"
            "MERGE (c)-[:MENTIONS]->(e)\n"
            "RETURN c.chunk_id AS chunk_id",
            {"chunk_id": source["chunk_id"], "entity_key": target["entity_key"]},
        )
    if source.get("kind") != "extracted" or target.get("kind") != "extracted":
        raise LayerRejected(f"{edge['type']} backup edge is not between extracted nodes")
    rel_key = properties.get("rel_key")
    if not isinstance(rel_key, str) or rel_key == "":
        raise LayerRejected(f"{edge['type']} backup edge has no rel_key")
    source_label = str(source["label"])
    target_label = str(target["label"])
    _check_name(source_label, _LABELS, "entity label")
    _check_name(target_label, _LABELS, "entity label")
    _check_name(str(edge["type"]), _REL_TYPES, "relationship type")
    return (
        f"MATCH (s:{source_label}:Extracted {{entity_key: $source_key}})\n"
        f"MATCH (t:{target_label}:Extracted {{entity_key: $target_key}})\n"
        f"MERGE (s)-[r:{edge['type']} {{rel_key: $rel_key}}]->(t)\n"
        "SET r.origin = $origin, r.description = $description,\n"
        "    r.from_year = $from_year, r.to_year = $to_year, r.role = $role,\n"
        "    r.source_chunk_ids = $source_chunk_ids\n"
        "RETURN r.rel_key AS rel_key",
        {
            "source_key": source["entity_key"],
            "target_key": target["entity_key"],
            "rel_key": rel_key,
            "origin": properties.get("origin"),
            "description": properties.get("description"),
            "from_year": properties.get("from_year"),
            "to_year": properties.get("to_year"),
            "role": properties.get("role"),
            "source_chunk_ids": properties.get("source_chunk_ids"),
        },
    )


def restore_extracted_backup(path: Path, open_tx: Opener) -> dict:
    """Replace the current :Extracted layer with one backup, in one transaction.

    Refuses when a protected label shares an :Extracted node. Does not match
    document or seed nodes.
    """
    payload = read_extracted_backup(path)
    prepared = []
    for node in payload["nodes"]:
        label = _type_label([str(item) for item in node["labels"]])
        props = node["properties"]
        prepared.append((label, props, _embedding_params(props)))

    def work(tx: GraphTx) -> None:
        mixed = tx.run(MIXED_LABEL_QUERY, {})
        if mixed:
            raise LayerRejected(
                "an :Extracted node also has a protected label; "
                "restore will not delete it"
            )
        tx.run(DELETE_EXTRACTED_CYPHER, {})
        for label, props, embedding in prepared:
            params = {
                "entity_key": props["entity_key"],
                "name": props.get("name"),
                "name_norm": props.get("name_norm"),
                "description": props.get("description"),
            }
            if embedding is not None:
                params.update(embedding)
            tx.run(_restore_node_cypher(label, with_embedding=embedding is not None), params)
        for edge in payload["edges"]:
            cypher, params = _restore_edge_cypher(edge)
            found = tx.run(cypher, params)
            if not found:
                raise LayerRejected(
                    f"restore could not match {edge['type']} endpoints"
                )

    run_unit_of_work(open_tx, work)
    return payload


def replace_extracted_layer(input_dir: Path, backup_path: Path, *,
                            write: bool = False,
                            open_tx: Opener | None = None,
                            query_fn: Query | None = None) -> tuple[dict, CorpusPlan]:
    """Plan a replacement. Delete and load only when ``write`` is true.

    Dry-run reads the scope and does not open a write transaction.
    """
    planned = plan_validated_corpus(input_dir)
    scope = extracted_scope(query_fn)
    if not write:
        return scope, planned
    if scope["mixed"]:
        raise LayerRejected(
            "an :Extracted node also has Seed, Document, Chunk, Section, "
            "or Corpus; automatic deletion was not run"
        )
    if planned.failures:
        raise LayerRejected(
            f"{len(planned.failures)} plans failed; the layer was not deleted"
        )
    payload = read_extracted_backup(backup_path)
    if (len(payload["nodes"]) != scope["nodes"]
            or len(payload["edges"]) != scope["edges"]):
        raise LayerRejected(
            "backup counts do not match the current :Extracted layer; "
            "the layer was not deleted"
        )
    opener = open_tx if open_tx is not None else open_neo4j_transaction
    run_unit_of_work(opener, lambda tx: tx.run(DELETE_EXTRACTED_CYPHER, {}))
    written = 0
    try:
        for plan in planned.plans:
            load_approved_plan(plan, opener)
            written += 1
    except Exception as exc:
        raise PartialLoad(written, len(planned.plans), backup_path) from exc
    return scope, planned


def corpus_plan_summary(planned: CorpusPlan) -> str:
    entity_keys = {
        entity.entity_key
        for plan in planned.plans
        for entity in plan.entities
    }
    rel_keys = {
        rel.rel_key
        for plan in planned.plans
        for rel in plan.relationships
    }
    lines = [
        "write: no",
        f"planned: {len(planned.plans)}",
        f"failed: {len(planned.failures)}",
        f"entity_keys: {len(entity_keys)}",
        f"rel_keys: {len(rel_keys)}",
    ]
    reasons = Counter(reason for _label, reason in planned.failures)
    if not reasons:
        lines.append("failures: none")
    else:
        for reason, count in reasons.most_common():
            lines.append(f"failure: {count} {reason}")
    return "\n".join(line for line in lines if line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m naive_rag.extraction_load")
    parser.add_argument("--input-dir", required=True,
                        help="saved extraction directory; files are not modified")
    parser.add_argument("--write", action="store_true",
                        help="write plans with the existing loader; default is dry-run")
    parser.add_argument("--replace", action="store_true",
                        help="replace only the :Extracted layer; default is dry-run")
    parser.add_argument("--backup", default=None,
                        help="extracted-layer backup required by --replace")
    parser.add_argument("--restore", action="store_true",
                        help="restore the :Extracted layer from --backup")
    args = parser.parse_args(argv)
    try:
        if args.restore:
            if not args.backup:
                print("error: --restore requires --backup", file=sys.stderr)
                return 1
            if not args.write:
                payload = read_extracted_backup(Path(args.backup))
                print("write: no")
                print(f"restore_nodes: {len(payload['nodes'])}")
                print(f"restore_edges: {len(payload['edges'])}")
                print(f"mixed: {len(payload['mixed'])}")
                return 0
            restore_extracted_backup(Path(args.backup), open_neo4j_transaction)
            print("write: yes")
            print(f"restored: {args.backup}")
            return 0
        if args.replace:
            if not args.backup:
                print("error: --replace requires --backup", file=sys.stderr)
                return 1
            scope, planned = replace_extracted_layer(
                Path(args.input_dir), Path(args.backup), write=args.write)
            print("write: yes" if args.write else "write: no")
            print(f"mixed: {len(scope['mixed'])}")
            print(f"delete_nodes: {scope['nodes']}")
            print(f"delete_edges: {scope['edges']}")
            print(corpus_plan_summary(planned).replace("write: no\n", ""))
            print("delete: " + " ".join(DELETE_EXTRACTED_CYPHER.split()))
            return 0
        planned = load_validated_corpus(Path(args.input_dir), write=args.write)
    except PartialLoad as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (SourceRejected, LayerRejected) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = corpus_plan_summary(planned)
    if args.write:
        text = text.replace("write: no", "write: yes", 1)
    print(text)
    return 0


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


if __name__ == "__main__":
    sys.exit(main())
