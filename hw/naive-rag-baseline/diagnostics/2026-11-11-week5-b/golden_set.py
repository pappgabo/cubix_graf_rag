"""Loader for the approved week5 golden set (v1-approval-draft, 15
questions). Standard library only.

The file lives outside this project directory (the HW handoff folder);
its path is a parameter, never hardcoded assumption about history.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class GoldenSetError(ValueError):
    """The golden-set file is not in the expected shape."""


@dataclass(frozen=True)
class Criterion:
    id: str
    text: str
    expected_content: tuple[str, ...]
    required: bool


@dataclass(frozen=True)
class EvidenceGroup:
    id: str
    criterion: str | None  # None for a retrieval_bridge group (Q05)
    any_of_chunk_ids: tuple[str, ...]
    role: str | None = None  # e.g. "retrieval_bridge"


@dataclass(frozen=True)
class GoldenQuestion:
    id: str
    type: str  # simple | multi-hop | global
    status: str  # frozen_w4 | held_out
    question: str
    expected_answer: str
    criteria: tuple[Criterion, ...]
    evidence_groups: tuple[EvidenceGroup, ...]
    gold_docs: tuple[str, ...]
    notes: str
    golden_set_version: str
    corpus_chunks_file: str
    corpus_chunks_sha256: str
    corpus_chunk_count: int

    def required_criteria(self) -> tuple[Criterion, ...]:
        return tuple(c for c in self.criteria if c.required)

    def optional_criteria(self) -> tuple[Criterion, ...]:
        return tuple(c for c in self.criteria if not c.required)

    def required_evidence_groups(self) -> tuple[EvidenceGroup, ...]:
        """Groups that count toward the mandatory retrieval denominator:
        groups tied to a required criterion, plus retrieval_bridge groups
        (criterion is None but the role marks them mandatory-for-retrieval,
        per golden/week5-golden-set-jovahagyas.md's Q05 bridge note)."""
        required_ids = {c.id for c in self.required_criteria()}
        result = []
        for group in self.evidence_groups:
            if group.role == "retrieval_bridge":
                result.append(group)
            elif group.criterion in required_ids:
                result.append(group)
        return tuple(result)


def _criterion_from_row(row: dict[str, Any]) -> Criterion:
    for field_name in ("id", "text", "required"):
        if field_name not in row:
            raise GoldenSetError(f"criterion missing {field_name!r}: {row}")
    return Criterion(
        id=row["id"],
        text=row["text"],
        expected_content=tuple(row.get("expected_content") or ()),
        required=bool(row["required"]),
    )


def _evidence_group_from_row(row: dict[str, Any]) -> EvidenceGroup:
    if "id" not in row or "any_of_chunk_ids" not in row:
        raise GoldenSetError(f"evidence_group missing id/any_of_chunk_ids: {row}")
    return EvidenceGroup(
        id=row["id"],
        criterion=row.get("criterion"),
        any_of_chunk_ids=tuple(row["any_of_chunk_ids"]),
        role=row.get("role"),
    )


def _question_from_row(row: dict[str, Any], line_number: int) -> GoldenQuestion:
    required_top = ("id", "type", "status", "question", "criteria", "evidence_groups", "corpus")
    for field_name in required_top:
        if field_name not in row:
            raise GoldenSetError(f"line {line_number}: missing {field_name!r}")
    corpus = row["corpus"]
    for field_name in ("chunks_file", "chunks_sha256", "chunk_count"):
        if field_name not in corpus or corpus[field_name] is None:
            raise GoldenSetError(
                f"line {line_number} ({row['id']}): corpus.{field_name} is "
                "missing or null -- this golden set is not measurement-ready")
    return GoldenQuestion(
        id=row["id"],
        type=row["type"],
        status=row["status"],
        question=row["question"],
        expected_answer=row.get("expected_answer", ""),
        criteria=tuple(_criterion_from_row(c) for c in row["criteria"]),
        evidence_groups=tuple(_evidence_group_from_row(g) for g in row["evidence_groups"]),
        gold_docs=tuple(row.get("gold_docs") or ()),
        notes=row.get("notes", ""),
        golden_set_version=row.get("golden_set_version", ""),
        corpus_chunks_file=corpus["chunks_file"],
        corpus_chunks_sha256=corpus["chunks_sha256"],
        corpus_chunk_count=corpus["chunk_count"],
    )


def load_golden_set(path: Path) -> tuple[GoldenQuestion, ...]:
    questions: list[GoldenQuestion] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            questions.append(_question_from_row(row, line_number))
    if not questions:
        raise GoldenSetError(f"{path}: no questions found")
    ids = [q.id for q in questions]
    if len(ids) != len(set(ids)):
        raise GoldenSetError(f"{path}: duplicate question ids: {ids}")
    return tuple(questions)


def golden_set_sha256(path: Path) -> str:
    """Hash of the golden-set FILE ITSELF (not the corpus) -- used, together
    with the run configuration, to decide whether a saved partial run can
    be resumed or must be treated as a different measurement."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_single_corpus_snapshot(questions: tuple[GoldenQuestion, ...]) -> str:
    """All questions must point at the same corpus file/hash/count. Returns
    that shared sha256. Raises if the golden set mixes corpus snapshots."""
    snapshots = {
        (q.corpus_chunks_file, q.corpus_chunks_sha256, q.corpus_chunk_count)
        for q in questions
    }
    if len(snapshots) != 1:
        raise GoldenSetError(f"golden set mixes corpus snapshots: {snapshots}")
    return next(iter(snapshots))[1]


# Same corpus snapshot. The golden set stores the historical Windows CRLF
# raw hash; the measurement gate compares LF-normalized bytes.
HISTORICAL_CRLF_CORPUS_SHA256 = "79d46d6291bc07924ddc13703f9b4804f8cf9c86de9de3ebaf435248f04e012e"
LF_NORMALIZED_CORPUS_SHA256 = "7ea361e60c2a9c06e2628f7d008d25c35ebb58ebcbebc31902ab2380dbebee27"


def normalized_chunk_bytes(raw: bytes) -> bytes:
    """LF bytes. CRLF and CR-only newlines compare as the same corpus."""
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def verify_corpus_matches_disk(expected_sha256: str, chunks_path: Path) -> None:
    normalized = hashlib.sha256(normalized_chunk_bytes(chunks_path.read_bytes())).hexdigest()
    if normalized == expected_sha256:
        return
    if (expected_sha256 == HISTORICAL_CRLF_CORPUS_SHA256
            and normalized == LF_NORMALIZED_CORPUS_SHA256):
        return
    raise GoldenSetError(
        f"corpus on disk ({chunks_path}) has lf-normalized sha256 {normalized}, "
        f"golden set expects {expected_sha256} -- refusing to measure "
        "against a different corpus snapshot")


def by_status(questions: tuple[GoldenQuestion, ...], status: str) -> tuple[GoldenQuestion, ...]:
    return tuple(q for q in questions if q.status == status)


def by_ids(questions: tuple[GoldenQuestion, ...], ids: tuple[str, ...]) -> tuple[GoldenQuestion, ...]:
    wanted = set(ids)
    return tuple(q for q in questions if q.id in wanted)
