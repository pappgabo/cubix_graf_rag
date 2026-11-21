"""Explicit, offline-triggered report-index build for the week6 drift
mode. Never runs automatically -- ``drift_measure.py`` only ever LOADS the
cache (``naive_rag.drift_search.load_report_index``) and raises a clear,
no-paid-call error if it is missing or stale (``ReportIndexNotReady`` in
``drift_measure.py``). This script is the one explicit command that may
spend money, and only for the single embedding batch the report index
needs.

Reuses ``naive_rag.drift_search.build_report_index``/``save_report_index``/
``load_report_index``/``reports_content_hash`` unchanged. The only new
logic here is the cost-guard wiring -- B-phase's own ``drift_search.main()``
CLI intentionally left that out (matching ``entity_index.py``'s own
``main()``, which also builds without any ledger), so the week6
measurement layer owns it, exactly where every other ledger-aware wrapper
in this project (``generation_runner.py``, ``measure.py``) lives.

A valid, matching cache is reused with zero embedding calls -- the
"already valid" check runs before the ledger or the embeddings client is
ever constructed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import week6_bootstrap  # noqa: F401
import cost_guard  # week5-b, unchanged

from naive_rag.drift_search import (
    EMBEDDING_MODEL,
    ReportIndexCacheError,
    build_report_index,
    load_report_index,
    reports_content_hash,
    save_report_index,
)
from naive_rag.global_search import load_reports
from naive_rag.local_search import estimate_tokens

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
DEFAULT_LEDGER_PATH = RESULTS_DIR / "week6-cost-ledger.json"
DEFAULT_CACHE_PATH = RESULTS_DIR / "report-index-cache.json"
DEFAULT_INDEX_COST_SUMMARY_PATH = RESULTS_DIR / "week6-index-cost.json"


def ledger_tracked_embed_documents(embeddings, ledger, texts: list[str], label: str) -> list[list[float]]:
    """Checked against the shared ledger before the call, recorded after --
    same convention as every other paid call in this project. The
    installed langchain embeddings client exposes no token usage, so the
    actual cost booked is the pre-call upper bound, never zero."""
    tokens = sum(estimate_tokens(text) for text in texts)
    upper = ledger.check_embedding(tokens, label)
    vectors = embeddings.embed_documents(texts)
    ledger.record_embedding("unknown", upper)
    return vectors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python build_index.py")
    parser.add_argument("--build", action="store_true", required=True,
                        help="required flag; makes the paid embedding call explicit")
    parser.add_argument("--collection-path", required=True, type=Path)
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--expected-reporting-level", type=int, default=0)
    parser.add_argument("--out", type=Path, default=DEFAULT_CACHE_PATH)
    parser.add_argument("--ledger-path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--index-cost-summary-path", type=Path, default=DEFAULT_INDEX_COST_SUMMARY_PATH)
    args = parser.parse_args(argv)

    loaded = load_reports(
        args.collection_path, expected_run_id=args.expected_run_id,
        expected_reporting_level=args.expected_reporting_level,
    )
    content_hash = reports_content_hash(loaded)

    try:
        load_report_index(args.out, expected_reports_hash=content_hash, expected_embedding_model=EMBEDDING_MODEL)
        print(f"reports: {len(loaded)}")
        print(f"cache already valid at {args.out}; no embedding call")
        return 0
    except ReportIndexCacheError:
        pass  # falls through to an explicit, one-time build below

    from naive_rag.models import get_embeddings

    embeddings = get_embeddings()
    ledger = cost_guard.SharedCostLedger.load(args.ledger_path)
    before_count = len(ledger.entries)

    index = build_report_index(
        loaded,
        lambda texts: ledger_tracked_embed_documents(embeddings, ledger, texts, "drift-report-index-build"),
    )

    # SharedCostLedger's own persisted entries carry no label (see
    # cost_guard.py's ``_record_entry``) -- a report-index entry is
    # otherwise indistinguishable from a later case's embedding entry in
    # the same shared ledger file. This sidecar is what lets the week6
    # report show the index cost as one summary row, never re-attributed
    # per question type (see report_week6.py).
    new_entries = ledger.entries[before_count:]
    index_cost_usd = round(sum(entry["cost_usd"] for entry in new_entries), 6)
    args.index_cost_summary_path.parent.mkdir(parents=True, exist_ok=True)
    args.index_cost_summary_path.write_text(json.dumps({
        "reports_hash": content_hash, "embedding_model": EMBEDDING_MODEL,
        "report_count": len(loaded), "cost_usd": index_cost_usd,
        "entry_count": len(new_entries), "ledger_path": str(args.ledger_path),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    save_report_index(index, args.out, reports_hash=content_hash, embedding_model=EMBEDDING_MODEL)
    print(f"reports: {len(loaded)}")
    print(f"index cost (usd): {index_cost_usd}")
    print(f"wrote {args.out}")
    print(f"wrote {args.index_cost_summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
