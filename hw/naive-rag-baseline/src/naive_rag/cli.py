"""Command line interface.

  uv run naive-rag ingest [--chunk-size N --chunk-overlap N]
  uv run naive-rag ask "your question"
  uv run naive-rag baseline [--tag NAME]
  uv run naive-rag serve [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings
from .dependencies import MissingDependency

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

    args = p.parse_args()
    try:
        args.fn(args)
    except MissingDependency as e:
        raise SystemExit(f"error: {e}\n{_install_hint(e.name)}") from None


if __name__ == "__main__":
    main()
