"""Offline chunking checks. No corpus load, model, or database."""

from __future__ import annotations

import unittest

from langchain_core.documents import Document

from naive_rag.config import Settings
from naive_rag.ingest import (
    ChunkConfigError,
    attach_bare_headings,
    chunk_sources,
    split_by_headings,
    validate_chunk_config,
)


def _doc(text: str, doc_id: str = "d", fmt: str = "txt",
         page: int | None = None) -> Document:
    meta: dict = {"doc_id": doc_id, "format": fmt, "file": f"{doc_id}.txt",
                  "title": "Példa"}
    if page is not None:
        meta["page"] = page
    return Document(page_content=text, metadata=meta)


def _nonws(text: str) -> str:
    return "".join(text.split())


def _reconstruct(chunks: list[Document], overlap: int) -> str:
    parts: list[str] = []
    previous = ""
    for chunk in chunks:
        text = chunk.page_content
        shared = 0
        limit = min(len(previous), len(text), overlap)
        for size in range(limit, 0, -1):
            if previous[-size:] == text[:size]:
                shared = size
                break
        parts.append(text[shared:])
        previous = text
    return "".join(parts)


class ChunkConfigTests(unittest.TestCase):
    def test_defaults_are_explicit_characters(self) -> None:
        self.assertEqual(Settings.model_fields["chunk_size"].default, 1200)
        self.assertEqual(Settings.model_fields["chunk_overlap"].default, 100)

    def test_entry_point_uses_the_given_configuration(self) -> None:
        chunks = chunk_sources([_doc("Rövid mondat a konfigurációról.")], 80, 10)
        self.assertEqual(chunks[0].metadata["chunk_size"], 80)
        self.assertEqual(chunks[0].metadata["chunk_overlap"], 10)
        self.assertEqual(chunks[0].metadata["chunk_id"], "d#0")

    def test_invalid_configuration_is_rejected(self) -> None:
        for size, overlap in ((0, 0), (-1, 0), (10, 10), (10, 11), (10, -1),
                              (True, 0), (10, False)):
            with self.assertRaises(ChunkConfigError):
                validate_chunk_config(size, overlap)
            with self.assertRaises(ChunkConfigError):
                chunk_sources([_doc("Szöveg.")], size, overlap)
        with self.assertRaises(ValueError):
            Settings(chunk_size=10, chunk_overlap=10)


class ChunkSplitTests(unittest.TestCase):
    def test_empty_input(self) -> None:
        self.assertEqual(chunk_sources([], 1200, 100), [])
        self.assertEqual(chunk_sources([_doc("")], 1200, 100), [])
        self.assertEqual(chunk_sources([_doc("   \n")], 1200, 100), [])

    def test_short_text_stays_one_chunk(self) -> None:
        text = "Egy rövid mondat, amit nem kell vágni."
        chunks = chunk_sources([_doc(text)], 1200, 100)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].page_content, text)
        self.assertEqual(chunks[0].metadata["ordinal"], 0)

    def test_paragraphs_and_sections_keep_order(self) -> None:
        text = (
            "## Áttekintés\n\n"
            "Az első bekezdés együtt marad a címmel.\n\n"
            "A második bekezdés is ehhez a szakaszhoz tartozik.\n\n"
            "## Részletek\n\n"
            "A részlet külön szakasz, és a sorrend megmarad."
        )
        chunks = chunk_sources([_doc(text)], 1200, 50)
        self.assertGreaterEqual(len(chunks), 2)
        joined = "\n".join(chunk.page_content for chunk in chunks)
        self.assertIn("első bekezdés", joined)
        self.assertLess(joined.index("Áttekintés"), joined.index("Részletek"))
        self.assertLess(joined.index("Részletek"), joined.index("részlet külön"))
        self.assertEqual(
            [chunk.metadata["chunk_id"] for chunk in chunks],
            [f"d#{index}" for index in range(len(chunks))])
        self.assertEqual(_nonws(_reconstruct(chunks, 50)), _nonws(text))

    def test_bare_heading_stays_with_the_following_section(self) -> None:
        text = "## Karrier\n\n## 2016\n\nHamilton ebben az évben nyert."
        raw = split_by_headings([_doc(text)])
        self.assertTrue(any(
            part.page_content.strip() == "## Karrier" for part in raw))
        chunks = chunk_sources([_doc(text)], 1200, 20)
        self.assertEqual(len(chunks), 1)
        self.assertIn("## Karrier", chunks[0].page_content)
        self.assertIn("## 2016", chunks[0].page_content)
        self.assertIn("Hamilton ebben az évben nyert.", chunks[0].page_content)
        self.assertEqual(chunks[0].metadata["section"], "Karrier > 2016")

    def test_bare_heading_does_not_cross_a_page(self) -> None:
        docs = [
            _doc("# Csak cím", page=1),
            _doc("A következő oldal szövege.", page=2),
        ]
        attached = attach_bare_headings(docs)
        self.assertEqual(len(attached), 2)
        self.assertEqual(attached[0].page_content, "# Csak cím")
        self.assertNotIn("Csak cím", attached[1].page_content)

    def test_exact_boundary_and_oversized_unit(self) -> None:
        exact = "a" * 20
        self.assertEqual(
            [chunk.page_content for chunk in chunk_sources([_doc(exact)], 20, 0)],
            [exact])
        longer = "Á" * 25
        chunks = chunk_sources([_doc(longer)], 10, 2)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.page_content) <= 10 for chunk in chunks))
        self.assertEqual(_reconstruct(chunks, 2), longer)

    def test_overlap_zero_and_near_size(self) -> None:
        text = "aaaa bbbb cccc dddd eeee ffff gggg"
        zero = chunk_sources([_doc(text)], 12, 0)
        self.assertGreater(len(zero), 1)
        self.assertEqual(_nonws(_reconstruct(zero, 0)), _nonws(text))
        overlapped = chunk_sources([_doc(text)], 12, 11)
        self.assertGreater(len(overlapped), 1)
        self.assertEqual(_nonws(_reconstruct(overlapped, 11)), _nonws(text))

    def test_hungarian_text_is_not_split_inside_a_word(self) -> None:
        text = "Árvíztűrő tükörfúrógép és a következő mondat."
        chunks = chunk_sources([_doc(text)], 80, 10)
        self.assertEqual(chunks[0].page_content, text)
        self.assertIn("Árvíztűrő", chunks[0].page_content)

    def test_split_is_deterministic(self) -> None:
        text = "# Cím\n\n" + ("Mondat a dokumentumban. " * 40)
        first = chunk_sources([_doc(text)], 100, 15)
        second = chunk_sources([_doc(text)], 100, 15)
        self.assertEqual(
            [(chunk.metadata["chunk_id"], chunk.page_content) for chunk in first],
            [(chunk.metadata["chunk_id"], chunk.page_content) for chunk in second])
        self.assertEqual(_nonws(_reconstruct(first, 15)), _nonws(text))


if __name__ == "__main__":
    unittest.main()
