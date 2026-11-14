"""Week 5 / A2: keyword-only chunk-candidate survey and a fixed random
sample, both over the existing Section-1200-23 chunk file. Standard
library only -- no search system, no embeddings, no LLM call, no network.

Two subcommands:

``search``
    For every question in the week5 golden-set draft, scores every chunk
    by how many of the question's own criteria terms it contains and
    writes the top-scoring chunks as *candidates* (never as gold). A
    question with no criteria (Q13 in the v1 draft) falls back to terms
    taken from the question text itself, which is marked in the output.

``sample``
    Picks ten distinct documents and one chunk from each, with
    ``random.Random(42)`` so the pick is exactly reproducible, and writes
    the full chunk (every stored field) for manual inspection.

Both outputs carry the corpus file's own sha256 and the seed used, so a
later run can be checked against the same corpus snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
# .../naive-rag-baseline/diagnostics/2026-11-11-week5-a2 -> .../naive-rag-baseline
PROJECT_ROOT = HERE.parents[1]

DEFAULT_CHUNKS_PATH = PROJECT_ROOT / "graph" / "corpus" / "chunks-section-1200-23" / "chunks.jsonl"
DEFAULT_GOLDEN_PATH = PROJECT_ROOT / "golden" / "week5-golden-set-v1-draft.jsonl"

SEED = 42
SAMPLE_SIZE = 10
SEARCH_CANDIDATES_PER_QUESTION = 5
SNIPPET_WINDOW_CHARS = 160

_STOP = frozenset({
    "a", "an", "the", "of", "at", "his", "her", "their", "that", "this",
    "for", "and", "with", "from", "who", "what", "when", "where", "which",
    "whom", "whose", "was", "were", "has", "have", "had", "how", "many",
    "does", "did", "its", "him", "she", "he", "they", "them", "not", "but",
    "or", "as", "to", "in", "on", "by", "be", "is", "are", "it", "did",
})

_WORD = re.compile(r"[a-z0-9]+")


class SurveyError(ValueError):
    """The chunk file or the golden-set draft is not in the expected shape."""


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_chunks(path: Path) -> list[dict[str, Any]]:
    """One row per JSONL line, in file order. Raises on a row missing the
    fields this script actually reads (chunk_id, doc_id, text)."""
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            for field in ("chunk_id", "doc_id", "text"):
                if field not in row:
                    raise SurveyError(f"{path}:{line_number}: missing {field!r}")
            rows.append(row)
    if not rows:
        raise SurveyError(f"{path}: no chunk rows found")
    return rows


def load_questions(path: Path) -> list[dict[str, Any]]:
    """One row per JSONL line of the golden-set draft, in file order."""
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "id" not in row or "question" not in row:
                raise SurveyError(f"{path}:{line_number}: missing 'id' or 'question'")
            rows.append(row)
    if not rows:
        raise SurveyError(f"{path}: no question rows found")
    return rows


def corpus_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# search: keyword candidates per question
# --------------------------------------------------------------------------


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.casefold()))


def question_terms(question: dict[str, Any]) -> tuple[list[str], str]:
    """Terms to search for, plus where they came from.

    Primary source is ``criteria[].expected_content`` (the fields the
    golden-set draft itself proposes as evidence words). A question with
    no criteria (the v1 draft leaves Q13's rubric empty on purpose) falls
    back to the question text's own non-stopword terms, and the source
    string says so explicitly.
    """
    terms: list[str] = []
    for criterion in question.get("criteria") or []:
        for phrase in criterion.get("expected_content") or []:
            for word in _WORD.findall(str(phrase).casefold()):
                if word in _STOP or (not word.isdigit() and len(word) < 3):
                    continue
                if word not in terms:
                    terms.append(word)
    if terms:
        return terms, "criteria.expected_content"
    for word in _WORD.findall(str(question.get("question", "")).casefold()):
        if word in _STOP or (not word.isdigit() and len(word) < 3):
            continue
        if word not in terms:
            terms.append(word)
    return terms, "question_text_fallback (criteria empty in v1-draft)"


def score_chunk(chunk_words: set[str], terms: list[str]) -> int:
    return sum(1 for term in terms if term in chunk_words)


def make_snippet(text: str, terms: list[str], window: int = SNIPPET_WINDOW_CHARS) -> str:
    """Context around the first matching term; the whole text if it is
    already short enough, or the start of the text if no term is found as
    a literal substring (case-insensitive) -- still a usable preview."""
    if len(text) <= window * 2:
        return text
    folded = text.casefold()
    position = -1
    for term in terms:
        position = folded.find(term)
        if position != -1:
            break
    if position == -1:
        return text[: window * 2] + " [...]"
    start = max(0, position - window)
    end = min(len(text), position + window)
    prefix = "[...] " if start > 0 else ""
    suffix = " [...]" if end < len(text) else ""
    return prefix + text[start:end] + suffix


def search_candidates(
    questions: list[dict[str, Any]], chunks: list[dict[str, Any]], *,
    top_n: int = SEARCH_CANDIDATES_PER_QUESTION,
) -> list[dict[str, Any]]:
    """Per-question top-N chunk candidates, highest score first, ties
    broken by chunk order in the source file (stable sort). Candidates
    only -- not a verified or gold chunk list."""
    indexed = [(chunk, _words(str(chunk.get("text", "")))) for chunk in chunks]
    results: list[dict[str, Any]] = []
    for question in questions:
        terms, term_source = question_terms(question)
        scored = [
            (score_chunk(words, terms), chunk)
            for chunk, words in indexed
        ]
        scored = [(score, chunk) for score, chunk in scored if score > 0]
        scored.sort(key=lambda pair: -pair[0])
        top = scored[:top_n]
        results.append({
            "question_id": question["id"],
            "question": question["question"],
            "term_source": term_source,
            "terms": terms,
            "candidate_count_found": len(scored),
            "candidates_returned": len(top),
            "candidates": [
                {
                    "doc_id": chunk["doc_id"],
                    "chunk_id": chunk["chunk_id"],
                    "score": score,
                    "snippet": make_snippet(str(chunk.get("text", "")), terms),
                }
                for score, chunk in top
            ],
            "note": "keyword candidates only, not gold chunk ids",
        })
    return results


# --------------------------------------------------------------------------
# sample: ten documents, one chunk each, seed=42
# --------------------------------------------------------------------------


def sample_one_chunk_per_doc(
    chunks: list[dict[str, Any]], *, seed: int = SEED, sample_size: int = SAMPLE_SIZE,
) -> list[dict[str, Any]]:
    """Ten distinct documents (sorted doc_id universe, so the input order
    of the JSONL file does not bias the draw), one chunk per chosen
    document. Both the document draw and the per-document chunk draw use
    the same ``random.Random(seed)`` sequence, so the whole sample is
    reproducible end to end from the seed alone."""
    rng = random.Random(seed)
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk["doc_id"], []).append(chunk)
    doc_ids = sorted(by_doc)
    if len(doc_ids) < sample_size:
        raise SurveyError(
            f"only {len(doc_ids)} distinct documents available, need {sample_size}")
    chosen_docs = rng.sample(doc_ids, sample_size)
    sample: list[dict[str, Any]] = []
    for doc_id in chosen_docs:
        doc_chunks = sorted(by_doc[doc_id], key=lambda c: c.get("ordinal", 0))
        chunk = rng.choice(doc_chunks)
        sample.append(dict(chunk))
    return sample


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_search(args: argparse.Namespace) -> int:
    chunks = load_chunks(args.chunks)
    questions = load_questions(args.golden)
    candidates = search_candidates(questions, chunks, top_n=args.top_n)
    payload = {
        "corpus_file": str(args.chunks),
        "corpus_sha256": corpus_sha256(args.chunks),
        "chunk_count": len(chunks),
        "golden_file": str(args.golden),
        "question_count": len(questions),
        "candidates_per_question": args.top_n,
        "method": "keyword substring match on question criteria terms; "
                  "no embeddings, no search system, no LLM",
        "questions": candidates,
    }
    _write_json(args.out, payload)
    print(f"questions processed: {len(questions)}")
    print(f"wrote {args.out}")
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    chunks = load_chunks(args.chunks)
    sample = sample_one_chunk_per_doc(chunks, seed=args.seed, sample_size=args.size)
    payload = {
        "corpus_file": str(args.chunks),
        "corpus_sha256": corpus_sha256(args.chunks),
        "chunk_count": len(chunks),
        "seed": args.seed,
        "sample_size": args.size,
        "method": "random.Random(seed).sample() over sorted doc_ids, then "
                  "random.Random(seed).choice() per document; no new "
                  "questions are written from this sample",
        "sample": sample,
    }
    _write_json(args.out, payload)
    print(f"documents sampled: {len(sample)}")
    print(f"wrote {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="survey_candidates.py",
        description="Week 5 A2: keyword chunk-candidate search and a fixed "
                     "random sample over the Section-1200-23 corpus.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    search_p = sub.add_parser("search", help="keyword chunk candidates per golden-set question")
    search_p.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    search_p.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN_PATH)
    search_p.add_argument("--out", type=Path, required=True)
    search_p.add_argument("--top-n", type=int, default=SEARCH_CANDIDATES_PER_QUESTION)
    search_p.set_defaults(func=cmd_search)

    sample_p = sub.add_parser("sample", help="ten documents, one chunk each, seed=42")
    sample_p.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    sample_p.add_argument("--out", type=Path, required=True)
    sample_p.add_argument("--seed", type=int, default=SEED)
    sample_p.add_argument("--size", type=int, default=SAMPLE_SIZE)
    sample_p.set_defaults(func=cmd_sample)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
