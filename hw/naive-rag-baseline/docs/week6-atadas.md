# 6. hét — DRIFT-adaptáció: felmérés és javaslat (átadás)

Az 1–10. pont és az előzetes jóslat történeti, B fázis előtti felmérés.
Eltérés esetén a jóváhagyott jóslat, a B fázis lezárása és az azt követő
fázisok rögzített döntései irányadók.

**Státusz: A, B és C fázis lezárva — felmérés, implementáció és a mérési
illesztés/parancsok elkészültek, valódi (fizetős) futás még nem történt.**

## 1. Riportindex
`src/naive_rag/entity_index.py` mintája átvehető: `EntityIndex` (in-memory,
kozinusz-hasonlóság, injektált `embed_texts`), `build_index`. 37 validált
riport forrása: `diagnostics/2026-11-10-phase3-measurement/results/
week4-report-v3-collection.jsonl` (`global_search.load_reports`), átlag
~553 kar/riport (mért). Egy `ReportIndex` ugyanezt a mintát követhetné.

## 2. Lokális keresés újrahasznosítása
`local_search.local_search(question, graph, index, *, embed_query,
answer_fn, k, min_score, chunk_texts, budget) -> LocalAnswer`
(`src/naive_rag/local_search.py:1036`), önálló, injektált. Visszaadja:
`subgraph` (nodes/edges/sources, `chunk_ids`), `anchors`, `prompt`,
`raw_answer`, `context_budget`. A DRIFT-részkérdés ugyanezt hívná.

## 3. Router negyedik ága
`search_router.py`: `VALID_MODES = ("naiv","lokalis","globalis")`,
zero-shot JSON döntés (`ROUTER_SYSTEM_PROMPT`, 30–56. sor). Negyedik ág
(`"drift"`) a `VALID_MODES` bővítésével + egy új mód-leírás bekezdéssel
illeszthető. Explicit módválasztás: `measure.py` rögzített `MODES`
listán fut (`build_real_gen_fns`) — egy negyedik `gen_fn` elég, a router
csak a routerprompt-méréshez kell.

## 4. Újrahasználható infrastruktúra
Bírók: `correctness_judge.judge_one`, `faithfulness_judge.judge_one`
változatlanul. Mentés: `measure.py` state-gépe (`answer_saved` →
`criteria_scored` → `faithfulness_scored` → `langfuse_synced`)
módfüggetlen. Költségmérés: `cost_guard.SharedCostLedger`
(`check_generative`/`check_embedding`, `diagnostics/2026-11-11-week5-b/
cost_guard.py:89,97`), heti 0,50 USD sapka. Langfuse:
`build_real_langfuse_sync_fn`, módcsoportos szinkron, új mód névvel
változtatás nélkül bővíthető.

## 5. Minimális fájlkészlet (javaslat)
`diagnostics/2026-11-14-week6-drift/` + `src/naive_rag/drift_search.py`
(primer+2 részkérdés orchestrátor, meglévő `global_search`/`local_search`
hívásaira építve, azokat nem módosítva). Offline tesztek: primer→
részkérdés-választás (fake call_fn), `local_search`-újrahasználás
(meglévő fake-ek), router negyedik ág validációja — a
`tests/test_measure_orchestration.py` mintáját követve, valódi hívás
nélkül.

## 6. Hívási felső korlát / kérdés
Primer (1 globális riport-lekérdezés) + ≤2 részkérdés × (1 embedding +
1 lokális generálás) + 1 szintézis. Generálás: ≤4 (1 primer + 2 lokális
+ 1 szintézis). Embedding: ≤3 (riportindex-lekérdezés + 2 részkérdés).
Bírói hívások (correctness+faithfulness) külön, 2/kérdés, nem a
generálási/embedding keretben.

## 7. Indexköltség — örökölt vs. többlet
**Örökölt, mért**: 37 riport, $0,0537; 329 108 prompt + 7237 completion
token, 161,6 s (`docs/week4-kozossegi-riportok-v3.md:44`) — nem futtatjuk
újra. **Új, becsült (nem mért)**: 37 riport × ~140 token ≈ ~5200 token
összesen; egységár a projektben jelenleg nem dokumentált, nagyságrendileg
elhanyagolható. A tényleges költséget az első valós futás `cost_guard`
naplója adja; a két tétel külön sorban marad.

## 8. Inkrementális frissítés
Nincs: a riportkészlet és gráf rögzített, teljes újraépítési lánc
eredménye (chunkolás → extrakció → gráf-összevonás → Leiden →
riportgenerálás). Új korpuszelemnél a teljes lánc újrafuttatása kell; a
mért 4. heti költségek (7. pont) az irányadók. Nem tervezünk új
frissítési rendszert vagy mérőkörnyezetet.

## 9. Routerprompt-bővítés és opcionális mérés
`ROUTER_SYSTEM_PROMPT` egy új mód-leírással bővíthető a 3 meglévő minta
szerint. Opcionális, csak döntést mérő újrafuttatás: `route_many` a 15
golden-set kérdésen (nincs keresés, csak JSON döntés), 4 mód közti
eloszlás összevetve — ez nem keresési újrafuttatás, golden set és 5. heti
eredmények változatlanok.

## 10. Smoke/full állapot
`RunSignature` (`config_sha256`+`golden_set_sha256`) kizárja eltérő
konfiguráció resume-ját (`measure.py:353`). Új mód → új `config_sha256`
→ meglévő állapot nem újrahasználható. Javaslat: külön state-fájl
(`week6-drift-state-{smoke,full}.json`) és `case_store_dir`, migráció
nélkül.

## Célkérdés-javaslatok (jóváhagyásra)
- **Q07** (multi-hop): egyik módban sem konzisztens — teszteli, hogy a
  globális primer jobb részkérdés-bontást ad-e, mint az egylépéses
  lokális keresés.
- **Q09, Q10, Q11** (global): az 5. heti táblázat szerint a globális mód
  itt gyenge; a DRIFT primer+részkérdés pont azt a hibamintát célozza,
  ahol a riport-szintű összegzés elveszít egy konkrét, entitásokat
  összekötő tényt.

**Előzetes jóslat** (irány, nem bizonyíték): a primer lépés javíthatja a
lefedettséget ott, ahol a hiba oka riport-összegzési információvesztés
volt (Q09–Q11, dokumentált 4. heti audit: izolált csúcsok, extrakciós
kiesés), mert a részkérdés konkrét entitásra anchorol a lokális
keresésen át. Q07-nél kisebb javulást várunk, mert ott az 5. heti hiba
nem volt globálisfüggő.

## Microsoft DRIFT-hez képest elhagyott elemek
Forrás (Microsoft Research blog, DRIFT Search) ebben a felmérésben nem
lett közvetlenül lekérve; az alábbiak nem ellenőrzött forrásazonosítással:
- nincs rekurzív, több körös továbbkérdezés (1 primer kör, ≤2 részkérdés);
- nincs HyDE a primer lépésben;
- nincs dinamikus, pontszám alapján bővülő részkérdés-fa, csak fix ≤2 ág;
- a meglévő három keresőt (naiv/lokális/globális) építőelemként
  használja, nem a Microsoft GraphRAG saját DRIFT implementációját.

---
A célkérdések és a jóslat **javaslatok**: jóváhagyás szükséges az
implementáció és bármely új mérési futás előtt.

## Jóváhagyott jóslat (kód előtt) — 2026-11-14

Célkérdések: Q07, Q09, Q10, Q11; Q01 egyszerű kontroll. A teljes mérés
változatlanul mind a 15 kérdésre vonatkozik.

„A korlátozott DRIFT-adaptációtól elsősorban a jelenlegi globális
módhoz képest várok teljesebb válaszokat a Q09–Q11 kérdéseken,
amennyiben a szükséges részletek a közösségi riportokból kimaradtak,
de a lokális gráfkereséssel még elérhetők. A Q07-en azt vizsgálom,
segít-e a riportok alapján készített részkérdés-bontás a több tény
összekapcsolásában. A gráfból vagy korpuszból hiányzó információ
pótlását nem várom a módszertől. A Q01 egyszerű kontrollkérdésen
nem várok javulást a naiv módhoz képest, viszont többletköltség
és késleltetés várható. A legfeljebb két részkérdés miatt a teljes
felsorolást igénylő válaszok továbbra is hiányosak maradhatnak.
A költségelőnyt a jelenlegi globális módhoz képest mérésnek
kell igazolnia.”

## B fázis zárás — 2026-11-14

**Módosult/új fájlok:**
- `src/naive_rag/drift_search.py` (új): `ReportIndex`/cache,
  primer-validáció, költségkövetett lépés-wrapperek, szintézis-kontextus
  determinisztikus levágással, `drift_search()` orchestrátor, `--build` CLI.
- `src/naive_rag/answer_question.py` (új): vékony kérdés→router→kereső
  belépési pont, a régi három ág és az új `drift` ág számára egyaránt.
- `src/naive_rag/search_router.py` (módosítva, additív): `VALID_MODES`
  bővítve `"drift"`-tel, `ROUTER_SYSTEM_PROMPT` egy új mód-bekezdéssel.
- `tests/test_drift_search.py`, `tests/test_answer_question.py` (új),
  `tests/test_search_router.py` (egy új teszteset).
- `diagnostics/2026-11-14-week6-drift/README.md` (új, elkülönített hely
  a cache-nek és egy későbbi mérésnek; jelenleg üres, nincs valódi futás).

**Tesztek:** `PYTHONPATH=src .venv/Scripts/python.exe -m unittest discover
-s tests` — **351/351 ok**, nincs regresszió. Az új 24 teszt (18 + 6)
fake modell/embedding/gráf függőségekkel fedi: top-3 riport, ≤2
részkérdés, hívásplafonok (4 generálás/3 embedding), hibás és üres
primer, `local_search.local_search` újrahasználása, szintézis-kontextus
levágás és metaadat, cache-egyezés/-eltérés (hash/modell/dimenzió),
költségőr-ellenőrzés minden fizetős hívás előtt, router `drift`-döntés
tényleges végrehajtása, explicit módválasztás, a régi három ág
megmaradása, rögzített modellbeállítások.

**Következő belépési pontok (nem most):** `measure.py`
`build_real_gen_fns`-be egy ötödik `"drift"` kulcs; a riportindex-cache
tényleges, explicit felépítése; egy 15 kérdéses teljes DRIFT-mérés a
golden seten; opcionális routerprompt-újramérés (9. pont).

## C fázis zárás — 2026-11-14

**Módosult/új fájlok** (mind `diagnostics/2026-11-14-week6-drift/` alatt,
az 5. heti kód/golden set/állapot/eredmény/ledger változatlan):
- `week6_bootstrap.py` (új) — sys.path, szándékosan eltérő néven, mint
  a week5-b saját `_bootstrap.py`-ja (modulnév-ütközés elkerülése, l.
  a fájl docstringje).
- `drift_runner.py` (új) — valós `call_chat`/`call_embed` wiring
  (`naive_rag.call_logging` újrahasználásával), lokális gráf/entitásindex/
  chunkszöveg betöltés meglévő, előre kiszámolt artefaktumokból (nincs új
  embeddinghívás), `run_drift_capture`.
- `build_index.py` (új) — explicit, költségőrzött riportindex-építő CLI;
  érvényes cache mellett nem hív embeddinget.
- `drift_measure.py` (új) — a mérési CLI (`run --smoke`/`run --full`);
  week5-b `measure.py` `process_case`/`CaseContext` lépésgépét
  **változatlanul importálja**, csak a módonkénti külső ciklust váltja
  ki egy egymódú (`drift`) változattal (`run_drift_cases`).
- `langfuse_week6.py` (új) — week5-b `langfuse_sync.py` generikus
  részeinek újrahasználása saját, `"week6-drift-"` kísérletnévvel (a
  week5-b modul ezt hardkódolja `"week5-b-"`-re).
- `report_week6.py` (új) — egyoszlopos drift-riport, az 5. heti 3-módos
  táblával azonos típusnevekkel/kategóriákkal; `report.py` nincs átírva.
- `README.md` (frissítve) — pontos parancsok, smoke/full újragenerálási
  megjegyzés, router-megjegyzés, faithfulness/retrieval-proxy korlátok,
  egy dokumentált adatkonzisztencia-figyelmeztetés (entitásindex 401 vs.
  jelenlegi gráf 393 csomópont), és egy előzetes, explicit feltevésekkel
  jelölt költségbecslés.
- `tests/test_drift_measure_orchestration.py`, `tests/test_drift_runner.py`,
  `tests/test_build_index_cost.py`, `tests/test_report_week6.py` (új).

**Tesztek:** `cd diagnostics/2026-11-14-week6-drift && PYTHONPATH=../../src
../../.venv/Scripts/python.exe -m unittest discover -s tests` —
**25/25 ok**. Lefuttatva és zöld maradt a week5-b teljes szuitja is
(`diagnostics/2026-11-11-week5-b`, **120/120 ok**) és a projekt gyökerének
szuitja (**351/351 ok**) — az 5. heti és a B fázisú kód érintetlen. Az új
25 teszt fake modell-/embedding-/gráf-függőségekkel fedi: smoke=3/full=15
kizárólag drift móddal, resume-kor nem ismétlődő válasz/bírói lépés,
konfigurációeltérés (`StateError`) elutasítása, a faithfulness-bírónak
átadott tényleges (levágott) szintéziskontextus, golden válasz/kritérium
ki nem szivárgása a generálásba, a riport-cache hiánya előtti leállás
(`ReportIndexNotReady`), indexépítés költségelszámolása és cache-újrafelhasználás
embeddinghívás nélkül, riport- vs. lokális-chunk evidencia elkülönítése,
smoke/full költségek riportbeli szétválasztása. Valódi API-/embedding-/
adatbázis-hívás, Langfuse-feltöltés, csomagtelepítés vagy smoke/full
futtatás sehol nem történt.

**Előzetes költségbecslés** (feltevésekkel, nem mért — részletek a
README "Költségbecslés" szakaszában): realisztikus ≈0.02 USD, felső
korlát ≈0.075 USD a teljes C fázis (indexépítés + smoke + full) valódi
lefuttatására, a közös 0.50 USD keret alatt. Az átlagos hívásköltség a
week5-b **ténylegesen mért** ledgeréből származik (3 régi mód kevert
átlaga), nem drift-specifikus mérésből — ezt a README és a jelen
bekezdés is kifejezetten jelzi.

**Blokkoló:** nincs. Egyetlen pont sem igényelt lényegi régi
kódátírást: a week5-b `process_case`/`CaseContext` már mode-paraméteres
volt, a `langfuse_sync.py` kísérletnév-hardkódolása pedig egy kis,
különnevű adapterrel (nem módosítással) volt megkerülhető.

## Smoke-diagnózis és feltételes javítás — 2026-11-14 (második kör)

A megelőző szakaszok jóváhagyása után ténylegesen lefutott egy valódi
smoke mérés (Q01, Q07, Q10, csak drift) — ez a jelen beszélgetésen
kívül történt, a mentett esetfájlokból és naplókból rekonstruálva.

**1. Esetenkénti tények** (a mentett `results/cases/smoke/*.json` és a
`logs/drift-smoke-*.json` hívásnaplókból, nem a ledger hívássorrendjéből):
- **Q01**: primer kezdeti válasza *helyes és magabiztos* ("Lewis Hamilton
  has won seven World Drivers' Championships."), `subquestions: []` → 0
  tényleges `local_search` hívás. A végső szintézis mégis **elutasítást**
  adott.
- **Q07**: primer kezdeti válasza explicit elégtelen ("a riportok nem
  adják meg a csapatot/szezont..."), `subquestions: []` → 0 `local_search`
  hívás. Szintézis elutasítás.
- **Q10**: `subquestions`: 2 (Schumacher Ferrari-évei; Räikkönen Ferrari
  alatti eredményei) → 2 tényleges `local_search` hívás, sikeres válasz.
  **Fontos, külön talált hiba** (nem ennek a körnek a hatóköre, csak
  jelzés): a mentett `actual_chunk_ids` mező a `subgraph["chunk_ids"]`
  (a kiválasztott csomópontok/élek **teljes jelölt**
  forráschunk-halmaza, ~150 elem) alapján épült, nem a ténylegesen a
  promptba bekerült, idézett `subgraph["sources"]` alapján — a
  `drift-subq-gen-*` naplók szerint részkérdésenként ténylegesen
  **14–17 chunk** szerepelt a promptban `[chunk_id]` idézetként. Ez a
  `drift_runner.run_drift_capture` egy mezőhiba-jellegű pontatlansága,
  nem a keresés minőségi problémája — jelen kör ezt szándékosan **nem
  javítja** (hatókörön kívül), csak dokumentálja a következő körnek.

**2. Korpuszalap-ellenőrzés** (célzott, helyi, API/DB-hívás nélkül): a
`drift_runner.build_local_search_fixtures()` az `naive_rag.ingest.load_and_chunk()`
függvénnyel **újra lefuttatja** a chunkolást (nem egy mentett fájlt tölt
be), ezért ellenőriztem, hogy ez pontosan ugyanazt adja-e, mint az 5.
heti fagyasztott mérési alap (`graph/corpus/chunks-section-1200-23/chunks.jsonl`,
1651 chunk, `chunk_size=1200`/`chunk_overlap=100`). **Eredmény: azonos**
— 1651/1651 chunk id egyezik, 0 eltérő szöveg, 0 hiányzó/többlet id
mindkét irányban. A "Loaded 95 source documents from corpus." sor csak
az `ingest.load_corpus()` informatív kiírása; a tényleges chunk-alap
bitre egyezik az 5. heti befagyasztott fájllal. **Nem talált eltérés**
→ a 2. pont szerinti megállási feltétel nem állt fenn, folytatható a
3. pont.

**3. Diagnózis és javítás.** A korpuszalap igazoltan azonos, és Q01/Q07
üres részkérdéslistája ténylegesen kihagyta a lokális lépést. A primer
promptja és validációja (`src/naive_rag/drift_search.py`) módosult:
`PRIMER_PROMPT_VERSION` → `"drift-primer-prompt-v2"`, `MIN_SUBQUESTIONS = 1`
— a `validate_primer_response` mostantól **elutasítja** az üres
`subquestions` listát (`primer_invalid` státusz, nem csendes,
riport-only válasz). A promptszöveg is frissült: "nevezz meg 1-2
részkérdést... mindig nevezz meg legalább egyet, még akkor is, ha a
kezdeti válasz már valószínűnek tűnik". Nincs extra javító LLM-hívás;
a hívásplafon (≤4 generálás/≤3 embedding) változatlan.

Mellékmegfigyelés, nem javítva: a szintézisprompt a `local_search.REFUSAL`
gráf-specifikus mondatát ("A rendelkezésre álló *részgráf* nem...")
használja az elutasítás jelzésére akkor is, amikor nincs is részgráf
(0 részkérdés esetén) — ez valószínűleg hozzájárult a Q01 spurious
elutasításához a primer saját, helyes válasza ellenére. A v2 validáció
(mindig ≥1 részkérdés) ezt a jövőben szerkezetileg elkerüli, mert
`subquestions: []` többé nem jut el a szintézisig — de a szintézisprompt
szövege maga **nem** változott ebben a körben (hatókörön kívül).

**Az előzetes jóslat és a jóváhagyott célkérdések változatlanok maradtak**
— ez a szigorítás a smoke-eredmények megismerése UTÁN történt, nem
befolyásolta a korábban rögzített jóslatot.

**4. Verziózott útvonalak** (`diagnostics/2026-11-14-week6-drift/drift_measure.py`):
`CODE_VERSION = "v2"`. Új, a réginél elkülönülő smoke/full állapot-
(`state/week6-drift-state-{run_kind}-v2.json`), eset-
(`results/cases/v2/{run_kind}/`) és eredményútvonalak
(`results/results-v2.jsonl`, `results/week6-drift-report-v2-{run_kind}.md`)
— a v1 smoke adatok (`results/cases/smoke/Q01-drift.json` stb.,
`results/results.jsonl`, `results/week6-drift-report-smoke.md`,
`state/week6-drift-state-smoke.json`) **változatlanul megmaradtak** a
lemezen. A riportindex-cache (`results/report-index-cache.json`) és a
kumulatív week6 ledger (`results/week6-cost-ledger.json`) **nem
verziózott, változatlan** — a promptváltozás nem indokolja a cache
érvénytelenítését, és **nem történt új indexembedding** (ez becsült,
nem mért állítás volt már a C fázisban is: a riportindex-embedding
költsége a korábbi becslés szerint elhanyagolható, <0.001 USD, és most
sem futott újra, mert a cache tartalma nem változott).

**5. Tesztek.** `tests/test_drift_search.py`: 1 meglévő teszt frissítve
(`test_empty_valid_subquestion_list_still_synthesizes` →
`test_empty_subquestion_list_is_now_a_clear_invalid_status`, az új,
szándékos viselkedésre), 2 meglévő teszt bemenete igazítva (1
részkérdésre, mert az üres lista már nem érvényes bemenet), 1 új teszt
(`test_primer_prompt_version_v2_requires_at_least_one_subquestion`).
Eredmény: `PYTHONPATH=src .venv/Scripts/python.exe -m unittest discover
-s tests` a repó gyökerén **352/352 ok**; a week6 szuit
(`diagnostics/2026-11-14-week6-drift`) **25/25 ok**; a week5-b szuit
**120/120 ok**, érintetlen. Valódi API-/embedding-hívás, smoke/full
futtatás vagy Langfuse-feltöltés ebben a körben nem történt.

## Mérési adatillesztés — `actual_chunk_ids` javítás (ugyanaz a v2 kör)

`drift_runner.py`-ban az `actual_chunk_ids` eddig a `subgraph["chunk_ids"]`-t
(teljes jelölt chunk-halmaz, Q10-nél ~150 elem) adta vissza. Javítva: most
a `subgraph["sources"]`-ból (a `fit_context` által ténylegesen a lokális
promptba beillesztett, `text_found` chunkok) épül — ez méri, mi került be
a lokális kontextusba, nem azt, mit idéz a végső szintézis szövege (azt
nem elemezzük). Új, külön mező: `local_candidate_chunk_ids` (a teljes
jelölt halmaz) — a jelölt, a kontextusba került és a riport-jelölt chunkok
így négy, egymástól elkülönített mező. A `actual_context`/faithfulness
bemenet (`synthesis_context`) emiatt **nem változott**. A javítás a
változatlanul `v2`-es (még nem futtatott) konfigurációba került; a v1
smoke-eredmények (`results/cases/smoke/`, `results/results.jsonl`)
érintetlenek. Cache és ledger változatlan, nincs indexembedding.
Tesztek: 2 új/frissített eset `tests/test_drift_runner.py`-ban (jelölt
vs. kontextus elkülönítés) — gyökér **352/352**, week6 **26/26**,
week5-b **120/120**, mind zöld.

**Az új smoke pontos parancsa** (nem futtatva):
```powershell
uv run python diagnostics\2026-11-14-week6-drift\drift_measure.py run --smoke
```
(A `CODE_VERSION = "v2"` miatt ez automatikusan az új
`state/week6-drift-state-smoke-v2.json` + `results/cases/v2/smoke/`
útvonalakat használja; a v1 eredmények nem íródnak felül.)

## E fázis zárás — 2026-11-14 (dokumentáció)

A v2 full mérés (15/15 kérdés) kódfejlesztés és újrafuttatás nélkül,
csak helyi összesítéssel dokumentálva: `docs/week6-eredmenyek.md` (új,
4-módos tábla, célkérdés-jóslatértékelés, faithfulness-ellenőrzés,
költségek, korlátok, DoD), `README.md` (új "6. házifeladat — Modern
irány" szakasz, az 5. heti rész változatlan). Faithfulness-ellenőrzés
eredménye: **nem találtam hibát** a mentett bírói kimenetekben (a simple
csoport 0,50-es átlaga 2 evaluálható esetből helyesen adódik, 3 n/a eset
helyesen kizárva). Költségeltérés (0,056394 vs. ledger-delta 0,05639731)
tisztázva: lépésenkénti vs. futásszintű kerekítés különbsége, nem hiba.
DoD: 1., 3., 4. pont teljesült; 2. pont **csak részben** (router-ág és
végrehajtás offline tesztelt, valós routeren-át-mért futás nem történt).
Nem történt API-/DB-hívás, embeddingépítés, Langfuse-feltöltés vagy
keresőjavítás ebben a fázisban.

## Végső dokumentációs lezárás — 2026-11-14

A README.md, a `docs/week6-eredmenyek.md` és e dokumentum pontosítva:
a Q09-es célkérdésnél a drift lokális kontextusa (retrieval=1.00) és a
globalis riportforrás-proxyja eltérő jelentésű, közvetlenül nem
összevethető mutatók — a korábbi "javulás"/"győzelem" megfogalmazás
törölve. A teljes 15 kérdéses mintán a helyes válaszok száma (régi
módok újra nem futtatva, 5. heti mentett FULL-ból átvéve): drift v2
FULL 3/15, naiv 9/15, lokális 7/15, globális 2/15 — kis minta, nem
algoritmusrangsor. A DoD 2. pontja (router negyedik ága) **"Igen"**-re
állítva: a meglévő kód (`search_router.py`, `answer_question.py`) és az
offline teszt (`tests/test_answer_question.py`) igazolja a router →
drift végrehajtást; ehhez nem szükséges külön valós mérési futás. A
valós `route_demo.py` demó ettől elkülönítve dokumentált: az
automatikus router érvényes `globalis` döntést adott, de a demóban
csak a `drift` ág volt bekötve, ezért a `globalis` végrehajtás
elmaradt — ez a demó megmaradó, tudatos korlátja, nem router- vagy
DoD-hiány. Jelenlegi kumulatív week6 ledger-fogyasztás (a demót is
beleértve): 0,075836 USD. A korábbi, időponthoz kötött történeti
összegek (v2 smoke/full utáni konzolértékek) és a már dokumentált
faithfulness-/költségeltérés-levezetés nem változott.

## M3 lezárás

Az M3 local-followup abláció lezárva. A célkérdések, a
`m3-followup-usagefix-on` / `m3-followup-usagefix-off` pár, a jóslatok
ellenőrzése és a ledgerállapot a `docs/week6-eredmenyek.md` M3
szakaszában vannak. A fenti, 2026-11-14-i jóváhagyott jóslat szövege
nem változott. Az ON az alapértelmezett; nincs új DRIFT-verzió.
