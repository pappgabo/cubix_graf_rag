"""Offline provenance check for an extracted-layer backup.

Reads a ``extracted-layer-backup-1`` file and a frozen ``chunks.jsonl``.
Does not connect to Neo4j and does not write either input.

Domain edges use ``properties.source_chunk_ids``. ``MENTIONS`` edges use
the chunk endpoint's ``chunk_id``. Those names come from
``extraction_load.build_extracted_backup``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def chunk_ids(path: Path) -> set[str]:
    found: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            chunk_id = record.get("chunk_id")
            if isinstance(chunk_id, str) and chunk_id:
                found.add(chunk_id)
    return found


def _chunk_refs(edge: dict) -> list[str]:
    if edge.get("type") == "MENTIONS":
        for end in ("source", "target"):
            ref = edge.get(end)
            if isinstance(ref, dict) and ref.get("kind") == "chunk":
                chunk_id = ref.get("chunk_id")
                if isinstance(chunk_id, str) and chunk_id:
                    return [chunk_id]
        return []
    properties = edge.get("properties")
    if not isinstance(properties, dict):
        return []
    raw = properties.get("source_chunk_ids")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str) and item]


def check(backup_path: Path, chunks_path: Path) -> dict[str, int]:
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    if payload.get("format") != "extracted-layer-backup-1":
        raise ValueError(f"{backup_path} is not an extracted-layer backup")
    edges = payload.get("edges")
    if not isinstance(edges, list):
        raise ValueError(f"{backup_path} has no edge list")
    known = chunk_ids(chunks_path)
    edges_with = 0
    refs = 0
    resolved = 0
    for edge in edges:
        sources = _chunk_refs(edge)
        if sources:
            edges_with += 1
        refs += len(sources)
        resolved += sum(1 for item in sources if item in known)
    checked = len(edges)
    return {
        "nodes": len(payload.get("nodes") or []),
        "edges_checked": checked,
        "edges_with_provenance": edges_with,
        "edges_missing_provenance": checked - edges_with,
        "source_chunk_refs": refs,
        "resolved_source_chunk_refs": resolved,
        "missing_source_chunk_refs": refs - resolved,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/check_extracted_provenance.py")
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--chunks", type=Path, required=True)
    args = parser.parse_args(argv)
    result = check(args.backup, args.chunks)
    for key, value in result.items():
        print(f"{key} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
