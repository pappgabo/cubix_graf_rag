"""Selection and overwrite checks for the pilot export. Stdlib unittest only."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from langchain_core.documents import Document

from naive_rag.pilot import CONTENT_DOCS, PilotSelectionError, select_pilot, write_pilot


def _chunk(doc_id: str, ordinal: int, text: str, chunk_id: str | None = None) -> Document:
    return Document(
        page_content=text,
        metadata={
            "doc_id": doc_id,
            "ordinal": ordinal,
            "chunk_id": chunk_id or f"{doc_id}#{ordinal}",
            "file": f"{doc_id}.txt",
            "format": "txt",
            "source": f"https://example.test/{doc_id}",
        },
    )


def _words(n: int) -> str:
    return " ".join(f"w{i}" for i in range(n))


def _corpus() -> list[Document]:
    chunks: list[Document] = []
    for doc_id in CONTENT_DOCS:
        chunks.append(_chunk(doc_id, 2, _words(40)))
        chunks.append(_chunk(doc_id, 0, "## Cím"))
        chunks.append(_chunk(doc_id, 1, _words(50)))
        chunks.append(_chunk(doc_id, 3, "12345 ---"))
    chunks.append(_chunk("driver-nico-rosberg", 64, "123 --- 99",
                         "driver-nico-rosberg#64"))
    chunks.append(_chunk("driver-sebastian-vettel", 75, "## Csak címsor",
                         "driver-sebastian-vettel#75"))
    return chunks


class SelectPilotTest(unittest.TestCase):
    def test_deterministic_eight_plus_two(self) -> None:
        first = select_pilot(_corpus())
        second = select_pilot(list(reversed(_corpus())))
        ids = [row["chunk_id"] for row in first]
        self.assertEqual(ids, [row["chunk_id"] for row in second])
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)
        self.assertEqual(
            [row["selection_reason"] for row in first],
            ["content_sample"] * 8 + ["no_letters", "heading_only"])
        self.assertEqual(ids[0], "driver-lewis-hamilton#1")
        self.assertEqual(ids[1], "driver-lewis-hamilton#2")
        self.assertEqual(ids[-2:], [
            "driver-nico-rosberg#64", "driver-sebastian-vettel#75"])

    def test_missing_document(self) -> None:
        chunks = [c for c in _corpus()
                  if c.metadata["doc_id"] != "team-scuderia-ferrari"]
        with self.assertRaises(PilotSelectionError) as caught:
            select_pilot(chunks)
        self.assertIn("team-scuderia-ferrari", str(caught.exception))

    def test_not_enough_content(self) -> None:
        chunks = [c for c in _corpus()
                  if c.metadata["chunk_id"] != "team-scuderia-ferrari#2"]
        with self.assertRaises(PilotSelectionError) as caught:
            select_pilot(chunks)
        self.assertIn("need 2", str(caught.exception))

    def test_missing_problem_chunk(self) -> None:
        chunks = [c for c in _corpus()
                  if c.metadata["chunk_id"] != "driver-nico-rosberg#64"]
        with self.assertRaises(PilotSelectionError) as caught:
            select_pilot(chunks)
        self.assertIn("driver-nico-rosberg#64", str(caught.exception))

    def test_changed_problem_category(self) -> None:
        chunks = _corpus()
        for chunk in chunks:
            if chunk.metadata["chunk_id"] == "driver-sebastian-vettel#75":
                chunk.page_content = _words(40)
        with self.assertRaises(PilotSelectionError) as caught:
            select_pilot(chunks)
        self.assertIn("expected heading_only", str(caught.exception))
        self.assertIn("other", str(caught.exception))


class WritePilotTest(unittest.TestCase):
    def test_refuses_existing_without_overwrite(self) -> None:
        rows = select_pilot(_corpus())
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_pilot(rows, directory, overwrite=False)
            original = (directory / "chunks.jsonl").read_text(encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_pilot(rows, directory, overwrite=False)
            self.assertEqual(
                (directory / "chunks.jsonl").read_text(encoding="utf-8"), original)
            write_pilot(rows, directory, overwrite=True)
            self.assertIn("driver-lewis-hamilton#1",
                          (directory / "chunks.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
