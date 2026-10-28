# Séma-terv — Formula 1 korpusz (GraphRAG, 2. hét)

Ez a dokumentum a gráf **tervét** írja le: milyen csomópont- és kapcsolattípusok
vannak, melyik él melyik irányban hordoz jelentést, és mi lett tulajdonság
a külön csomópont helyett. A séma két, szándékosan elkülönített rétegből áll:

| Réteg | Mi hozza létre | Valódi vagy kitalált |
|---|---|---|
| **Dokumentum-gráf** | `naive-rag graph load` a `corpus/`-ból | valódi (23 Wikipédia-dokumentum) |
| **Szakterületi gráf** | `naive-rag graph seed` a `graph/seed/f1-seed.json`-ból | kitalált (`:Seed` címkével jelölve) |

A két réteg a 2. héten **nincs összekötve**: a dokumentumok valódiak, a
szakterületi entitások kitaláltak, így egy `(:Document)-[:MENTIONS]->(:Driver)`
él hamis állítás lenne. A 3. heti extrakció fogja a valódi entitásokat
ugyanezekre a címkékre felvenni, és a chunkokhoz kötni — a dokumentum-gráf
`Section` és `Chunk` csomópontjai pontosan ezt a felakasztási pontot adják.
A `:Seed` címke azért kell, hogy a kitalált adat akkor is megkülönböztethető
(és egy paranccsal törölhető) maradjon: `naive-rag graph clear seed`.

A tényleges, lefuttatott sémát a `naive-rag graph stats` írja ki, a
lekérdezések kimenetét pedig a [`../graph/query-results.md`](../graph/query-results.md)
tartalmazza.

---

## 1. Dokumentum-gráf

```
(:Corpus)-[:HAS_DOCUMENT]->(:Document)-[:CONTAINS]----->(:Chunk)
                                     -[:HAS_SECTION]-->(:Section)-[:CONTAINS]->(:Chunk)
                                                        (:Chunk)-[:NEXT_CHUNK]->(:Chunk)
```

### Csomóponttípusok

| Címke | Kulcs | Tulajdonságok | Miért külön csomópont |
|---|---|---|---|
| `Corpus` | `name` | `chunk_size`, `chunk_overlap`, `run_id`, `created_at`, `updated_at` | Gyökér, amiről minden globális lekérdezés indul (`MATCH (:Corpus {name: $corpus})-[:HAS_DOCUMENT]->...`). Egyben rögzíti, **milyen paraméterekkel** készült a betöltés — a chunk-méret a gráf tulajdonsága, nem a kódé. |
| `Document` | `doc_id` | `title`, `file`, `format`, `category`, `url`, `source`, `license`, `revision_id`, `revision_timestamp`, `n_chars`, `n_chunks`, `n_pages` | A `metadata.json` egy sora. A `n_chars` a **forrásszövegen** mért hossz, nem a chunkok összege (az overlap duplán számolna — lásd Q2 `overlap_overhead_pct` oszlopát). |
| `Section` | `section_id` = `<doc_id>::<útvonal>` | `path` (pl. `Lewis Hamilton > Early life`), `title`, `level`, `ordinal`, `doc_id` | Itt a legfontosabb döntés. A `section` az 1. héten **chunk-tulajdonság** volt; most külön csomópont, mert (a) sok chunk osztozik rajta, ezért az ismétlés redundancia, (b) a 3. héten az entitásokat szekció-szinten lesz értelme felakasztani („Hamilton 2008-as szezonja" szekció), (c) így a szekció maga is lehet a bejárás csomópontja. A `path` string **megmarad a chunkon is**, mert a forrásmegjelölés (`rag.py::_location`) egyetlen mezőt vár. |
| `Chunk` | `chunk_id` = `<doc_id>#<n>` | `text`, `ordinal`, `page`, `section`, `start_index`, `source`, `n_chars`, `n_words`, `doc_id` | A visszakereshető egység. A `chunk_id` **ugyanaz, mint a Qdrant payloadban**, mert ugyanaz a `ingest.load_and_chunk()` állítja elő — így egy vektortalálat leképezés nélkül megkereshető a gráfban. |

### Kapcsolattípusok és az él iránya

| Él | Irány jelentése | Miért így |
|---|---|---|
| `(:Corpus)-[:HAS_DOCUMENT]->(:Document)` | tartalmazás, egész → rész | Egy dokumentum egy korpuszhoz tartozik. |
| `(:Document)-[:CONTAINS]->(:Chunk)` | egész → rész | A visszafelé irány („melyik dokumentumból való ez a chunk") ugyanezen az élen, nyíl nélkül kérdezhető. |
| `(:Document)-[:HAS_SECTION]->(:Section)` | egész → rész | — |
| `(:Section)-[:CONTAINS]->(:Chunk)` | egész → rész | Egy chunk pontosan egy szekcióhoz tartozik (vagy egyhez sem, ha a címsor előtt áll). |
| `(:Chunk)-[:NEXT_CHUNK]->(:Chunk)` | **sorrend**, előző → következő | Ez az egyetlen él, ahol az irány önálló jelentést hordoz: `a -[:NEXT_CHUNK]-> b` azt mondja, hogy `b` **követi** `a`-t az olvasási sorrendben. Ebből lesz később a „találat kibővítése a szomszédaival". Megfordítva értelmetlen lenne. |

### Mi lett tulajdonság, és miért nem csomópont

- **`page` (oldalszám)** → tulajdonság. Felmerült `(:Document)-[:HAS_PAGE]->(:Page)-[:CONTAINS]->(:Chunk)`, de egy oldal ebben a korpuszban nem hordoz saját jelentést, nincs rá kapcsolat, és semelyik kérdés nem indul oldalról. Egy soha be nem járt csomópont csak lassítja a bejárást.
- **`format`, `category`** → tulajdonság, holott kézenfekvő lenne `(:Document)-[:HAS_FORMAT]->(:Format)`. Alacsony számosságú (5 formátum, 4 kategória), nem kapcsolódik semmi máshoz, és az aggregáláshoz (Q1) a `GROUP BY` tulajdonságon ugyanúgy működik, indexszel.
- **`text`** → tulajdonság. A teljes chunk-szöveg a gráfban van, nem csak az azonosítója: így egy gráf-alapú lekérdezés önmagában is tud kontextust adni az LLM-nek, nem kell hozzá a vektortár.
- **`n_chars` / `n_words`** → tulajdonság, és **betöltéskor számolt**, nem lekérdezéskor. A Q3/Q4 szemét-chunk kereséshez kell, és Cypherben a szóhatár-számolás (`split(text, ' ')`) a sortöréseket is szónak venné.

---

## 2. Szakterületi séma (F1-fogalmak)

Nem `PERSON / ORG / GEO`, hanem a korpusz saját fogalmai: pilóta, csapat,
szezon, nagydíj, pálya, autó, erőforrás, bajnoki cím, futameredmény.

```
(:Driver)-[:DROVE_FOR {from_year, to_year, role}]->(:Team)-[:FIELDED]->(:Car)-[:POWERED_BY]->(:PowerUnit)
(:Driver)-[:TEAMMATE_OF {team_id, years}]-(:Driver)                 (:Car)-[:RACED_IN]->(:Season)
(:Driver)-[:ACHIEVED]->(:RaceResult)-[:AT_RACE]->(:GrandPrix)-[:ROUND_OF]->(:Season)
                       (:RaceResult)-[:FOR_TEAM]->(:Team)          (:GrandPrix)-[:HELD_AT]->(:Circuit)
(:Driver)-[:WON]->(:Title)-[:AWARDED_IN]->(:Season)<-[:ENTERED]-(:Team)-[:WON]->(:Title)
```

### Csomóponttípusok

| Címke | Kulcs | Tulajdonságok |
|---|---|---|
| `Driver` | `driver_id` | `name`, `nationality`, `born`, `race_number` |
| `Team` | `team_id` | `name`, `base`, `founded`, `principal` |
| `Season` | `year` | `rounds`, `regulation_era` |
| `GrandPrix` | `gp_id` | `name`, `round`, `date`, `laps` |
| `Circuit` | `circuit_id` | `name`, `country`, `length_km`, `turns` |
| `Car` | `car_id` | `model`, `year` |
| `PowerUnit` | `name` | `manufacturer`, `layout` |
| `Title` | `title_id` | `type` (`WDC`/`WCC`), `year`, `points` |
| `RaceResult` | `result_id` = `<gp_id>:<driver_id>` | `position`, `grid`, `points`, `status`, `fastest_lap`, `classified` |

### Kapcsolattípusok és az él iránya

| Él | Irány jelentése |
|---|---|
| `(:Driver)-[:DROVE_FOR]->(:Team)` | **Aszimmetrikus**: a pilóta versenyez a csapatnak, nem fordítva. A „kik voltak a csapattársak" kérdés ezért nem egy irányba haladó út, hanem középen találkozás: `(a)-[:DROVE_FOR]->(t)<-[:DROVE_FOR]-(b)` (lásd Q6). |
| `(:Driver)-[:TEAMMATE_OF]-(:Driver)` | **Szimmetrikus**, ezért az irány *nem* hordoz jelentést. Neo4j-ben nincs irány nélküli él, ezért egy irányban tároljuk (kisebb `driver_id` → nagyobb), és a lekérdezés **nyíl nélkül** járja be. Ezt a `graph_seed.py` vezeti le a `DROVE_FOR` idősávok metszetéből. |
| `(:Team)-[:FIELDED]->(:Car)` | A csapat nevezi az autót. |
| `(:Car)-[:POWERED_BY]->(:PowerUnit)` | Az autó kapja az erőforrást a szállítótól. |
| `(:Car)-[:RACED_IN]->(:Season)` / `(:Team)-[:ENTERED]->(:Season)` | Rész → az idősáv, amiben szerepel. Az `ENTERED` **levezetett** él (`FIELDED` + `RACED_IN`), azért tárolt, mert ez az a hop, amit a kérdések járnak. |
| `(:GrandPrix)-[:ROUND_OF]->(:Season)` | A futam a szezon egy fordulója. |
| `(:GrandPrix)-[:HELD_AT]->(:Circuit)` | Esemény → helyszín. Fordítva nem igaz: egy pálya több futamnak is helyet ad (a Pannonia Ring 2031-ben és 2032-ben is). |
| `(:Driver)-[:ACHIEVED]->(:RaceResult)` · `(:RaceResult)-[:AT_RACE]->(:GrandPrix)` · `(:RaceResult)-[:FOR_TEAM]->(:Team)` | Az eredmény „küllői". |
| `(:Driver\|:Team)-[:WON]->(:Title)` | Győztes → cím. |
| `(:Title)-[:AWARDED_IN]->(:Season)` | A cím egy szezonhoz tartozik. |

### Mi lett külön csomópont, és miért

- **`RaceResult` — reifikált n-áris kapcsolat.** Egy helyezés nem a pilóta, nem
  a futam és nem a csapat tulajdonsága, hanem a **hármasuké**: „Varga a 2031-es
  Pannonia Nagydíjon a Vertex színeiben 1. lett". Ezt éllel nem lehet leírni
  (egy él két végpontot köt), ezért a tény maga lett csomópont, három küllővel.
  Ez teszi a Q8 aggregálást egyáltalán lehetségessé.
- **`Title` — külön csomópont, nem a pilóta `championships: 7` tulajdonsága.**
  Mert (a) a WDC-t pilóta, a WCC-t csapat nyeri, tehát a tulajdonság két
  különböző címkén ismétlődne, (b) a címhez tartozik szezon és pontszám,
  (c) a „ki volt a 2016-os bajnok" kérdés a *címről* indul és a győztes felé
  halad — pontosan az a lépés, amit az 1. heti baseline a Q04/Q05-nél
  elvétett. Egy tulajdonságon ez a kérdés csak teljes szkenneléssel válaszolható.
- **`PowerUnit` — külön csomópont, nem `Car.engine` string.** Mert több csapat
  osztozik ugyanazon a szállítón (a seedben a Brennan BD-9-en kettő is), és
  ez a megosztás maga az információ: ez a Q7 3-hopos útjának a vége.
- **`Car` — külön csomópont, nem `Team.car_2031`.** Évente más, és saját
  kapcsolatai vannak (erőforrás, szezon).

### Mi maradt tulajdonság, és miért

- **`DROVE_FOR.from_year` / `to_year` / `role`** → élen lévő tulajdonság, nem
  külön `Spell`/`Contract` csomópont. A szerződés csak két dolgot köt össze
  (pilóta + csapat), tehát elfér élen — ellentétben a `RaceResult`-tal, ami
  hármat. **A `from_year` része a kapcsolat kulcsának**, mert egy pilóta
  visszatérhet egy csapathoz: az a *második* szerepvállalás, nem az első
  felülírása (`MERGE (d)-[r:DROVE_FOR {from_year: ...}]->(t)`).
  A `to_year = null` azt jelenti, hogy még tart.
- **`Driver.nationality`** → tulajdonság, nem `(:Country)` csomópont. Ebben a
  korpuszban semelyik kérdés nem köt össze két pilótát az állampolgárságán
  keresztül. (Ha ilyen kérdés jönne, ez az első, amit csomóponttá kéne emelni.)
- **`Title.points`** → tulajdonság, pedig a `RaceResult`-okból is összegezhető.
  Szándékos redundancia: a Q8 a kettőt **összeveti**, így a lekérdezés egyben
  konzisztencia-ellenőrzés is.
- **`Circuit.length_km`, `turns`; `GrandPrix.laps`** → tulajdonság, mert nem
  kapcsolódnak semmihez.

---

## 3. Kulcsok és idempotencia

Minden címkének pontosan **egy üzleti kulcsa** van (`graph_schema.py :: UNIQUE_KEYS`),
és minden betöltő erre `MERGE`-öl. Ebből következik, hogy a betöltés
újrafuttatásra nem duplikál — nem azért, mert a szkript ellenőrzi, hanem mert
az adatbázis-megszorítás nem engedi. Két különböző stratégia:

- **Seed (`graph seed`):** tiszta `MERGE` + `SET`. Kétszer lefuttatva nincs
  változás; a JSON egy értékét átírva a meglévő csomópont **frissül**.
- **Dokumentum-gráf (`graph load`):** `MERGE` + *mark-and-sweep*. Minden
  csomópont megkapja a futás `run_id`-ját, és a végén törlődik minden olyan
  `Document`/`Section`/`Chunk`, amin régi bélyeg maradt. Erre azért van szükség,
  mert más chunk-mérettel újratöltve a `chunk_id`-k halmaza *megváltozik* —
  a puszta `MERGE` ilyenkor a régi chunkokat bent hagyná (ez pontosan az a
  hiba, ami az 1. héten a Qdranttal megtörtént).

Indexek a ténylegesen használt elérési utakhoz: `Chunk(doc_id, ordinal)`,
`Document(category)`, `Document(format)`, `Driver(name)`, `Team(name)`, valamint
egy fulltext index a `Chunk.text`-en (a hibrid keresés lexikális fele, amit a
vektortár nem tud — a 2. heti lekérdezések még nem használják).

## 4. Ismert korlátok

- A szakterületi réteg **kitalált adat**; a valódi korpuszból a 3. hétig semmi
  nincs kinyerve, így a két réteg között nincs él.
- A `TEAMMATE_OF` és az `ENTERED` levezetett él **tárolt**, nem nézet: ha a
  `DROVE_FOR` élek kézzel változnának, újra kellene futtatni a `graph seed`-et.
  A nyitott (`to_year: null`) idősávokat a seed utolsó szezonjánál zárjuk le.
- A `Section` csak ott jön létre, ahol a betöltő Markdown-címsort talált, tehát
  PDF-nél egyáltalán nem (ott `page` van helyette) — lásd Q1.
- Egy chunk a `section` útvonalat tulajdonságként **és** élként is hordozza.
  Tudatos redundancia a forrásmegjelölés kedvéért, de két helyen kell karban
  tartani.
