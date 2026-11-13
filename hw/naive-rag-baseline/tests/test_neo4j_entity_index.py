"""Offline checks for the Neo4j entity index. No model and no database."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from naive_rag.entity_index import Anchor, index_text
from naive_rag.neo4j_entity_index import (
    NODE_QUERY,
    SET_EMBEDDING,
    VECTOR_INDEX_NAME,
    IndexRejected,
    build_neo4j_index,
    copy_matching_embeddings,
    create_vector_index_cypher,
    describe_index,
    index_decision,
    neo4j_anchors,
    plan_index,
    text_hash,
)


def _row(key="Driver:lewis hamilton", name="Lewis Hamilton",
         description="A driver.", **extra):
    body = {
        "entity_key": key,
        "name": name,
        "description": description,
        "embedding_model": None,
        "embedding_dimensions": None,
        "embedding_text_sha256": None,
        "has_embedding": False,
        "embedding_size": 0,
    }
    body.update(extra)
    return body


def _valid(key="Driver:lewis hamilton", name="Lewis Hamilton",
           description="A driver.", model="text-embedding-3-small"):
    text = index_text(name, description)
    return _row(
        key, name, description,
        embedding_model=model,
        embedding_dimensions=3,
        embedding_text_sha256=text_hash(text),
        has_embedding=True,
        embedding_size=3,
    )


class PlanTests(unittest.TestCase):
    def test_index_text_is_the_stored_hash_source(self):
        row = _valid()
        plan = plan_index([row], [], model="text-embedding-3-small")
        self.assertEqual(index_text("Lewis Hamilton", "A driver."),
                         "Lewis Hamilton\nA driver.")
        self.assertEqual(plan["reusable_vectors"], 1)
        self.assertEqual(plan["vectors_to_create"], 0)
        self.assertEqual(
            row["embedding_text_sha256"],
            text_hash(index_text(row["name"], row["description"])),
        )

    def test_missing_description_uses_the_same_text(self):
        self.assertEqual(index_text("Ferrari", None), "Ferrari\n")
        row = _valid(name="Ferrari", description=None)
        row["description"] = None
        row["embedding_text_sha256"] = text_hash(index_text("Ferrari", None))
        plan = plan_index([row], [], model="text-embedding-3-small")
        self.assertEqual(plan["reusable_vectors"], 1)

    def test_other_model_or_text_is_not_reusable(self):
        stale_model = _valid()
        stale_model["embedding_model"] = "other-model"
        stale_text = _valid(key="Team:scuderia ferrari", name="Scuderia Ferrari")
        stale_text["description"] = "Changed after the embedding."
        missing = _row(key="Team:red bull racing", name="Red Bull Racing")
        plan = plan_index(
            [stale_model, stale_text, missing], [],
            model="text-embedding-3-small")
        self.assertEqual(plan["entities"], 3)
        self.assertEqual(plan["existing_vectors"], 2)
        self.assertEqual(plan["reusable_vectors"], 0)
        self.assertEqual(plan["vectors_to_create"], 3)

    def test_different_index_is_not_replaced(self):
        indexes = [{
            "name": "other_index",
            "state": "ONLINE",
            "labelsOrTypes": ["Extracted"],
            "properties": ["embedding"],
            "options": {"indexConfig": {
                "vector.dimensions": 3,
                "vector.similarity_function": "euclidean",
            }},
        }]
        plan = plan_index([_row()], indexes, model="text-embedding-3-small")
        self.assertIn("will not be dropped", plan["index_error"])
        self.assertIsNone(describe_index({
            "name": VECTOR_INDEX_NAME,
            "labelsOrTypes": ["Extracted"],
            "properties": ["embedding"],
            "options": {"indexConfig": {"vector.dimensions": 3}},
        })["similarity"])

    def _index(self, similarity, dimensions, name=VECTOR_INDEX_NAME):
        return [{
            "name": name,
            "state": "ONLINE",
            "labelsOrTypes": ["Extracted"],
            "properties": ["embedding"],
            "options": {"indexConfig": {
                "vector.dimensions": dimensions,
                "vector.similarity_function": similarity,
            }},
        }]

    def test_cosine_is_accepted_in_either_case(self):
        for similarity in ("COSINE", "cosine"):
            self.assertEqual(
                index_decision(self._index(similarity, 1536), 1536),
                "reuse",
            )

    def test_a_different_similarity_is_rejected(self):
        with self.assertRaises(IndexRejected):
            index_decision(self._index("euclidean", 1536), 1536)

    def test_a_different_dimension_is_rejected(self):
        with self.assertRaises(IndexRejected):
            index_decision(self._index("COSINE", 768), 1536)
        self.assertNotIn("DROP", create_vector_index_cypher(3))
        self.assertIn("cosine", create_vector_index_cypher(3))


class BuildTests(unittest.TestCase):
    def test_vectors_are_stored_by_entity_key(self):
        calls = []

        def query(cypher, params=None):
            if cypher.startswith("MATCH (n:Extracted)"):
                return [
                    _valid(),
                    _row(key="Team:ferrari", name="Ferrari", description="A team."),
                ]
            if cypher.startswith("SHOW INDEXES"):
                return []
            raise AssertionError(cypher)

        def write(cypher, params=None):
            calls.append((cypher, params))
            if cypher == SET_EMBEDDING:
                return [{"entity_key": params["entity_key"]}]
            return [{"ok": True}]

        def embed(texts):
            self.assertEqual(texts, [index_text("Ferrari", "A team.")])
            return [[1.0, 0.0, 0.0]]

        build_neo4j_index(
            query, write, embed, model="text-embedding-3-small")
        stored = [params for cypher, params in calls if cypher == SET_EMBEDDING]
        self.assertEqual([item["entity_key"] for item in stored], ["Team:ferrari"])
        self.assertEqual(stored[0]["embedding_model"], "text-embedding-3-small")
        self.assertEqual(stored[0]["embedding_dimensions"], 3)
        self.assertEqual(
            stored[0]["embedding_text_sha256"],
            text_hash(index_text("Ferrari", "A team.")),
        )
        self.assertIn(VECTOR_INDEX_NAME, calls[-1][0])
        self.assertIn("cosine", calls[-1][0])

    def test_conflicting_index_stops_before_a_write(self):
        def query(cypher, params=None):
            if cypher.startswith("SHOW INDEXES"):
                return [{
                    "name": "other_index",
                    "state": "ONLINE",
                    "labelsOrTypes": ["Extracted"],
                    "properties": ["embedding"],
                    "options": {"indexConfig": {
                        "vector.dimensions": 4,
                        "vector.similarity_function": "cosine",
                    }},
                }]
            return [_row()]

        def write(cypher, params=None):
            raise AssertionError("write")

        def embed(texts):
            raise AssertionError("embed")

        with self.assertRaises(IndexRejected):
            build_neo4j_index(query, write, embed, model="text-embedding-3-small")


class AnchorTests(unittest.TestCase):
    def test_anchor_keeps_the_neo4j_score_and_drops_a_stale_row(self):
        valid = _valid()

        def query(cypher, params):
            self.assertEqual(params["k"], 2)
            self.assertEqual(params["vector"], [1.0, 0.0, 0.0])
            return [
                {**valid, "score": 0.1},
                {
                    **_valid(key="Team:ferrari", name="Ferrari",
                             description="Old text."),
                    "description": "New text.",
                    "score": 0.99,
                },
            ]

        anchors = neo4j_anchors(
            [1.0, 0.0, 0.0], k=2, query_fn=query,
            model="text-embedding-3-small")
        self.assertEqual(anchors, (Anchor("Driver:lewis hamilton", 0.1),))


def _backup_node(name, description, vector, *, model="text-embedding-3-small",
                 dimensions=3, digest=None, key="Driver:stored"):
    text = index_text(name, description)
    return {
        "labels": ["Driver", "Extracted"],
        "properties": {
            "entity_key": key,
            "name": name,
            "description": description,
            "embedding": vector,
            "embedding_model": model,
            "embedding_dimensions": dimensions,
            "embedding_text_sha256": text_hash(text) if digest is None else digest,
        },
    }


class CopyEmbeddingTests(unittest.TestCase):
    def test_copy_requires_the_same_text_model_and_dimension(self):
        same = _backup_node("Lewis Hamilton", "A driver.", [0.2, 0.0, 0.4])
        other_model = _backup_node(
            "Ferrari", "A team.", [0.1, 0.1, 0.1],
            model="other-model", key="Team:ferrari")
        other_width = _backup_node(
            "Red Bull", "A team.", [0.3, 0.3],
            dimensions=2, key="Team:red bull")
        stale = _backup_node(
            "McLaren", "Old text.", [0.5, 0.5, 0.5],
            digest="not-the-text", key="Team:mclaren")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backup.json"
            path.write_text(json.dumps({
                "format": "extracted-layer-backup-1",
                "mixed": [],
                "nodes": [same, other_model, other_width, stale],
                "edges": [],
            }), encoding="utf-8")
            calls = []

            def query(cypher, params=None):
                self.assertEqual(cypher, NODE_QUERY)
                return [
                    _row(name="Lewis Hamilton", description="A driver."),
                    _row(key="Team:ferrari", name="Ferrari",
                         description="A different description."),
                    _row(key="Team:mclaren", name="McLaren",
                         description="Old text."),
                ]

            def write(cypher, params=None):
                calls.append((cypher, params))
                return [{"entity_key": params["entity_key"]}]

            copied = copy_matching_embeddings(
                path, query, write,
                model="text-embedding-3-small", dimensions=3)

        self.assertEqual(copied, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], SET_EMBEDDING)
        self.assertEqual(calls[0][1]["embedding"], [0.2, 0.0, 0.4])
        self.assertEqual(calls[0][1]["embedding_model"], "text-embedding-3-small")
        self.assertEqual(calls[0][1]["embedding_dimensions"], 3)
        self.assertEqual(
            calls[0][1]["embedding_text_sha256"],
            text_hash(index_text("Lewis Hamilton", "A driver.")),
        )

    def test_conflicting_backup_vectors_are_not_written(self):
        first = _backup_node("Lewis Hamilton", "A driver.", [0.2, 0.0, 0.4])
        second = _backup_node(
            "Lewis Hamilton", "A driver.", [0.9, 0.9, 0.9],
            key="Driver:other")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backup.json"
            path.write_text(json.dumps({
                "format": "extracted-layer-backup-1",
                "mixed": [],
                "nodes": [first, second],
                "edges": [],
            }), encoding="utf-8")

            def write(cypher, params=None):
                raise AssertionError("write")

            with self.assertRaises(IndexRejected):
                copy_matching_embeddings(
                    path, lambda *args, **kwargs: [], write,
                    model="text-embedding-3-small", dimensions=3)


if __name__ == "__main__":
    unittest.main()
