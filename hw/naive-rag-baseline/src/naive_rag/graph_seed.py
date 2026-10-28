"""Load the fictional seed graph from `graph/seed/f1-seed.json`.

Data lives in JSON, the mapping to the schema lives here. Two reasons: the
JSON stays reviewable as data (and diffable when the schema changes), and the
Cypher stays parameterized -- no value is ever formatted into a query string.

Everything is MERGEd on its business key, so running `graph seed` twice is a
no-op rather than a duplication. Every seed node carries an extra `:Seed`
label: the data is invented, and week 3 will extract *real* Drivers/Teams from
the corpus into the same labels. The marker keeps the two apart (and makes
`graph clear --seed` possible).
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import get_settings
from .graph import query, write_batched

# --- entity nodes ---------------------------------------------------------
# Each statement MERGEs on the business key and then SETs the rest, so a
# changed JSON value updates the node instead of creating a second one.

_SEASONS = """
UNWIND $rows AS row
MERGE (s:Season:Seed {year: row.year})
SET s.rounds = row.rounds, s.regulation_era = row.regulation_era
RETURN count(*) AS n
"""

_POWER_UNITS = """
UNWIND $rows AS row
MERGE (p:PowerUnit:Seed {name: row.name})
SET p.manufacturer = row.manufacturer, p.layout = row.layout
RETURN count(*) AS n
"""

_TEAMS = """
UNWIND $rows AS row
MERGE (t:Team:Seed {team_id: row.team_id})
SET t.name = row.name, t.base = row.base, t.founded = row.founded,
    t.principal = row.principal
RETURN count(*) AS n
"""

_DRIVERS = """
UNWIND $rows AS row
MERGE (d:Driver:Seed {driver_id: row.driver_id})
SET d.name = row.name, d.nationality = row.nationality, d.born = row.born,
    d.race_number = row.race_number
RETURN count(*) AS n
"""

_CIRCUITS = """
UNWIND $rows AS row
MERGE (c:Circuit:Seed {circuit_id: row.circuit_id})
SET c.name = row.name, c.country = row.country,
    c.length_km = row.length_km, c.turns = row.turns
RETURN count(*) AS n
"""

# A car belongs to exactly one team in one season, so team and season are
# edges, while model/year stay as properties.
_CARS = """
UNWIND $rows AS row
MERGE (c:Car:Seed {car_id: row.car_id})
SET c.model = row.model, c.year = row.year
WITH row, c
MATCH (t:Team {team_id: row.team})
MATCH (p:PowerUnit {name: row.power_unit})
MATCH (s:Season {year: row.year})
MERGE (t)-[:FIELDED]->(c)
MERGE (c)-[:POWERED_BY]->(p)
MERGE (c)-[:RACED_IN]->(s)
RETURN count(*) AS n
"""

_GRANDS_PRIX = """
UNWIND $rows AS row
MERGE (g:GrandPrix:Seed {gp_id: row.gp_id})
SET g.name = row.name, g.round = row.round, g.date = date(row.date),
    g.laps = row.laps
WITH row, g
MATCH (s:Season {year: row.season})
MATCH (c:Circuit {circuit_id: row.circuit})
MERGE (g)-[:ROUND_OF]->(s)
MERGE (g)-[:HELD_AT]->(c)
RETURN count(*) AS n
"""

# --- relationships --------------------------------------------------------
# `from_year` is part of the relationship key: a driver can return to a team
# later, and that is a second spell, not an edit of the first one.
_DROVE_FOR = """
UNWIND $rows AS row
MATCH (d:Driver {driver_id: row.driver})
MATCH (t:Team {team_id: row.team})
MERGE (d)-[r:DROVE_FOR {from_year: row.from_year}]->(t)
SET r.to_year = row.to_year, r.role = row.role
RETURN count(*) AS n
"""

# A title is its own node, not a property of the winner: both a Driver and a
# Team can win one, it belongs to a season, and it is what a question like
# "who was champion in year X" starts from.
_TITLES = """
UNWIND $rows AS row
MERGE (ti:Title:Seed {title_id: row.title_id})
SET ti.type = row.type, ti.year = row.season, ti.points = row.points
WITH row, ti
MATCH (s:Season {year: row.season})
MERGE (ti)-[:AWARDED_IN]->(s)
RETURN count(*) AS n
"""

# The winner is a Driver (WDC) or a Team (WCC); one statement each, so both
# can start from an indexed lookup instead of an unlabelled scan.
_TITLE_WON_BY_DRIVER = """
UNWIND $rows AS row
WITH row WHERE row.driver IS NOT NULL
MATCH (ti:Title {title_id: row.title_id})
MATCH (d:Driver {driver_id: row.driver})
MERGE (d)-[:WON]->(ti)
RETURN count(*) AS n
"""

_TITLE_WON_BY_TEAM = """
UNWIND $rows AS row
WITH row WHERE row.team IS NOT NULL
MATCH (ti:Title {title_id: row.title_id})
MATCH (t:Team {team_id: row.team})
MERGE (t)-[:WON]->(ti)
RETURN count(*) AS n
"""

# A finishing position is a fact about (driver x race x team), so it cannot be
# a property of any one of them: RaceResult is the reified n-ary relationship.
_RESULTS = """
UNWIND $rows AS row
MATCH (d:Driver {driver_id: row.driver})
MATCH (g:GrandPrix {gp_id: row.gp})
MATCH (t:Team {team_id: row.team})
MERGE (r:RaceResult:Seed {result_id: row.gp + ':' + row.driver})
SET r.position = row.position, r.grid = row.grid, r.points = row.points,
    r.status = row.status, r.fastest_lap = row.fastest_lap,
    r.classified = row.position IS NOT NULL
MERGE (d)-[:ACHIEVED]->(r)
MERGE (r)-[:AT_RACE]->(g)
MERGE (r)-[:FOR_TEAM]->(t)
RETURN count(*) AS n
"""

# --- derived edges --------------------------------------------------------
# Shortcuts that are implied by the data above. They are stored (not computed
# on every query) because they are the hops a question actually walks, and
# recomputing them on each `graph seed` keeps them consistent.

_DERIVE_ENTERED = """
MATCH (t:Team)-[:FIELDED]->(:Car)-[:RACED_IN]->(s:Season)
MERGE (t)-[:ENTERED]->(s)
RETURN count(*) AS n
"""

# Stored in one direction only (lower driver_id -> higher). Being teammates is
# symmetric, so the direction carries no meaning and queries must traverse it
# without an arrow: `(a)-[:TEAMMATE_OF]-(b)`.
# An open-ended spell (`to_year: null`) is closed at $last_year, the last
# season in the seed file -- "still there" has to end somewhere to intersect.
_DERIVE_TEAMMATES = """
MATCH (a:Driver)-[ra:DROVE_FOR]->(t:Team)<-[rb:DROVE_FOR]-(b:Driver)
WHERE a.driver_id < b.driver_id
WITH a, b, t,
     [y IN range(ra.from_year, coalesce(ra.to_year, $last_year))
      WHERE y >= rb.from_year AND y <= coalesce(rb.to_year, $last_year)
     ] AS shared
WHERE size(shared) > 0
MERGE (a)-[m:TEAMMATE_OF {team_id: t.team_id}]->(b)
SET m.years = shared
RETURN count(*) AS n
"""

# name in the report -> (key in the JSON, statement)
_LOADERS: list[tuple[str, str, str]] = [
    ("seasons", "seasons", _SEASONS),
    ("power_units", "power_units", _POWER_UNITS),
    ("teams", "teams", _TEAMS),
    ("drivers", "drivers", _DRIVERS),
    ("circuits", "circuits", _CIRCUITS),
    ("cars", "cars", _CARS),
    ("grands_prix", "grands_prix", _GRANDS_PRIX),
    ("drove_for", "drove_for", _DROVE_FOR),
    ("titles", "titles", _TITLES),
    ("titles_won_by_driver", "titles", _TITLE_WON_BY_DRIVER),
    ("titles_won_by_team", "titles", _TITLE_WON_BY_TEAM),
    ("results", "results", _RESULTS),
]


def seed_file() -> Path:
    return get_settings().graph_dir / "seed" / "f1-seed.json"


def load_seed_graph(path: Path | None = None) -> dict[str, int]:
    """Load the fictional domain graph. Safe to re-run (MERGE everywhere)."""
    path = path or seed_file()
    if not path.exists():
        raise FileNotFoundError(f"Seed file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))

    loaded: dict[str, int] = {}
    for name, key, cypher in _LOADERS:
        rows = data.get(key, [])
        # Optional keys (a Title has either a driver or a team) must still be
        # present as None, otherwise Cypher sees a missing parameter.
        keys = {k for row in rows for k in row}
        rows = [{k: row.get(k) for k in keys} for row in rows]
        loaded[name] = write_batched(cypher, rows)

    last_year = max(s["year"] for s in data["seasons"])
    loaded["derived_entered"] = query(_DERIVE_ENTERED)[0]["n"]
    loaded["derived_teammate_of"] = query(
        _DERIVE_TEAMMATES, last_year=last_year)[0]["n"]
    return loaded


def clear_seed_graph() -> int:
    """Delete every :Seed node (the fictional data), leaving the corpus."""
    return query("MATCH (n:Seed) DETACH DELETE n "
                 "RETURN count(*) AS deleted")[0]["deleted"]
