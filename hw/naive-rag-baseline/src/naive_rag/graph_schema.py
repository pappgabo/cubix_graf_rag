"""Schema DDL: uniqueness constraints and indexes.

The constraints are what make every loader in this project idempotent: each
node type has exactly one business key, so `MERGE (n:Label {key: ...})`
either finds the existing node or creates it -- never a duplicate. Re-running
`graph init` is free (`IF NOT EXISTS` everywhere).

The prose version of this schema, with the modelling decisions, is in
`docs/graph-schema.md`.
"""

from __future__ import annotations

from .graph import query

# label -> business key. Document graph first, then the domain entities.
UNIQUE_KEYS: dict[str, str] = {
    # --- document graph (built from the real corpus, no extraction) -------
    "Corpus": "name",
    "Document": "doc_id",
    "Section": "section_id",
    "Chunk": "chunk_id",
    # --- domain entities (week 2: fictional seed, week 3: extraction) -----
    "Driver": "driver_id",
    "Team": "team_id",
    "Season": "year",
    "GrandPrix": "gp_id",
    "Circuit": "circuit_id",
    "Car": "car_id",
    "PowerUnit": "name",
    "Title": "title_id",
    "RaceResult": "result_id",
}

# Secondary indexes for the access paths the Cypher queries actually use.
INDEXES: list[tuple[str, str, list[str]]] = [
    # name, label, properties
    ("chunk_doc_ordinal", "Chunk", ["doc_id", "ordinal"]),
    ("document_category", "Document", ["category"]),
    ("document_format", "Document", ["format"]),
    ("driver_name", "Driver", ["name"]),
    ("team_name", "Team", ["name"]),
]

# Lexical search over chunk text. Not used by the week-2 queries, but it is
# the half of hybrid retrieval that the vector store cannot do, so it belongs
# to the schema rather than to a later ad-hoc migration.
FULLTEXT_INDEXES: list[tuple[str, str, str]] = [
    ("chunk_text_ft", "Chunk", "text"),
]


def apply_schema() -> dict[str, int]:
    """Create every constraint and index. Safe to run repeatedly."""
    for label, key in UNIQUE_KEYS.items():
        query(
            f"CREATE CONSTRAINT {label.lower()}_{key}_unique IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")
    for name, label, props in INDEXES:
        cols = ", ".join(f"n.{p}" for p in props)
        query(f"CREATE INDEX {name} IF NOT EXISTS "
              f"FOR (n:{label}) ON ({cols})")
    for name, label, prop in FULLTEXT_INDEXES:
        query(f"CREATE FULLTEXT INDEX {name} IF NOT EXISTS "
              f"FOR (n:{label}) ON EACH [n.{prop}]")
    # Make the schema usable immediately: population is async, and the very
    # next command (`graph load`) MERGEs against these constraints.
    query("CALL db.awaitIndexes($timeout)", timeout=300)
    return {
        "constraints": len(query("SHOW CONSTRAINTS YIELD name RETURN name")),
        "indexes": len(query("SHOW INDEXES YIELD name RETURN name")),
    }


def describe_schema() -> list[dict]:
    """The (start label)-[type]->(end label) triples present in the data.

    Read from the data itself rather than from `db.schema.visualization()`,
    so the output is the shape that actually got loaded -- which is what the
    documentation should be checked against.
    """
    return query("""
        MATCH (a)-[r]->(b)
        UNWIND labels(a) AS from_label
        UNWIND labels(b) AS to_label
        WITH from_label, type(r) AS rel, to_label, count(*) AS count
        WHERE from_label <> 'Seed' AND to_label <> 'Seed'
        RETURN from_label, rel, to_label, count
        ORDER BY from_label, rel, to_label
    """)
