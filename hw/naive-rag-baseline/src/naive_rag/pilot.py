"""Export a fixed 10-chunk pilot sample. No extraction, no database.

    python -m naive_rag.pilot [--overwrite]

Uses `ingest.load_and_chunk(500, 75)` and writes `graph/pilot/chunks.jsonl`
and `graph/pilot/chunks.md` only after every selection check passes.
Existing outputs are kept unless `--overwrite` is given.

On a Windows path containing non-ASCII characters the editable install's
`.pth` entry may not load, so `python -m naive_rag.pilot` needs `src` on
`PYTHONPATH` (see the week-1 note in the README). This module does not
change the CLI.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from langchain_core.documents import Document

from .config import PROJECT_ROOT
from .ingest import load_and_chunk

# Same word count as graph_ingest._WORD (whitespace-separated tokens).
_WORD = re.compile(r"\S+")
# Same "heading only" test as graph/cypher/queries.cypher Q4:
# the whole trimmed text is a single Markdown heading line.
_HEADING_ONLY = re.compile(r"#{1,6} [^\n]*")

CHUNK_SIZE = 500
CHUNK_OVERLAP = 75

CONTENT_DOCS = (
    "driver-lewis-hamilton",
    "season-2021-formula-one-world-championship",
    "team-mercedes-benz-in-formula-one",
    "team-scuderia-ferrari",
)
# Recorded in graph/query-results.md. Not replaced if they no longer match.
PROBLEM_CHUNKS = (
    ("driver-nico-rosberg#64", "no_letters"),
    ("driver-sebastian-vettel#75", "heading_only"),
)

_FIELDS = (
    "chunk_id", "doc_id", "ordinal", "file", "format", "source",
    "page", "section", "n_chars", "n_words", "selection_reason", "text",
)


class PilotSelectionError(RuntimeError):
    """The fixed sample cannot be built. No output files are written."""


def n_words(text: str) -> int:
    return len(_WORD.findall(text))


def has_letter(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def is_heading_only(text: str) -> bool:
    return _HEADING_ONLY.fullmatch(text.strip()) is not None


def problem_category(text: str) -> str | None:
    """Q4 priority: no letters, then a heading-only line."""
    if not has_letter(text):
        return "no_letters"
    if is_heading_only(text):
        return "heading_only"
    return None


def is_content_chunk(text: str) -> bool:
    return n_words(text) >= 40 and has_letter(text) and not is_heading_only(text)


def _by_ordinal(chunks: list[Document]) -> list[Document]:
    return sorted(chunks, key=lambda c: (c.metadata.get("ordinal"),
                                         c.metadata.get("chunk_id", "")))


def _record(chunk: Document, reason: str) -> dict:
    meta = chunk.metadata
    text = chunk.page_content
    page = meta.get("page")
    section = meta.get("section")
    return {
        "chunk_id": meta["chunk_id"],
        "doc_id": meta.get("doc_id"),
        "ordinal": meta.get("ordinal"),
        "file": meta.get("file"),
        "format": meta.get("format"),
        "source": meta.get("source"),
        "page": page if page is not None else None,
        "section": section if section else None,
        "n_chars": len(text),
        "n_words": n_words(text),
        "selection_reason": reason,
        "text": text,
    }


def select_pilot(chunks: list[Document]) -> list[dict]:
    """Eight content chunks, then the two fixed problem chunks, in order."""
    by_doc: dict[str, list[Document]] = {}
    by_id: dict[str, list[Document]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.metadata.get("doc_id"), []).append(chunk)
        by_id.setdefault(chunk.metadata.get("chunk_id"), []).append(chunk)

    selected: list[dict] = []
    for doc_id in CONTENT_DOCS:
        group = by_doc.get(doc_id, [])
        if not group:
            raise PilotSelectionError(
                f"{doc_id}: document not in the chunked corpus. "
                "No pilot files written.")
        content = [c for c in _by_ordinal(group) if is_content_chunk(c.page_content)]
        if len(content) < 2:
            raise PilotSelectionError(
                f"{doc_id}: {len(content)} content chunk(s), need 2. "
                "No pilot files written.")
        selected.extend(_record(c, "content_sample") for c in content[:2])

    for chunk_id, expected in PROBLEM_CHUNKS:
        matches = by_id.get(chunk_id, [])
        if len(matches) != 1:
            raise PilotSelectionError(
                f"{chunk_id}: expected exactly one chunk, found {len(matches)}. "
                "No pilot files written.")
        text = matches[0].page_content
        actual = problem_category(text)
        if actual != expected:
            raise PilotSelectionError(
                f"{chunk_id}: expected {expected}, got {actual or 'other'}. "
                "No pilot files written.")
        selected.append(_record(matches[0], expected))

    ids = [row["chunk_id"] for row in selected]
    if len(ids) != 10 or len(set(ids)) != 10:
        raise PilotSelectionError(
            f"Expected 10 distinct chunk ids, got {ids}. "
            "No pilot files written.")
    return selected


def render_markdown(rows: list[dict]) -> str:
    lines = [
        "# Pilotminta",
        "",
        "500 karakter, 75 karakter overlap. Ellenőrizhető mintakimenet, "
        "nem minőségi elemzés.",
        "",
    ]
    for row in rows:
        lines += [
            f"## {row['chunk_id']}",
            "",
            f"- Kiválasztási ok: `{row['selection_reason']}`",
            f"- Dokumentum: `{row['doc_id']}`",
            f"- Fájl: `{row['file']}`",
            f"- Formátum: `{row['format']}`",
            f"- Forrás: {row['source']}",
            f"- Oldal: {row['page'] if row['page'] is not None else 'nincs'}",
            f"- Szekció: {row['section'] if row['section'] else 'nincs'}",
            f"- Karakter: {row['n_chars']}",
            f"- Szó: {row['n_words']}",
            "",
            row["text"].rstrip(),
            "",
        ]
    return "\n".join(lines)


def pilot_dir(root: Path | None = None) -> Path:
    return (root or PROJECT_ROOT) / "graph" / "pilot"


def write_pilot(rows: list[dict], directory: Path, *, overwrite: bool,
                ) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    jsonl_path = directory / "chunks.jsonl"
    md_path = directory / "chunks.md"
    existing = [path for path in (jsonl_path, md_path) if path.exists()]
    if existing and not overwrite:
        listed = ", ".join(str(path) for path in existing)
        raise FileExistsError(
            f"Refusing to overwrite {listed}. Re-run with --overwrite.")
    body = "".join(
        json.dumps({key: row[key] for key in _FIELDS}, ensure_ascii=False) + "\n"
        for row in rows)
    jsonl_path.write_text(body, encoding="utf-8")
    md_path.write_text(render_markdown(rows), encoding="utf-8")
    return jsonl_path, md_path


def _print_summary(rows: list[dict]) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["selection_reason"]] = counts.get(row["selection_reason"], 0) + 1
        print(f"{row['chunk_id']}  {row['selection_reason']}")
    for reason in ("content_sample", "no_letters", "heading_only"):
        print(f"{reason}: {counts.get(reason, 0)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m naive_rag.pilot")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace graph/pilot/chunks.jsonl and chunks.md")
    args = parser.parse_args(argv)
    directory = pilot_dir()
    existing = [path for path in (directory / "chunks.jsonl", directory / "chunks.md")
                if path.exists()]
    if existing and not args.overwrite:
        listed = ", ".join(str(path) for path in existing)
        print(f"error: Refusing to overwrite {listed}. Re-run with --overwrite.",
              file=sys.stderr)
        return 1
    print(f"chunk_size={CHUNK_SIZE} chunk_overlap={CHUNK_OVERLAP} (characters)")
    _, chunks = load_and_chunk(CHUNK_SIZE, CHUNK_OVERLAP)
    try:
        rows = select_pilot(chunks)
    except PilotSelectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        jsonl_path, md_path = write_pilot(rows, pilot_dir(), overwrite=args.overwrite)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_summary(rows)
    print(f"wrote {jsonl_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
