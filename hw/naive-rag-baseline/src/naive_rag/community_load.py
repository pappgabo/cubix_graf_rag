"""Week 4 community layer: prepared-projection Leiden communities -> Neo4j.

Dry-run by default. Nothing in this module opens a Neo4j connection or
writes anything unless the caller passes a ``write_fn`` *and* ``apply=True``
explicitly (same injection pattern as ``extraction_load.py`` /
``neo4j_entity_index.py``). No Leiden run happens here, no package is
installed, no model is called.

Source artifact (read-only): ``docs/week4-vetulet-leképezés.json``
(node -> path mapping, alias map, excluded list, hash block, parameters).
``docs/week4-kozosseg-statisztika.md`` is the human-readable report; it is
not parsed here and this module never writes to it.

Community node model
---------------------
One ``:Community`` per genuine distinct Leiden partition output -- not one
per reporting level. A branch that stops splitting keeps a single Community
node for every deeper reporting level; it is not duplicated. Membership is
leaf-only (Model B): each non-isolated canonical node gets exactly one
``MEMBER_OF`` edge, to the deepest community its path actually reached.
Shallower-level membership is derived by following ``PARENT_OF`` upward
(see ``reporting_level_paths`` / ``REPORTING_LEVEL_QUERY``).

Run isolation
-------------
``community_id`` is ``"{run_id}:{path}"``, never ``"{projection}:{path}"``.
The same ``path`` string in two different runs is not the same community:
a different run gets an entirely different, non-colliding set of
``community_id`` values, so it can never silently overwrite a previous
run's communities. ``run_id`` is a deterministic fingerprint of the
projection hash, the Leiden parameters (including library versions), and
an ``assignment_hash`` of the canonical node -> path mapping itself.

``assignment_hash`` is **not** present in the mapping JSON's ``"hash"``
block. That block (``hash.nyers`` / ``hash.elokeszitett``) is a hash of the
*pre-partition input* (sorted node list + sorted edge list + parameters),
computed by ``week4_leiden.py`` to prove the two Leiden runs saw identical
input. It is not a hash of the *output* node -> path assignment, so this
loader computes ``assignment_hash`` fresh from the canonical mapping.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

Query = Callable[..., list[dict[str, Any]]]

PROJECTION = "elokeszitett"
DEFAULT_MAPPING_PATH = Path("docs/week4-vetulet-leképezés.json")

# Dataset-specific regression guard for the audited week4 prepared
# projection. Passed explicitly to build_plan()/validate_plan(); never
# assumed for an arbitrary mapping (see the small fixture in the tests).
EXPECTED_COUNTS_WEEK4_PREPARED: dict[str, Any] = {
    "canonical": 2645,
    "isolated": 736,
    "members": 1909,
    "excluded": 77,
    "alias": 39,
    "total_universe": 2761,
    "communities_total": 520,
    "communities_by_level": {0: 37, 1: 176, 2: 253, 3: 54},
    "member_of": 1909,
    "parent_of": 483,
    "has_community": 520,
}


class MappingRejected(ValueError):
    """The week4 mapping artifact is not in the expected shape."""


class PlanInconsistent(RuntimeError):
    """A computed count diverges from an always-true invariant, or from an
    explicitly supplied, audited expectation."""


class PreflightRejected(RuntimeError):
    """The live graph (or its backup) does not match what the plan needs."""


# --------------------------------------------------------------------------
# Loading and shaping the mapping artifact
# --------------------------------------------------------------------------


def load_mapping(path: Path = DEFAULT_MAPPING_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = ("parameterek", "hash", "alias", "kizart", "nyers", "elokeszitett")
    missing = [key for key in required if key not in payload]
    if missing:
        raise MappingRejected(f"{path} is missing {missing}")
    return payload


def canonical_entries(mapping: dict[str, Any]) -> dict[str, str]:
    """The 2645 canonical prepared-projection nodes, alias sources excluded.

    ``mapping["elokeszitett"]`` also carries one entry per alias *source*
    key (mirroring its canonical target's path, for convenient lookup) --
    those are not independent graph nodes and must never be treated as a
    separate community member.
    """
    alias_sources = set(mapping["alias"].keys())
    prepared = mapping["elokeszitett"]
    return {key: value for key, value in prepared.items() if key not in alias_sources}


def split_isolated(canonical: dict[str, str]) -> tuple[frozenset[str], frozenset[str]]:
    """(isolated keys, member keys). Isolated = alone in its level-0 group."""
    level0_counts: dict[str, int] = {}
    for path in canonical.values():
        level0 = path.split("/", 1)[0]
        level0_counts[level0] = level0_counts.get(level0, 0) + 1
    isolated = frozenset(
        key for key, path in canonical.items()
        if level0_counts[path.split("/", 1)[0]] == 1
    )
    members = frozenset(canonical) - isolated
    return isolated, members


@dataclass(frozen=True)
class CommunityRecord:
    path: str
    level: int
    size: int
    is_leaf: bool


def build_communities(
    canonical: dict[str, str], member_keys: Iterable[str]
) -> tuple[dict[str, CommunityRecord], list[tuple[str, str]], dict[str, str]]:
    """(path -> CommunityRecord, [(parent_path, child_path), ...], entity_key -> leaf path).

    One Community per distinct path prefix that actually occurs -- not one
    per reporting level. ``is_leaf`` is true for a path that is nobody's
    parent (the branch stopped there).
    """
    member_of: dict[str, str] = {}
    subtree_size: dict[str, int] = {}
    parent_of_path: dict[str, str | None] = {}
    for key in member_keys:
        path = canonical[key]
        parts = path.split("/")
        member_of[key] = path
        previous: str | None = None
        for length in range(1, len(parts) + 1):
            current = "/".join(parts[:length])
            subtree_size[current] = subtree_size.get(current, 0) + 1
            parent_of_path.setdefault(current, previous)
            previous = current
    has_children: dict[str, bool] = {}
    for child, parent in parent_of_path.items():
        if parent is not None:
            has_children[parent] = True
    communities = {
        path: CommunityRecord(
            path=path,
            level=path.count("/"),
            size=size,
            is_leaf=not has_children.get(path, False),
        )
        for path, size in subtree_size.items()
    }
    parent_of = [
        (parent, child) for child, parent in parent_of_path.items() if parent is not None
    ]
    return communities, parent_of, member_of


# --------------------------------------------------------------------------
# Reproducibility fingerprint
# --------------------------------------------------------------------------


def compute_assignment_hash(canonical: dict[str, str]) -> str:
    """SHA-256 of the sorted, deterministically serialized canonical mapping.

    Not present anywhere in the mapping JSON -- see the module docstring.
    """
    lines = [f"{key}\t{value}" for key, value in sorted(canonical.items())]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def compute_audit_artifact_hash(alias: dict[str, str], kizart: list[str]) -> str:
    """SHA-256 over the alias map and excluded-key list, sorted and fixed."""
    payload = {"alias": dict(sorted(alias.items())), "kizart": sorted(kizart)}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_params(mapping: dict[str, Any]) -> dict[str, Any]:
    raw = mapping["parameterek"]
    return {
        "partition_algorithm": raw["particio"],
        "resolution_parameter": raw["resolution_parameter"],
        "n_iterations": raw["n_iterations"],
        "seed": raw["seed"],
        "leidenalg_version": raw["leidenalg"],
        "igraph_version": raw["igraph"],
        "edge_weight_semantics": raw["weights"],
    }


def compute_run_id(
    *, projection: str, projection_hash: str, assignment_hash: str, params: dict[str, Any]
) -> str:
    """Deterministic fingerprint: identical inputs always give the same run_id.

    This is what makes a rerun of the *same* analysis a true no-op (same
    community_id values, MERGE finds the existing nodes) while a rerun with
    *any* different parameter, hash, or assignment produces a run_id that
    cannot collide with the previous one.
    """
    param_text = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    source = "\n".join([projection, projection_hash, assignment_hash, param_text])
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return f"week4-leiden-{projection}-{digest[:16]}"


def community_id(run_id: str, path: str) -> str:
    return f"{run_id}:{path}"


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CommunityPlan:
    run_id: str
    projection: str
    projection_hash: str
    assignment_hash: str
    audit_artifact_hash: str
    params: dict[str, Any]
    communities: dict[str, CommunityRecord]
    member_of: dict[str, str]
    parent_of: list[tuple[str, str]]
    isolated_keys: frozenset[str]
    excluded_keys: frozenset[str]
    alias_keys: frozenset[str]
    canonical_keys: frozenset[str]


def validate_plan(plan: CommunityPlan, *, expected: dict[str, Any] | None = None) -> None:
    """Always-on structural invariants, plus an optional dataset-specific
    regression guard (``expected``, e.g. ``EXPECTED_COUNTS_WEEK4_PREPARED``).

    Any deviation raises ``PlanInconsistent`` -- this is meant to be called
    before any write is attempted.
    """
    errors: list[str] = []
    canonical_n = len(plan.canonical_keys)
    isolated_n = len(plan.isolated_keys)
    members_n = len(plan.member_of)
    excluded_n = len(plan.excluded_keys)
    alias_n = len(plan.alias_keys)

    if isolated_n + members_n != canonical_n:
        errors.append(
            f"isolated+members ({isolated_n}+{members_n}) != canonical ({canonical_n})"
        )
    if set(plan.member_of) != (plan.canonical_keys - plan.isolated_keys):
        errors.append("member_of keys do not equal canonical-minus-isolated")
    if set(plan.member_of) & plan.alias_keys:
        errors.append("alias keys leaked into membership")

    by_level: dict[int, int] = {}
    for record in plan.communities.values():
        by_level[record.level] = by_level.get(record.level, 0) + 1
    if sum(by_level.values()) != len(plan.communities):
        errors.append("per-level community counts do not sum to the total")
    level0_n = by_level.get(0, 0)
    if len(plan.parent_of) != len(plan.communities) - level0_n:
        errors.append("parent_of count != communities - level0 roots")
    level0_size_sum = sum(r.size for r in plan.communities.values() if r.level == 0)
    if level0_size_sum != members_n:
        errors.append(f"level-0 size sum ({level0_size_sum}) != member count ({members_n})")

    if expected is not None:
        def check(label: str, actual: Any, exp: Any) -> None:
            if actual != exp:
                errors.append(f"{label}: expected {exp}, got {actual}")

        check("canonical nodes", canonical_n, expected["canonical"])
        check("isolated nodes", isolated_n, expected["isolated"])
        check("member nodes", members_n, expected["members"])
        check("excluded nodes", excluded_n, expected["excluded"])
        check("alias keys", alias_n, expected["alias"])
        check("total universe", members_n + isolated_n + excluded_n + alias_n,
              expected["total_universe"])
        check("community total", len(plan.communities), expected["communities_total"])
        for level, exp_count in expected["communities_by_level"].items():
            check(f"level {level} community count", by_level.get(level, 0), exp_count)
        check("member_of edges", members_n, expected["member_of"])
        check("parent_of edges", len(plan.parent_of), expected["parent_of"])
        check("has_community edges", len(plan.communities), expected["has_community"])

    if errors:
        raise PlanInconsistent("; ".join(errors))


def build_plan(mapping: dict[str, Any], *, expected: dict[str, Any] | None = None) -> CommunityPlan:
    canonical = canonical_entries(mapping)
    isolated, members = split_isolated(canonical)
    communities, parent_of, member_of = build_communities(canonical, members)
    params = run_params(mapping)
    projection_hash = mapping["hash"][PROJECTION]
    assignment_hash = compute_assignment_hash(canonical)
    audit_hash = compute_audit_artifact_hash(mapping["alias"], mapping["kizart"])
    run_id = compute_run_id(
        projection=PROJECTION,
        projection_hash=projection_hash,
        assignment_hash=assignment_hash,
        params=params,
    )
    plan = CommunityPlan(
        run_id=run_id,
        projection=PROJECTION,
        projection_hash=projection_hash,
        assignment_hash=assignment_hash,
        audit_artifact_hash=audit_hash,
        params=params,
        communities=communities,
        member_of=member_of,
        parent_of=parent_of,
        isolated_keys=isolated,
        excluded_keys=frozenset(mapping["kizart"]),
        alias_keys=frozenset(mapping["alias"].keys()),
        canonical_keys=frozenset(canonical),
    )
    validate_plan(plan, expected=expected)
    return plan


# --------------------------------------------------------------------------
# Reporting-level view (derived, not separately persisted)
# --------------------------------------------------------------------------


def reporting_level_paths(plan: CommunityPlan, level: int) -> set[str]:
    """Pure-Python mirror of REPORTING_LEVEL_QUERY, for offline testing.

    A community belongs to the level-L report if it is exactly at level L,
    or it is a leaf at a shallower level (its branch stopped early, so the
    same grouping is still the correct answer at every deeper level). A
    plain ``level == L`` filter alone misses every early-stopped branch.
    """
    return {
        path
        for path, record in plan.communities.items()
        if record.level == level or (record.level < level and record.is_leaf)
    }


def subtree_members(plan: CommunityPlan, root_path: str) -> set[str]:
    """Pure-Python mirror of SUBTREE_MEMBERS_QUERY (root included once)."""
    children: dict[str, list[str]] = {}
    for parent, child in plan.parent_of:
        children.setdefault(parent, []).append(child)
    descendants = {root_path}
    frontier = [root_path]
    while frontier:
        current = frontier.pop()
        for child in children.get(current, []):
            if child not in descendants:
                descendants.add(child)
                frontier.append(child)
    return {key for key, path in plan.member_of.items() if path in descendants}


# --------------------------------------------------------------------------
# Preflight (written, not run against a live database in this change)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityAlignmentResult:
    missing_members: frozenset[str]
    missing_isolated: frozenset[str]
    missing_excluded: frozenset[str]
    missing_alias: frozenset[str]
    extra_live_only: frozenset[str]

    @property
    def ok(self) -> bool:
        return not self.missing_members


def check_entity_alignment(plan: CommunityPlan, live_entity_keys: Iterable[str]) -> EntityAlignmentResult:
    live = frozenset(live_entity_keys)
    members = frozenset(plan.member_of)
    universe = members | plan.isolated_keys | plan.excluded_keys | plan.alias_keys
    return EntityAlignmentResult(
        missing_members=members - live,
        missing_isolated=plan.isolated_keys - live,
        missing_excluded=plan.excluded_keys - live,
        missing_alias=plan.alias_keys - live,
        extra_live_only=live - universe,
    )


def require_entity_alignment(plan: CommunityPlan, live_entity_keys: Iterable[str]) -> EntityAlignmentResult:
    """Reject the write outright when any member key has no live :Extracted
    node -- a missing MATCH must never silently produce a missing
    membership edge."""
    result = check_entity_alignment(plan, live_entity_keys)
    if not result.ok:
        raise PreflightRejected(
            f"{len(result.missing_members)} member entity_key(s) have no live "
            f":Extracted node: {sorted(result.missing_members)}"
        )
    return result


@dataclass(frozen=True)
class BackupCheckResult:
    key_sets_match: bool
    edge_count_matches: bool
    missing_in_backup: frozenset[str]
    extra_in_backup: frozenset[str]

    @property
    def ok(self) -> bool:
        return self.key_sets_match and self.edge_count_matches


def check_backup_compatibility(
    backup_path: Path, live_entity_keys: Iterable[str], live_edge_count: int
) -> BackupCheckResult:
    """Validate the hard-copy backup's CONTENT, not just its counts.

    Reuses the existing, already-proven ``extraction_load.read_extracted_backup``
    validator (rejects a malformed file), then compares the backup's
    entity_key *set* -- not merely its length -- against the live
    :Extracted universe, plus the domain edge count. Equal counts with a
    different member set must not pass as "adequate".
    """
    from .extraction_load import read_extracted_backup

    payload = read_extracted_backup(backup_path)
    backup_keys = frozenset(node["properties"]["entity_key"] for node in payload["nodes"])
    live_keys = frozenset(live_entity_keys)
    return BackupCheckResult(
        key_sets_match=backup_keys == live_keys,
        edge_count_matches=len(payload["edges"]) == live_edge_count,
        missing_in_backup=live_keys - backup_keys,
        extra_in_backup=backup_keys - live_keys,
    )


# --------------------------------------------------------------------------
# Cypher (constants only -- none of these run against a live database here)
# --------------------------------------------------------------------------

COMMUNITY_ID_UNIQUE_CONSTRAINT = (
    "CREATE CONSTRAINT community_id_unique IF NOT EXISTS\n"
    "FOR (n:Community) REQUIRE n.community_id IS UNIQUE"
)
COMMUNITY_RUN_ID_UNIQUE_CONSTRAINT = (
    "CREATE CONSTRAINT community_run_id_unique IF NOT EXISTS\n"
    "FOR (n:CommunityRun) REQUIRE n.run_id IS UNIQUE"
)
COMMUNITY_LEVEL_INDEX = (
    "CREATE INDEX community_level IF NOT EXISTS\n"
    "FOR (n:Community) ON (n.run_id, n.level)"
)

MERGE_COMMUNITY_RUN = """
MERGE (r:CommunityRun {run_id: $run_id})
ON CREATE SET r.created_at = datetime()
SET r.projection = $projection,
    r.projection_hash = $projection_hash,
    r.assignment_hash = $assignment_hash,
    r.audit_artifact_hash = $audit_artifact_hash,
    r.partition_algorithm = $partition_algorithm,
    r.resolution_parameter = $resolution_parameter,
    r.n_iterations = $n_iterations,
    r.seed = $seed,
    r.leidenalg_version = $leidenalg_version,
    r.igraph_version = $igraph_version,
    r.edge_weight_semantics = $edge_weight_semantics,
    r.updated_at = datetime()
RETURN r.run_id AS run_id
""".strip()

MERGE_COMMUNITY = """
MERGE (c:Community {community_id: $community_id})
ON CREATE SET c.created_at = datetime()
SET c.run_id = $run_id,
    c.projection = $projection,
    c.path = $path,
    c.level = $level,
    c.size = $size,
    c.is_leaf = $is_leaf,
    c.updated_at = datetime()
RETURN c.community_id AS community_id
""".strip()

MERGE_HAS_COMMUNITY = """
MATCH (r:CommunityRun {run_id: $run_id})
MATCH (c:Community {community_id: $community_id})
MERGE (r)-[:HAS_COMMUNITY]->(c)
""".strip()

MERGE_PARENT_OF = """
MATCH (p:Community {community_id: $parent_id})
MATCH (c:Community {community_id: $child_id})
MERGE (p)-[:PARENT_OF]->(c)
""".strip()

MERGE_MEMBER_OF = """
MATCH (e:Extracted {entity_key: $entity_key})
MATCH (c:Community {community_id: $community_id})
MERGE (e)-[:MEMBER_OF]->(c)
""".strip()

# ---- subtree / reporting-level read queries ----

SUBTREE_MEMBERS_QUERY = """
MATCH (root:Community {community_id: $root_id})
OPTIONAL MATCH (root)-[:PARENT_OF*0..]->(descendant:Community)
WITH collect(DISTINCT descendant) AS subtree
UNWIND subtree AS c
MATCH (e:Extracted)-[:MEMBER_OF]->(c)
RETURN DISTINCT e.entity_key AS entity_key, e.name AS name
""".strip()

REPORTING_LEVEL_QUERY = """
MATCH (run:CommunityRun {run_id: $run_id})-[:HAS_COMMUNITY]->(c:Community)
WHERE c.level = $level OR (c.level < $level AND c.is_leaf = true)
RETURN c.community_id AS community_id, c.level AS level, c.path AS path, c.size AS size
ORDER BY c.path
""".strip()

LIVE_ENTITY_KEYS_QUERY = "MATCH (n:Extracted) RETURN n.entity_key AS entity_key"

# ---- post-write validation (label-based source-graph filtering) ----

SOURCE_GRAPH_NODE_COUNT_QUERY = "MATCH (n:Extracted) RETURN count(n) AS extracted_count"

SOURCE_GRAPH_RELATIONSHIP_COUNTS_QUERY = """
MATCH (a)-[r]->(b)
WHERE NOT a:Community AND NOT a:CommunityRun
  AND NOT b:Community AND NOT b:CommunityRun
RETURN type(r) AS rel_type, count(r) AS count
ORDER BY rel_type
""".strip()

COMMUNITY_COUNT_BY_LEVEL_QUERY = """
MATCH (c:Community {run_id: $run_id})
RETURN c.level AS level, count(c) AS n
ORDER BY level
""".strip()

MEMBER_OF_COUNT_QUERY = """
MATCH (e:Extracted)-[r:MEMBER_OF]->(c:Community {run_id: $run_id})
RETURN count(r) AS member_of_count
""".strip()

PARENT_OF_COUNT_QUERY = """
MATCH (:Community {run_id: $run_id})-[r:PARENT_OF]->(:Community {run_id: $run_id})
RETURN count(r) AS parent_of_count
""".strip()

LEVEL0_SIZE_SUM_QUERY = """
MATCH (c:Community {run_id: $run_id, level: 0})
RETURN sum(c.size) AS total_level0_size
""".strip()

COMMUNITY_SIZE_CONSISTENCY_QUERY = """
MATCH (c:Community {run_id: $run_id})
CALL {
  WITH c
  MATCH (c)-[:PARENT_OF*0..]->(d:Community)
  MATCH (:Extracted)-[:MEMBER_OF]->(d)
  RETURN count(*) AS computed_size
}
WITH c, computed_size
WHERE c.size <> computed_size
RETURN c.community_id AS community_id, c.size AS stored_size, computed_size
""".strip()

PARENT_CHILD_COMPLETENESS_QUERY = """
MATCH (c:Community {run_id: $run_id})
WHERE c.level > 0
OPTIONAL MATCH (p:Community {run_id: $run_id})-[:PARENT_OF]->(c)
WITH c, count(p) AS parents
WHERE parents <> 1
RETURN c.community_id AS community_id, parents AS problem_parent_count
""".strip()

PARENT_CHILD_ACYCLIC_QUERY = """
MATCH p = (c:Community {run_id: $run_id})-[:PARENT_OF*1..10]->(c)
RETURN count(p) AS cycle_count
""".strip()

ALIAS_AUDIT_QUERY = """
UNWIND $alias_pairs AS pair
MATCH (canonical:Extracted {entity_key: pair.target})
OPTIONAL MATCH (canonical)-[:MEMBER_OF]->(c:Community {run_id: $run_id})
RETURN pair.source AS alias_source, pair.target AS canonical, c.community_id AS community_id
""".strip()

# ---- rollback ----
#
# Both queries match Community nodes by the denormalized run_id PROPERTY,
# not by walking the HAS_COMMUNITY edge from CommunityRun. A partial or
# interrupted write can leave orphans either way (a Community whose
# HAS_COMMUNITY edge never got written, or a CommunityRun whose Community
# nodes are already gone) -- matching by property catches both, and the
# two deletes are independent so either orphan is still removed.

ROLLBACK_PREVIEW_QUERY = """
OPTIONAL MATCH (c:Community {run_id: $run_id})
OPTIONAL MATCH (e:Extracted)-[m:MEMBER_OF]->(c)
OPTIONAL MATCH (c)-[p:PARENT_OF]->(:Community {run_id: $run_id})
OPTIONAL MATCH (r:CommunityRun {run_id: $run_id})
RETURN count(DISTINCT c) AS communities,
       count(DISTINCT m) AS member_of_edges,
       count(DISTINCT p) AS parent_of_edges,
       count(DISTINCT r) AS community_run_nodes
""".strip()

ROLLBACK_DELETE_COMMUNITIES_QUERY = """
MATCH (c:Community {run_id: $run_id})
DETACH DELETE c
""".strip()

ROLLBACK_DELETE_RUN_QUERY = """
MATCH (r:CommunityRun {run_id: $run_id})
DETACH DELETE r
""".strip()


# --------------------------------------------------------------------------
# Applying the plan (dry-run unless apply=True and write_fn is given)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteSummary:
    run_id: str
    community_run_upserts: int
    community_upserts: int
    has_community_edges: int
    member_of_edges: int
    parent_of_edges: int
    applied: bool


def _run_params_payload(plan: CommunityPlan) -> dict[str, Any]:
    return {
        "run_id": plan.run_id,
        "projection": plan.projection,
        "projection_hash": plan.projection_hash,
        "assignment_hash": plan.assignment_hash,
        "audit_artifact_hash": plan.audit_artifact_hash,
        **plan.params,
    }


def _community_payload(plan: CommunityPlan, record: CommunityRecord) -> dict[str, Any]:
    return {
        "community_id": community_id(plan.run_id, record.path),
        "run_id": plan.run_id,
        "projection": plan.projection,
        "path": record.path,
        "level": record.level,
        "size": record.size,
        "is_leaf": record.is_leaf,
    }


def persist_plan(plan: CommunityPlan, *, write_fn: Query | None, apply: bool) -> WriteSummary:
    """Dry-run (no write_fn call) unless ``apply=True`` *and* ``write_fn`` is
    given. This function never opens a Neo4j connection itself."""
    if apply and write_fn is None:
        raise ValueError("apply=True requires a write_fn")
    if apply:
        assert write_fn is not None
        write_fn(MERGE_COMMUNITY_RUN, **_run_params_payload(plan))
        for record in plan.communities.values():
            write_fn(MERGE_COMMUNITY, **_community_payload(plan, record))
            write_fn(
                MERGE_HAS_COMMUNITY,
                run_id=plan.run_id,
                community_id=community_id(plan.run_id, record.path),
            )
        for parent_path, child_path in plan.parent_of:
            write_fn(
                MERGE_PARENT_OF,
                parent_id=community_id(plan.run_id, parent_path),
                child_id=community_id(plan.run_id, child_path),
            )
        for entity_key, path in plan.member_of.items():
            write_fn(
                MERGE_MEMBER_OF,
                entity_key=entity_key,
                community_id=community_id(plan.run_id, path),
            )
    return WriteSummary(
        run_id=plan.run_id,
        community_run_upserts=1,
        community_upserts=len(plan.communities),
        has_community_edges=len(plan.communities),
        member_of_edges=len(plan.member_of),
        parent_of_edges=len(plan.parent_of),
        applied=apply,
    )


def rollback_preview(query_fn: Query, run_id: str) -> dict[str, int]:
    """Read-only counts of what a rollback of this run_id would remove,
    including orphans (a Community with this run_id but no live
    CommunityRun, or vice versa)."""
    rows = query_fn(ROLLBACK_PREVIEW_QUERY, run_id=run_id)
    if not rows:
        return {"communities": 0, "member_of_edges": 0, "parent_of_edges": 0,
                "community_run_nodes": 0}
    return rows[0]


def rollback_run(write_fn: Query, run_id: str) -> None:
    """Remove exactly one Week4 community run's layer, orphans included.

    Two independent deletes, each matching by the run_id PROPERTY rather
    than by traversing HAS_COMMUNITY: a Community whose HAS_COMMUNITY edge
    never got written (interrupted apply) and a CommunityRun whose
    Community nodes are already gone are both still removed. Structurally
    cannot touch :Extracted nodes or domain relationships: DETACH DELETE
    only removes edges incident to the deleted Community / CommunityRun
    nodes, never the :Extracted node on the far end of a MEMBER_OF edge.
    """
    write_fn(ROLLBACK_DELETE_COMMUNITIES_QUERY, run_id=run_id)
    write_fn(ROLLBACK_DELETE_RUN_QUERY, run_id=run_id)


# --------------------------------------------------------------------------
# Preflight report, source-graph snapshot, post-write validation, and the
# gated --apply pipeline. All read-only except apply_with_gates' own write
# step, which it only reaches after the preflight gate passes.
# --------------------------------------------------------------------------


def take_source_graph_snapshot(query_fn: Query) -> dict[str, Any]:
    """Read-only. :Extracted count plus domain-relationship counts,
    label-filtered so the community layer never counts as "source graph"
    even before any Community node exists."""
    extracted_count = query_fn(SOURCE_GRAPH_NODE_COUNT_QUERY)[0]["extracted_count"]
    rel_rows = query_fn(SOURCE_GRAPH_RELATIONSHIP_COUNTS_QUERY)
    relationships = {row["rel_type"]: row["count"] for row in rel_rows}
    return {"extracted_count": extracted_count, "relationships": relationships}


@dataclass(frozen=True)
class PreflightReport:
    ok: bool
    entity_alignment: EntityAlignmentResult
    backup_check: BackupCheckResult | None
    source_graph_snapshot: dict[str, Any]


def run_preflight(
    plan: CommunityPlan, query_fn: Query, *, backup_path: Path | None
) -> PreflightReport:
    """Read-only, never writes. Live entity-key alignment, a source-graph
    snapshot, and (if ``backup_path`` is given) the backup compatibility
    check. Does not raise on failure -- it reports, so ``--preflight`` can
    print a full picture even when something is wrong; ``apply_with_gates``
    is what turns a failing report into a hard stop before any write."""
    live_rows = query_fn(LIVE_ENTITY_KEYS_QUERY)
    live_entity_keys = {row["entity_key"] for row in live_rows if row.get("entity_key")}
    alignment = check_entity_alignment(plan, live_entity_keys)
    snapshot = take_source_graph_snapshot(query_fn)
    backup_check = None
    if backup_path is not None:
        # The backup only ever contains edges with at least one :Extracted
        # endpoint (extraction_load.EXTRACTED_EDGE_QUERY / build_extracted_backup).
        # Comparing it against sum(snapshot["relationships"].values()) compares
        # it to EVERY non-community relationship in the whole graph -- which
        # also includes other layers (Document/Section/Chunk, etc.) that the
        # backup never covers, and would reject on their count alone. Reuse
        # the exact same scope the backup itself was built from.
        from .extraction_load import EXTRACTED_EDGE_COUNT_QUERY

        edge_rows = query_fn(EXTRACTED_EDGE_COUNT_QUERY)
        live_extracted_edge_count = edge_rows[0]["edges"] if edge_rows else 0
        backup_check = check_backup_compatibility(
            backup_path, live_entity_keys, live_extracted_edge_count
        )
    ok = alignment.ok and (backup_check is None or backup_check.ok)
    return PreflightReport(
        ok=ok, entity_alignment=alignment, backup_check=backup_check,
        source_graph_snapshot=snapshot,
    )


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    mismatches: list[str]


def validate_after_write(
    query_fn: Query, plan: CommunityPlan, pre_snapshot: dict[str, Any]
) -> ValidationResult:
    """Read-only. Compares the post-write state against (a) the pre-write
    source-graph snapshot, which must be byte-for-byte unchanged, and
    (b) the plan's own expected community/membership/parent-child counts.

    Never rolls back by itself on a mismatch -- the caller decides what to
    do with a failing result (see ``rollback_preview`` / ``rollback_run``).
    """
    mismatches: list[str] = []
    post_snapshot = take_source_graph_snapshot(query_fn)
    if post_snapshot["extracted_count"] != pre_snapshot["extracted_count"]:
        mismatches.append(
            ":Extracted count changed: "
            f"{pre_snapshot['extracted_count']} -> {post_snapshot['extracted_count']}"
        )
    if post_snapshot["relationships"] != pre_snapshot["relationships"]:
        mismatches.append(
            "domain relationship counts changed: "
            f"{pre_snapshot['relationships']} -> {post_snapshot['relationships']}"
        )
    by_level_plan: dict[int, int] = {}
    for record in plan.communities.values():
        by_level_plan[record.level] = by_level_plan.get(record.level, 0) + 1
    level_rows = query_fn(COMMUNITY_COUNT_BY_LEVEL_QUERY, run_id=plan.run_id)
    by_level_live = {row["level"]: row["n"] for row in level_rows}
    if by_level_live != by_level_plan:
        mismatches.append(
            f"community count by level: expected {by_level_plan}, got {by_level_live}"
        )
    member_of_rows = query_fn(MEMBER_OF_COUNT_QUERY, run_id=plan.run_id)
    member_of_live = member_of_rows[0]["member_of_count"] if member_of_rows else 0
    if member_of_live != len(plan.member_of):
        mismatches.append(
            f"MEMBER_OF count: expected {len(plan.member_of)}, got {member_of_live}"
        )
    parent_of_rows = query_fn(PARENT_OF_COUNT_QUERY, run_id=plan.run_id)
    parent_of_live = parent_of_rows[0]["parent_of_count"] if parent_of_rows else 0
    if parent_of_live != len(plan.parent_of):
        mismatches.append(
            f"PARENT_OF count: expected {len(plan.parent_of)}, got {parent_of_live}"
        )
    return ValidationResult(ok=not mismatches, mismatches=mismatches)


def apply_with_gates(
    plan: CommunityPlan, query_fn: Query, write_fn: Query, *, backup_path: Path | None
) -> tuple[WriteSummary, ValidationResult]:
    """The full --apply pipeline, in order: preflight, snapshot, constraint
    and index creation, write, validate_after_write.

    Raises ``PreflightRejected`` *before any write* when the gate fails --
    either because ``backup_path`` is missing, or because the preflight
    report (entity alignment and/or backup compatibility) is not ok. A
    failing post-write validation does NOT trigger an automatic rollback;
    it is returned to the caller alongside the write summary so it can
    print a rollback preview and stop (see ``main``).
    """
    if backup_path is None:
        raise PreflightRejected("--apply requires --backup PATH; none was given")
    report = run_preflight(plan, query_fn, backup_path=backup_path)
    if not report.ok:
        reasons = []
        if not report.entity_alignment.ok:
            reasons.append(
                f"missing entities: {sorted(report.entity_alignment.missing_members)}"
            )
        if report.backup_check is not None and not report.backup_check.ok:
            reasons.append(
                "backup mismatch: "
                f"missing_in_backup={sorted(report.backup_check.missing_in_backup)} "
                f"extra_in_backup={sorted(report.backup_check.extra_in_backup)} "
                f"edge_count_matches={report.backup_check.edge_count_matches}"
            )
        raise PreflightRejected("preflight failed: " + "; ".join(reasons))
    pre_snapshot = report.source_graph_snapshot
    for statement in (
        COMMUNITY_ID_UNIQUE_CONSTRAINT,
        COMMUNITY_RUN_ID_UNIQUE_CONSTRAINT,
        COMMUNITY_LEVEL_INDEX,
    ):
        write_fn(statement)
    summary = persist_plan(plan, write_fn=write_fn, apply=True)
    validation = validate_after_write(query_fn, plan, pre_snapshot)
    return summary, validation


# --------------------------------------------------------------------------
# CLI (dry-run by default; --apply is required to write)
# --------------------------------------------------------------------------


def _print_preflight(report: PreflightReport) -> None:
    print(f"entity_alignment ok={report.entity_alignment.ok}")
    if report.entity_alignment.missing_members:
        print(f"  missing_members={sorted(report.entity_alignment.missing_members)}")
    if report.entity_alignment.missing_isolated:
        print(f"  missing_isolated={sorted(report.entity_alignment.missing_isolated)}")
    if report.entity_alignment.missing_excluded:
        print(f"  missing_excluded={sorted(report.entity_alignment.missing_excluded)}")
    if report.entity_alignment.missing_alias:
        print(f"  missing_alias={sorted(report.entity_alignment.missing_alias)}")
    if report.entity_alignment.extra_live_only:
        print(f"  extra_live_only={sorted(report.entity_alignment.extra_live_only)}")
    if report.backup_check is not None:
        print(
            f"backup_check ok={report.backup_check.ok} "
            f"key_sets_match={report.backup_check.key_sets_match} "
            f"edge_count_matches={report.backup_check.edge_count_matches}"
        )
        if report.backup_check.missing_in_backup:
            print(f"  missing_in_backup={sorted(report.backup_check.missing_in_backup)}")
        if report.backup_check.extra_in_backup:
            print(f"  extra_in_backup={sorted(report.backup_check.extra_in_backup)}")
    snapshot = report.source_graph_snapshot
    print(f"source_graph_snapshot extracted_count={snapshot['extracted_count']}")
    for rel_type, count in sorted(snapshot["relationships"].items()):
        print(f"  {rel_type}={count}")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m naive_rag.community_load")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument(
        "--preflight", action="store_true",
        help="read-only: entity alignment, backup check (with --backup), "
             "and a source-graph snapshot. Opens a live connection, writes nothing.",
    )
    parser.add_argument(
        "--backup", type=Path, default=None,
        help="hard-copy :Extracted backup to check. Required for --apply.",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="write to Neo4j (opens a live connection). Requires --backup and "
             "a passing preflight, run automatically as the first step. "
             "Default: dry-run only.",
    )
    args = parser.parse_args(argv)

    mapping = load_mapping(args.mapping)
    plan = build_plan(mapping, expected=EXPECTED_COUNTS_WEEK4_PREPARED)

    if not args.preflight and not args.apply:
        summary = persist_plan(plan, write_fn=None, apply=False)
        print(f"DRY-RUN run_id={summary.run_id}")
        print(
            f"communities={summary.community_upserts} "
            f"member_of={summary.member_of_edges} "
            f"parent_of={summary.parent_of_edges} "
            f"has_community={summary.has_community_edges}"
        )
        return 0

    from .graph import query as _live_query  # lazy import; opened only here

    if args.preflight and not args.apply:
        report = run_preflight(plan, _live_query, backup_path=args.backup)
        _print_preflight(report)
        return 0 if report.ok else 2

    # --apply always runs the preflight gate itself, whether or not
    # --preflight was also passed; a failing gate raises before any write.
    summary, validation = apply_with_gates(
        plan, _live_query, _live_query, backup_path=args.backup
    )
    if not validation.ok:
        preview = rollback_preview(_live_query, plan.run_id)
        print("VALIDATION FAILED after write -- no automatic rollback.")
        for mismatch in validation.mismatches:
            print(f"  {mismatch}")
        print(f"rollback preview for run_id={plan.run_id}: {preview}")
        print(f"to roll back: rollback_run(query, {plan.run_id!r})")
        return 3
    print(f"APPLIED run_id={summary.run_id}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
