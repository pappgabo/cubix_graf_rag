"""Database-free checks for the Week4 community-layer loader.

No Neo4j connection is opened anywhere in this file. Writes go through a
small in-memory FakeGraph built only for these tests -- it understands
exactly the Cypher constants community_load.py defines; it is not a Cypher
interpreter. The Leiden partitioning algorithm is never invoked.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag import community_load as cl
from naive_rag.extraction_load import EXTRACTED_EDGE_COUNT_QUERY

REAL_MAPPING_PATH = Path(__file__).resolve().parents[1] / "docs" / "week4-vetulet-leképezés.json"


def _sample_mapping(seed: int = 42) -> dict:
    """A small, hand-verified mapping with the same shape as the real
    artifact: a root that splits ("0" -> "0/0", "0/1"), a root that never
    splits further ("1", a leaf at level 0), one isolated node ("9"), one
    excluded key, and one alias source mirroring its canonical target."""
    prepared = {
        "A1": "0/0", "A2": "0/0",
        "B1": "0/1", "B2": "0/1", "B3": "0/1",
        "Team:canon": "1", "C2": "1",
        "Z1": "9",
        "Team:alias-src": "1",
    }
    return {
        "parameterek": {
            "particio": "RBConfigurationVertexPartition",
            "resolution_parameter": 1.0,
            "weights": "egyedi source_chunk_ids unioja",
            "n_iterations": -1,
            "seed": seed,
            "leidenalg": "0.12.0",
            "igraph": "1.0.0",
        },
        "hash": {"nyers": "nyers-hash-x", "elokeszitett": "prepared-hash-x"},
        "ketszer_azonos": True,
        "alias": {"Team:alias-src": "Team:canon"},
        "kizart": ["Season:bad"],
        "nyers": dict(prepared),
        "elokeszitett": dict(prepared),
    }


class FakeGraph:
    """Minimal in-memory stand-in for Neo4j understanding this module's
    MERGE/rollback statements. Nodes are keyed by (label, business_key)."""

    def __init__(self, extracted_entity_keys=(), domain_edges=()):
        self.nodes: dict[tuple[str, str], dict] = {}
        self.edges: set[tuple[tuple[str, str], str, tuple[str, str]]] = set()
        for key in extracted_entity_keys:
            self.nodes[("Extracted", key)] = {"entity_key": key}
        for source, rel_type, target in domain_edges:
            self.edges.add((("Extracted", source), rel_type, ("Extracted", target)))

    def _communities_for_run(self, run_id: str) -> set[str]:
        return {
            key for (label, key) in self.nodes
            if label == "Community" and self.nodes[(label, key)].get("run_id") == run_id
        }

    def __call__(self, cypher: str, **params) -> list[dict]:
        if cypher.startswith("CREATE CONSTRAINT") or cypher.startswith("CREATE INDEX"):
            return []  # schema statements are no-ops in this fake
        if cypher == cl.MERGE_COMMUNITY_RUN:
            self.nodes.setdefault(("CommunityRun", params["run_id"]), {}).update(params)
            return [{"run_id": params["run_id"]}]
        if cypher == cl.MERGE_COMMUNITY:
            self.nodes.setdefault(("Community", params["community_id"]), {}).update(params)
            return [{"community_id": params["community_id"]}]
        if cypher == cl.MERGE_HAS_COMMUNITY:
            self.edges.add((
                ("CommunityRun", params["run_id"]), "HAS_COMMUNITY",
                ("Community", params["community_id"]),
            ))
            return []
        if cypher == cl.MERGE_PARENT_OF:
            self.edges.add((
                ("Community", params["parent_id"]), "PARENT_OF",
                ("Community", params["child_id"]),
            ))
            return []
        if cypher == cl.MERGE_MEMBER_OF:
            self.edges.add((
                ("Extracted", params["entity_key"]), "MEMBER_OF",
                ("Community", params["community_id"]),
            ))
            return []
        if cypher == cl.LIVE_ENTITY_KEYS_QUERY:
            return [{"entity_key": key} for (label, key) in self.nodes if label == "Extracted"]
        if cypher == cl.SOURCE_GRAPH_NODE_COUNT_QUERY:
            return [{"extracted_count": self.count(label="Extracted")}]
        if cypher == EXTRACTED_EDGE_COUNT_QUERY:
            # mirrors `MATCH (a)-[r]->(b) WHERE a:Extracted OR b:Extracted`
            # exactly -- the same scope the real backup was built from.
            n = sum(
                1 for (s_label, _s), _rel, (e_label, _e) in self.edges
                if s_label == "Extracted" or e_label == "Extracted"
            )
            return [{"edges": n}]
        if cypher == cl.SOURCE_GRAPH_RELATIONSHIP_COUNTS_QUERY:
            return [
                {"rel_type": rel_type, "count": count}
                for rel_type, count in sorted(self.source_graph_edge_counts().items())
            ]
        if cypher == cl.COMMUNITY_COUNT_BY_LEVEL_QUERY:
            run_id = params["run_id"]
            by_level: dict[int, int] = {}
            for key in self._communities_for_run(run_id):
                level = self.nodes[("Community", key)]["level"]
                by_level[level] = by_level.get(level, 0) + 1
            return [{"level": level, "n": n} for level, n in sorted(by_level.items())]
        if cypher == cl.MEMBER_OF_COUNT_QUERY:
            communities = self._communities_for_run(params["run_id"])
            n = sum(
                1 for (s_label, _s), rel, (e_label, e_key) in self.edges
                if rel == "MEMBER_OF" and s_label == "Extracted"
                and e_label == "Community" and e_key in communities
            )
            return [{"member_of_count": n}]
        if cypher == cl.PARENT_OF_COUNT_QUERY:
            communities = self._communities_for_run(params["run_id"])
            n = sum(
                1 for (s_label, s_key), rel, (e_label, e_key) in self.edges
                if rel == "PARENT_OF" and s_label == "Community" and e_label == "Community"
                and s_key in communities and e_key in communities
            )
            return [{"parent_of_count": n}]
        if cypher == cl.ROLLBACK_PREVIEW_QUERY:
            run_id = params["run_id"]
            communities = self._communities_for_run(run_id)
            member_of = sum(
                1 for (_s, rel, (e_label, e_key)) in self.edges
                if rel == "MEMBER_OF" and e_label == "Community" and e_key in communities
            )
            parent_of = sum(
                1 for ((s_label, s_key), rel, _e) in self.edges
                if rel == "PARENT_OF" and s_label == "Community" and s_key in communities
            )
            run_nodes = 1 if ("CommunityRun", run_id) in self.nodes else 0
            return [{"communities": len(communities), "member_of_edges": member_of,
                     "parent_of_edges": parent_of, "community_run_nodes": run_nodes}]
        if cypher == cl.ROLLBACK_DELETE_COMMUNITIES_QUERY:
            run_id = params["run_id"]
            communities = self._communities_for_run(run_id)
            self.nodes = {
                (label, key): value for (label, key), value in self.nodes.items()
                if not (label == "Community" and key in communities)
            }
            self.edges = {
                (s, rel, e) for (s, rel, e) in self.edges
                if not (s[0] == "Community" and s[1] in communities)
                and not (e[0] == "Community" and e[1] in communities)
            }
            return []
        if cypher == cl.ROLLBACK_DELETE_RUN_QUERY:
            run_id = params["run_id"]
            self.nodes.pop(("CommunityRun", run_id), None)
            self.edges = {
                (s, rel, e) for (s, rel, e) in self.edges
                if s != ("CommunityRun", run_id) and e != ("CommunityRun", run_id)
            }
            return []
        raise AssertionError(f"FakeGraph received an unexpected statement: {cypher[:60]}")

    def count(self, *, label: str | None = None, rel_type: str | None = None) -> int:
        if rel_type is not None:
            return sum(1 for (_s, rel, _e) in self.edges if rel == rel_type)
        return sum(1 for (node_label, _key) in self.nodes if node_label == label)

    def source_graph_edge_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for (s_label, _s), rel, (e_label, _e) in self.edges:
            if s_label in ("Community", "CommunityRun") or e_label in ("Community", "CommunityRun"):
                continue
            counts[rel] = counts.get(rel, 0) + 1
        return counts


class PlanBuildingTests(unittest.TestCase):
    def test_sample_mapping_shape(self):
        plan = cl.build_plan(_sample_mapping())
        self.assertEqual(plan.canonical_keys, {"A1", "A2", "B1", "B2", "B3", "Team:canon", "C2", "Z1"})
        self.assertEqual(plan.isolated_keys, {"Z1"})
        self.assertEqual(set(plan.member_of), {"A1", "A2", "B1", "B2", "B3", "Team:canon", "C2"})
        self.assertEqual(plan.excluded_keys, {"Season:bad"})
        self.assertEqual(plan.alias_keys, {"Team:alias-src"})

    def test_communities_and_parent_child(self):
        plan = cl.build_plan(_sample_mapping())
        self.assertEqual(set(plan.communities), {"0", "0/0", "0/1", "1"})
        self.assertEqual(plan.communities["0"].level, 0)
        self.assertEqual(plan.communities["0"].size, 5)
        self.assertFalse(plan.communities["0"].is_leaf)
        self.assertEqual(plan.communities["0/0"].size, 2)
        self.assertTrue(plan.communities["0/0"].is_leaf)
        self.assertEqual(plan.communities["1"].level, 0)
        self.assertEqual(plan.communities["1"].size, 2)
        self.assertTrue(plan.communities["1"].is_leaf)
        self.assertCountEqual(plan.parent_of, [("0", "0/0"), ("0", "0/1")])

    def test_real_week4_artifact_matches_the_audited_counts(self):
        mapping = cl.load_mapping(REAL_MAPPING_PATH)
        plan = cl.build_plan(mapping, expected=cl.EXPECTED_COUNTS_WEEK4_PREPARED)
        self.assertEqual(len(plan.communities), 520)
        self.assertEqual(len(plan.member_of), 1909)
        self.assertEqual(len(plan.parent_of), 483)
        by_level = {}
        for record in plan.communities.values():
            by_level[record.level] = by_level.get(record.level, 0) + 1
        self.assertEqual(by_level, {0: 37, 1: 176, 2: 253, 3: 54})

    def test_assignment_hash_is_not_in_the_existing_hash_block(self):
        """The mapping's own hash.* fields hash the pre-partition INPUT, not
        the output node->path assignment -- this loader computes
        assignment_hash fresh. This test pins that fact to the real file."""
        mapping = cl.load_mapping(REAL_MAPPING_PATH)
        self.assertEqual(set(mapping["hash"]), {"nyers", "elokeszitett"})
        canonical = cl.canonical_entries(mapping)
        computed = cl.compute_assignment_hash(canonical)
        self.assertNotIn(computed, mapping["hash"].values())


class RunFingerprintTests(unittest.TestCase):
    def test_run_id_is_deterministic(self):
        plan_a = cl.build_plan(_sample_mapping())
        plan_b = cl.build_plan(_sample_mapping())
        self.assertEqual(plan_a.run_id, plan_b.run_id)

    def test_different_seed_changes_run_id(self):
        plan_a = cl.build_plan(_sample_mapping(seed=42))
        plan_b = cl.build_plan(_sample_mapping(seed=43))
        self.assertNotEqual(plan_a.run_id, plan_b.run_id)

    def test_community_id_embeds_run_id_not_projection(self):
        plan = cl.build_plan(_sample_mapping())
        cid = cl.community_id(plan.run_id, "0")
        self.assertEqual(cid, f"{plan.run_id}:0")
        self.assertNotEqual(cid, f"{plan.projection}:0")


class RequiredOfflineTests(unittest.TestCase):
    """The six scenarios the implementation prompt calls mandatory."""

    def test_1_same_run_applied_twice_is_a_no_op(self):
        plan = cl.build_plan(_sample_mapping())
        graph = FakeGraph(extracted_entity_keys=plan.canonical_keys | plan.alias_keys)
        cl.persist_plan(plan, write_fn=graph, apply=True)
        communities_after_first = graph.count(label="Community")
        member_of_after_first = graph.count(rel_type="MEMBER_OF")
        parent_of_after_first = graph.count(rel_type="PARENT_OF")
        cl.persist_plan(plan, write_fn=graph, apply=True)
        self.assertEqual(graph.count(label="Community"), communities_after_first)
        self.assertEqual(graph.count(rel_type="MEMBER_OF"), member_of_after_first)
        self.assertEqual(graph.count(rel_type="PARENT_OF"), parent_of_after_first)
        self.assertEqual(graph.count(label="CommunityRun"), 1)

    def test_2_two_runs_with_identical_paths_do_not_collide(self):
        plan_a = cl.build_plan(_sample_mapping(seed=42))
        plan_b = cl.build_plan(_sample_mapping(seed=43))
        self.assertNotEqual(plan_a.run_id, plan_b.run_id)
        graph = FakeGraph(extracted_entity_keys=plan_a.canonical_keys | plan_a.alias_keys)
        cl.persist_plan(plan_a, write_fn=graph, apply=True)
        cl.persist_plan(plan_b, write_fn=graph, apply=True)
        self.assertEqual(
            graph.count(label="Community"),
            len(plan_a.communities) + len(plan_b.communities),
        )
        self.assertIn(("Community", cl.community_id(plan_a.run_id, "0")), graph.nodes)
        self.assertIn(("Community", cl.community_id(plan_b.run_id, "0")), graph.nodes)
        self.assertNotEqual(
            cl.community_id(plan_a.run_id, "0"), cl.community_id(plan_b.run_id, "0")
        )

    def test_3_rollback_of_one_run_leaves_the_other_run_and_source_graph_intact(self):
        plan_a = cl.build_plan(_sample_mapping(seed=42))
        plan_b = cl.build_plan(_sample_mapping(seed=43))
        extracted = plan_a.canonical_keys | plan_a.alias_keys
        domain_edge = ("A1", "DROVE_FOR", "B1")
        graph = FakeGraph(extracted_entity_keys=extracted, domain_edges=[domain_edge])
        cl.persist_plan(plan_a, write_fn=graph, apply=True)
        cl.persist_plan(plan_b, write_fn=graph, apply=True)

        preview = cl.rollback_preview(graph, plan_a.run_id)
        self.assertEqual(preview["communities"], len(plan_a.communities))
        self.assertEqual(preview["member_of_edges"], len(plan_a.member_of))

        cl.rollback_run(graph, plan_a.run_id)

        self.assertNotIn(("CommunityRun", plan_a.run_id), graph.nodes)
        self.assertEqual(graph.count(label="Community"), len(plan_b.communities))
        self.assertIn(("Community", cl.community_id(plan_b.run_id, "0")), graph.nodes)
        self.assertEqual(
            [edge for edge in graph.edges if edge[1] == "MEMBER_OF"
             and edge[2][1].startswith(plan_a.run_id)],
            [],
        )
        # source graph untouched
        self.assertEqual(sum(1 for (label, _key) in graph.nodes if label == "Extracted"), len(extracted))
        self.assertEqual(graph.source_graph_edge_counts(), {"DROVE_FOR": 1})

    def test_4_early_stopping_branch_is_leaf_and_reports_at_every_deeper_level(self):
        plan = cl.build_plan(_sample_mapping())
        community_one = plan.communities["1"]
        self.assertEqual(community_one.level, 0)
        self.assertTrue(community_one.is_leaf)
        for level in (0, 1, 2, 3):
            self.assertIn("1", cl.reporting_level_paths(plan, level))
        # "0" split further, so it must NOT stand in for level 1+ itself
        self.assertNotIn("0", cl.reporting_level_paths(plan, 1))
        self.assertIn("0/0", cl.reporting_level_paths(plan, 1))
        self.assertIn("0/0", cl.reporting_level_paths(plan, 3))

    def test_5_missing_source_entity_rejects_the_write(self):
        plan = cl.build_plan(_sample_mapping())
        live_keys = (plan.canonical_keys | plan.alias_keys) - {"B3"}
        with self.assertRaises(cl.PreflightRejected) as ctx:
            cl.require_entity_alignment(plan, live_keys)
        self.assertIn("B3", str(ctx.exception))

    def test_6_alias_source_keys_never_get_member_of(self):
        plan = cl.build_plan(_sample_mapping())
        self.assertNotIn("Team:alias-src", plan.member_of)
        graph = FakeGraph(extracted_entity_keys=plan.canonical_keys | plan.alias_keys)
        cl.persist_plan(plan, write_fn=graph, apply=True)
        alias_edges = [
            edge for edge in graph.edges
            if edge[0] == ("Extracted", "Team:alias-src") and edge[1] == "MEMBER_OF"
        ]
        self.assertEqual(alias_edges, [])


class QueryFixTests(unittest.TestCase):
    """The specific bugs/gaps called out in the second pass over the plan."""

    def test_subtree_members_does_not_duplicate_the_root(self):
        plan = cl.build_plan(_sample_mapping())
        members = cl.subtree_members(plan, "0")
        self.assertEqual(members, {"A1", "A2", "B1", "B2", "B3"})
        self.assertEqual(len(members), 5)

    def test_source_graph_counts_are_excluded_by_label_not_by_type_name(self):
        plan = cl.build_plan(_sample_mapping())
        domain_edge = ("A1", "DROVE_FOR", "B1")
        graph = FakeGraph(
            extracted_entity_keys=plan.canonical_keys | plan.alias_keys,
            domain_edges=[domain_edge],
        )
        cl.persist_plan(plan, write_fn=graph, apply=True)
        counts = graph.source_graph_edge_counts()
        self.assertEqual(counts, {"DROVE_FOR": 1})


class EntityAlignmentTests(unittest.TestCase):
    def test_extra_live_only_keys_are_reported_but_do_not_block(self):
        plan = cl.build_plan(_sample_mapping())
        live_keys = (plan.canonical_keys | plan.alias_keys) | {"Driver:unknown"}
        result = cl.check_entity_alignment(plan, live_keys)
        self.assertTrue(result.ok)
        self.assertEqual(result.extra_live_only, {"Driver:unknown"})

    def test_missing_isolated_or_excluded_is_reported_but_does_not_block(self):
        plan = cl.build_plan(_sample_mapping())
        live_keys = (plan.canonical_keys | plan.alias_keys) - {"Z1"}
        result = cl.check_entity_alignment(plan, live_keys)
        self.assertTrue(result.ok)
        self.assertEqual(result.missing_isolated, {"Z1"})


def _write_minimal_backup(path: Path, entity_keys: list[str]) -> None:
    payload = {
        "format": "extracted-layer-backup-1",
        "mixed": [],
        "nodes": [
            {"labels": ["Driver", "Extracted"], "properties": {"entity_key": key}}
            for key in entity_keys
        ],
        "edges": [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_minimal_backup_with_edge(path: Path, entity_keys: list[str], *, edge: tuple[str, str, str]) -> None:
    source_key, rel_type, target_key = edge
    payload = {
        "format": "extracted-layer-backup-1",
        "mixed": [],
        "nodes": [
            {"labels": ["Driver", "Extracted"], "properties": {"entity_key": key}}
            for key in entity_keys
        ],
        "edges": [
            {
                "type": rel_type,
                "properties": {},
                "source": {"kind": "extracted", "label": "Driver", "entity_key": source_key},
                "target": {"kind": "extracted", "label": "Driver", "entity_key": target_key},
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class BackupEdgeCountScopeTests(unittest.TestCase):
    """The javítás: the backup edge-count comparison must use the same scope
    the backup itself was built from (edges with an :Extracted endpoint),
    not the whole-graph non-community relationship count. Otherwise edges
    belonging to other layers (Document/Section/Chunk, ...) -- which the
    backup never covers at all -- inflate the live count and cause a false
    rejection."""

    def test_other_layer_edges_do_not_cause_a_false_backup_rejection(self):
        plan = cl.build_plan(_sample_mapping())
        live_keys = plan.canonical_keys | plan.alias_keys
        graph = FakeGraph(
            extracted_entity_keys=live_keys,
            domain_edges=[("A1", "DROVE_FOR", "B1")],
        )
        # a whole other layer the backup never covers at all
        graph.edges.add((("Document", "doc1"), "HAS_SECTION", ("Section", "sec1")))
        graph.edges.add((("Section", "sec1"), "CONTAINS", ("Chunk", "chunk1")))
        graph.edges.add((("Chunk", "chunk1"), "NEXT_CHUNK", ("Chunk", "chunk2")))

        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "backup.json"
            _write_minimal_backup_with_edge(
                backup, sorted(live_keys), edge=("A1", "DROVE_FOR", "B1")
            )
            report = cl.run_preflight(plan, graph, backup_path=backup)

        self.assertTrue(report.backup_check.edge_count_matches)
        self.assertTrue(report.ok)

    def test_a_real_extracted_edge_count_mismatch_still_rejects(self):
        plan = cl.build_plan(_sample_mapping())
        live_keys = plan.canonical_keys | plan.alias_keys
        # two domain edges live; the backup only knows about one of them
        graph = FakeGraph(
            extracted_entity_keys=live_keys,
            domain_edges=[("A1", "DROVE_FOR", "B1"), ("A2", "DROVE_FOR", "B2")],
        )

        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "backup.json"
            _write_minimal_backup_with_edge(
                backup, sorted(live_keys), edge=("A1", "DROVE_FOR", "B1")
            )
            report = cl.run_preflight(plan, graph, backup_path=backup)

        self.assertFalse(report.backup_check.edge_count_matches)
        self.assertFalse(report.ok)


class BackupCompatibilityTests(unittest.TestCase):
    def test_matching_key_set_and_edge_count_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backup.json"
            _write_minimal_backup(path, ["Driver:a", "Driver:b"])
            result = cl.check_backup_compatibility(
                path, live_entity_keys=["Driver:a", "Driver:b"], live_edge_count=0
            )
            self.assertTrue(result.ok)

    def test_key_set_mismatch_is_not_ok_even_with_matching_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backup.json"
            _write_minimal_backup(path, ["Driver:a", "Driver:b"])
            result = cl.check_backup_compatibility(
                path, live_entity_keys=["Driver:a", "Driver:c"], live_edge_count=0
            )
            self.assertFalse(result.ok)
            self.assertFalse(result.key_sets_match)
            self.assertEqual(result.missing_in_backup, {"Driver:c"})
            self.assertEqual(result.extra_in_backup, {"Driver:b"})


class DryRunDefaultTests(unittest.TestCase):
    def test_persist_plan_without_apply_calls_nothing(self):
        plan = cl.build_plan(_sample_mapping())
        calls = []

        def _spy(cypher, **params):
            calls.append(cypher)
            return []

        summary = cl.persist_plan(plan, write_fn=_spy, apply=False)
        self.assertEqual(calls, [])
        self.assertFalse(summary.applied)
        self.assertEqual(summary.community_upserts, len(plan.communities))

    def test_apply_without_write_fn_is_rejected(self):
        plan = cl.build_plan(_sample_mapping())
        with self.assertRaises(ValueError):
            cl.persist_plan(plan, write_fn=None, apply=True)

    def test_main_dry_run_does_not_import_the_graph_module(self):
        """Confirm the CLI's default path never touches naive_rag.graph
        (which is where a live Neo4j connection would be opened). Checked
        in isolation against community_load's own source, not against
        process-wide sys.modules, since other test modules in the same
        suite legitimately import naive_rag.graph elsewhere."""
        import inspect

        source = inspect.getsource(cl.main)
        before_apply, _, after_apply = source.partition(
            "if not args.preflight and not args.apply:"
        )
        # the early-return dry-run branch must not mention the graph import
        dry_run_branch, _, _ = after_apply.partition("from .graph import query")
        self.assertIn("return 0", dry_run_branch)
        self.assertNotIn("from .graph import", before_apply)

        exit_code = cl.main(["--mapping", str(REAL_MAPPING_PATH)])
        self.assertEqual(exit_code, 0)


class ApplyGatingTests(unittest.TestCase):
    """The javítás-round requirements: --apply is gated by preflight and by
    --backup, rollback handles orphans, and a failed post-write validation
    never triggers an automatic rollback."""

    def test_apply_rejected_when_preflight_fails(self):
        plan = cl.build_plan(_sample_mapping())
        live_keys = (plan.canonical_keys | plan.alias_keys) - {"B3"}
        graph = FakeGraph(extracted_entity_keys=live_keys)
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "backup.json"
            _write_minimal_backup(backup, sorted(live_keys))
            with self.assertRaises(cl.PreflightRejected) as ctx:
                cl.apply_with_gates(plan, graph, graph, backup_path=backup)
            self.assertIn("B3", str(ctx.exception))
        self.assertEqual(graph.count(label="Community"), 0)
        self.assertEqual(graph.count(label="CommunityRun"), 0)

    def test_apply_rejected_without_backup(self):
        plan = cl.build_plan(_sample_mapping())
        graph = FakeGraph(extracted_entity_keys=plan.canonical_keys | plan.alias_keys)
        with self.assertRaises(cl.PreflightRejected) as ctx:
            cl.apply_with_gates(plan, graph, graph, backup_path=None)
        self.assertIn("backup", str(ctx.exception).lower())
        self.assertEqual(graph.count(label="Community"), 0)

    def test_apply_with_gates_end_to_end_success(self):
        plan = cl.build_plan(_sample_mapping())
        live_keys = plan.canonical_keys | plan.alias_keys
        graph = FakeGraph(extracted_entity_keys=live_keys)
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "backup.json"
            _write_minimal_backup(backup, sorted(live_keys))
            summary, validation = cl.apply_with_gates(plan, graph, graph, backup_path=backup)
        self.assertTrue(validation.ok)
        self.assertEqual(validation.mismatches, [])
        self.assertEqual(summary.community_upserts, len(plan.communities))
        self.assertEqual(graph.count(label="Community"), len(plan.communities))
        self.assertEqual(graph.count(label="CommunityRun"), 1)

    def test_orphan_communities_without_a_linked_run_are_still_rolled_back(self):
        plan = cl.build_plan(_sample_mapping())
        graph = FakeGraph(extracted_entity_keys=plan.canonical_keys | plan.alias_keys)
        cl.persist_plan(plan, write_fn=graph, apply=True)
        # simulate an interrupted write: the CommunityRun node and its
        # HAS_COMMUNITY edges never made it, but the Community nodes (which
        # carry run_id as a denormalized property) are already there.
        graph.nodes.pop(("CommunityRun", plan.run_id), None)
        graph.edges = {edge for edge in graph.edges if edge[1] != "HAS_COMMUNITY"}

        preview = cl.rollback_preview(graph, plan.run_id)
        self.assertEqual(preview["communities"], len(plan.communities))
        self.assertEqual(preview["community_run_nodes"], 0)

        cl.rollback_run(graph, plan.run_id)
        self.assertEqual(graph.count(label="Community"), 0)
        self.assertNotIn(("CommunityRun", plan.run_id), graph.nodes)

    def test_orphan_community_run_without_communities_is_still_rolled_back(self):
        plan = cl.build_plan(_sample_mapping())
        graph = FakeGraph(extracted_entity_keys=plan.canonical_keys | plan.alias_keys)
        cl.persist_plan(plan, write_fn=graph, apply=True)
        # the reverse orphan: Community nodes already gone, CommunityRun left behind.
        graph.nodes = {k: v for k, v in graph.nodes.items() if k[0] != "Community"}
        graph.edges = {
            edge for edge in graph.edges
            if edge[0][0] != "Community" and edge[2][0] != "Community"
        }

        preview = cl.rollback_preview(graph, plan.run_id)
        self.assertEqual(preview["communities"], 0)
        self.assertEqual(preview["community_run_nodes"], 1)

        cl.rollback_run(graph, plan.run_id)
        self.assertNotIn(("CommunityRun", plan.run_id), graph.nodes)

    def test_validate_after_write_fails_on_wrong_member_of_count_and_does_not_rollback(self):
        plan = cl.build_plan(_sample_mapping())
        graph = FakeGraph(extracted_entity_keys=plan.canonical_keys | plan.alias_keys)
        pre_snapshot = cl.take_source_graph_snapshot(graph)
        cl.persist_plan(plan, write_fn=graph, apply=True)
        # simulate an incomplete write: one MEMBER_OF edge never landed
        dropped = next(edge for edge in graph.edges if edge[1] == "MEMBER_OF")
        graph.edges.discard(dropped)

        result = cl.validate_after_write(graph, plan, pre_snapshot)
        self.assertFalse(result.ok)
        self.assertTrue(any("MEMBER_OF" in mismatch for mismatch in result.mismatches))
        # read-only: nothing was removed as a side effect of validating
        self.assertEqual(graph.count(label="Community"), len(plan.communities))
        self.assertEqual(graph.count(label="CommunityRun"), 1)

    def test_validate_after_write_detects_a_changed_source_graph(self):
        plan = cl.build_plan(_sample_mapping())
        domain_edge = ("A1", "DROVE_FOR", "B1")
        graph = FakeGraph(
            extracted_entity_keys=plan.canonical_keys | plan.alias_keys,
            domain_edges=[domain_edge],
        )
        pre_snapshot = cl.take_source_graph_snapshot(graph)
        cl.persist_plan(plan, write_fn=graph, apply=True)
        # a source-graph edge disappearing would be a real integrity problem
        graph.edges.discard((("Extracted", "A1"), "DROVE_FOR", ("Extracted", "B1")))

        result = cl.validate_after_write(graph, plan, pre_snapshot)
        self.assertFalse(result.ok)
        self.assertTrue(any("domain relationship" in mismatch for mismatch in result.mismatches))


REAL_BACKUP_PATH = (
    Path(__file__).resolve().parents[1]
    / "graph" / "corpus" / "extracted-layer-backup-after-chunk-sweep-1200-23.json"
)


class RealBackupOfflineCheckTests(unittest.TestCase):
    """Item 5 of the javítás prompt: run check_backup_compatibility offline
    (no DB) against the real backup file, using the mapping's 2761 "nyers"
    keys as the stand-in "live" set, and report what it finds."""

    @unittest.skipUnless(REAL_BACKUP_PATH.exists(), "real backup file not present")
    def test_real_backup_against_mapping_nyers_universe(self):
        from naive_rag.extraction_load import read_extracted_backup

        mapping = cl.load_mapping(REAL_MAPPING_PATH)
        live_stand_in = set(mapping["nyers"].keys())
        self.assertEqual(len(live_stand_in), 2761)

        payload = read_extracted_backup(REAL_BACKUP_PATH)
        backup_edge_count = len(payload["edges"])

        result = cl.check_backup_compatibility(
            REAL_BACKUP_PATH, live_entity_keys=live_stand_in, live_edge_count=backup_edge_count,
        )
        print(
            "\n[offline backup check against docs/week4-vetulet-leképezés.json "
            "'nyers' keys as the live stand-in]\n"
            f"  key_sets_match={result.key_sets_match}\n"
            f"  missing_in_backup={len(result.missing_in_backup)} "
            f"(in mapping, not in backup)\n"
            f"  extra_in_backup={len(result.extra_in_backup)} "
            f"(in backup, not in mapping)\n"
            "  edge_count_matches is not meaningful here: no live DB count "
            "exists offline, so it is compared against the backup's own "
            "edge count and will trivially be True."
        )
        # this is a reconnaissance run over real data, not a code invariant:
        # it must complete and return a well-formed result, not assert a
        # specific pass/fail outcome.
        self.assertIsInstance(result.key_sets_match, bool)


if __name__ == "__main__":
    unittest.main()
