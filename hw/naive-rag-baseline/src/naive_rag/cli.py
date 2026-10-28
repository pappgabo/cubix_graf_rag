"""Command line interface.

  uv run naive-rag ingest [--chunk-size N --chunk-overlap N]
  uv run naive-rag ask "your question"
  uv run naive-rag baseline [--tag NAME]
  uv run naive-rag serve [--port 8000]
  uv run naive-rag graph up | init | load | seed | query | stats | clear
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import PROJECT_ROOT, get_settings
from .dependencies import MissingDependency
from .graph import GraphUnavailable

TYPE_ORDER = ["simple", "multi-hop", "global"]

# How to install external programs, per platform (sys.platform).
_INSTALL_HINTS = {
    "pandoc": {
        "win32": "Install: winget install JohnMacFarlane.Pandoc  "
                 "(then open a new terminal so PATH is refreshed)",
        "darwin": "Install: brew install pandoc",
        "linux": "Install: sudo apt install pandoc  (or your distro's package)",
        "default": "See https://pandoc.org/installing.html",
    },
}


_GRAPH_HINT = ("Start it from the repo:  docker compose up -d neo4j\n"
               "or let the CLI do it:    uv run naive-rag graph up\n"
               "Check NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in .env "
               "(compose.yaml reads the same values).")


def _install_hint(name: str) -> str:
    hints = _INSTALL_HINTS.get(name, {})
    return hints.get(sys.platform) or hints.get(
        "default", "Install it and make sure it is on PATH.")


def parse_questions(path: Path) -> list[dict]:
    """Parse questions.md: '### Qnn — type' followed by '**Kérdés:** ...'."""
    out, cur = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"###\s+(Q\d+)\s+[—-]\s+(\S+)", line)
        if m:
            cur = {"id": m.group(1), "type": m.group(2)}
            out.append(cur)
            continue
        m = re.match(r"\*\*Kérdés:\*\*\s*(.+)", line)
        if m and cur is not None and "question" not in cur:
            cur["question"] = m.group(1).strip()
    return [q for q in out if "question" in q]


def _print_answer(res: dict) -> None:
    print(f"\nQ: {res['question']}\n\nA: {res['answer']}\n\nSources:")
    for s in res["sources"]:
        print(f"  [{s['tag']}] {s['chunk_id']}  ({s['file']}, "
              f"{s['location']})  score={s['score']}")


def cmd_ingest(args) -> None:
    from .ingest import run_ingest
    run_ingest(args.chunk_size, args.chunk_overlap)


def cmd_ask(args) -> None:
    from .rag import get_rag
    _print_answer(get_rag().ask(args.question, args.k))


def _answers_markdown(meta: dict, results: list[dict]) -> str:
    lines = ["# Baseline answers (naive RAG)", "",
             "```json", json.dumps(meta, indent=2), "```", "",
             "> Answers are saved exactly as produced. They are NOT corrected.",
             ""]
    for t in TYPE_ORDER:
        group = [r for r in results if r["type"] == t]
        if not group:
            continue
        lines += [f"## {t}", ""]
        for r in group:
            lines += [f"### {r['id']} — {t}", "",
                      f"**Question:** {r['question']}", "",
                      f"**Answer:** {r['answer']}", "", "**Sources:**", ""]
            for s in r["sources"]:
                lines.append(f"- [{s['tag']}] `{s['chunk_id']}` — "
                             f"{s['file']}, {s['location']} "
                             f"(score {s['score']})")
            lines.append("")
    return "\n".join(lines)


def cmd_baseline(args) -> None:
    from .rag import get_rag
    s = get_settings()
    rag = get_rag()
    questions = parse_questions(s.questions_file)
    print(f"Running {len(questions)} questions ...")
    results = []
    for q in questions:
        res = rag.ask(q["question"])
        results.append({"id": q["id"], "type": q["type"], **res})
        print(f"  {q['id']} ({q['type']}) done")

    info = {}
    if s.index_info_file.exists():
        info = json.loads(s.index_info_file.read_text(encoding="utf-8"))
    meta = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "chat_model": s.chat_model,
        "embedding_model": info.get("embedding_model", s.embedding_model),
        "chunk_size": info.get("chunk_size", s.chunk_size),
        "chunk_overlap": info.get("chunk_overlap", s.chunk_overlap),
        "num_chunks": info.get("num_chunks"),
        "top_k": s.top_k,
        "note": args.note or "",
    }
    out = s.baseline_dir / args.tag if args.tag else s.baseline_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "answers.json").write_text(
        json.dumps({"meta": meta, "results": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "answers.md").write_text(
        _answers_markdown(meta, results), encoding="utf-8")
    print(f"Saved to {out}")


def cmd_serve(args) -> None:
    import uvicorn
    uvicorn.run("naive_rag.api:app", host=args.host, port=args.port)


# --- graph (week 2) -------------------------------------------------------

def _report(title: str, stats: dict) -> None:
    print(title)
    width = max(len(k) for k in stats)
    for key, value in stats.items():
        print(f"  {key:<{width}} {value}")


def cmd_graph_up(args) -> None:
    """`docker compose up -d neo4j`, then wait until the container is healthy."""
    if not shutil.which("docker"):
        raise MissingDependency("docker", "running Neo4j from compose.yaml")
    subprocess.run(["docker", "compose", "up", "-d", "neo4j"],
                   cwd=PROJECT_ROOT, check=True)
    print("Waiting for Neo4j to become healthy ...", end="", flush=True)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}",
             "f1-graphrag-neo4j"],
            capture_output=True, text=True, check=False)
        if out.stdout.strip() == "healthy":
            s = get_settings()
            print(f" ok.\nBolt: {s.neo4j_uri}   Browser: http://localhost:7474")
            return
        print(".", end="", flush=True)
        time.sleep(2)
    raise SystemExit(f"\nerror: Neo4j did not become healthy in "
                     f"{args.timeout}s. Try: docker compose logs neo4j")


def cmd_graph_init(args) -> None:
    from .graph_schema import apply_schema
    _report("Schema applied.", apply_schema())


def cmd_graph_load(args) -> None:
    from .graph_ingest import load_document_graph
    _report("Document graph loaded.",
            load_document_graph(args.chunk_size, args.chunk_overlap))


def cmd_graph_seed(args) -> None:
    from .graph_seed import load_seed_graph
    _report("Seed graph loaded (rows merged per section).", load_seed_graph())


def cmd_graph_query(args) -> None:
    from .graph_queries import render_table, run_queries, write_report
    results = run_queries(args.only)
    if args.only:
        # A single query prints to the terminal; the report file is only
        # rewritten by a full run, so it always contains all 8 queries.
        for r in results:
            print(f"\n{r['id']} — {r['title']}\n")
            print(render_table(r["rows"]))
        return
    for r in results:
        print(f"  {r['id']} — {r['title']}: {len(r['rows'])} row(s)")
    print(f"Saved to {write_report(results)}")


def cmd_graph_stats(args) -> None:
    from .graph import counts_by_label
    from .graph_schema import describe_schema
    rows = counts_by_label()
    if not rows:
        print("The graph is empty. Run: graph init, graph load, graph seed")
        return
    _report("Nodes per label:",
            {r["name"]: r["count"] for r in rows if r["kind"] == "node"})
    _report("Relationships per type:",
            {r["name"]: r["count"] for r in rows if r["kind"] == "rel"})
    print("Shapes present in the data:")
    for t in describe_schema():
        print(f"  (:{t['from_label']})-[:{t['rel']}]->(:{t['to_label']})"
              f"  x{t['count']}")


def cmd_graph_clear(args) -> None:
    from .graph import query
    from .graph_seed import clear_seed_graph
    if args.what == "seed":
        print(f"Deleted {clear_seed_graph()} :Seed nodes.")
        return
    if args.what == "corpus":
        n = query("MATCH (n) WHERE n:Corpus OR n:Document OR n:Section "
                  "OR n:Chunk DETACH DELETE n "
                  "RETURN count(*) AS deleted")[0]["deleted"]
        print(f"Deleted {n} document-graph nodes.")
        return
    n = query("MATCH (n) DETACH DELETE n RETURN count(*) AS deleted"
              )[0]["deleted"]
    print(f"Deleted all {n} nodes (the schema is kept).")


def main() -> None:
    p = argparse.ArgumentParser(prog="naive-rag")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ingest", help="build the vector index")
    sp.add_argument("--chunk-size", type=int)
    sp.add_argument("--chunk-overlap", type=int)
    sp.set_defaults(fn=cmd_ingest)

    sp = sub.add_parser("ask", help="ask a single question")
    sp.add_argument("question")
    sp.add_argument("-k", type=int)
    sp.set_defaults(fn=cmd_ask)

    sp = sub.add_parser("baseline", help="run all questions.md questions")
    sp.add_argument("--tag", help="save into baseline/<tag>/ (e.g. c500)")
    sp.add_argument("--note", help="free-text note stored with the run")
    sp.set_defaults(fn=cmd_baseline)

    sp = sub.add_parser("serve", help="start the FastAPI app")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.set_defaults(fn=cmd_serve)

    sp = sub.add_parser("graph", help="Neo4j: schema, data loading, Cypher")
    gsub = sp.add_subparsers(dest="graph_cmd", required=True)

    g = gsub.add_parser("up", help="start Neo4j (docker compose) and wait")
    g.add_argument("--timeout", type=int, default=120)
    g.set_defaults(fn=cmd_graph_up)

    g = gsub.add_parser("init", help="create constraints and indexes")
    g.set_defaults(fn=cmd_graph_init)

    g = gsub.add_parser("load", help="load the real corpus as Document/Chunk")
    g.add_argument("--chunk-size", type=int)
    g.add_argument("--chunk-overlap", type=int)
    g.set_defaults(fn=cmd_graph_load)

    g = gsub.add_parser("seed", help="load graph/seed/f1-seed.json")
    g.set_defaults(fn=cmd_graph_seed)

    g = gsub.add_parser("query", help="run cypher/queries.cypher -> report")
    g.add_argument("--only", help="run a single query by id (e.g. Q4)")
    g.set_defaults(fn=cmd_graph_query)

    g = gsub.add_parser("stats", help="node/relationship counts and shapes")
    g.set_defaults(fn=cmd_graph_stats)

    g = gsub.add_parser("clear", help="delete data (the schema is kept)")
    g.add_argument("what", choices=["all", "seed", "corpus"], default="all",
                   nargs="?")
    g.set_defaults(fn=cmd_graph_clear)

    args = p.parse_args()
    try:
        args.fn(args)
    except MissingDependency as e:
        raise SystemExit(f"error: {e}\n{_install_hint(e.name)}") from None
    except GraphUnavailable as e:
        raise SystemExit(f"error: {e}\n{_GRAPH_HINT}") from None


if __name__ == "__main__":
    main()
