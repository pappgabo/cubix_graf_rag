"""Context-window checks. No model call and no database."""

from __future__ import annotations

import unittest

from naive_rag.entity_index import index_text
from naive_rag.local_search import (
    TOKEN_ESTIMATE,
    ContextBudgetError,
    answer_prompt,
    cited_chunks,
    context_text,
    estimate_tokens,
    fit_context,
    validate_context_budget,
)
from naive_rag.neo4j_entity_index import text_hash
from naive_rag.neo4j_local_search import (
    CHUNK_TEXT_QUERY,
    MENTIONS_QUERY,
    NEIGHBORHOOD_QUERY,
    neo4j_local_search,
)

MODEL = "text-embedding-3-small"
HAMILTON = "Driver:lewis hamilton"
FERRARI = "Team:scuderia ferrari"


def _budget(window: int, reserve: int = 32, share: float = 0.5) -> dict:
    return {
        "model_window": window,
        "answer_reserve": reserve,
        "graph_share": share,
    }


def _node(key: str, name: str, description: str = "", chunks: list[str] | None = None):
    return {
        "entity_key": key,
        "entity_type": "Driver" if key.startswith("Driver:") else "Team",
        "name": name,
        "description": description,
        "source_chunk_ids": list(chunks or []),
    }


def _edge(source: str, target: str, chunks: list[str], description: str = "Drove."):
    return {
        "rel_type": "DROVE_FOR",
        "rel_key": f"{source}|{target}",
        "source_key": source,
        "target_key": target,
        "from_year": 2013,
        "to_year": None,
        "description": description,
        "source_chunk_ids": list(chunks),
    }


def _source(chunk_id: str, text: str, score: int) -> dict:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "text_found": True,
        "score": score,
    }


class ContextBudgetTests(unittest.TestCase):
    def test_comfortable_budget_keeps_graph_text_and_exact_excerpt(self):
        excerpt = "Hamilton drove for Ferrari from 2013."
        payload = {
            "nodes": [_node(HAMILTON, "Lewis Hamilton", "A British driver.", ["a#0"])],
            "edges": [_edge(HAMILTON, FERRARI, ["a#0"])],
            "sources": [_source("a#0", excerpt, 3)],
        }
        fitted, report = fit_context("Who?", payload, _budget(8192, 1024, 0.5))
        prompt = answer_prompt("Who?", context_text(fitted))
        self.assertIn("leírás: A British driver.", prompt)
        self.assertIn("leírás: Drove.", prompt)
        self.assertIn("from_year: 2013", prompt)
        self.assertIn(f"[a#0] {excerpt}", prompt)
        self.assertLessEqual(report["prompt_estimate"], report["input_budget"])
        self.assertEqual(report["measurement"], TOKEN_ESTIMATE)
        self.assertEqual(report["omitted_for_budget"], 0)
        self.assertEqual(estimate_tokens(prompt), report["prompt_estimate"])

    def test_narrow_budget_keeps_the_higher_scoring_chunk(self):
        weak = "x" * 40 + " ferrari"
        strong = "y" * 40 + " ferrari"
        self.assertEqual(len(weak), len(strong))
        both = {
            "nodes": [],
            "edges": [],
            "sources": [
                _source("weak#0", weak, 1),
                _source("strong#0", strong, 9),
            ],
        }
        one = {
            "nodes": [],
            "edges": [],
            "sources": [_source("strong#0", strong, 9)],
        }
        reserve = 16
        window = estimate_tokens(answer_prompt("ferrari", context_text(one))) + reserve
        first, first_report = fit_context("ferrari", both, _budget(window, reserve, 0.0))
        second, _second_report = fit_context("ferrari", both, _budget(window, reserve, 0.0))
        self.assertEqual(
            [item["chunk_id"] for item in first["sources"]],
            [item["chunk_id"] for item in second["sources"]],
        )
        self.assertEqual([item["chunk_id"] for item in first["sources"]], ["strong#0"])
        self.assertGreater(first_report["omitted_for_budget"], 0)
        self.assertNotIn(weak, answer_prompt("ferrari", context_text(first)))
        self.assertIn(strong, answer_prompt("ferrari", context_text(first)))

    def test_a_shared_chunk_is_included_once(self):
        text = "Shared source sentence."
        payload = {
            "nodes": [
                _node(HAMILTON, "Lewis Hamilton", "Driver.", ["same#0"]),
                _node(FERRARI, "Scuderia Ferrari", "Team.", ["same#0"]),
            ],
            "edges": [_edge(HAMILTON, FERRARI, ["same#0"])],
            "sources": [_source("same#0", text, 2)],
        }
        fitted, _report = fit_context("shared", payload, _budget(8192, 128, 0.5))
        prompt = answer_prompt("shared", context_text(fitted))
        self.assertEqual(prompt.count(f"[same#0] {text}"), 1)
        self.assertEqual(prompt.count("források: same#0"), 3)

    def test_first_entity_does_not_reserve_the_only_excerpt(self):
        nodes = (
            type("Node", (), {"name": "Alpha Driver", "source_chunk_ids": ("low#0",)})(),
            type("Node", (), {"name": "Beta Driver", "source_chunk_ids": ("high#0",)})(),
        )
        ranked = cited_chunks(
            (), nodes,
            {
                "low#0": "alpha note",
                "high#0": "beta ferrari championship",
            },
            "ferrari championship",
        )
        self.assertEqual(ranked[0]["chunk_id"], "high#0")
        self.assertEqual(ranked[0]["text"], "beta ferrari championship")

    def test_graph_descriptions_consume_the_budget(self):
        description = "D" * 300
        excerpt = "E" * 300
        payload = {
            "nodes": [_node(HAMILTON, "Lewis Hamilton", description, ["a#0"])],
            "edges": [],
            "sources": [_source("a#0", excerpt, 1)],
        }
        only_graph = {"nodes": payload["nodes"], "edges": [], "sources": []}
        reserve = 8
        window = estimate_tokens(
            answer_prompt("budget", context_text(only_graph))) + reserve
        fitted, report = fit_context(
            "budget", payload, _budget(window, reserve, 1.0))
        prompt = answer_prompt("budget", context_text(fitted))
        self.assertIn(description, prompt)
        self.assertNotIn(excerpt, prompt)
        self.assertGreater(report["omitted_sources"], 0)
        self.assertLessEqual(report["prompt_estimate"], report["input_budget"])

    def test_unused_graph_share_is_available_to_excerpts(self):
        excerpt = "Transferred excerpt. " * 40
        payload = {
            "nodes": [_node(HAMILTON, "Lewis Hamilton", "Short.", ["a#0"])],
            "edges": [],
            "sources": [_source("a#0", excerpt, 1)],
        }
        reserve = 8
        window = estimate_tokens(answer_prompt("move", context_text(payload))) + reserve
        fitted, _report = fit_context(
            "move", payload, _budget(window, reserve, 0.9))
        self.assertIn(excerpt, answer_prompt("move", context_text(fitted)))

    def test_oversized_block_is_omitted_without_cutting_text(self):
        huge = "H" * 5000
        small = "Small exact excerpt."
        payload = {
            "nodes": [_node(HAMILTON, "Lewis Hamilton", "", ["huge#0", "small#0"])],
            "edges": [],
            "sources": [
                _source("huge#0", huge, 5),
                _source("small#0", small, 1),
            ],
        }
        only_small = {
            "nodes": payload["nodes"],
            "edges": [],
            "sources": [_source("small#0", small, 1)],
        }
        reserve = 8
        window = estimate_tokens(
            answer_prompt("size", context_text(only_small))) + reserve
        fitted, report = fit_context(
            "size", payload, _budget(window, reserve, 0.0))
        prompt = answer_prompt("size", context_text(fitted))
        self.assertIn(small, prompt)
        self.assertNotIn(huge[:100], prompt)
        self.assertGreaterEqual(report["omitted_oversized"], 1)

    def test_missing_optional_fields_still_render(self):
        payload = {
            "nodes": [{
                "entity_key": HAMILTON,
                "name": "",
                "description": None,
                "source_chunk_ids": None,
            }],
            "edges": [{
                "rel_type": "DROVE_FOR",
                "source_key": HAMILTON,
                "target_key": FERRARI,
                "description": "",
                "from_year": None,
                "source_chunk_ids": [],
            }],
            "sources": [],
        }
        fitted, _report = fit_context("empty", payload, _budget(8192, 64, 0.5))
        text = context_text(fitted)
        self.assertIn(HAMILTON, text)
        self.assertNotIn("leírás:", text)
        self.assertIn("nincs kiválasztott forrásszöveg", text)

    def test_invalid_budgets_are_rejected(self):
        for window, reserve, share in (
            (0, 0, 0.5),
            (100, -1, 0.5),
            (100, 100, 0.5),
            (100, 10, 1.5),
            (True, 1, 0.5),
        ):
            with self.assertRaises(ContextBudgetError):
                validate_context_budget(window, reserve, share)
        with self.assertRaises(ContextBudgetError):
            fit_context("Q" * 5000, {"nodes": [], "edges": [], "sources": []},
                        _budget(40, 8, 0.5))

    def test_rendered_prompt_stays_inside_the_input_budget(self):
        payload = {
            "nodes": [
                _node(f"Driver:{index}", f"Driver {index}", "N" * 80, [f"c#{index}"])
                for index in range(6)
            ],
            "edges": [],
            "sources": [
                _source(f"c#{index}", "S" * 80, index) for index in range(6)
            ],
        }
        _fitted, report = fit_context("limit", payload, _budget(500, 40, 0.5))
        self.assertLessEqual(report["prompt_estimate"], report["input_budget"])
        self.assertLess(report["selected_nodes"] + report["selected_sources"], 12)

    def test_omitted_entity_name_stays_on_the_relationship(self):
        payload = {
            "nodes": [_node(
                HAMILTON, "Lewis Hamilton", "D" * 4000, ["a#0"])],
            "edges": [_edge(HAMILTON, FERRARI, ["a#0"], "Short link.")],
            "sources": [],
            "endpoint_names": {
                HAMILTON: "Lewis Hamilton",
                FERRARI: "Scuderia Ferrari",
            },
        }
        fitted, report = fit_context(
            "edge", payload, _budget(8192, 64, 0.5))
        prompt = answer_prompt("edge", context_text(fitted))
        self.assertIn(f"{HAMILTON} (Lewis Hamilton)", prompt)
        self.assertNotIn("D" * 100, prompt)
        self.assertIn("(+1 leírássor kimaradt)", prompt)
        self.assertEqual(report["omitted_oversized"], 0)
        self.assertLessEqual(report["prompt_estimate"], report["input_budget"])

    def test_neo4j_path_applies_the_budget_before_the_answer(self):
        excerpt = "Hamilton drove for Ferrari from 2013."
        extra = "Z" * 4000

        def query(cypher, params):
            if "queryNodes" in cypher:
                return [{
                    "entity_key": HAMILTON,
                    "name": "Lewis Hamilton",
                    "description": "A driver.",
                    "embedding_model": MODEL,
                    "embedding_dimensions": 3,
                    "embedding_text_sha256": text_hash(
                        index_text("Lewis Hamilton", "A driver.")),
                    "score": 0.4,
                }]
            if cypher == NEIGHBORHOOD_QUERY:
                return [{
                    "source_key": HAMILTON,
                    "source_label": "Driver",
                    "source_name": "Lewis Hamilton",
                    "source_description": "A driver.",
                    "target_key": FERRARI,
                    "target_label": "Team",
                    "target_name": "Scuderia Ferrari",
                    "target_description": "A team.",
                    "rel_type": "DROVE_FOR",
                    "rel_key": "drove",
                    "from_year": 2013,
                    "to_year": 2020,
                    "role": None,
                    "description": "Drove for Ferrari.",
                    "source_chunk_ids": ["short#0"],
                }]
            if cypher.startswith("MATCH (n:Extracted)"):
                return [
                    {"entity_key": HAMILTON, "label": "Driver",
                     "name": "Lewis Hamilton", "description": "A driver."},
                    {"entity_key": FERRARI, "label": "Team",
                     "name": "Scuderia Ferrari", "description": "A team."},
                ]
            if cypher == MENTIONS_QUERY:
                return [
                    {"entity_key": HAMILTON, "chunk_id": "short#0"},
                    {"entity_key": HAMILTON, "chunk_id": "long#0"},
                ]
            if cypher == CHUNK_TEXT_QUERY:
                return [
                    {"chunk_id": "short#0", "text": excerpt},
                    {"chunk_id": "long#0", "text": extra},
                ]
            raise AssertionError(cypher)

        prompts = []
        found = neo4j_local_search(
            "Which team did Lewis Hamilton drive for?",
            embed_query=lambda _question: [1.0, 0.0, 0.0],
            answer_fn=lambda prompt: prompts.append(prompt) or "mocked",
            query_fn=query,
            model=MODEL,
            budget=_budget(900, 64, 0.5),
        )
        self.assertEqual(prompts, [found.prompt])
        self.assertIn("Gráfállítások:", found.prompt)
        self.assertIn(excerpt, found.prompt)
        self.assertNotIn(extra[:80], found.prompt)
        self.assertLessEqual(
            found.context_budget["prompt_estimate"],
            found.context_budget["input_budget"])
        self.assertEqual(found.context_budget["answer_reserve"], 64)
        self.assertGreaterEqual(found.context_budget["omitted_oversized"], 1)

    def test_matching_description_lines_come_first(self):
        won = "Lewis Hamilton won the World Drivers' Championship title."
        placed = "Hamilton placed second in the World Drivers' Championship."
        other = "Lotus E20 raced in the 2012 season."
        payload = {
            "nodes": [_node(
                HAMILTON, "Lewis Hamilton",
                "\n".join((other, placed, won)),
                ["a#0"],
            )],
            "edges": [],
            "sources": [_source("a#0", "Hamilton won the title.", 1)],
        }
        fitted, report = fit_context(
            "How many World Drivers' Championship titles did Lewis Hamilton win?",
            payload, _budget(8192, 1024, 0.5) | {"description_lines": 2},
        )
        prompt = answer_prompt("titles", context_text(fitted))
        self.assertLess(prompt.index(won), prompt.index(placed))
        self.assertNotIn(other, prompt)
        self.assertIn("(+1 leírássor kimaradt)", prompt)
        self.assertLessEqual(report["prompt_estimate"], report["input_budget"])

    def test_a_line_over_the_character_limit_is_not_sliced(self):
        sentence = "Lewis Hamilton won the World Drivers' Championship title."
        payload = {
            "nodes": [_node(HAMILTON, "Lewis Hamilton", sentence, ["a#0"])],
            "edges": [],
            "sources": [],
        }
        fitted, _report = fit_context(
            "Lewis Hamilton", payload,
            _budget(8192, 64, 0.5) | {"description_chars": 40},
        )
        prompt = answer_prompt("Lewis Hamilton", context_text(fitted))
        self.assertNotIn(sentence, prompt)
        self.assertNotIn(sentence[:20], prompt)
        self.assertIn("(+1 leírássor kimaradt)", prompt)
        self.assertIn(HAMILTON, prompt)

    def test_unselected_chunk_ids_are_counted_not_listed(self):
        payload = {
            "nodes": [_node(
                HAMILTON, "Lewis Hamilton", "A British driver.",
                ["kept#0", "other#1", "other#2"],
            )],
            "edges": [],
            "sources": [_source("kept#0", "Hamilton won the title.", 1)],
        }
        fitted, _report = fit_context("Hamilton", payload, _budget(8192, 64, 0.5))
        prompt = answer_prompt("Hamilton", context_text(fitted))
        self.assertIn("források: kept#0, további 2", prompt)
        self.assertNotIn("other#1", prompt)
        self.assertNotIn("other#2", prompt)

    def test_a_long_description_is_not_an_oversized_block(self):
        line = "Lewis Hamilton won the World Drivers' Championship title."
        payload = {
            "nodes": [_node(
                HAMILTON, "Lewis Hamilton",
                "\n".join(f"{line} {index}" for index in range(212)),
                [f"driver-lewis-hamilton#{index}" for index in range(236)],
            )],
            "edges": [],
            "sources": [_source("driver-lewis-hamilton#0", line, 1)],
        }
        fitted, report = fit_context(
            "How many championships did Lewis Hamilton win?",
            payload, _budget(8192, 1024, 0.5),
        )
        prompt = answer_prompt("championships", context_text(fitted))
        self.assertEqual(report["oversized_nodes"], [])
        self.assertIn(HAMILTON, [node["entity_key"] for node in fitted["nodes"]])
        self.assertLessEqual(report["prompt_estimate"], report["input_budget"])
        self.assertNotIn("driver-lewis-hamilton#1", prompt)
        self.assertIn("források: driver-lewis-hamilton#0, további 235", prompt)
