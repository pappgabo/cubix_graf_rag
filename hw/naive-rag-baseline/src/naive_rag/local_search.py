"""Entity-anchor local search over the extracted domain graph.

The chain is: embed the question, anchor on entity keys, expand one hop
over the stored domain relationship types, keep the edges that match the
question or the selected anchors, limit the context, then ask the supplied
answer function. Seed nodes are not in this graph.

An empty anchor set returns the refusal sentence and does not call the
answer function. The answer function is instructed to return that same
sentence when the context is not enough.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .entity_index import Anchor, EntityIndex
from .graph_merge import DomainEdge, DomainGraph, DomainNode

REFUSAL = "A rendelkezésre álló részgráf nem támasztja alá a választ."


@dataclass(frozen=True)
class LocalAnswer:
    question: str
    answer: str
    refused: bool
    model_called: bool
    subgraph: dict
    anchors: tuple[tuple[str, float], ...] = ()
    prompt: str = ""
    raw_answer: str = ""


_STOP = frozenset({
    "a", "an", "the", "of", "at", "his", "her", "their", "that", "this",
    "for", "and", "with", "from", "who", "what", "when", "where", "which",
    "whom", "whose", "was", "were", "has", "have", "had", "how", "many",
    "does", "did", "its", "him", "she", "he", "they", "them", "not", "but",
    "or", "as", "to", "in", "on", "by", "be", "is", "are", "it",
})


def question_terms(question: str) -> tuple[str, ...]:
    """Question words and years. Names are not supplied by the caller."""
    folded = question.casefold().replace("'", "")
    found: list[str] = []
    for token in re.findall(r"[0-9]{4}|[a-z0-9]+", folded):
        if token in _STOP:
            continue
        if not token.isdigit() and len(token) < 3:
            continue
        if token not in found:
            found.append(token)
    return tuple(found)


def _covers(term: str, blob: str) -> bool:
    words = set(re.findall(r"[a-z0-9]+", blob))
    if term in words:
        return True
    if len(term) >= 5 and term.endswith("s") and term[:-1] in words:
        return True
    return False


def _years(terms: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(int(term) for term in terms if term.isdigit() and len(term) == 4)


def _year_match(edge: DomainEdge, years: tuple[int, ...]) -> bool:
    for year in years:
        if edge.from_year == year or edge.to_year == year:
            return True
        if (edge.from_year is not None and edge.to_year is not None
                and edge.from_year <= year <= edge.to_year):
            return True
        if str(year) in edge.source_id or str(year) in edge.target_id:
            return True
    return False


def _blob(edge: DomainEdge, names: Mapping[str, str]) -> str:
    rel_words = edge.rel_type.casefold().replace("_", " ")
    return " ".join((
        names.get(edge.source_id, edge.source_id),
        names.get(edge.target_id, edge.target_id),
        edge.description or "",
        rel_words,
        edge.role or "",
    )).casefold().replace("'", "")


def _hits(edge: DomainEdge, terms: tuple[str, ...], years: tuple[int, ...],
          names: Mapping[str, str]) -> int:
    blob = _blob(edge, names)
    hits = sum(1 for term in terms if _covers(term, blob))
    for year in years:
        if str(year) not in blob and _year_match(edge, (year,)):
            hits += 1
    return hits


def expand(graph: DomainGraph, anchor_keys: tuple[str, ...],
           hops: int = 1) -> tuple[tuple[DomainNode, ...], tuple[DomainEdge, ...]]:
    """Walk domain edges in either direction. Stored direction is kept."""
    by_key = {node.entity_key: node for node in graph.nodes}
    incident: dict[str, list[DomainEdge]] = {key: [] for key in by_key}
    for edge in graph.edges:
        incident.setdefault(edge.source_id, []).append(edge)
        incident.setdefault(edge.target_id, []).append(edge)
    seen = {key for key in anchor_keys if key in by_key}
    frontier = set(seen)
    kept_edges: list[DomainEdge] = []
    for _hop in range(hops):
        nxt: set[str] = set()
        for key in frontier:
            for edge in incident.get(key, []):
                if edge not in kept_edges:
                    kept_edges.append(edge)
                other = edge.target_id if edge.source_id == key else edge.source_id
                if other not in seen:
                    seen.add(other)
                    nxt.add(other)
        frontier = nxt
    nodes = tuple(by_key[key] for key in seen if key in by_key)
    return nodes, tuple(kept_edges)


def _eligible(graph: DomainGraph, expanded: set[str], anchor_keys: set[str],
              years: tuple[int, ...], terms: tuple[str, ...]) -> list[DomainEdge]:
    """Anchor edges, edges inside the neighborhood, and a justified step out.

    A step outside the one-hop set is kept only when the question names the
    relation type or the edge covers a year from the question.
    """
    found: list[DomainEdge] = []
    for edge in graph.edges:
        ends = {edge.source_id, edge.target_id}
        inside = ends & expanded
        if not inside:
            continue
        outside = ends - expanded
        justified = (
            _year_match(edge, years) or _rel_mentioned(edge.rel_type, terms)
        )
        if outside and not (inside & anchor_keys) and not justified:
            continue
        found.append(edge)
    return found


def _rel_mentioned(rel_type: str, terms: tuple[str, ...]) -> bool:
    for word in rel_type.casefold().split("_"):
        if len(word) < 3 or word in _STOP:
            continue
        if any(_covers(word, term) or _covers(term, word) for term in terms):
            return True
    return False


def select_context(graph: DomainGraph, question: str,
                   anchors: tuple[Anchor, ...] | tuple[tuple[str, float], ...],
                   *,
                   node_limit: int = 8,
                   edge_limit: int = 12,
                   ) -> tuple[tuple[DomainNode, ...], tuple[DomainEdge, ...]]:
    """Keep edges that match the question or touch a selected anchor.

    Stored edge order does not fill the context. A relation type named by
    the question reserves one edge, then the remaining slots follow term
    overlap and a year in the question. An anchor's unrelated edges do not
    spend the node budget ahead of those.
    """
    pairs = tuple(
        (item.entity_key, item.score) if isinstance(item, Anchor)
        else (str(item[0]), float(item[1]))
        for item in anchors
    )
    anchor_keys = [key for key, _score in pairs]
    anchor_set = set(anchor_keys)
    expanded_nodes, _hop_edges = expand(graph, tuple(anchor_keys))
    by_key = {node.entity_key: node for node in graph.nodes}
    expanded = {node.entity_key for node in expanded_nodes}
    names = {key: node.name for key, node in by_key.items()}
    terms = question_terms(question)
    years = _years(terms)
    eligible = _eligible(graph, expanded, anchor_set, years, terms)
    eligible.sort(
        key=lambda edge: (
            -_hits(edge, terms, years, names),
            -int(_year_match(edge, years)),
            -len({edge.source_id, edge.target_id} & anchor_set),
            edge.rel_key,
        ),
    )
    chosen: list[DomainEdge] = []
    chosen_keys = {key for key in anchor_keys if key in expanded}

    def add(edge: DomainEdge) -> bool:
        if any(edge.rel_key == item.rel_key for item in chosen):
            return False
        if len(chosen) >= edge_limit:
            return False
        new = {edge.source_id, edge.target_id} - chosen_keys
        if len(chosen_keys) + len(new) > node_limit:
            return False
        if not new <= set(by_key):
            return False
        chosen.append(edge)
        chosen_keys.update(new)
        return True

    seen_types: set[str] = set()
    for edge in eligible:
        if not _rel_mentioned(edge.rel_type, terms) or edge.rel_type in seen_types:
            continue
        if add(edge):
            seen_types.add(edge.rel_type)
    for edge in eligible:
        ends = {edge.source_id, edge.target_id}
        if not _year_match(edge, years):
            continue
        if ends & (chosen_keys - anchor_set):
            add(edge)
    for edge in eligible:
        if _hits(edge, terms, years, names) <= 0:
            continue
        if len(chosen) >= edge_limit:
            break
        add(edge)
    if not chosen:
        for key in anchor_keys:
            for edge in eligible:
                if key in (edge.source_id, edge.target_id) and add(edge):
                    break
    score = dict(pairs)
    ordered = sorted(
        (by_key[key] for key in chosen_keys if key in by_key),
        key=lambda node: (
            0 if node.entity_key in score else 1,
            -score.get(node.entity_key, 0.0),
            node.entity_key,
        ),
    )
    return tuple(ordered), tuple(chosen)


def subgraph_payload(nodes: tuple[DomainNode, ...],
                     edges: tuple[DomainEdge, ...]) -> dict:
    chunk_ids: list[str] = []
    for node in nodes:
        for chunk_id in node.source_chunk_ids:
            if chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
    for edge in edges:
        for chunk_id in edge.source_chunk_ids:
            if chunk_id not in chunk_ids:
                chunk_ids.append(chunk_id)
    return {
        "nodes": [
            {
                "entity_key": node.entity_key,
                "entity_type": node.label,
                "name": node.name,
                "description": node.description,
                "source_chunk_ids": list(node.source_chunk_ids),
            }
            for node in nodes
        ],
        "edges": [
            {
                "rel_key": edge.rel_key,
                "rel_type": edge.rel_type,
                "source_key": edge.source_id,
                "target_key": edge.target_id,
                "from_year": edge.from_year,
                "to_year": edge.to_year,
                "role": edge.role,
                "description": edge.description,
                "source_chunk_ids": list(edge.source_chunk_ids),
            }
            for edge in edges
        ],
        "chunk_ids": chunk_ids,
        "sources": [],
    }


def cited_chunks(edges: tuple[DomainEdge, ...],
                 nodes: tuple[DomainNode, ...],
                 texts: Mapping[str, str],
                 question: str, *, limit: int = 6,
                 chars: int = 500) -> list[dict]:
    """Source texts for the selected subgraph, still a limited context.

    Both the selected edges and the selected entities contribute candidates:
    the sentence that answers a question is often on an entity's own chunk,
    not on a relationship's chunk. Each selected entity may reserve one
    excerpt first, so a multi-hop chain keeps evidence for every hop instead
    of spending every slot on the best-matching hop.
    """
    terms = question_terms(question)
    entity_words = tuple(
        tuple(
            word for word in re.findall(r"[a-z0-9]+", node.name.casefold())
            if len(word) > 2
        )
        for node in nodes
    )

    def _folded(chunk_id: str) -> str:
        return (texts.get(chunk_id) or "").casefold().replace("'", "")

    def score(chunk_id: str) -> int:
        folded = _folded(chunk_id)
        hits = sum(1 for term in terms if _covers(term, folded))
        # A chunk naming several selected entities is the bridge a multi-hop
        # question needs; one naming none is unlikely to be the evidence.
        named = sum(
            1 for words in entity_words
            if words and all(_covers(word, folded) for word in words)
        )
        return hits + named

    def best_first(chunk_ids: tuple[str, ...]) -> list[str]:
        return sorted(set(chunk_ids), key=lambda cid: (-score(cid), cid))

    picked: list[str] = []

    def take(chunk_id: str, *, require_hit: bool) -> bool:
        if chunk_id in picked or len(picked) >= limit:
            return False
        if require_hit and score(chunk_id) <= 0:
            return False
        picked.append(chunk_id)
        return True

    for node in nodes:
        for chunk_id in best_first(node.source_chunk_ids):
            if take(chunk_id, require_hit=True):
                break
    pool: list[str] = []
    for edge in edges:
        pool.extend(edge.source_chunk_ids)
    for node in nodes:
        pool.extend(node.source_chunk_ids)
    for chunk_id in best_first(tuple(pool)):
        take(chunk_id, require_hit=True)
    if not picked:
        for chunk_id in best_first(tuple(pool)):
            take(chunk_id, require_hit=False)
    picked.sort(key=lambda cid: (-score(cid), cid))
    return [
        {
            "chunk_id": chunk_id,
            "text": (texts.get(chunk_id) or "")[:chars],
            "text_found": chunk_id in texts and texts.get(chunk_id) != "",
        }
        for chunk_id in picked
    ]


_UPPER = "A-Z\u00c1\u00c9\u00cd\u00d3\u00d6\u0150\u00da\u00dc\u0170\u00c4\u00d4"
_NAME = re.compile(
    rf"[{_UPPER}][^\W\d_]+(?:[ \t]+[{_UPPER}][^\W\d_]+)*",
)


def _flat(text: str) -> str:
    """Casefolded, apostrophe-free, single-spaced. The corpus has runs of
    spaces from the PDF loader, so a raw substring test would miss."""
    return " ".join(text.casefold().replace("'", "\u2019")
                    .replace("\u2019", "").split())


def unsupported_claims(answer: str, sources: list[dict]) -> list[str]:
    """Names and numbers in the answer that no excerpt contains."""
    if answer.strip() == REFUSAL:
        return []
    evidence = _flat(" ".join(
        (source.get("text") or "") for source in sources
    ))
    found: list[str] = []
    claims = _NAME.findall(answer) + re.findall(r"\d+", answer)
    for token in claims:
        cleaned = _flat(token)
        if not cleaned or cleaned in found:
            continue
        if cleaned not in evidence:
            found.append(cleaned)
    return found


def context_text(payload: dict) -> str:
    """Names and structure only. Prose evidence is the source excerpts."""
    lines = ["Entitások:"]
    for node in payload["nodes"]:
        lines.append(f"- {node['entity_key']}")
    lines.append("Kapcsolatok:")
    if not payload["edges"]:
        lines.append("- nincs")
    for edge in payload["edges"]:
        years = f"{edge['from_year']}-{edge['to_year']}"
        lines.append(
            f"- {edge['source_key']} -{edge['rel_type']}-> {edge['target_key']} "
            f"years={years} | chunks={','.join(edge['source_chunk_ids'])}"
        )
    lines.append("Forrásszövegek:")
    sources = payload.get("sources") or []
    if not sources:
        lines.append("- nincs kiválasztott forrásszöveg")
    for source in sources:
        header = source["chunk_id"]
        if source.get("text_found") and source.get("text"):
            lines.append(f"- [{header}] {source['text']}")
        else:
            lines.append(f"- [{header}] a forrásszöveg helyben nem elérhető")
    return "\n".join(lines)


def answer_prompt(question: str, context: str) -> str:
    return (
        "A válasz csak a Forrásszövegek szakaszból származhat. Nevet vagy "
        "számot csak akkor írj, ha az a forrásszövegben szerepel. Az "
        "entitásnevek és a kapcsolatok szerkezete nem helyettesíti a "
        "forrásszöveget. Ha a forrásszövegek nem támasztják alá, a válasz "
        f"pontosan ez legyen, más szöveg nélkül: {REFUSAL}\n\n"
        f"Kérdés: {question}\n\nKontextus:\n{context}"
    )


def _as_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def search_record(question_id: str, found: LocalAnswer) -> dict:
    """Fields the next answer run must persist. This writes nothing."""
    return {
        "id": question_id,
        "model_called": found.model_called,
        "unsupported": unsupported_claims(
            found.answer, found.subgraph.get("sources") or []),
        "anchors": [
            {"entity_key": key, "score": score}
            for key, score in found.anchors
        ],
        "prompt": found.prompt,
        "raw_answer": found.raw_answer,
        "answer": found.answer,
        "refused": found.refused,
    }


def local_search(question: str, graph: DomainGraph, index: EntityIndex, *,
                 embed_query, answer_fn, k: int = 3,
                 min_score: float = 0.25,
                 chunk_texts: Mapping[str, str] | None = None) -> LocalAnswer:
    """Run the chain. `embed_query` and `answer_fn` are injected."""
    if graph.kind != "merged":
        raise ValueError("Local search uses the merged extracted graph.")
    if not index.entities:
        return LocalAnswer(
            question=question,
            answer=REFUSAL,
            refused=True,
            model_called=False,
            subgraph=subgraph_payload((), ()),
        )
    vector = embed_query(question)
    anchors = index.anchor(vector, k=k, min_score=min_score)
    if not anchors:
        return LocalAnswer(
            question=question,
            answer=REFUSAL,
            refused=True,
            model_called=False,
            subgraph=subgraph_payload((), ()),
        )
    chosen_nodes, chosen_edges = select_context(graph, question, anchors)
    payload = subgraph_payload(chosen_nodes, chosen_edges)
    payload["sources"] = cited_chunks(
        chosen_edges, chosen_nodes, chunk_texts or {}, question,
    )
    prompt = answer_prompt(question, context_text(payload))
    raw_answer = _as_text(answer_fn(prompt))
    text = raw_answer.strip()
    return LocalAnswer(
        question=question,
        answer=text,
        refused=text == REFUSAL,
        model_called=True,
        subgraph=payload,
        anchors=tuple((item.entity_key, item.score) for item in anchors),
        prompt=prompt,
        raw_answer=raw_answer,
    )


def filter_questions(items: list[dict], spec: str | None) -> list[dict]:
    """Keep every question, or only ids in ``Q01`` / ``Q01-Q04``."""
    if not spec:
        return list(items)
    from .question_scope import question_ids_from_scope

    wanted = set(question_ids_from_scope(spec))
    return [item for item in items if item.get("id") in wanted]


def main(argv: list[str] | None = None) -> int:
    """List the baseline questions. Answer only when ``--run`` is set."""
    parser = argparse.ArgumentParser(prog="python -m naive_rag.local_search")
    parser.add_argument("--index", required=True)
    parser.add_argument("--extraction-dir", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--questions", default=None,
                        help="Q01 or Q01-Q04; default is every baseline question")
    parser.add_argument("--run", action="store_true",
                        help="embed the questions and call the chat model")
    args = parser.parse_args(argv)
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    questions = filter_questions(baseline.get("results", []), args.questions)
    print(f"questions: {len(questions)}")
    if not args.run:
        print("no model call (--run not set)")
        return 0
    from .compare_baseline import write_comparison
    from .entity_index import load_index
    from .graph_merge import merged_graph
    from .models import get_chat_model, get_embeddings
    from .quality_report import load_records

    from .ingest import load_and_chunk

    index = load_index(Path(args.index))
    graph = merged_graph(load_records(Path(args.extraction_dir)))
    _sources, chunks = load_and_chunk()
    texts = {
        chunk.metadata.get("chunk_id"): chunk.page_content
        for chunk in chunks
    }
    embedder = get_embeddings()
    chat = get_chat_model()
    local = {}
    records = []
    for item in questions:
        found = local_search(
            item["question"],
            graph,
            index,
            embed_query=embedder.embed_query,
            answer_fn=lambda prompt: chat.invoke(prompt).content,
            chunk_texts=texts,
        )
        missing = unsupported_claims(
            found.answer, found.subgraph.get("sources") or [])
        if found.refused:
            evaluation = (
                "A lánc elutasította a választ, mert a részgráf nem volt elég."
            )
        elif missing:
            evaluation = (
                "A válasz nem forrással alátámasztott: a kiválasztott "
                "részletekben nem szerepel: " + ", ".join(missing) + ". "
                "GraphRAG-fölény nincs állítva."
            )
        else:
            evaluation = (
                "A válasz minden megnevezett neve és száma szerepel a "
                "kiválasztott forrásszövegekben. A tartalmi helyességet ez "
                "nem bizonyítja. GraphRAG-fölény nincs állítva."
            )
        local[item["id"]] = {
            "answer": found.answer,
            "subgraph": found.subgraph,
            "evaluation": evaluation,
        }
        records.append(search_record(item["id"], found))
    write_comparison(Path(args.baseline), Path(args.out), local)
    record_path = Path(args.out).with_name(Path(args.out).stem + "-run.json")
    record_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out}")
    print(f"wrote {record_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
