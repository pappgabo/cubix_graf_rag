# Extrakció és lokális keresés

Ez a fájl a beadandó kötelező pontjait köti konkrét fájlhoz vagy futtatási eredményhez. Ami nem futott le, az nincs késznek jelölve.

## Jelenlegi gráf

A beadott gráf a 23 dokumentumos korpusz. A `corpus/driver-charles-leclerc.html` megvan. A chunkméret 1200 karakter, az átfedés 100 karakter. A betöltött réteg: 23 dokumentum, 544 section, 1651 chunk, 1628 `NEXT_CHUNK`. Az extrakció `graph/corpus/extraction-reuse-1200-23`: 1651 strukturálisan sikeres rekord, 0 hibás, 315 üres siker.

A Neo4j-ben 2761 `:Extracted` csomópont, 4326 szakterületi él és 10782 `MENTIONS` él van. A 29 `:Seed` csomópont külön marad. Az entitásvektorok a név és a leírás együttesei, modell `text-embedding-3-small`, dimenzió 1536.

A minőségi számok és a példák: `graph/corpus/quality-report-section-1200-23.md`. Sűrű chunk: `team-williams-racing#31`, 30 entitás és 37 kapcsolat. Ritka chunk: `driver-charles-leclerc#14`, a forrás a `## FIA Formula 2 (2017)` címsor, üres eredmény, nem hibás extrakció. Sémán kívüli típus nincs. Pontosan egy chunkban szereplő összevont entitás: 1967. A legnagyobb fokszám 194, egyedül `Team:mclaren`.

Deduplikáció ugyanebből a 1651 rekordból, a meglévő összevonással. Előtte az előfordulási gráf: 10782 csomópont, 6533 él, legnagyobb gyengén összefüggő komponens 30. Utána az összevont gráf: 2761 csomópont, 4326 él, legnagyobb komponens 1896. Az éles gráf a méréshez nem változott.

Megnevezett, validáción átment hiba: `driver-sebastian-vettel#21`. A forrás csak a `## 2012: Triple World Champion following Alonso title duel` címsor. A kimenet `Title` néven Title entitást gyárt, és `WON` valamint `AWARDED_IN` éllel köti a pilótához és a 2012-es szezonhoz. A hiba nincs javítva.

A Q01–Q13 összevetés a jelenlegi gráfon lefutott: `docs/osszehasonlitas-section-1200-23.md`, naplója `docs/osszehasonlitas-section-1200-23-run.json`. Mind a 13 kérdés szerepel. Üres horgonylista nem volt; a napló mind a 13 kérdésnél `model_called: true`, tehát 13 válaszhívás készült a `gpt-4o-mini` modellel. A Q04, Q05, Q09 és Q13 válasza az elutasító mondat. A Q04–Q08 multi-hop kérdések külön szakaszban vannak, a meglévő értékelési szabállyal. A baseline `baseline/answers.json` változatlan. A `docs/osszehasonlitas.md` a régi 401 entitásos gráf történeti összevetése.

## Történeti Q01–Q08 kör

A következő szakaszok a korábbi, 11 dokumentumos kört írják. A Leclerc-fájl hiánya és a 401 entitásos Neo4j-számok ennek a körnek az akkori állapota, nem a jelenlegi gráf.

## Adatkör

A feldolgozási kör a `questions.md` Q01–Q08 kérdéseinek Dokumentum mezőiben backtickben megnevezett dokumentumok összes chunkja. A kiválasztás `src/naive_rag/question_scope.py`. A wildcard, például a Q09 `driver-*` kifejezése, nincs kibontva, ezért Q09–Q13 nincs a körben.

A korpusz betöltése után, modellhívás nélkül, a kör:

| doc_id | chunk |
|---|---|
| season-2012-formula-one-world-championship | 229 |
| driver-lewis-hamilton | 199 |
| driver-michael-schumacher | 192 |
| driver-fernando-alonso | 166 |
| driver-sebastian-vettel | 165 |
| driver-valtteri-bottas | 163 |
| driver-nico-rosberg | 132 |
| season-2016-formula-one-world-championship | 106 |
| season-2021-formula-one-world-championship | 106 |
| team-mercedes-benz-in-formula-one | 102 |
| reference-list-of-formula-one-world-drivers-champions | 5 |

11 dokumentum, 1565 chunk. Hiányzó azonosító ebben a listában nincs.

A manifestben szereplő `driver-charles-leclerc.html` hiányzik a korpusz könyvtárból. A betöltő figyelmeztet és kihagyja. Ez a fájl nincs a Q01–Q08 listában, ezért a 1565-öt nem csökkenti. A teljes jelenlegi korpusz 22 dokumentum, 94 forrásoldal és 3639 chunk. A baseline `baseline/answers.json` metaadata 3832 chunkot rögzít. A két lefedettség eltér.

A `graph/pilot/extraction-v3` 10 mentett rekordjából 8 esik a körbe, azonos `gpt-4o-mini` és `f1-pilot-3` bemenettel. Ezek új hívás nélkül bekerültek: 6 sikeres és 2 hibás. A másik kettő, a Ferrari-chunkok, nincs a körben. Új extrakciós hívás: 1557. A rekordok: `graph/corpus/extraction`, 1565 fájl. Összesen 880 strukturálisan sikeres és 685 hibás. A 2 újrahasznált hibás rekord nem lett újrahívva.

## Séma, chunkolás, modellek

- Entitás- és kapcsolattípusok: `src/naive_rag/extraction_models.py`.
- Gráfséma: `docs/graph-schema.md`. A Q6 rétegszűrés nélküli Driver-illesztése változatlan, `src/naive_rag/extraction_load.py` elején dokumentálva.
- Chunk: 500 karakter, 75 átfedés, `src/naive_rag/config.py`. Ugyanez a baseline metaadatában.
- Chat: `gpt-4o-mini`. Embedding: `text-embedding-3-small`. Szolgáltató: OpenAI. Prompt: `f1-pilot-3`.
- Azonosság: `src/naive_rag/extraction_identity.py`. Az aliaslista üres, `graph_merge.ALIAS_MAP`.

## Extrakció és betöltés

A 10 chunkos v3 pilot kész: `graph/pilot/extraction-v3` és `graph/pilot/extraction-summary-v3.md`. Ezek a fájlok ebben a menetben nem változtak.

A betöltő a séma minden entitás- és kapcsolattípusát írhatja, entitásonként leírást és MENTIONS-élt, élenként `origin=extracted` és `source_chunk_ids` listát tárol. A seed azonosítói nem kerülnek az extrahált csomópontokra. A nyers rekord önmagában nem jóváhagyás: `plan_validated_raw` az `accept_validated_raw` jelző nélkül elutasít, és nem ír `approved` státuszt.

A 880 sikeres rekord bekerült a helyi Neo4j-be, a hibás 685 nem. A rekordokra nem került `approved` mező. A betöltés után: 401 `:Extracted` csomópont, 1441 `MENTIONS` él, 580 `origin=extracted` szakterületi él. Ez a 401 és 580 megegyezik az összevont gráf mértékével.

## Minőség és deduplikáció

Lefutott a 10 chunkos piloton: `graph/pilot/quality-report-v3.md` és `graph/pilot/quality-report-v3.json`.

- 10 feldolgozott, 7 strukturálisan sikeres, 3 hibás, 3 sikeres üres chunk.
- A strukturális siker nem szemantikai helyesség.
- Sűrű chunk: `driver-lewis-hamilton#0`, 2 entitás és 1 DROVE_FOR. Forrásszöveg és extrakció a riportban.
- Ritka chunk: `driver-nico-rosberg#64`, 0 entitás. A forrásszöveg a `## 2013–2016` címsor. Ez üres eredmény, nem hibás extrakció.
- Sémán kívüli típus nincs. Elutasított jelöltek: a 2021-es chunkban a Team → Driver DROVE_FOR, valamint két ENTERED kapcsolat évvel. Idézetek a riportban.
- Pontosan egy chunkban szereplő összevont entitás: 5.
- Legnagyobb fokszám 1, döntetlen: `Driver:lewis hamilton`, `GrandPrix:grand prix`, `Season:2021 formula one world championship`, `Team:ferrari`. A fokszám az összevont szakterületi élek száma. A `GrandPrix:grand prix` általános neve minőségi észrevétel, a fokszám ezt nem igazolja helyesnek.
- Az indexelhető hat entitás neve: Lewis Hamilton, Grand Prix, 2021 Formula One World Championship, Ferrari, McLaren-Mercedes Young Driver Programme, Scuderia Ferrari. A program Team típusa a nyers v3 rekordban van; ez a rekord nincs emberi jóváhagyással betöltve.

Deduplikáció ugyanezen a piloton. Előtte egy csomópont egy chunk egy entitása, egy él egy chunk egy kapcsolata. Utána egy csomópont egy `entity_key`, egy él egy `rel_key`. A komponens az irányított gráf gyengén összefüggő komponense: az irány nem számít, a méret csomópontszám, MENTIONS, seed és dokumentumgráf nélkül.

- Előtte: 7 csomópont, 2 él, legnagyobb komponens 2.
- Utána: 6 csomópont, 2 él, legnagyobb komponens 2.

A csökkenés a két chunkban szereplő Lewis Hamilton összevonása. Az élek nem olvadtak össze. Különböző év vagy szerep a tesztben külön él marad: `tests/test_domain_round.py`.

A Q01–Q08 kör riportja: `graph/corpus/quality-report.md` és `graph/corpus/quality-report.json`.

- 1565 feldolgozott, 880 strukturálisan sikeres, 685 hibás, 517 sikeres üres chunk.
- Sűrű chunk: `reference-list-of-formula-one-world-drivers-champions#1`, 16 entitás, 15 kapcsolat.
- Ritka chunk: `driver-fernando-alonso#101`, 0 entitás. A forrásszöveg a `## McLaren Racing (2019)` címsor. Üres eredmény, nem hibás extrakció.
- Pontosan egy chunkban szereplő összevont entitás: 237.
- Legnagyobb fokszám 42, egyedül `Season:2012`. A fokszám szerkezeti, a 2012-es szezon fontosságát nem igazolja.
- Deduplikáció előtt: 1442 csomópont, 726 él, legnagyobb gyengén összefüggő komponens 13. Utána: 401 csomópont, 580 él, legnagyobb komponens 283. Az aliaslista üres.
- Konkrét, validáción átment szemantikai hiba: `driver-sebastian-vettel#58`. A „Triple World Champion” kifejezés Title típusú entitás lett, és `AWARDED_IN` éllel a 2012-es szezonhoz kötődött. A mondat összesített győzelmi szám, nem egy bajnoki cím.

## Lokális keresés és összevetés

A lánc a projektben van: `entity_index.py`, `local_search.py`. A tanórai `Videók/4.hét/codes_4week/local-search` kód nincs importálva. Az embedding bemenete a név és a leírás együtt. A keresés az összevont extrahált kulcsokon megy. Üres horgony esetén a válasz a rögzített elutasító mondat, modellhívás nélkül.

A 401 összevont entitás embeddingje elkészült: `graph/corpus/entity-index.json`. A válaszgenerálás csak a kiválasztott forrásszövegekből mondhat nevet vagy számot, és a riport minden kimondott nevet és számot visszaellenőriz a mellékelt részleteken: `unsupported_claims`.

A bizonyítékválogatás az élek chunkjai mellett a kiválasztott entitások saját forrásait is figyelembe veszi, entitásonként egy lefoglalt részlettel, legfeljebb hattal. A kérdést megválaszoló mondat jellemzően egy entitás chunkján van, nem egy kapcsolat chunkján; emiatt utasított el a korábbi futás mindent.

Futások: `docs/osszehasonlitas-elso-futas.md`, `docs/osszehasonlitas-masodik-futas.md`, `docs/osszehasonlitas-harmadik-futas.md`, és a lezáró `docs/osszehasonlitas.md` a `docs/osszehasonlitas-run.json` naplóval.

A lezáró futás: 9 elutasítás és 4 válasz. Mind a 4 válasz minden neve és száma szerepel a mellékelt forrásszövegekben. A `questions.md` gold értékeivel összevetve a Q01 és a Q09 helyes, a Q10 hiányos, a Q04 téves: a 2016-os bajnokot nevezte meg a csapattársa helyett.

A Q01–Q03 egyszerű kérdés, a Q04–Q08 multi-hop, külön szakaszban. A Q09–Q13 a 11 dokumentumos körön futott. Javulás nincs állítva, és az összevetés a 3832 és a 3639 chunkos eltérés miatt nem kontrollált. A baseline fájl `baseline/answers.json` változatlan.

Megmaradó adatminőségi korlát: a gráf a 3639 chunkból csak 363-at ér el, mert 685 rekord strukturálisan hibás és 517 sikeres rekord üres. A Q08-hoz egyetlen elérhető chunk sem tartalmazza egyszerre Bottast és Rosberget, pedig a korpuszban tíz ilyen van. A Q04 második lépéséhez tizenegy korpuszchunkból egy érhető el. Ez extrakciós hiány, nem visszakeresési hiba.

## Ellenőrzés

Adatbázis nélküli tesztek: `python -m unittest discover -s tests -q` a `src` könyvtárral a `PYTHONPATH`-on. A Neo4j-t és a modelleket nem hívják.

| Pont | Hol látszik |
|---|---|
| Jelenlegi korpusz és Leclerc-fájl | ennek a fájlnak a jelenlegi gráf szakasza |
| Séma és provenance | `extraction_models.py`, `extraction_load.py` |
| Chunkolás és modellek | `config.py`; a jelenlegi chunk 1200/100 |
| Nyers extrakció | `graph/corpus/extraction-reuse-1200-23` |
| Minőségi számok és a megnevezett hiba | `graph/corpus/quality-report-section-1200-23.md` |
| Deduplikációs számok | ugyanennek a riportnak a deduplikáció szakasza |
| Keresési lánc | `local_search.py`; a Neo4j-index a jelenlegi 2761 entitás |
| Q01–Q13 összevetés | `docs/osszehasonlitas-section-1200-23.md`, a jelenlegi gráfon; a `docs/osszehasonlitas.md` történeti |
| Neo4j, provenance-szal | 2761 Extracted, 10782 MENTIONS, 4326 szakterületi él |

A `graph/corpus/quality-report.md` és a 401 entitásos Neo4j-szám a történeti Q01–Q08 köré.

## Parancsok

Pilot riport, modell és adatbázis nélkül:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m naive_rag.quality_report
.\.venv\Scripts\python.exe -m naive_rag.compare_baseline
.\.venv\Scripts\python.exe -m naive_rag.entity_index --extraction-dir graph\pilot\extraction-v3 --out graph\pilot\entity-index.json
```

Az utolsó parancs `--run` nélkül 6 entitást számol, és nem hív embeddinget. A Q01–Q08 kör parancsai lefutottak:

```powershell
.\.venv\Scripts\python.exe -m naive_rag.extract_pilot --corpus --question-scope Q01-Q08 --reuse-from graph\pilot\extraction-v3 --run
.\.venv\Scripts\python.exe -m naive_rag.quality_report --extraction-dir graph\corpus\extraction --markdown graph\corpus\quality-report.md --json graph\corpus\quality-report.json --title "Q01-Q08 kor" --join-corpus
.\.venv\Scripts\python.exe -m naive_rag.entity_index --extraction-dir graph\corpus\extraction --out graph\corpus\entity-index.json --run
.\.venv\Scripts\python.exe -m naive_rag.local_search --index graph\corpus\entity-index.json --extraction-dir graph\corpus\extraction --baseline baseline\answers.json --out docs\osszehasonlitas.md --run
```

A Neo4j-betöltés nincs parancssori kapcsolóra kötve. A kapu `plan_validated_raw(..., accept_validated_raw=True)` volt, csak a `status=ok` rekordokra, 880 tranzakcióval. A JSON-fájlokra nem került `approved` mező.

## M4 — bizonyítéklánc

A dokumentációs kör itt lezárul. A követelmények hiánytalan teljesülése
nincs állítva. Az M5-nek átadott hiányok a szakasz végén vannak.

### 1. Futás és riport

A `1200/100` a chunk mérete és átfedése: 1200 karakter, 100 karakter
átfedés. Nem csomópontszám. A mentett chunkfájl
`graph/corpus/chunks-section-1200-23/chunks.jsonl`; az első rekord
`chunk_size` mezője 1200, `chunk_overlap` mezője 100. A fájlnévben a
`23` a dokumentumszám. A `config.py` 63–64. sora ugyanezt a két számot
tartalmazza; ez kódbeli alapérték, nem önálló futási napló.

Az összetartozás mentett mondata a
`graph/corpus/quality-report-section-1200-23.md` 3. sora: a riport
bemenete `graph/corpus/extraction-reuse-1200-23`, 1651 sikeres rekord,
a chunkszöveg a fenti `chunks.jsonl`. A páros JSON ugyanezeket a
darabszámokat őrzi (`processed` 1651, `ok` 1651, `empty_ok` 315), de
nincs benne bemeneti útvonal vagy hash. A kötés tehát a markdown
mondata, nem külön futási metaadat.

### 2. Deduplikálás

Csak a `quality-report-section-1200-23.json` `before` és `after`
mezői. Előtte `kind=occurrence`: 10782 csomópont, 6533 él, legnagyobb
komponens 30. Utána `kind=merged`: 2761 csomópont, 4326 él, legnagyobb
komponens 1896. A komponens jelentése ugyanebben a két objektumban van:
szakterületi gráf, irány nélkül, seed, dokumentumgráf és MENTIONS nélkül.

Külön szám, nem ez a pár: a markdown 2469. sora a fázis-3
önhurok-szűrés utáni memóriagráfot 2761 csomópontnak és 4325 élnek
írja, és a Neo4j-ben megmaradt 4326 élt ettől elválasztja.

A szabály kód, nem a riport futási naplója: `occurrence_graph` és
`merged_graph` a `graph_merge.py`-ban; `entity_key` az
`extraction_identity.make_entity_key` (177. sor), `rel_key` a
`make_rel_key` (189. sor), alias az `ALIAS_MAP` (68. sor).

### 3. Él → forrásrekord → dokumentum

Egy mentett él, a
`diagnostics/2026-11-07-review/results/01_graph_review.json`
`q08_edges` első eleme: `Driver:jenson button`, `TEAMMATE_OF`,
`Driver:nico rosberg`, `from_year` null, `to_year` null, forráslista
`driver-jenson-button#31`. A lista egy elemű. A fájlt író szkript
(`01_graph_review.py` 21. és 95. sora) az
`extraction-reuse-1200-23` könyvtár `merged_graph` eredményét írja, és
az él forráslistáját legfeljebb négy elemre vágja. A JSON saját
mezőben nem őrzi a bemenet útvonalát.

A forrásrekord:
`graph/corpus/extraction-reuse-1200-23/driver-jenson-button_31.json`.
Mezők: `chunk_id` = `driver-jenson-button#31`, `doc_id` =
`driver-jenson-button`, `status` = `ok`. A `result.relationships`
második eleme `source_id` `e1`, `target_id` `e3`, `relationship_type`
`TEAMMATE_OF`. A nyers kapcsolaton nincs `source_chunk_ids`; a chunk a
rekord mezője.

A dokumentum: `chunks.jsonl` 180. sora, `chunk_id`
`driver-jenson-button#31`, `doc_id` `driver-jenson-button`,
`chunk_size` 1200, `chunk_overlap` 100.

### 4. Lefedettség és parancs

A `graph/corpus/extracted-layer-backup-week4-community-preflight-20261110.json`
fájl offline ellenőrzése lefutott a
`scripts/check_extracted_provenance.py` szkripttel, a fagyasztott
`chunks-section-1200-23/chunks.jsonl` ellen. Eredmény: 2761 csomópont,
15108 él, 0 él provenance nélkül, 17315 forrás-chunk hivatkozás, 0
feloldatlan. A domain él `properties.source_chunk_ids`, a `MENTIONS`
él a chunk végpont `chunk_id` mezője. Ez a backup fájl, nem élő
Neo4j-lekérdezés. Az egyedi `driver-jenson-button#31` példa érvényes
marad, és nem helyettesíti ezt a számlálást.

A 23 dokumentumos extrakció első betöltésének történeti shellparancsa
nincs meg. A mostani visszaállító belépő az `extraction_load --restore`,
és ebben a körben nem futott Neo4j ellen. A `quality_report.py`
argumentumaiból összerakható parancs rekonstruált parancs: nem
bizonyíték arra, hogy történetileg lefutott.

**M4 dokumentációs köre lezárva volt hiányokkal. A backup fájl
él-lefedettsége utólag, offline, igazolódott.** A történeti betöltő
shell továbbra is hiányzik.

