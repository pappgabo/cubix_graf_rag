"""Offline checks for the explicit J3 naive prompt. No model or database."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "diagnostics" / "2026-11-10-phase5-run"))

from naive_rag.rag import (  # noqa: E402
    BASELINE_SYSTEM, HUMAN_TEMPLATE, J3_RULE, PROMPT, format_context, prompt_for,
)

BASELINE_BEFORE = (
    "You are a question answering assistant. Answer the question using ONLY "
    "the context below. Each context passage starts with a tag like [S1]. "
    "Cite the passages you used in the answer, e.g. [S1][S3]. "
    "If the context does not contain the answer, say that you cannot "
    "answer from the provided documents."
)
SOURCES = [
    {"tag": "S1", "file": "a", "location": "n/a", "text": "alpha fragment"},
    {"tag": "S2", "file": "b", "location": "page 1", "text": "beta continues"},
]


def _system(variant: str) -> str:
    return prompt_for(variant).format_messages(
        context="CTX", question="Q?")[0].content


class J3PromptTests(unittest.TestCase):
    def test_baseline_text_is_unchanged_and_default(self):
        self.assertEqual(BASELINE_SYSTEM, BASELINE_BEFORE)
        self.assertEqual(PROMPT.messages[0].prompt.template, BASELINE_BEFORE)
        self.assertEqual(PROMPT.messages[1].prompt.template, HUMAN_TEMPLATE)
        self.assertIs(prompt_for(), PROMPT)
        self.assertIs(prompt_for("baseline"), PROMPT)
        self.assertEqual(_system("baseline"), BASELINE_BEFORE)

    def test_j3_adds_only_the_stated_rule(self):
        system = _system("j3")
        self.assertEqual(system, BASELINE_BEFORE + " " + J3_RULE)
        extra = system[len(BASELINE_BEFORE):]
        self.assertEqual(extra, " " + J3_RULE)
        for banned in ("Q07", "Kimi", "Hamilton", "Alonso", "Rosberg", "Räikkönen"):
            self.assertNotIn(banned, extra)
        self.assertNotRegex(extra, r"\d")
        self.assertEqual(
            prompt_for("j3").messages[1].prompt.template, HUMAN_TEMPLATE)

    def test_unknown_variant_errors(self):
        with self.assertRaises(ValueError):
            prompt_for("j2")
        with self.assertRaises(ValueError):
            prompt_for("J3")

    def test_same_input_differs_only_by_the_rule_and_context_order_stays(self):
        import run_phase5 as phase5

        context = format_context(SOURCES)
        again = format_context(list(SOURCES))
        self.assertEqual(context, again)
        self.assertLess(context.find("alpha fragment"), context.find("beta continues"))
        seen = []

        class Embed:
            def __init__(self):
                self.embeddings = SimpleNamespace(create=self._create)

            def _create(self, model, input):
                return SimpleNamespace(
                    data=[SimpleNamespace(embedding=[0.1])],
                    usage=SimpleNamespace(total_tokens=4),
                )

        class Chat:
            def invoke(self, messages):
                seen.append([message.content for message in messages])
                return SimpleNamespace(
                    content="ok",
                    response_metadata={
                        "model_name": "fake", "finish_reason": "stop",
                        "token_usage": {"prompt_tokens": 2, "completion_tokens": 1},
                    },
                )

        def search(_vector):
            return [
                (SimpleNamespace(page_content=row["text"], metadata={"file": row["file"]}), 0.5)
                for row in SOURCES
            ]

        calls = {"embed": 0}

        class CountingEmbed(Embed):
            def _create(self, model, input):
                calls["embed"] += 1
                return super()._create(model, input)

        with tempfile.TemporaryDirectory() as tmp:
            phase5.LOG_DIR = Path(tmp)
            budget = phase5.Budget(cap_usd=0.15)
            ledger = phase5.Ledger(run_id="j3-offline", path=Path(tmp) / "ledger.json")
            with self.assertRaises(ValueError):
                phase5.run_naiv(
                    "T", "Question?", budget, ledger,
                    openai_client=CountingEmbed(), chat_client=Chat(), search_fn=search,
                    prompt_variant="nope",
                )
            self.assertEqual(calls["embed"], 0)
            for variant in (None, "j3"):
                kwargs = {} if variant is None else {"prompt_variant": variant}
                phase5.run_naiv(
                    "T", "Question?", budget, ledger,
                    openai_client=Embed(), chat_client=Chat(), search_fn=search,
                    **kwargs,
                )
        self.assertEqual(seen[0][1], seen[1][1])
        self.assertIn("alpha fragment", seen[0][1])
        self.assertLess(seen[0][1].find("alpha fragment"), seen[0][1].find("beta continues"))
        self.assertEqual(seen[0][0], BASELINE_BEFORE)
        self.assertEqual(seen[1][0], BASELINE_BEFORE + " " + J3_RULE)


class MeasuredPathTests(unittest.TestCase):
    def test_pair_generator_selects_baseline_or_j3_on_the_same_path(self):
        import json
        from unittest import mock

        sys.path.insert(0, str(ROOT / "diagnostics" / "2026-11-21-week78-j2-naive-measure"))
        import run_phase5 as phase5
        import j2_naive_measure as j2

        previous_log = phase5.LOG_DIR
        seen = []

        class Chat:
            model_name = "gpt-4o-mini"
            temperature = 0
            max_tokens = 900
            max_retries = 0

            def invoke(self, messages):
                seen.append([(message.type, message.content) for message in messages])
                return SimpleNamespace(
                    content="ok",
                    response_metadata={
                        "model_name": "fake", "finish_reason": "stop",
                        "token_usage": {"prompt_tokens": 2, "completion_tokens": 1},
                    },
                )

        def query_points(_vector, limit):
            self.assertEqual(limit, 4)
            return [
                SimpleNamespace(payload={"text": "alpha fragment", "chunk_id": "c0", "file": "a"}, score=0.5),
                SimpleNamespace(payload={"text": "beta continues", "chunk_id": "c1", "file": "b"}, score=0.4),
            ]

        question = SimpleNamespace(id="T", question="Question?")
        embeds = {"n": 0}

        def embed(*_args, **_kwargs):
            embeds["n"] += 1
            return [[0.1]]

        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                phase5.LOG_DIR = root
                budget = phase5.Budget(cap_usd=0.15)
                ledger = phase5.Ledger(run_id="measured", path=root / "ledger.json")
                with mock.patch.object(phase5, "embed_texts", embed):
                    bad = j2.build_j2_naiv_fn(
                        budget, ledger, "offline", log_dir=root, query_points=query_points,
                        j2_enabled=False, prompt_variant="nope",
                    )
                    with self.assertRaises(ValueError):
                        bad(question)
                    self.assertEqual(embeds["n"], 0)
                    self.assertEqual(j2.build_j2_naiv_fn.__kwdefaults__["prompt_variant"], "baseline")
                    self.assertEqual(j2.run_pair.__kwdefaults__["prompt_variant"], "baseline")
                    records = []
                    logs = []
                    calls = (
                        {},
                        {"prompt_variant": "baseline"},
                        {"prompt_variant": "j3"},
                    )
                    for extra in calls:
                        fn = j2.build_j2_naiv_fn(
                            budget, ledger, "offline", log_dir=root, query_points=query_points,
                            j2_enabled=False, **extra,
                        )
                        with mock.patch("naive_rag.models.get_chat_model", return_value=Chat()):
                            records.append(fn(question))
                        logs.append(json.loads((root / "naive-log-naiv-T.json").read_text(encoding="utf-8")))
                self.assertEqual(records[0]["actual_context"], records[1]["actual_context"])
                self.assertEqual(records[1]["actual_context"], records[2]["actual_context"])
                self.assertIn("alpha fragment", records[0]["actual_context"])
                self.assertLess(
                    records[0]["actual_context"].find("alpha fragment"),
                    records[0]["actual_context"].find("beta continues"),
                )
                self.assertEqual(seen[0], seen[1])
                self.assertEqual(seen[0][1], seen[2][1])
                self.assertEqual(seen[0][0], ("system", BASELINE_BEFORE))
                self.assertEqual(seen[2][0], ("system", BASELINE_BEFORE + " " + J3_RULE))
                self.assertEqual(logs[0]["params"], logs[2]["params"])
                self.assertEqual(logs[1]["messages"][1], logs[2]["messages"][1])
                self.assertEqual(logs[0]["messages"][0]["content"], BASELINE_BEFORE)
                self.assertEqual(logs[2]["messages"][0]["content"], BASELINE_BEFORE + " " + J3_RULE)
        finally:
            phase5.LOG_DIR = previous_log


class SavedContextReplayTests(unittest.TestCase):
    def test_measurement_path_replays_context_without_embed_or_retrieval(self):
        import json
        from unittest import mock

        sys.path.insert(0, str(ROOT / "diagnostics" / "2026-11-21-week78-j2-naive-measure"))
        import run_phase5 as phase5
        import j2_naive_measure as j2

        saved = "  alpha fragment\n\nbeta continues  "
        previous_log = phase5.LOG_DIR
        seen = []
        calls = {"embed": 0, "query": 0}

        class Chat:
            model_name = "gpt-4o-mini"
            temperature = 0
            max_tokens = 900
            max_retries = 0

            def invoke(self, messages):
                seen.append([(message.type, message.content) for message in messages])
                return SimpleNamespace(
                    content="ok",
                    response_metadata={
                        "model_name": "fake", "finish_reason": "stop",
                        "token_usage": {"prompt_tokens": 2, "completion_tokens": 1},
                    },
                )

        def query_points(_vector, limit):
            calls["query"] += 1
            self.assertEqual(limit, 4)
            return [
                SimpleNamespace(payload={"text": "alpha fragment", "chunk_id": "c0", "file": "a"}, score=0.5),
                SimpleNamespace(payload={"text": "beta continues", "chunk_id": "c1", "file": "b"}, score=0.4),
            ]

        def embed(*_args, **_kwargs):
            calls["embed"] += 1
            return [[0.1]]

        question = SimpleNamespace(id="T", question="Question?")
        expected = format_context([
            {"tag": "S1", "file": "a", "location": "n/a", "text": "alpha fragment"},
            {"tag": "S2", "file": "b", "location": "n/a", "text": "beta continues"},
        ])

        def run(override, prompt=None):
            extra = {} if prompt is None else {"prompt_variant": prompt}
            fn = j2.build_j2_naiv_fn(
                budget, ledger, "offline", log_dir=root, query_points=query_points,
                j2_enabled=False, actual_context_override=override, **extra,
            )
            with mock.patch("naive_rag.models.get_chat_model", return_value=Chat()):
                record = fn(question)
            log = json.loads((root / "naive-log-naiv-T.json").read_text(encoding="utf-8"))
            return record, log

        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                phase5.LOG_DIR = root
                budget = phase5.Budget(cap_usd=0.15)
                ledger = phase5.Ledger(run_id="replay", path=root / "ledger.json")
                with mock.patch.object(phase5, "embed_texts", embed):
                    self.assertIsNone(j2.run_pair.__kwdefaults__["actual_context_override"])
                    self.assertEqual(j2.build_j2_naiv_fn.__kwdefaults__["prompt_variant"], "baseline")
                    normal, _log_n = run(None)
                    after_normal = dict(calls)
                    replay, log_b = run(saved, "baseline")
                    after_replay = dict(calls)
                    default_prompt, _log_d = run(saved)
                    empty, _log_e = run("", "j3")
                    _replay_j3, log_j = run(saved, "j3")
        finally:
            phase5.LOG_DIR = previous_log

        self.assertEqual(after_normal, {"embed": 1, "query": 1})
        self.assertEqual(normal["actual_context"], expected)
        self.assertNotIn("context_source", normal)
        self.assertLess(
            normal["actual_context"].find("alpha fragment"),
            normal["actual_context"].find("beta continues"),
        )
        self.assertEqual(after_replay, after_normal)
        self.assertEqual(replay["actual_context"], saved)
        self.assertEqual(replay["context_source"], "saved_context_replay")
        self.assertEqual(empty["actual_context"], "")
        self.assertEqual(empty["context_source"], "saved_context_replay")
        self.assertEqual(default_prompt["actual_context"], saved)
        self.assertEqual(default_prompt["context_source"], "saved_context_replay")
        self.assertEqual(calls, {"embed": 1, "query": 1})
        self.assertEqual(seen[2][0], ("system", BASELINE_BEFORE))
        self.assertEqual(seen[1][1], seen[4][1])
        tail = "\n\nQuestion: Question?"
        self.assertTrue(seen[1][1][1].endswith(tail))
        self.assertEqual(seen[1][1][1][: -len(tail)], "Context:\n" + saved)
        self.assertEqual(seen[1][0], ("system", BASELINE_BEFORE))
        self.assertEqual(seen[4][0], ("system", BASELINE_BEFORE + " " + J3_RULE))
        self.assertEqual(log_b["params"], log_j["params"])
        self.assertEqual(log_b["messages"][1], log_j["messages"][1])


if __name__ == "__main__":
    unittest.main()
