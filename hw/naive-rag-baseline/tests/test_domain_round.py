"""Offline checks for dedup, quality, local search, and the comparison.

No model call and no database. The v3 pilot files are read and not written.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from naive_rag.compare_baseline import render_comparison
from naive_rag.entity_index import build_index, index_text, load_index, save_index
from naive_rag.graph_merge import (
    ALIAS_MAP,
    measure,
    merged_graph,
    occurrence_graph,
)
from naive_rag.local_search import (
    REFUSAL,
    cited_chunks,
    filter_questions,
    local_search,
    search_record,
    select_context,
    unsupported_claims,
    main as search_main,
)
from naive_rag.quality_report import quality_payload, render_markdown
from naive_rag.question_scope import (
    doc_ids_for,
    documents_by_question,
    question_ids_from_scope,
)

ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "graph" / "pilot" / "extraction-v3"
CHUNKS = ROOT / "graph" / "pilot" / "chunks.jsonl"
RAW = V3 / "driver-lewis-hamilton_0.json"
RAW_SHA = "bbbf214402a8c22e87d3fc41d6e25ee3efc7b7c5036c3f831b39e2e1dd73f8be"


def _record(chunk_id, entities, relationships=None):
    return {
        "chunk_id": chunk_id,
        "status": "ok",
        "result": {
            "entities": entities,
            "relationships": relationships or [],
        },
    }


def _driver(local_id, name, description="A driver in the text."):
    return {
        "local_id": local_id,
        "name": name,
        "entity_type": "Driver",
        "description": description,
    }


def _team(local_id, name):
    return {
        "local_id": local_id,
        "name": name,
        "entity_type": "Team",
        "description": "A team in the text.",
    }


def _drove(source, target, from_year=None, role=None):
    return {
        "source_id": source,
        "target_id": target,
        "relationship_type": "DROVE_FOR",
        "description": "The text states a racing spell.",
        "from_year": from_year,
        "to_year": None,
        "role": role,
    }


class MergeTests(unittest.TestCase):
    def test_same_key_merges_and_keeps_both_chunks(self):
        records = [
            _record("a#0", [_driver("e1", "Lewis Hamilton"), _team("e2", "Ferrari")],
                    [_drove("e1", "e2")]),
            _record("a#1", [_driver("e1", "lewis hamilton")], []),
        ]
        before = occurrence_graph(records)
        after = merged_graph(records)
        self.assertEqual(len(before.nodes), 3)
        self.assertEqual(len(after.nodes), 2)
        hamilton = next(node for node in after.nodes
                        if node.entity_key == "Driver:lewis hamilton")
        self.assertEqual(hamilton.source_chunk_ids, ("a#0", "a#1"))
        self.assertEqual(len(before.edges), 1)
        self.assertEqual(len(after.edges), 1)
        self.assertEqual(after.edges[0].source_chunk_ids, ("a#0",))
        self.assertEqual(ALIAS_MAP, {})

    def test_different_years_stay_two_edges(self):
        records = [
            _record("a#0", [_driver("e1", "Lewis Hamilton"), _team("e2", "Ferrari")],
                    [_drove("e1", "e2", from_year=2007)]),
            _record("a#1", [_driver("e1", "Lewis Hamilton"), _team("e2", "Ferrari")],
                    [_drove("e1", "e2", from_year=2013)]),
        ]
        after = merged_graph(records)
        self.assertEqual(len(after.nodes), 2)
        self.assertEqual(len(after.edges), 2)
        self.assertEqual(
            {edge.from_year for edge in after.edges},
            {2007, 2013},
        )

    def test_same_edge_unions_sources(self):
        records = [
            _record("a#0", [_driver("e1", "Lewis Hamilton"), _team("e2", "Ferrari")],
                    [_drove("e1", "e2")]),
            _record("b#0", [_driver("e1", "Lewis Hamilton"), _team("e2", "Ferrari")],
                    [_drove("e1", "e2")]),
        ]
        edge = merged_graph(records).edges[0]
        self.assertEqual(edge.source_chunk_ids, ("a#0", "b#0"))

    def test_component_count_ignores_direction(self):
        records = [
            _record("a#0", [_driver("e1", "Lewis Hamilton"), _team("e2", "Ferrari")],
                    [_drove("e1", "e2")]),
            _record("b#0", [_driver("e1", "Other Driver")], []),
        ]
        measured = measure(merged_graph(records))
        self.assertEqual(measured["nodes"], 3)
        self.assertEqual(measured["edges"], 1)
        self.assertEqual(measured["largest_weak_component_nodes"], 2)
        self.assertIn("az irány nem számít", measured["component_meaning"])


class SearchTests(unittest.TestCase):
    def _graph(self):
        return merged_graph([
            _record(
                "a#0",
                [_driver("e1", "Lewis Hamilton", "British racing driver."),
                 _team("e2", "Ferrari")],
                [_drove("e1", "e2")],
            ),
        ])

    def test_index_text_keeps_a_missing_description_empty(self):
        self.assertEqual(index_text("Ferrari", None), "Ferrari\n")
        self.assertEqual(index_text("Ferrari", ""), "Ferrari\n")

    def test_saved_index_roundtrip(self):
        graph = self._graph()
        index = build_index(graph, lambda texts: [[1.0, 0.0] for _text in texts])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            save_index(index, path)
            loaded = load_index(path)
        self.assertEqual(
            [item.entity_key for item in loaded.entities],
            [item.entity_key for item in index.entities],
        )
        self.assertEqual(loaded.entities[0].text, index.entities[0].text)

    def test_anchor_expands_and_cites_the_chunk(self):
        graph = self._graph()
        seen = []

        def embed(texts):
            seen.extend(texts)
            vectors = []
            for text in texts:
                if text.startswith("Lewis Hamilton"):
                    vectors.append([1.0, 0.0])
                else:
                    vectors.append([0.0, 1.0])
            return vectors

        index = build_index(graph, embed)
        self.assertEqual(seen[0], "Lewis Hamilton\nBritish racing driver.")

        def answer(prompt):
            self.assertIn("Driver:lewis hamilton", prompt)
            self.assertIn("a#0", prompt)
            self.assertNotIn("British racing driver", prompt)
            return "Hamilton versenyez a Ferrarinak."

        result = local_search(
            "Lewis Hamilton csapata?",
            graph,
            index,
            embed_query=lambda _question: [1.0, 0.0],
            answer_fn=answer,
        )
        self.assertFalse(result.refused)
        self.assertTrue(result.model_called)
        keys = {node["entity_key"] for node in result.subgraph["nodes"]}
        self.assertEqual(keys, {"Driver:lewis hamilton", "Team:ferrari"})
        self.assertEqual(result.subgraph["chunk_ids"], ["a#0"])
        self.assertEqual(result.subgraph["edges"][0]["rel_type"], "DROVE_FOR")
        saved = search_record("Q01", result)
        self.assertTrue(saved["model_called"])
        self.assertEqual(saved["raw_answer"], result.answer)
        self.assertIn("Driver:lewis hamilton", saved["prompt"])
        self.assertEqual(saved["anchors"][0]["entity_key"], "Driver:lewis hamilton")
        self.assertIn("score", saved["anchors"][0])

    def test_a_matching_edge_outranks_edges_stored_first(self):
        entities = [
            _driver("h", "Lewis Hamilton"),
            _driver("a", "Fernando Alonso"),
        ]
        relationships = []
        for index in range(15):
            entities.append(_team(f"t{index}", f"Team {index}"))
            relationships.append(_drove("a", f"t{index}"))
        entities.append({
            "local_id": "title",
            "name": "World Drivers' Championship",
            "entity_type": "Title",
            "description": "A championship title.",
        })
        relationships.append({
            "source_id": "h",
            "target_id": "title",
            "relationship_type": "WON",
            "description": "Hamilton won the World Drivers' Championship.",
            "from_year": None,
            "to_year": None,
            "role": None,
        })
        graph = merged_graph([_record("a#0", entities, relationships)])
        _nodes, edges = select_context(
            graph,
            "How many World Drivers' Championships has Lewis Hamilton won?",
            (("Driver:lewis hamilton", 0.9), ("Driver:fernando alonso", 0.4)),
        )
        self.assertIn("WON", [edge.rel_type for edge in edges])
        self.assertLess(sum(edge.rel_type == "DROVE_FOR" for edge in edges), 12)

    def test_question_can_keep_a_teammate_edge_between_neighbors(self):
        entities = [
            {"local_id": "title", "name": "Formula One World Drivers' Championship",
             "entity_type": "Title", "description": "Won by Nico Rosberg in 2016."},
            {"local_id": "season", "name": "2016", "entity_type": "Season",
             "description": "The 2016 season."},
            _driver("alonso", "Fernando Alonso"),
            _driver("rosberg", "Nico Rosberg"),
            _driver("hamilton", "Lewis Hamilton"),
            _team("mercedes", "Mercedes"),
        ]
        relationships = [
            {"source_id": "rosberg", "target_id": "title", "relationship_type": "WON",
             "description": "Nico Rosberg won the Formula One World Drivers' Championship.",
             "from_year": None, "to_year": None, "role": None},
            {"source_id": "title", "target_id": "season", "relationship_type": "AWARDED_IN",
             "description": "The championship was awarded in 2016.",
             "from_year": None, "to_year": None, "role": None},
            {"source_id": "hamilton", "target_id": "rosberg", "relationship_type": "TEAMMATE_OF",
             "description": "Hamilton was teammates with Rosberg at Mercedes.",
             "from_year": None, "to_year": None, "role": None},
            {"source_id": "rosberg", "target_id": "mercedes", "relationship_type": "DROVE_FOR",
             "description": "Nico Rosberg raced for Mercedes.",
             "from_year": 2006, "to_year": 2016, "role": None},
        ]
        for index in range(10):
            entities.append(_team(f"t{index}", f"Team {index}"))
            relationships.append(_drove("alonso", f"t{index}"))
        graph = merged_graph([_record("q#0", entities, relationships)])
        nodes, edges = select_context(
            graph,
            "Who was the teammate of the 2016 World Drivers' Champion at his team that season?",
            (
                ("Title:formula one world drivers' championship", 0.91),
                ("Driver:fernando alonso", 0.80),
                ("Season:2016", 0.70),
            ),
        )
        keys = {node.entity_key for node in nodes}
        self.assertIn("Driver:nico rosberg", keys)
        self.assertIn("Driver:lewis hamilton", keys)
        self.assertTrue(any(
            edge.rel_type == "TEAMMATE_OF"
            and {edge.source_id, edge.target_id} == {
                "Driver:lewis hamilton", "Driver:nico rosberg",
            }
            for edge in edges
        ))
        self.assertTrue(any(
            edge.rel_type == "DROVE_FOR" and edge.to_year == 2016
            for edge in edges
        ))

    def test_low_score_does_not_call_the_answer_model(self):
        graph = self._graph()
        index = build_index(graph, lambda texts: [[1.0, 0.0] for _text in texts])

        def answer(_prompt):
            raise AssertionError("answer model was called")

        result = local_search(
            "valami más",
            graph,
            index,
            embed_query=lambda _question: [0.0, 1.0],
            answer_fn=answer,
        )
        self.assertTrue(result.refused)
        self.assertFalse(result.model_called)
        self.assertEqual(result.answer, REFUSAL)
        self.assertEqual(result.subgraph["nodes"], [])

    def test_answer_command_without_run_makes_no_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "answers.json"
            baseline.write_text(
                json.dumps({"results": [{"id": "Q01"}]}), encoding="utf-8")
            output = Path(tmp) / "out.md"
            code = search_main([
                "--index", str(Path(tmp) / "missing.json"),
                "--extraction-dir", str(Path(tmp)),
                "--baseline", str(baseline),
                "--out", str(output),
            ])
            self.assertEqual(code, 0)
            self.assertFalse(output.exists())

    def test_entity_chunk_is_eligible_evidence(self):
        records = [
            _record("intro#0", [_driver("e1", "Lewis Hamilton")], []),
            _record(
                "move#0",
                [_driver("e1", "Lewis Hamilton"), _team("e2", "Ferrari")],
                [_drove("e1", "e2")],
            ),
        ]
        graph = merged_graph(records)
        nodes, edges = select_context(
            graph,
            "How many World Drivers' Championships has Lewis Hamilton won?",
            (("Driver:lewis hamilton", 0.9),),
        )
        texts = {
            "intro#0": "Hamilton has won a joint-record seven World Drivers' "
                       "Championship titles.",
            "move#0": "Hamilton competes for Ferrari.",
        }
        picked = [item["chunk_id"] for item in cited_chunks(
            edges, nodes, texts,
            "How many World Drivers' Championships has Lewis Hamilton won?",
        )]
        self.assertIn("intro#0", picked)
        self.assertEqual(picked[0], "intro#0")

    def test_unsupported_names_are_reported(self):
        sources = [{"chunk_id": "a#0", "text": "Nico Rosberg won in 2016."}]
        self.assertEqual(unsupported_claims(REFUSAL, sources), [])
        self.assertEqual(unsupported_claims("Nico Rosberg", sources), [])
        self.assertIn(
            "charles leclerc",
            unsupported_claims("Nico Rosberg, Charles Leclerc.", sources),
        )
        self.assertIn("7", unsupported_claims("He won 7 titles.", sources))

    def test_question_filter_keeps_an_inclusive_range(self):
        items = [{"id": "Q01"}, {"id": "Q04"}, {"id": "Q05"}]
        self.assertEqual(
            [item["id"] for item in filter_questions(items, "Q01-Q04")],
            ["Q01", "Q04"],
        )
        self.assertEqual(len(filter_questions(items, None)), 3)


class ScopeTests(unittest.TestCase):
    def test_concrete_ids_are_kept_and_wildcards_are_not_expanded(self):
        text = "\n".join([
            "### Q01 — simple",
            "**Dokumentum(ok):** `driver-lewis-hamilton`",
            "### Q09 — global",
            "**Dokumentum(ok):** az összes `driver-*` dokumentum",
        ])
        found = documents_by_question(text)
        self.assertEqual(found["Q01"], ("driver-lewis-hamilton",))
        self.assertEqual(found["Q09"], ())
        self.assertEqual(
            doc_ids_for(text, ("Q01", "Q09")),
            ("driver-lewis-hamilton",),
        )
        self.assertEqual(question_ids_from_scope("Q01-Q08")[0], "Q01")
        self.assertEqual(question_ids_from_scope("Q01-Q08")[-1], "Q08")
        self.assertEqual(len(question_ids_from_scope("Q01-Q08")), 8)


class ComparisonTests(unittest.TestCase):
    def test_missing_local_run_is_not_called_an_improvement(self):
        baseline = {
            "meta": {"chat_model": "gpt-4o-mini", "num_chunks": 3832, "top_k": 4},
            "results": [{
                "id": "Q04",
                "type": "multi-hop",
                "question": "Who won?",
                "answer": "Baseline answer.",
                "sources": [{"chunk_id": "season-2016#0"}],
            }],
        }
        text = render_comparison(baseline, None)
        self.assertIn("Baseline answer.", text)
        self.assertIn("Nem futott.", text)
        self.assertIn("## Q01–Q08", text)
        self.assertIn("## Q09–Q13", text)
        self.assertIn("kontrollált összehasonlítás", text)
        self.assertIn("Javulás nincs állítva", text)
        ran = render_comparison(baseline, {
            "Q04": {"answer": "A rendelkezésre álló részgráf nem támasztja alá a választ.",
                    "subgraph": {"nodes": [], "edges": [], "chunk_ids": []},
                    "evaluation": "A lánc elutasította a választ, mert a részgráf nem volt elég."},
        })
        self.assertNotIn("Nem futott.", ran)
        self.assertIn("A lokális lánc lefutott.", ran)


class PilotReportTests(unittest.TestCase):
    def test_v3_report_reads_without_changing_the_raw_file(self):
        before = hashlib.sha256(RAW.read_bytes()).hexdigest()
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(V3.glob("*.json"))
        ]
        texts = {}
        for line in CHUNKS.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            texts[row["chunk_id"]] = row["text"]
        payload = quality_payload(records, texts)
        self.assertEqual(hashlib.sha256(RAW.read_bytes()).hexdigest(), before)
        self.assertEqual(before, RAW_SHA)
        self.assertEqual(payload["processed"], 10)
        self.assertEqual(payload["ok"], 7)
        self.assertEqual(payload["error"], 3)
        self.assertGreater(payload["empty_ok"], 0)
        self.assertGreater(
            payload["before"]["nodes"], payload["after"]["nodes"])
        self.assertEqual(payload["highest_degree"]["degree"], 1)
        self.assertGreater(len(payload["highest_degree"]["entity_keys"]), 1)
        self.assertEqual(payload["alias_map"], {})
        self.assertEqual(payload["outside_schema"], {})
        self.assertTrue(payload["rejected"][0]["quote"])
        self.assertNotIn("MENTIONS", payload["relationship_types"])
        markdown = render_markdown(payload, title="pilot")
        self.assertIn("nem hibás extrakció", markdown)
        self.assertIn("strukturális", markdown.lower())


if __name__ == "__main__":
    unittest.main()
