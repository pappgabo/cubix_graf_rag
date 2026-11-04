"""Database-free checks for the extracted-layer loader.

The Neo4j driver is not opened. Approved records in this file are built in
memory from example names. They are not written to the pending Hamilton
review file.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import unittest
from pathlib import Path

from naive_rag.extract_pilot import input_hash
from naive_rag.extraction_identity import (
    EmptyNameError,
    drove_for_rel_key,
    make_entity_key,
    make_rel_key,
    merge_source_ids,
    normalize_name,
)
from naive_rag.extraction_load import (
    MATCH_CHUNK,
    MERGE_DROVE_FOR,
    Q6_LAYER_NOTE,
    RAW_INPUT_HASH_SCOPE,
    SET_DESCRIPTION,
    SET_SOURCES,
    VERSION_QUERY,
    ApprovalRejected,
    MissingChunk,
    ResultRejected,
    SourceRejected,
    apply_extracted_constraints,
    extracted_constraint_statements,
    load_approved_plan,
    load_approved_records,
    plan_approved_load,
    plan_validated_raw,
    relationship_uniqueness_supported,
    run_unit_of_work,
    write_plan,
)
from naive_rag.extraction_models import (
    EntityType,
    ExtractionResult,
    validate_extraction,
)

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "graph" / "pilot" / "review" / "driver-lewis-hamilton_0.json"
RAW = ROOT / "graph" / "pilot" / "extraction-v3" / "driver-lewis-hamilton_0.json"
# Byte hash of the raw v3 file. This is not input_hash.
RAW_FILE_SHA256 = (
    "bbbf214402a8c22e87d3fc41d6e25ee3efc7b7c5036c3f831b39e2e1dd73f8be"
)
DRIVER = "Driver:example driver"
TEAM = "Team:example team"
CHUNK_A = "example-a#1"
CHUNK_B = "example-b#2"


def _example_result(from_year=None, to_year=None, role=None, extra=None):
    relationships = [{
        "source_id": "e1",
        "target_id": "e2",
        "relationship_type": "DROVE_FOR",
        "description": "Example Driver races for Example Team.",
        "from_year": from_year,
        "to_year": to_year,
        "role": role,
    }]
    if extra is not None:
        relationships.append(extra)
    return {
        "entities": [
            {
                "local_id": "e1",
                "name": "Example Driver",
                "entity_type": "Driver",
                "description": "An example driver used only in this test.",
            },
            {
                "local_id": "e2",
                "name": "Example Team",
                "entity_type": "Team",
                "description": "An example team used only in this test.",
            },
        ],
        "relationships": relationships,
    }


def _approved(result=None, chunk_id=CHUNK_A, raw_hash="hash-a", **overrides):
    record = {
        "approval_status": "approved",
        "raw_result_path": "graph/pilot/fixtures/example-only.json",
        "raw_input_hash": raw_hash,
        "chunk_id": chunk_id,
        "review_notes": [],
        "corrections": [],
        "result": _example_result() if result is None else result,
    }
    record.update(overrides)
    return record


def _documented_correction():
    return {
        "entity_local_id": "e2",
        "entity_name": "Example Team",
        "field": "description",
        "previous": "An example team used only in this test.",
        "new": "Example Driver competes for Example Team.",
        "reason": "The description was narrowed to the racing claim in the source.",
    }


def _teammate_result():
    return {
        "entities": [
            {
                "local_id": "e1",
                "name": "Example Driver",
                "entity_type": "Driver",
                "description": "An example driver used only in this test.",
            },
            {
                "local_id": "e2",
                "name": "Example Teammate",
                "entity_type": "Driver",
                "description": "Another example driver used only here.",
            },
        ],
        "relationships": [{
            "source_id": "e1",
            "target_id": "e2",
            "relationship_type": "TEAMMATE_OF",
            "description": "The text says they were teammates.",
            "from_year": None,
            "to_year": None,
            "role": None,
        }],
    }


def _raw(chunk_id=CHUNK_A, raw_hash="hash-a", status="ok", **overrides):
    record = {
        "chunk_id": chunk_id,
        "input_hash": raw_hash,
        "status": status,
        "result": {"entities": [], "relationships": []},
    }
    record.update(overrides)
    return record


class FakeTx:
    """Records statements. This is not a Neo4j session."""

    def __init__(self, chunk_id=CHUNK_A, rel_sources=None, fail_on=None):
        self.chunk_id = chunk_id
        self.rel_sources = list(rel_sources or [[CHUNK_A]])
        self.fail_on = fail_on
        self.calls = []
        self.committed = False
        self.rolled_back = False

    def run(self, cypher, parameters):
        stored = {
            key: list(value) if isinstance(value, list) else value
            for key, value in parameters.items()
        }
        self.calls.append((cypher, stored))
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise RuntimeError("write failed")
        if cypher == MATCH_CHUNK:
            if self.chunk_id is None:
                return []
            return [{"chunk_id": self.chunk_id}]
        if "RETURN r.source_chunk_ids AS source_chunk_ids" in cypher:
            current = self.rel_sources.pop(0) if self.rel_sources else None
            return [{"source_chunk_ids": current}]
        return []

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class NormalizeTests(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(normalize_name("Lewis Hamilton"), "lewis hamilton")
        self.assertEqual(normalize_name("lewis hamilton"), "lewis hamilton")
        self.assertEqual(
            normalize_name("  Lewis   Hamilton  "), "lewis hamilton")
        self.assertEqual(normalize_name("Lewis\u00a0Hamilton"), "lewis hamilton")
        self.assertEqual(normalize_name("Lewis\u3000Hamilton"), "lewis hamilton")
        self.assertEqual(normalize_name("Ferrari"), "ferrari")
        self.assertEqual(normalize_name("Räikkönen"), "räikkönen")
        self.assertEqual(normalize_name("Mercedes-AMG"), "mercedes-amg")
        self.assertEqual(normalize_name("O'Ward"), "o'ward")
        self.assertEqual(normalize_name("\ufb01"), "fi")
        self.assertEqual(normalize_name("\u212a"), "k")
        # casefold expands U+01F0; the second NFKC folds it back.
        self.assertEqual(normalize_name("\u01f0"), "\u01f0")
        self.assertNotEqual(normalize_name("\u01f0"), "j\u030c")

    def test_empty_name_is_rejected(self):
        for name in ("", "   ", "\n\t"):
            with self.assertRaises(EmptyNameError):
                normalize_name(name)


class EntityKeyTests(unittest.TestCase):
    def test_hamilton_and_ferrari_keys(self):
        self.assertEqual(
            make_entity_key(EntityType.Driver, "Lewis Hamilton"),
            "Driver:lewis hamilton",
        )
        self.assertEqual(
            make_entity_key(EntityType.Driver, "  Lewis   Hamilton  "),
            "Driver:lewis hamilton",
        )
        self.assertEqual(
            make_entity_key(EntityType.Team, "Ferrari"),
            "Team:ferrari",
        )

    def test_same_name_with_two_types_has_two_keys(self):
        driver = make_entity_key(EntityType.Driver, "Example Name")
        team = make_entity_key(EntityType.Team, "Example Name")
        self.assertEqual(driver, "Driver:example name")
        self.assertEqual(team, "Team:example name")
        self.assertNotEqual(driver, team)

    def test_empty_name_has_no_key(self):
        with self.assertRaises(EmptyNameError):
            make_entity_key(EntityType.Driver, "   ")


class RelationshipIdentityTests(unittest.TestCase):
    def test_case_1_same_from_year_is_one_relationship_and_two_sources(self):
        first = drove_for_rel_key(DRIVER, TEAM, 2021, None, None)
        second = drove_for_rel_key(DRIVER, TEAM, 2021, None, None)
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            '["Driver:example driver","DROVE_FOR","Team:example team",2021,null,null]',
        )
        self.assertEqual(
            merge_source_ids([CHUNK_A], CHUNK_B),
            [CHUNK_A, CHUNK_B],
        )

    def test_case_2_two_missing_from_years_are_one_relationship(self):
        first = drove_for_rel_key(DRIVER, TEAM, None, None, None)
        second = drove_for_rel_key(DRIVER, TEAM, None, None, None)
        self.assertEqual(first, second)
        self.assertEqual(
            merge_source_ids([CHUNK_A], CHUNK_B),
            [CHUNK_A, CHUNK_B],
        )

    def test_case_3_missing_year_and_2021_are_two_relationships(self):
        missing = drove_for_rel_key(DRIVER, TEAM, None, None, None)
        dated = drove_for_rel_key(DRIVER, TEAM, 2021, None, None)
        self.assertNotEqual(missing, dated)

    def test_case_4_2020_and_2021_are_two_relationships(self):
        earlier = drove_for_rel_key(DRIVER, TEAM, 2020, None, None)
        later = drove_for_rel_key(DRIVER, TEAM, 2021, None, None)
        self.assertNotEqual(earlier, later)

    def test_case_5_to_year_or_role_splits_the_relationship(self):
        until_2022 = drove_for_rel_key(DRIVER, TEAM, 2021, 2022, None)
        until_2023 = drove_for_rel_key(DRIVER, TEAM, 2021, 2023, None)
        race = drove_for_rel_key(DRIVER, TEAM, 2021, None, "race driver")
        reserve = drove_for_rel_key(DRIVER, TEAM, 2021, None, "reserve")
        self.assertNotEqual(until_2022, until_2023)
        self.assertNotEqual(race, reserve)

    def test_case_6_an_existing_source_is_kept_in_place(self):
        self.assertEqual(
            merge_source_ids([CHUNK_A, CHUNK_B], CHUNK_A),
            [CHUNK_A, CHUNK_B],
        )
        self.assertEqual(merge_source_ids([CHUNK_A], CHUNK_A), [CHUNK_A])

    def test_json_null_is_not_the_string_null(self):
        missing = drove_for_rel_key(DRIVER, TEAM, None, None, None)
        text = drove_for_rel_key(DRIVER, TEAM, None, None, "null")
        self.assertEqual(
            missing,
            '["Driver:example driver","DROVE_FOR","Team:example team",null,null,null]',
        )
        self.assertIn('"null"', text)
        self.assertNotEqual(missing, text)

    def test_bool_year_is_rejected(self):
        with self.assertRaises(TypeError):
            drove_for_rel_key(DRIVER, TEAM, True, None, None)


class GateTests(unittest.TestCase):
    def test_raw_record_is_rejected_before_a_transaction(self):
        raw = json.loads(RAW.read_text(encoding="utf-8"))
        opened = []
        with self.assertRaises(ApprovalRejected):
            load_approved_records(raw, raw, self._opener(opened))
        self.assertEqual(opened, [])
        self.assertEqual(raw["status"], "ok")
        self.assertNotIn("approval_status", raw)

    def test_pending_review_is_rejected_before_a_transaction(self):
        opened = []
        review = _approved()
        review["approval_status"] = "pending_review"
        with self.assertRaises(ApprovalRejected):
            load_approved_records(review, _raw(), self._opener(opened))
        self.assertEqual(opened, [])

    def test_pending_review_with_corrections_is_rejected_before_a_transaction(self):
        opened = []
        review = _approved()
        review["approval_status"] = "pending_review"
        review["corrections"] = [_documented_correction()]
        with self.assertRaises(ApprovalRejected):
            load_approved_records(review, _raw(), self._opener(opened))
        self.assertEqual(opened, [])

    def test_approved_correction_uses_the_corrected_result_for_the_plan(self):
        corrected = _example_result()
        corrected["entities"][1]["description"] = (
            "Example Driver competes for Example Team."
        )
        corrected["relationships"][0]["description"] = (
            "Example Driver competes for Example Team."
        )
        review = _approved(corrected)
        review["corrections"] = [_documented_correction()]
        raw = _raw()
        raw["result"] = _example_result()
        plan = plan_approved_load(review, raw)
        self.assertNotEqual(review["result"], raw["result"])
        self.assertEqual(
            plan.relationships[0].description,
            "Example Driver competes for Example Team.",
        )
        self.assertEqual(plan.entities[1].entity_key, TEAM)
        self.assertIsNone(plan.relationships[0].from_year)
        tx = FakeTx()
        load_approved_records(review, raw, lambda: tx)
        merge = next(
            params for statement, params in tx.calls
            if statement == MERGE_DROVE_FOR
        )
        self.assertEqual(
            merge["description"],
            "Example Driver competes for Example Team.",
        )
        self.assertTrue(tx.committed)

    def test_invalid_status_is_rejected_before_a_transaction(self):
        opened = []
        review = _approved(approval_status="published")
        review["corrections"] = [_documented_correction()]
        with self.assertRaises(ApprovalRejected):
            load_approved_records(review, _raw(), self._opener(opened))
        self.assertEqual(opened, [])

    def test_invalid_extraction_is_rejected_before_a_transaction(self):
        opened = []
        result = _example_result()
        result["relationships"][0]["source_id"] = "missing"
        with self.assertRaises(ResultRejected):
            load_approved_records(
                _approved(result), _raw(), self._opener(opened))
        self.assertEqual(opened, [])

    def test_blank_entity_name_is_rejected_before_a_transaction(self):
        opened = []
        result = _example_result()
        result["entities"][0]["name"] = "   "
        with self.assertRaises(ResultRejected):
            load_approved_records(
                _approved(result), _raw(), self._opener(opened))
        self.assertEqual(opened, [])

    def test_chunk_id_mismatch_is_rejected_before_a_transaction(self):
        opened = []
        with self.assertRaises(SourceRejected):
            load_approved_records(
                _approved(chunk_id=CHUNK_A),
                _raw(chunk_id=CHUNK_B),
                self._opener(opened),
            )
        self.assertEqual(opened, [])

    def test_stored_hash_mismatch_is_rejected_before_a_transaction(self):
        opened = []
        with self.assertRaises(SourceRejected):
            load_approved_records(
                _approved(raw_hash="hash-a"),
                _raw(raw_hash="hash-b"),
                self._opener(opened),
            )
        self.assertEqual(opened, [])

    def test_raw_status_other_than_ok_is_rejected_before_a_transaction(self):
        opened = []
        with self.assertRaises(SourceRejected):
            load_approved_records(
                _approved(), _raw(status="error"), self._opener(opened))
        self.assertEqual(opened, [])

    def test_matching_stored_hash_does_not_compare_file_bodies(self):
        review = _approved()
        raw = _raw(document_title="different title", text="different text")
        plan = plan_approved_load(review, raw)
        self.assertEqual(plan.chunk_id, CHUNK_A)
        self.assertEqual(plan.entities[0].entity_key, DRIVER)
        self.assertNotEqual(review["result"], raw["result"])

    def test_teammate_of_is_planned_without_opening_a_transaction(self):
        opened = []
        result = _teammate_result()
        plan = plan_approved_load(_approved(result), _raw())
        self.assertEqual(opened, [])
        self.assertEqual(plan.relationships[0].rel_type, "TEAMMATE_OF")
        self.assertEqual(
            plan.relationships[0].rel_key,
            make_rel_key(
                "Driver:example driver",
                "TEAMMATE_OF",
                "Driver:example teammate",
                None,
                None,
                None,
            ),
        )

    def test_batch_gate_rejects_raw_without_the_flag(self):
        opened = []
        with self.assertRaises(ApprovalRejected):
            plan_validated_raw(_raw(), accept_validated_raw=False)
        self.assertEqual(opened, [])

    def test_batch_gate_does_not_mark_the_record_approved(self):
        record = _raw(result=_example_result())
        plan = plan_validated_raw(record, accept_validated_raw=True)
        self.assertEqual(plan.entities[0].entity_key, DRIVER)
        self.assertNotIn("approval_status", record)
        self.assertEqual(record["status"], "ok")

    def _opener(self, opened):
        def open_tx():
            opened.append("open")
            raise AssertionError("transaction opened")
        return open_tx


class WriterTests(unittest.TestCase):
    def test_missing_chunk_has_no_write_and_rolls_back_the_double(self):
        plan = plan_approved_load(_approved(), _raw())
        tx = FakeTx(chunk_id=None)
        opened = []

        def open_tx():
            opened.append("open")
            return tx

        with self.assertRaises(MissingChunk):
            load_approved_plan(plan, open_tx)
        self.assertEqual(opened, ["open"])
        self.assertEqual(len(tx.calls), 1)
        self.assertEqual(tx.calls[0][0], MATCH_CHUNK)
        self.assertNotIn("MERGE", tx.calls[0][0])
        self.assertNotIn("CREATE", tx.calls[0][0])
        self.assertTrue(tx.rolled_back)
        self.assertFalse(tx.committed)

    def test_unit_of_work_rolls_back_the_double_after_an_error(self):
        tx = FakeTx(fail_on=2)
        plan = plan_approved_load(_approved(), _raw())
        with self.assertRaises(RuntimeError):
            load_approved_plan(plan, lambda: tx)
        self.assertGreaterEqual(len(tx.calls), 2)
        self.assertIn("MERGE", tx.calls[1][0])
        self.assertTrue(tx.rolled_back)
        self.assertFalse(tx.committed)

    def test_direct_unit_of_work_commits_only_when_work_returns(self):
        tx = FakeTx()
        run_unit_of_work(lambda: tx, lambda _tx: None)
        self.assertTrue(tx.committed)
        self.assertFalse(tx.rolled_back)

    def test_example_plan_merges_extracted_nodes_mentions_and_sources(self):
        plan = plan_approved_load(_approved(), _raw())
        tx = FakeTx(rel_sources=[[CHUNK_A, CHUNK_B]])
        load_approved_plan(plan, lambda: tx)
        cypher = "\n".join(statement for statement, _params in tx.calls)
        self.assertTrue(tx.committed)
        self.assertFalse(tx.rolled_back)
        self.assertEqual(tx.calls[0][0], MATCH_CHUNK)
        self.assertIn(":Driver:Extracted", cypher)
        self.assertIn(":Team:Extracted", cypher)
        self.assertIn("MERGE (c)-[:MENTIONS]->(e)", cypher)
        self.assertNotIn("CREATE (c:Chunk", cypher)
        self.assertNotIn("MERGE (c:Chunk", cypher)
        self.assertNotIn("driver_id", cypher)
        self.assertNotIn("team_id", cypher)
        self.assertNotIn(":Seed", cypher)
        self.assertNotIn("CREATE CONSTRAINT", cypher)
        self.assertNotIn("CALL dbms.components", cypher)
        driver = tx.calls[1][1]
        self.assertEqual(driver, {
            "entity_key": DRIVER,
            "name": "Example Driver",
            "name_norm": "example driver",
        })
        mentions = [
            params for statement, params in tx.calls
            if "MENTIONS" in statement
        ]
        self.assertEqual(
            {item["entity_key"] for item in mentions},
            {DRIVER, TEAM},
        )
        merge = next(
            params for statement, params in tx.calls
            if statement == MERGE_DROVE_FOR
        )
        self.assertEqual(merge["origin"], "extracted")
        self.assertEqual(merge["rel_key"], (
            '["Driver:example driver","DROVE_FOR","Team:example team",null,null,null]'
        ))
        self.assertIsNone(merge["from_year"])
        self.assertIsNone(merge["to_year"])
        self.assertIsNone(merge["role"])
        updated = next(
            params for statement, params in tx.calls
            if statement == SET_SOURCES
        )
        self.assertEqual(updated["source_chunk_ids"], [CHUNK_A, CHUNK_B])
        self.assertNotIn("from_year", SET_SOURCES)
        described = next(
            params for statement, params in tx.calls
            if statement == SET_DESCRIPTION and params["entity_key"] == DRIVER
        )
        self.assertEqual(
            described["description"],
            "An example driver used only in this test.",
        )

    def test_teammate_of_merge_uses_the_schema_type(self):
        plan = plan_approved_load(_approved(_teammate_result()), _raw())
        tx = FakeTx()
        load_approved_plan(plan, lambda: tx)
        cypher = "\n".join(statement for statement, _params in tx.calls)
        self.assertIn(":Driver:Extracted", cypher)
        self.assertIn("TEAMMATE_OF", cypher)
        self.assertNotIn("DROVE_FOR", cypher)
        self.assertTrue(tx.committed)

    def test_distinct_years_are_two_merges_in_one_transaction(self):
        extra = {
            "source_id": "e1",
            "target_id": "e2",
            "relationship_type": "DROVE_FOR",
            "description": "A second example spell.",
            "from_year": 2021,
            "to_year": None,
            "role": None,
        }
        plan = plan_approved_load(
            _approved(_example_result(from_year=2020, extra=extra)),
            _raw(),
        )
        tx = FakeTx(rel_sources=[[CHUNK_A], [CHUNK_A]])
        load_approved_plan(plan, lambda: tx)
        keys = [
            params["rel_key"] for statement, params in tx.calls
            if statement == MERGE_DROVE_FOR
        ]
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(set(keys)), 2)
        self.assertTrue(tx.committed)
        self.assertFalse(tx.rolled_back)
        driver_merges = [
            statement for statement, _params in tx.calls
            if statement.startswith("MERGE (e:Driver:Extracted")
        ]
        self.assertEqual(len(driver_merges), 1)


class ConstraintTests(unittest.TestCase):
    def test_old_version_sends_no_create_to_the_query_double(self):
        calls = []

        def query(cypher, parameters):
            calls.append(cypher)
            return [{"versions": ["5.6.0"], "edition": "community"}]

        with self.assertRaises(Exception) as caught:
            apply_extracted_constraints(query)
        self.assertEqual(calls, [VERSION_QUERY])
        self.assertIn("no constraint was created", str(caught.exception))

    def test_unreadable_version_sends_no_create_to_the_query_double(self):
        calls = []

        def query(cypher, parameters):
            calls.append(cypher)
            raise RuntimeError("no server")

        with self.assertRaises(Exception):
            apply_extracted_constraints(query)
        self.assertEqual(calls, [VERSION_QUERY])

    def test_supported_version_is_sent_only_to_the_query_double(self):
        calls = []

        def query(cypher, parameters):
            calls.append(cypher)
            if cypher == VERSION_QUERY:
                return [{"versions": ["5.26.0"], "edition": "community"}]
            return []

        version = apply_extracted_constraints(query)
        self.assertEqual(version, "5.26.0")
        self.assertEqual(calls[0], VERSION_QUERY)
        self.assertEqual(calls[1:], list(extracted_constraint_statements()))
        self.assertIn("r.rel_key IS UNIQUE", calls[2])
        self.assertIn("n.entity_key IS UNIQUE", calls[1])

    def test_version_boundary(self):
        self.assertFalse(relationship_uniqueness_supported("5.6.0"))
        self.assertTrue(relationship_uniqueness_supported("5.7.0"))
        self.assertTrue(relationship_uniqueness_supported("5.26-community"))

    def test_import_does_not_call_the_database_or_the_constraint_command(self):
        source = (ROOT / "src" / "naive_rag" / "extraction_load.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        banned = {
            "apply_extracted_constraints",
            "open_neo4j_transaction",
            "get_driver",
            "write_plan",
            "load_approved_records",
        }
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    name = None
                    if isinstance(child.func, ast.Name):
                        name = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        name = child.func.attr
                    self.assertNotIn(name, banned)
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("graph"):
                self.fail("graph is imported at module level")
        self.assertNotIn(
            "open_neo4j_transaction",
            inspect.getsource(load_approved_records),
        )
        self.assertNotIn("write_plan", inspect.getsource(apply_extracted_constraints))


class SampleFileTests(unittest.TestCase):
    def test_approved_hamilton_sample_passes_prechecks_without_a_transaction(self):
        raw_before = RAW.read_bytes()
        review_before = REVIEW.read_bytes()
        raw = json.loads(raw_before)
        review = json.loads(review_before)
        self.assertEqual(review["approval_status"], "approved")
        self.assertNotEqual(review["result"], raw["result"])
        self.assertEqual(
            review["result"]["entities"][1]["description"],
            "Lewis Hamilton competes in Formula One for Ferrari.",
        )
        self.assertEqual(
            raw["result"]["entities"][1]["description"],
            "A Formula 1 team that Lewis Hamilton competes for.",
        )
        plan = plan_approved_load(review, raw)
        self.assertEqual(
            [entity.entity_key for entity in plan.entities],
            ["Driver:lewis hamilton", "Team:ferrari"],
        )
        self.assertEqual(
            plan.relationships[0].description,
            "Lewis Hamilton competes for Ferrari in Formula One.",
        )
        self.assertIsNone(plan.relationships[0].from_year)
        self.assertIsNone(plan.relationships[0].to_year)
        self.assertIsNone(plan.relationships[0].role)
        self.assertEqual(
            plan.relationships[0].rel_key,
            '["Driver:lewis hamilton","DROVE_FOR","Team:ferrari",null,null,null]',
        )
        self.assertEqual(RAW.read_bytes(), raw_before)
        self.assertEqual(REVIEW.read_bytes(), review_before)
        self.assertEqual(
            hashlib.sha256(RAW.read_bytes()).hexdigest(), RAW_FILE_SHA256)

    def test_hash_scope_matches_the_existing_input_hash_function(self):
        source = inspect.getsource(input_hash)
        for token in (
            "SYSTEM_PROMPT",
            "prompt_version",
            "document_title",
            "section",
            '"text"',
            "sha256",
            "sort_keys=True",
        ):
            self.assertIn(token, source)
        self.assertIn("SYSTEM_PROMPT", RAW_INPUT_HASH_SCOPE)
        self.assertIn("does not checksum the raw file", RAW_INPUT_HASH_SCOPE)
        self.assertIn("queries.cypher", Q6_LAYER_NOTE)

    def test_q6_match_has_no_layer_label(self):
        text = (ROOT / "graph" / "cypher" / "queries.cypher").read_text(
            encoding="utf-8")
        found = False
        for line in text.splitlines():
            if line.startswith("MATCH path = (d:Driver {name: $driver})"):
                found = True
                self.assertNotIn("Extracted", line)
                self.assertNotIn(":Seed", line)
        self.assertTrue(found)


if __name__ == "__main__":
    unittest.main()
