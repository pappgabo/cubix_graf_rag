"""The default question path uses the Neo4j searcher. No live services."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from naive_rag.entity_index import index_text
from naive_rag.graph import GraphUnavailable
from naive_rag.local_search import (
    LocalAnswer,
    configured_query,
    main,
    subgraph_payload,
)
from naive_rag.neo4j_entity_index import (
    INDEX_QUERY,
    VECTOR_INDEX_NAME,
    VECTOR_QUERY,
    text_hash,
)
from naive_rag.neo4j_local_search import CHUNK_TEXT_QUERY, NEIGHBORHOOD_QUERY

MODEL = "test-embed"
QUESTION = "Which team did Lewis Hamilton drive for?"


def _settings(**extra):
    values = {
        "llm_provider": "openai",
        "embedding_model": MODEL,
        "neo4j_uri": "bolt://configured:7687",
        "neo4j_user": "neo4j",
        "neo4j_password": "secret",
        "neo4j_database": "graphdb",
    }
    values.update(extra)
    return SimpleNamespace(**values)


def _index_row():
    return {
        "name": VECTOR_INDEX_NAME,
        "labelsOrTypes": ["Extracted"],
        "properties": ["embedding"],
        "state": "ONLINE",
        "options": {"indexConfig": {
            "vector.similarity_function": "COSINE",
            "vector.dimensions": 3,
        }},
    }


def _anchor():
    name = "Lewis Hamilton"
    description = "A driver."
    return {
        "entity_key": "Driver:lewis hamilton",
        "name": name,
        "description": description,
        "embedding_model": MODEL,
        "embedding_dimensions": 3,
        "embedding_text_sha256": text_hash(index_text(name, description)),
        "score": 0.91,
    }


def _baseline(path: Path) -> None:
    path.write_text(json.dumps({
        "meta": {},
        "results": [{"id": "Q01", "question": QUESTION, "answer": "baseline"}],
    }), encoding="utf-8")


class DefaultSearchPathTests(unittest.TestCase):
    def test_entry_point_uses_neo4j_for_anchors_graph_and_sources(self) -> None:
        calls = []
        prompts = []

        def query(cypher, params):
            calls.append((cypher, params))
            if cypher == INDEX_QUERY:
                return [_index_row()]
            if cypher == VECTOR_QUERY:
                self.assertEqual(params["k"], 3)
                self.assertEqual(params["index_name"], VECTOR_INDEX_NAME)
                self.assertEqual(params["vector"], [0.2, 0.0, 0.0])
                return [_anchor()]
            if cypher == NEIGHBORHOOD_QUERY:
                self.assertEqual(
                    params["anchor_keys"], ["Driver:lewis hamilton"])
                return [{
                    "source_key": "Driver:lewis hamilton",
                    "source_label": "Driver",
                    "source_name": "Lewis Hamilton",
                    "source_description": "A driver.",
                    "target_key": "Team:scuderia ferrari",
                    "target_label": "Team",
                    "target_name": "Scuderia Ferrari",
                    "target_description": "A team.",
                    "rel_type": "DROVE_FOR",
                    "rel_key": '["h","DROVE_FOR","f",2013,2020,null]',
                    "from_year": 2013,
                    "to_year": 2020,
                    "role": None,
                    "description": "Hamilton drove for Ferrari.",
                    "source_chunk_ids": ["driver-lewis-hamilton#0"],
                }]
            if cypher.startswith("MATCH (n:Extracted)"):
                return []
            if "MENTIONS" in cypher:
                return []
            if cypher == CHUNK_TEXT_QUERY:
                self.assertEqual(
                    params["chunk_ids"], ["driver-lewis-hamilton#0"])
                return [{
                    "chunk_id": "driver-lewis-hamilton#0",
                    "text": "Hamilton drove for Ferrari from 2013.",
                }]
            raise AssertionError(cypher)

        def embed(question):
            self.assertEqual(question, QUESTION)
            return [0.2, 0.0, 0.0]

        def answer(prompt):
            prompts.append(prompt)
            self.assertIn("Hamilton drove for Ferrari from 2013.", prompt)
            return "mocked answer"

        def memory(*_args, **_kwargs):
            raise AssertionError("in-memory search was called")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "answers.json"
            _baseline(baseline)
            out = root / "out.md"
            with patch("naive_rag.local_search.local_search", memory):
                code = main([
                    "--baseline", str(baseline),
                    "--out", str(out),
                    "--run",
                ], settings=_settings(), query_fn=query,
                    embed_query=embed, answer_fn=answer)
            saved = json.loads(out.with_name("out-run.json").read_text(
                encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(calls[0][0], INDEX_QUERY)
        self.assertIn(VECTOR_QUERY, [item[0] for item in calls])
        self.assertIn(NEIGHBORHOOD_QUERY, [item[0] for item in calls])
        self.assertIn(CHUNK_TEXT_QUERY, [item[0] for item in calls])
        self.assertEqual(saved[0]["raw_answer"], "mocked answer")
        self.assertIn("driver-lewis-hamilton#0", prompts[0])
        self.assertIn("DROVE_FOR", prompts[0])

    def test_memory_flag_is_the_only_in_memory_path(self) -> None:
        seen = {}

        def memory(question, graph, index, **kwargs):
            seen["question"] = question
            seen["graph"] = graph.kind
            return LocalAnswer(
                question=question, answer="memory", refused=False,
                model_called=True, subgraph=subgraph_payload((), ()),
                raw_answer="memory")

        def neo4j(*_args, **_kwargs):
            raise AssertionError("Neo4j search was called")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "answers.json"
            _baseline(baseline)
            out = root / "out.md"
            with patch("naive_rag.local_search.local_search", memory), \
                    patch("naive_rag.neo4j_local_search.neo4j_local_search",
                          neo4j), \
                    patch("naive_rag.entity_index.load_index",
                          return_value=SimpleNamespace(entities=[object()])), \
                    patch("naive_rag.graph_merge.merged_graph",
                          return_value=SimpleNamespace(kind="merged")), \
                    patch("naive_rag.quality_report.load_records",
                          return_value=[]), \
                    patch("naive_rag.ingest.load_and_chunk",
                          return_value=([], [])), \
                    patch("naive_rag.models.get_embeddings",
                          return_value=SimpleNamespace(embed_query=lambda _q: [])), \
                    patch("naive_rag.models.get_chat_model",
                          return_value=SimpleNamespace(
                              invoke=lambda _prompt: SimpleNamespace(content="x"))):
                code = main([
                    "--memory",
                    "--index", str(root / "index.json"),
                    "--extraction-dir", str(root),
                    "--baseline", str(baseline),
                    "--out", str(out),
                    "--run",
                ])
        self.assertEqual(code, 0)
        self.assertEqual(seen["question"], QUESTION)
        self.assertEqual(seen["graph"], "merged")

    def test_missing_configuration_is_an_error(self) -> None:
        def query(_cypher, _params):
            raise AssertionError("a query was sent")

        def memory(*_args, **_kwargs):
            raise AssertionError("in-memory search was called")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "answers.json"
            _baseline(baseline)
            with patch("naive_rag.local_search.local_search", memory):
                code = main([
                    "--baseline", str(baseline),
                    "--out", str(root / "out.md"),
                    "--run",
                ], settings=_settings(neo4j_uri=""), query_fn=query,
                    embed_query=lambda _q: [0.0], answer_fn=lambda _p: "no")
        self.assertEqual(code, 1)
        self.assertFalse((root / "out.md").exists())

    def test_unavailable_index_is_not_an_empty_success(self) -> None:
        def query(cypher, _params):
            if cypher == INDEX_QUERY:
                return []
            raise AssertionError(cypher)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "answers.json"
            _baseline(baseline)
            code = main([
                "--baseline", str(baseline),
                "--out", str(root / "out.md"),
                "--run",
            ], settings=_settings(), query_fn=query,
                embed_query=lambda _q: [0.0], answer_fn=lambda _p: "no")
        self.assertEqual(code, 1)
        self.assertFalse((root / "out-run.json").exists())

    def test_connection_error_is_reported(self) -> None:
        def query(_cypher, _params):
            raise GraphUnavailable("No Neo4j at bolt://configured:7687.")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "answers.json"
            _baseline(baseline)
            code = main([
                "--baseline", str(baseline),
                "--out", str(root / "out.md"),
                "--run",
            ], settings=_settings(), query_fn=query,
                embed_query=lambda _q: [0.0], answer_fn=lambda _p: "no")
        self.assertEqual(code, 1)

    def test_configured_query_delegates_to_graph_query(self) -> None:
        with patch("naive_rag.graph.query", return_value=[{"ok": 1}]) as graph:
            rows = configured_query("RETURN 1", {"database": "ignored-name"})
        self.assertEqual(rows, [{"ok": 1}])
        graph.assert_called_once_with("RETURN 1", database="ignored-name")
