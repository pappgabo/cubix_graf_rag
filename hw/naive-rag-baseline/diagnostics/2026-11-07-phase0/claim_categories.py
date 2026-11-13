"""Classify saved Q06, Q10 and Q12 answers. No model or database call.

Reads the existing comparison run. Does not modify it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naive_rag.local_search import classify_claims, graph_statement_text  # noqa: E402

RUN = ROOT / "docs" / "osszehasonlitas-section-1200-23-run.json"
WANTED = ("Q06", "Q10", "Q12")


def excerpt_text(prompt: str) -> str:
    marker = "Eredeti dokumentumrészletek:"
    if marker not in prompt:
        return ""
    return prompt.split(marker, 1)[1]


def main() -> None:
    rows = json.loads(RUN.read_text(encoding="utf-8"))
    report = []
    for row in rows:
        if row["id"] not in WANTED:
            continue
        prompt = row.get("prompt") or ""
        sources = [{"text": excerpt_text(prompt)}]
        claims = classify_claims(
            row.get("answer") or "", sources, graph_statement_text(prompt))
        saved = row.get("unsupported") or []
        report.append({
            "id": row["id"],
            "saved_unsupported": saved,
            "in_excerpts": claims["in_excerpts"],
            "graph_only": claims["graph_only"],
            "unsupported": claims["unsupported"],
            "saved_now_graph_only": [
                token for token in saved if token in claims["graph_only"]
            ],
            "saved_still_unsupported": [
                token for token in saved if token in claims["unsupported"]
            ],
        })
    destination = HERE / "results"
    destination.mkdir(exist_ok=True)
    (destination / "claim_categories.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for item in report:
        print(item["id"])
        print("  graph_only:", ", ".join(item["graph_only"]) or "-")
        print("  unsupported:", ", ".join(item["unsupported"]) or "-")
        print("  saved now graph_only:", ", ".join(item["saved_now_graph_only"]) or "-")
        print("  saved still unsupported:", ", ".join(item["saved_still_unsupported"]) or "-")


if __name__ == "__main__":
    main()
