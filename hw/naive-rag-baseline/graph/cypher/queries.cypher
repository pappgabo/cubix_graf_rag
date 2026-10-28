// Week 2 — 8 queries about the structure of this corpus and the seed graph.
//
// Run them all and write the output to graph/query-results.md:
//     uv run naive-rag graph query
// Run one:
//     uv run naive-rag graph query --only Q4
//
// Format read by graph_queries.py:
//   // === <id> | <title> ===     starts a query
//   // <text>                     description (what the answer should tell us)
//   // @param <name> = <value>    query parameter, overridable from the CLI
//   <cypher> ;                    the statement
//
// $corpus defaults to the `corpus_name` setting, so the queries stay scoped to
// the loaded corpus even if a second one is added later.


// === Q1 | Corpus overview per file format ===
// Aggregation over the whole document graph: how the 23 documents and their
// chunks are distributed, and how many chunks carry location metadata
// (page or section). This re-checks week 1's "96-100% located" claim
// against the graph instead of against the ingest log.
// @param corpus = f1-wikipedia
MATCH (:Corpus {name: $corpus})-[:HAS_DOCUMENT]->(d:Document)-[:CONTAINS]->(c:Chunk)
WITH d, count(c) AS chunks,
     sum(CASE WHEN c.page IS NOT NULL THEN 1 ELSE 0 END) AS with_page,
     sum(CASE WHEN c.section IS NOT NULL THEN 1 ELSE 0 END) AS with_section,
     sum(CASE WHEN c.page IS NOT NULL OR c.section IS NOT NULL
              THEN 1 ELSE 0 END) AS located
RETURN d.format AS format,
       count(d) AS documents,
       sum(chunks) AS chunks,
       sum(d.n_chars) AS source_chars,
       sum(with_page) AS chunks_with_page,
       sum(with_section) AS chunks_with_section,
       round(100.0 * sum(located) / sum(chunks), 1) AS located_pct
ORDER BY chunks DESC;


// === Q2 | Longest documents and their chunk count ===
// "How many chunks belong to the longest document?" Length is measured on the
// source text (d.n_chars), not on the sum of chunk lengths, because the
// 75-character overlap would count the boundaries twice.
// @param corpus = f1-wikipedia
MATCH (:Corpus {name: $corpus})-[:HAS_DOCUMENT]->(d:Document)-[:CONTAINS]->(c:Chunk)
WITH d, count(c) AS chunks, sum(c.n_chars) AS chunk_chars
ORDER BY d.n_chars DESC
LIMIT 5
RETURN d.doc_id AS doc_id, d.format AS format, d.category AS category,
       d.n_chars AS source_chars, chunks,
       round(toFloat(chunk_chars) / chunks, 1) AS avg_chunk_chars,
       round(100.0 * chunk_chars / d.n_chars - 100, 1) AS overlap_overhead_pct;


// === Q3 | Shortest documents ===
// The other end of the same list: a document with very few chunks, or with a
// suspiciously small average chunk, is where a loader silently dropped text.
// @param corpus = f1-wikipedia
MATCH (:Corpus {name: $corpus})-[:HAS_DOCUMENT]->(d:Document)
OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk)
WITH d, count(c) AS chunks, min(c.n_chars) AS shortest_chunk,
     round(avg(c.n_chars), 1) AS avg_chunk_chars
ORDER BY d.n_chars ASC
LIMIT 5
RETURN d.doc_id AS doc_id, d.format AS format, d.category AS category,
       d.n_chars AS source_chars, chunks, avg_chunk_chars, shortest_chunk;


// === Q4 | Empty or junk chunks after loading ===
// Classifies every chunk that is unlikely to be answerable on its own. These
// are the chunks that still take up a top-k slot at retrieval time, so the
// count matters for the baseline, not just for tidiness.
// @param corpus = f1-wikipedia
MATCH (:Corpus {name: $corpus})-[:HAS_DOCUMENT]->(:Document)-[:CONTAINS]->(c:Chunk)
WITH c, CASE
       WHEN trim(c.text) = ''                      THEN '1 empty'
       WHEN NOT c.text =~ '(?s).*\\p{L}.*'          THEN '2 no letters at all'
       WHEN c.n_words < 5                          THEN '3 fewer than 5 words'
       WHEN trim(c.text) =~ '(?s)#{1,6} [^\\n]*'    THEN '4 heading only'
       ELSE NULL
     END AS problem
WHERE problem IS NOT NULL
RETURN problem, count(*) AS chunks,
       round(avg(c.n_chars), 1) AS avg_chars,
       collect(c.chunk_id)[0..4] AS examples
ORDER BY problem;


// === Q5 | Is the NEXT_CHUNK reading order intact? ===
// A document with n chunks must have exactly n-1 NEXT_CHUNK edges, and the
// chain must start at ordinal 0. If this is wrong, "widen a vector hit to its
// neighbours" would silently return the wrong passage.
// @param corpus = f1-wikipedia
MATCH (:Corpus {name: $corpus})-[:HAS_DOCUMENT]->(d:Document)
OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk)
WITH d, count(c) AS chunks
OPTIONAL MATCH (d)-[:CONTAINS]->(:Chunk)-[r:NEXT_CHUNK]->(:Chunk)
WITH d, chunks, count(r) AS edges
OPTIONAL MATCH (d)-[:CONTAINS]->(head:Chunk)
WHERE NOT (:Chunk)-[:NEXT_CHUNK]->(head)
WITH d, chunks, edges, count(head) AS chain_starts
RETURN count(d) AS documents,
       sum(chunks) AS chunks,
       sum(edges) AS next_chunk_edges,
       sum(CASE WHEN edges = chunks - 1 AND chain_starts = 1
                THEN 1 ELSE 0 END) AS intact_chains,
       collect(CASE WHEN edges <> chunks - 1 OR chain_starts <> 1
                    THEN d.doc_id END)[0..5] AS broken_examples;


// === Q6 | Seed, 2 hops: who were the teammates ===
// Driver -> Team <- Driver. The hop back is a DROVE_FOR edge traversed
// against its direction: "drove for" only makes sense driver -> team, so a
// shared employer has to be found by meeting in the middle.
// The 2 hops alone only prove "was at the same team at some point", so the
// spells have to be intersected as well. `also_teammate_of` is the derived
// TEAMMATE_OF edge, traversed without an arrow because the relation is
// symmetric -- it should agree with the computed years.
// @param driver = Mateo Varga
// @param last_year = 2032
MATCH path = (d:Driver {name: $driver})-[spell:DROVE_FOR]->(t:Team)
             <-[mate_spell:DROVE_FOR]-(mate:Driver)
WITH d, t, mate, spell, mate_spell, length(path) AS hops,
     [y IN range(spell.from_year, coalesce(spell.to_year, $last_year))
      WHERE y >= mate_spell.from_year
        AND y <= coalesce(mate_spell.to_year, $last_year)] AS shared_years
RETURN d.name AS driver, t.name AS team, hops,
       mate.name AS other_driver, mate_spell.role AS their_role,
       mate_spell.from_year AS their_from_year,
       coalesce(toString(mate_spell.to_year), 'current') AS their_to_year,
       shared_years,
       EXISTS { (d)-[:TEAMMATE_OF]-(mate) } AS also_teammate_of
ORDER BY their_from_year, other_driver;


// === Q7 | Seed, 3 hops: from a driver to the engine behind them ===
// Driver -> Team -> Car -> PowerUnit. Nothing in this chain is a property of
// the driver, yet "which engine did X race with" is answerable in one
// traversal -- this is the hop a naive RAG cannot make.
MATCH path = (d:Driver)-[:DROVE_FOR]->(t:Team)-[:FIELDED]->(car:Car)
             -[:POWERED_BY]->(pu:PowerUnit)
RETURN d.name AS driver, t.name AS team, car.model AS car, car.year AS year,
       pu.name AS power_unit, pu.manufacturer AS manufacturer,
       length(path) AS hops
ORDER BY year, team, driver;


// === Q8 | Seed, aggregation: constructors' standings rebuilt from results ===
// Sums the reified RaceResult nodes per team and season, then checks the
// total against the Title node. Two independent paths to the same fact, so
// the query also validates that the seed data is internally consistent.
MATCH (s:Season)<-[:ROUND_OF]-(g:GrandPrix)<-[:AT_RACE]-(r:RaceResult)
      -[:FOR_TEAM]->(t:Team)
WITH s, t, count(r) AS entries, sum(r.points) AS points,
     sum(CASE WHEN r.position = 1 THEN 1 ELSE 0 END) AS wins,
     sum(CASE WHEN r.classified THEN 0 ELSE 1 END) AS retirements
OPTIONAL MATCH (t)-[:WON]->(title:Title {type: 'WCC'})-[:AWARDED_IN]->(s)
RETURN s.year AS season, t.name AS team, entries, wins, retirements, points,
       title.points AS title_node_points,
       title IS NOT NULL AS won_constructors_title
ORDER BY season, points DESC;
