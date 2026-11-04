"""Quality and deduplication report for saved extraction records.

Structural validity is counted separately from semantic correctness. A
chunk with no entities is reported as empty, not as a failed extraction.
Graph numbers come from the domain graphs in `graph_merge`.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .extraction_models import EntityType, RelType
from .graph_merge import (
    ALIAS_MAP,
    COMPONENT_MEANING,
    measure,
    merged_graph,
    occurrence_graph,
    undirected_degree,
)

_ENTITY_TYPES = {item.value for item in EntityType}
_REL_TYPES = {item.value for item in RelType}


def load_records(directory: Path) -> list[dict]:
    records = []
    for path in sorted(directory.glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def load_chunk_text(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    texts = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        texts[row["chunk_id"]] = row.get("text") or ""
    return texts


def quality_payload(records: list[dict], texts: dict[str, str]) -> dict:
    rows = [_chunk_row(record) for record in records]
    ok = [row for row in rows if row["status"] == "ok"]
    errors = [row for row in rows if row["status"] == "error"]
    empty = [row for row in ok if row["entities"] == 0]
    other = [row for row in rows if row["status"] not in {"ok", "error"}]
    accepted = [record for record in records if record.get("status") == "ok"]
    before = occurrence_graph(accepted)
    after = merged_graph(accepted)
    degree = undirected_degree(after)
    densest = max(ok, key=lambda row: (row["entities"], row["relationships"]),
                  default=None)
    rarest = min(ok, key=lambda row: (row["entities"], row["relationships"]),
                 default=None)
    entity_types: Counter[str] = Counter()
    rel_types: Counter[str] = Counter()
    outside: Counter[str] = Counter()
    for record in accepted:
        for entity in record["result"]["entities"]:
            kind = entity["entity_type"]
            entity_types[kind] += 1
            if kind not in _ENTITY_TYPES:
                outside[kind] += 1
        for rel in record["result"]["relationships"]:
            kind = rel["relationship_type"]
            rel_types[kind] += 1
            if kind not in _REL_TYPES:
                outside[kind] += 1
    singletons = sum(
        1 for node in after.nodes if len(node.source_chunk_ids) == 1
    )
    top_degree = max(degree.values(), default=0)
    top_keys = sorted(key for key, value in degree.items() if value == top_degree)
    top_edges = [
        {
            "rel_type": edge.rel_type,
            "source": edge.source_id,
            "target": edge.target_id,
            "rel_key": edge.rel_key,
        }
        for edge in after.edges
        if edge.source_id in top_keys or edge.target_id in top_keys
    ]
    return {
        "processed": len(rows),
        "ok": len(ok),
        "error": len(errors),
        "empty_ok": len(empty),
        "other_status": len(other),
        "entities_per_chunk": [
            {"chunk_id": row["chunk_id"], "entities": row["entities"],
             "relationships": row["relationships"], "status": row["status"]}
            for row in rows
        ],
        "dense_chunk": _inspection(densest, texts),
        "rare_chunk": _inspection(rarest, texts),
        "entity_types": dict(entity_types),
        "relationship_types": dict(rel_types),
        "outside_schema": dict(outside),
        "rejected": [
            {"chunk_id": row["chunk_id"], "error": row["error"],
             "candidate_types": row["candidate_types"],
             "quote": _quote(texts.get(row["chunk_id"], ""))}
            for row in errors
        ],
        "singleton_entities": singletons,
        "highest_degree": {
            "entity_keys": top_keys,
            "degree": top_degree,
            "edges": top_edges,
            "meaning": (
                "Az összevont szakterületi élek iránya nélküli száma. "
                "A szám nem igazolja, hogy az extrakció szemantikailag helyes."
            ),
        },
        "before": measure(before),
        "after": measure(after),
        "alias_map": dict(ALIAS_MAP),
        "component_meaning": COMPONENT_MEANING,
        "note": (
            "status ok is structural validity, not semantic correctness. "
            "An empty chunk is an accepted extraction with no entities."
        ),
    }


def render_markdown(payload: dict, *, title: str) -> str:
    lines = [
        f"# {title}",
        "",
        payload["note"],
        "",
        "A gráfmutatók az extrahált szakterületi gráfra vonatkoznak. "
        "A dokumentumgráf, a seed és a MENTIONS élek nincsenek benne.",
        "",
        f"- Feldolgozott chunk: {payload['processed']}",
        f"- Sikeres (strukturálisan érvényes): {payload['ok']}",
        f"- Hibás: {payload['error']}",
        f"- Üres, sikeres chunk: {payload['empty_ok']}",
        f"- Más státusz: {payload['other_status']}",
        "",
        "## Entitások chunkonként",
        "",
    ]
    for row in payload["entities_per_chunk"]:
        lines.append(
            f"- `{row['chunk_id']}`: status={row['status']}, "
            f"entitás={row['entities']}, kapcsolat={row['relationships']}"
        )
    lines += ["", "## Sűrű és ritka chunk", ""]
    lines.extend(_render_inspection("Sűrű", payload["dense_chunk"]))
    lines.extend(_render_inspection("Ritka vagy üres", payload["rare_chunk"]))
    lines += ["", "## Típusok", "", "Entitáselőfordulások:"]
    for kind, count in sorted(payload["entity_types"].items()):
        lines.append(f"- {kind}: {count}")
    if not payload["entity_types"]:
        lines.append("- nincs")
    lines.append("")
    lines.append("Kapcsolatelőfordulások:")
    for kind, count in sorted(payload["relationship_types"].items()):
        lines.append(f"- {kind}: {count}")
    if not payload["relationship_types"]:
        lines.append("- nincs")
    lines.append("")
    lines.append("Sémán kívüli típus: "
                 + (", ".join(payload["outside_schema"]) or "nincs"))
    lines += ["", "## Elutasított jelöltek", ""]
    if not payload["rejected"]:
        lines.append("Nincs hibás rekord.")
    for item in payload["rejected"]:
        lines.append(f"- `{item['chunk_id']}`: {item['error']}")
        kinds = ", ".join(item["candidate_types"]) or "nincs"
        lines.append(f"  - Jelölt típusok: {kinds}")
        lines.append(f"  - Forrásidézet: {item['quote']}")
    top = payload["highest_degree"]
    lines += [
        "",
        "## Egy chunkban előforduló entitások",
        "",
        f"Pontosan egy forráschunkban szereplő összevont entitás: "
        f"{payload['singleton_entities']}.",
        "",
        "## Legnagyobb fokszám",
        "",
        "A legnagyobb fokszám "
        f"{top['degree']}. Ezt eléri: "
        + (", ".join(f"`{key}`" for key in top["entity_keys"]) or "nincs")
        + f". {top['meaning']}",
        "",
    ]
    for edge in top["edges"]:
        lines.append(
            f"- {edge['source']} -{edge['rel_type']}-> {edge['target']}"
        )
    before = payload["before"]
    after = payload["after"]
    lines += [
        "",
        "## Deduplikáció",
        "",
        "Előtte egy csomópont egy chunk egy entitása, egy él egy chunk "
        "egy kapcsolata. Utána egy csomópont egy entity_key, egy él egy "
        "rel_key. Az aliaslista üres: "
        f"`{payload['alias_map'] or {}}`.",
        "",
        f"- Előtte: csomópont {before['nodes']}, él {before['edges']}, "
        f"legnagyobb gyengén összefüggő komponens "
        f"{before['largest_weak_component_nodes']} csomópont.",
        f"- Utána: csomópont {after['nodes']}, él {after['edges']}, "
        f"legnagyobb gyengén összefüggő komponens "
        f"{after['largest_weak_component_nodes']} csomópont.",
        "",
        payload["component_meaning"],
        "",
    ]
    return "\n".join(lines)


def write_reports(extraction_dir: Path, chunks_path: Path | None,
                  markdown_path: Path, json_path: Path, *,
                  title: str) -> dict:
    payload = quality_payload(load_records(extraction_dir),
                              load_chunk_text(chunks_path))
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(payload, title=title),
                             encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    return payload


def _chunk_row(record: dict) -> dict:
    status = record.get("status")
    result = record.get("result") if status == "ok" else None
    entities = result.get("entities", []) if isinstance(result, dict) else []
    relationships = result.get("relationships", []) if isinstance(result, dict) else []
    return {
        "chunk_id": record.get("chunk_id"),
        "status": status,
        "entities": len(entities),
        "relationships": len(relationships),
        "error": record.get("error"),
        "result": result,
        "candidate_types": _candidate_types(record),
    }


def _inspection(row: dict | None, texts: dict[str, str]) -> dict | None:
    if row is None:
        return None
    return {
        "chunk_id": row["chunk_id"],
        "status": row["status"],
        "entities": row["entities"],
        "relationships": row["relationships"],
        "text": texts.get(row["chunk_id"], ""),
        "result": row["result"],
    }


def main(argv: list[str] | None = None) -> int:
    """Write a report. The default is the v3 pilot. No model or database."""
    from .config import PROJECT_ROOT

    parser = argparse.ArgumentParser(prog="python -m naive_rag.quality_report")
    parser.add_argument(
        "--extraction-dir",
        default=str(PROJECT_ROOT / "graph" / "pilot" / "extraction-v3"),
    )
    parser.add_argument(
        "--chunks",
        default=str(PROJECT_ROOT / "graph" / "pilot" / "chunks.jsonl"),
    )
    parser.add_argument(
        "--markdown",
        default=str(PROJECT_ROOT / "graph" / "pilot" / "quality-report-v3.md"),
    )
    parser.add_argument(
        "--json",
        default=str(PROJECT_ROOT / "graph" / "pilot" / "quality-report-v3.json"),
    )
    parser.add_argument("--title", default="10 chunkos v3 pilot minőségi riport")
    parser.add_argument("--join-corpus", action="store_true",
                        help="read chunk text from the project corpus, no model")
    args = parser.parse_args(argv)
    if args.join_corpus:
        from .ingest import load_and_chunk

        _sources, chunks = load_and_chunk()
        texts = {
            chunk.metadata.get("chunk_id"): chunk.page_content
            for chunk in chunks
        }
    else:
        texts = load_chunk_text(Path(args.chunks))
    payload = quality_payload(load_records(Path(args.extraction_dir)), texts)
    markdown_path = Path(args.markdown)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(payload, title=args.title),
                             encoding="utf-8")
    Path(args.json).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(
        f"processed={payload['processed']} ok={payload['ok']} "
        f"error={payload['error']} empty={payload['empty_ok']}"
    )
    print(f"wrote {args.markdown}")
    return 0


def _candidate_types(record: dict) -> list[str]:
    candidate = record.get("candidate_result") or {}
    found = []
    for entity in candidate.get("entities") or []:
        found.append(str(entity.get("entity_type")))
    for rel in candidate.get("relationships") or []:
        found.append(str(rel.get("relationship_type")))
    return found


def _quote(text: str, limit: int = 400) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "(a forrásszöveg nincs a megadott chunks fájlban)"
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _render_inspection(label: str, item: dict | None) -> list[str]:
    if item is None:
        return [f"### {label}", "", "Nincs ilyen chunk.", ""]
    body = json.dumps(item["result"], ensure_ascii=False, indent=2)
    return [
        f"### {label}: `{item['chunk_id']}`",
        "",
        f"Státusz: {item['status']}. Entitás: {item['entities']}. "
        f"Kapcsolat: {item['relationships']}. "
        "A ritka vagy üres eredmény nem hibás extrakció.",
        "",
        "Forrásszöveg:",
        "",
        "```",
        item["text"],
        "```",
        "",
        "Extrakció:",
        "",
        "```json",
        body,
        "```",
        "",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
