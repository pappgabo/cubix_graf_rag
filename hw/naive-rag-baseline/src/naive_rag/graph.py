"""Neo4j connection layer.

Every query in this project goes through `query()` / `write_batched()`, which
only accept Cypher plus a parameter dict -- no f-strings into Cypher. That
keeps the queries injection-safe and lets Neo4j reuse the query plan.

Mirrors `vectorstore.py`: one module owns the store, so swapping it later
(or pointing at Aura) stays local to this file.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from functools import lru_cache
from typing import Any

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

from .config import get_settings


class GraphUnavailable(RuntimeError):
    """Neo4j is not reachable / rejected the credentials.

    The CLI turns this into an actionable message (see `_GRAPH_HINT`).
    """


@lru_cache
def get_driver() -> Driver:
    s = get_settings()
    driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user,
                                                     s.neo4j_password))
    try:
        driver.verify_connectivity()
    except AuthError as e:
        raise GraphUnavailable(
            f"Neo4j rejected user '{s.neo4j_user}' at {s.neo4j_uri}.") from e
    except ServiceUnavailable as e:
        raise GraphUnavailable(f"No Neo4j at {s.neo4j_uri}.") from e
    return driver


def query(cypher: str, **params: Any) -> list[dict]:
    """Run a parameterized query and return the records as dicts."""
    s = get_settings()
    records, _, _ = get_driver().execute_query(
        cypher, parameters_=params, database_=s.neo4j_database)
    return [r.data() for r in records]


def _batches(rows: list[dict], size: int) -> Iterator[list[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def write_batched(cypher: str, rows: Iterable[dict], batch_size: int = 500,
                  **params: Any) -> int:
    """Run `UNWIND $rows AS row ...` over `rows` in transaction-sized chunks.

    One transaction per batch keeps memory bounded on a 1 GB heap; the Cypher
    is expected to be idempotent (MERGE), so a partially applied load can be
    fixed by simply re-running the command.

    Returns the number of rows the statement actually applied if it ends with
    `RETURN count(*) AS n`, otherwise the number of rows sent. The difference
    matters for statements that filter (e.g. "titles won by a driver" is given
    every title row but only applies to some).
    """
    rows = list(rows)
    applied, counted = 0, False
    for batch in _batches(rows, batch_size):
        out = query(cypher, rows=batch, **params)
        if out and "n" in out[0]:
            counted = True
            applied += out[0]["n"]
    return applied if counted else len(rows)


def counts_by_label() -> list[dict]:
    """Node counts per label, plus relationship counts per type."""
    return query("""
        CALL () {
            MATCH (n) UNWIND labels(n) AS label
            RETURN 'node' AS kind, label AS name, count(*) AS count
          UNION ALL
            MATCH ()-[r]->()
            RETURN 'rel' AS kind, type(r) AS name, count(*) AS count
        }
        RETURN kind, name, count ORDER BY kind, count DESC, name
    """)
