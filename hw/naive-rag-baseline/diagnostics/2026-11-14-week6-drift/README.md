# week6-drift — korlátozott DRIFT mérés (C fázis)

Elkülönített futtatási hely a korlátozott DRIFT-adaptációhoz
(`src/naive_rag/drift_search.py`, B fázis). A régi három mód
(naiv/lokalis/globalis) kódja, golden setje, állapota, eredményei és
ledgere (`diagnostics/2026-11-11-week5-b/`) **változatlan** — ez a mappa
csak a negyedik, `drift` mód saját mérését tartalmazza, ugyanazon a 15
kérdéses golden seten, ugyanazzal a helyességi/faithfulness bíróval.

## Állapot és verziózás (v2, 2026-11-14)

Egy valódi smoke mérés (Q01, Q07, Q10) lefutott v1 primerrel. A mentett
esetek diagnózisa alapján (lásd `docs/week6-atadas.md` "Smoke-diagnózis
és feltételes javítás") a primer promptja és validációja szigorodott:
`naive_rag.drift_search.PRIMER_PROMPT_VERSION = "drift-primer-prompt-v2"`,
üres `subquestions` lista mostantól `primer_invalid` státusz, nem
csendes riport-only válasz. Emiatt `drift_measure.py`
`CODE_VERSION = "v2"`-re lépett: **új** smoke/full állapot-
(`state/week6-drift-state-{run_kind}-v2.json`), eset-
(`results/cases/v2/{run_kind}/`) és eredményútvonalakat
(`results/results-v2.jsonl`, `results/week6-drift-report-v2-{run_kind}.md`)
használ — a v1 smoke adatok (`results/cases/smoke/`, `results/results.jsonl`,
`state/week6-drift-state-smoke.json`) változatlanul megmaradtak. A
riportindex-cache és a kumulatív ledger **nem verziózott**: a
promptváltozás nem indokolja a cache érvénytelenítését, és nem történt
új indexembedding.

Az új smoke parancs (nem futtatva ebben a körben):

```powershell
uv run python diagnostics\2026-11-14-week6-drift\drift_measure.py run --smoke
```

## Fájlok

- `week6_bootstrap.py` — sys.path, szándékosan más néven, mint a
  week5-b saját `_bootstrap.py`-ja (lásd a fájl docstringjét: két
  azonos nevű, eltérő tartalmú modul összeakadna).
- `drift_runner.py` — valós hívás-wiring: `call_chat`/`call_embed`
  építők (`naive_rag.call_logging` újrahasználásával), a lokális
  gráf/entitásindex/chunkszöveg betöltése (meglévő, előre kiszámolt
  artefaktumokból, új embeddinghívás nélkül), `run_drift_capture`.
- `build_index.py` — explicit, költségőrzött riportindex-építő parancs.
- `drift_measure.py` — a mérési CLI (`run --smoke` / `run --full`),
  week5-b `measure.py`-jának **változatlanul importált**
  `process_case`/`CaseContext` lépésgépére épül; csak a módonkénti
  külső ciklust (`run_cases`) váltja ki egy egymódú (`drift`) változat.
- `langfuse_week6.py` — week5-b `langfuse_sync.py` generikus részeinek
  (LocalRecord, evaluátorok, `deterministic_experiment_id`)
  újrahasználása, saját `"week6-drift-"` kísérletnévvel (a week5-b
  modul ezt a nevet hardkódolja `"week5-b-"`-re, ezért nem hívható
  változatlanul erre a célra).
- `report_week6.py` — egyoszlopos (csak `drift`) riporttábla, azonos
  típusnevekkel/helyességi kategóriákkal, mint az 5. heti 3-módos
  táblázat, hogy egy későbbi 4-módos tábla ugyanazokból a mentett
  sorokból épülhessen fel, `report.py` módosítása nélkül.

## Parancsok (PowerShell, a repó gyökeréből)

### 1. Riportindex-cache építése (explicit, külön parancs)

```powershell
uv run python diagnostics\2026-11-14-week6-drift\build_index.py --build `
  --collection-path diagnostics\2026-11-10-phase3-measurement\results\week4-report-v3-collection.jsonl `
  --expected-run-id week4-leiden-elokeszitett-6f05327d7d88ebf0 `
  --out diagnostics\2026-11-14-week6-drift\results\report-index-cache.json `
  --ledger-path diagnostics\2026-11-14-week6-drift\results\week6-cost-ledger.json
```

A `--expected-run-id` értéke a riportgyűjtemény tényleges `run_id`-ja
(`drift_runner.detect_report_run_id` olvassa ki a fájl első sorából —
ez a jelenlegi fájlból tényleg ez az érték, nem feltételezés). Ha a
riportgyűjtemény run_id-ja időközben változik, a parancsot a tényleges
értékkel kell futtatni, a betöltés különben hibát dob.

Ha a `--out` alatt már van **érvényes** (azonos riporttartalom-hash +
embeddingmodell) cache, a parancs **nem hív embeddinget** — ezt a
`test_build_index_cost.py` teszt is ellenőrzi.

### 2. Smoke (Q01, Q07, Q10 — csak drift)

```powershell
uv run python diagnostics\2026-11-14-week6-drift\drift_measure.py run --smoke
```

### 3. Full (mind a 15 golden kérdés — csak drift)

```powershell
uv run python diagnostics\2026-11-14-week6-drift\drift_measure.py run --full
```

Mindkettő `--no-langfuse` kapcsolóval futtatható Langfuse-szinkron
nélkül (pl. hiányzó hitelesítő adatok mellett): a langfuse-ellenőrzés
minden fizetős hívás előtt fut, hiba esetén a futás azelőtt áll meg,
hogy bármi pénzbe kerülne.

Ha a riportindex-cache hiányzik vagy eltérő, a `drift_measure.py run`
**explicit hibával** (`ReportIndexNotReady`, kilépőkód 3) áll meg, még
az 1. lépés előtt — nincs automatikus újraépítés.

## Smoke/full: külön állapot, a 3 kérdés újragenerálása

A smoke (`state/week6-drift-state-smoke.json`,
`results/cases/smoke/`) és a full (`state/week6-drift-state-full.json`,
`results/cases/full/`) teljesen különálló állapotot és esetmappát
használ — nincs migráció. Emiatt a full futás **újra legenerálja**
Q01/Q07/Q10 drift-válaszát is (nem veszi át a smoke eredményét), tehát a
"Költségbecslés" szakasz full sora ezt a 3 kérdést is tartalmazza.

Egy korábbi smoke- vagy full-próba eredménye csak **azonos bemenet,
konfiguráció és implementáció** mellett használható fel újra — ezt a
futásazonosítás (`config_sha256` + `golden_set_sha256`,
`state_store.RunSignature`) kényszeríti ki: a `config_sha256` a
tényleges keresési konfigurációt (modell, token-keretek, `report_k`,
`max_subquestions`, szintézis karakterkeret), a bírói promptverziókat,
egy kódazonosítót (`drift_search_code_version`) és a riportindex
tényleges tartalom-hashét is tartalmazza. Eltérő konfigurációval a
`StateStore.load_or_create` **`StateError`-t dob**, nem fut tovább
csendben.

## Router

A router promptját a `drift` móddal bővítettük
(`src/naive_rag/search_router.py`). Az automatikus útválasztás 15
kérdéses viselkedését nem mértük újra; a DRIFT golden setes mérése
explicit módválasztással történik. A routerből történő végrehajtást
offline tesztek ellenőrzik (`tests/test_answer_question.py` a
projekt gyökerében).

## Faithfulness tényleges kontextusa és a retrieval-proxy korlátai

- A faithfulness-bíró a `drift_search.DriftAnswer.synthesis_context`
  mezőt kapja (`run_drift_capture`'s `actual_context`) — ez a
  szintézisnek **ténylegesen átadott**, a `synthesis_char_budget`
  szerint már levágott kontextus, nem a levágás előtti teljes
  riport- és lokális anyag.
- A retrieval mezőben (`actual_chunk_ids`) kizárólag a `local_search`
  által a részkérdésekre ténylegesen visszahozott és citált chunk id-k
  szerepelnek (`is_proxy_retrieval: false`) — ha nem futott
  részkérdés, ez üres lista, nem "nem visszavezethető".
- A primer által kiválasztott riportok `candidate_source_chunk_ids`
  kapcsolataiból képzett `report_candidate_chunk_ids` **külön mező**,
  kifejezetten jelölt/proxy jelleggel — ez SOHA nem kerül bele az
  `actual_chunk_ids`-be, és a riportban (`report_week6.py`) is külön
  sorban jelenik meg, nem átlagolva a valódi `retrieval_avg`-gal.
- A primer kezdeti válasza és egy-egy lokális részválasz önmagában nem
  igazolja a végső szintézis minden állításának tényszerűségét — ezt
  csak a faithfulness-bíró tényleges pontozása teszi.

## Ismert, dokumentált adatkonzisztencia-figyelmeztetés

A lokális kereséshez újrahasznosított, előre kiszámolt artefaktumok
(`graph/corpus/entity-index.json`: 401 entitás; a jelenlegi
`graph/corpus/extraction/`-ból épített összevont gráf: 393 csomópont)
**nem pontosan ugyanakkora elemszámúak** — az entitásindex valamivel
régebbi állapotot tükröz, mint a jelenlegi extrakciós könyvtár. Ez nem
új munka hibája: mindkét artefaktum változatlanul, a meglévő
`entity_index.load_index`/`graph_merge.merged_graph` függvényekkel
töltődik be, új embeddinghívás nélkül. Hatása: néhány entitásindex-beli
horgony esetleg nem lesz megtalálható a gráfban (a `local_search`
ilyenkor egyszerűen kevesebb éllel/csomóponttal dolgozik, nem hibázik),
ami a lokális részválaszok lefedettségét kismértékben ronthatja. Ha ez
a smoke/full eredményekben feltűnő mintázatot okoz, új, külön feladat
az entitásindex frissítése — ez a C fázis nem végzi el.

## Költségbecslés (ELŐZETES, nem mért)

**Feltevések** (mind jelezve, mert nincs drift-specifikus mérés még):
- A gpt-4o-mini hívásonkénti átlagköltsége a week5-b **ténylegesen
  mért** ledgeréből (`diagnostics/2026-11-11-week5-b/results/week5-b-cost-ledger.json`):
  710 generatív hívás, összesen 0.107345 USD, átlag ≈0.000151 USD/hívás.
  Ez a 3 régi mód kevert átlaga (a globális map-lépés sok kis hívása
  lehúzza az átlagot) — a DRIFT saját hívásmérete ettől eltérhet
  mindkét irányban; **ez a szám közelítés, nem drift-mérés**.
- Embedding ár: 0.02 USD/1M token (`cost_guard.PRICE_SOURCE`,
  változatlan). A riportindex-embedding becsült mérete ≈37 riport ×
  ~140 token ≈ 5200 token összesen → elhanyagolható (<0.001 USD).
- Kérdésenkénti hívásszám (B fázis plafonja): ≤4 generálás (primer +
  ≤2 lokális + szintézis) + ≤3 embedding a drift-lépéseken belül, plusz
  2 bírói hívás (helyesség + faithfulness) — összesen ≤6 generatív
  hívás/kérdés.

**Realisztikus becslés** (átlagköltséggel számolva, ≤6 hívás/kérdés):
- index építés: <0.001 USD
- smoke (3 kérdés): ≈3 × 6 × 0.000151 ≈ 0.003 USD
- full (15 kérdés, a 3 smoke-kérdést is újragenerálva): ≈15 × 6 × 0.000151 ≈ 0.014 USD
- **összesen ≈0.02 USD** a teljes C fázis valódi futtatására

**Felső korlát** (ha minden hívás a maximális kimeneti token-keretet
(900) és egy óvatos ~1000-2000 bemeneti tokent használna — ez a
`cost_guard.check_generative` tényleges, hívás előtti upper-bound
becslése, nem a várt tényleges fogyasztás):
- index építés: ≈0.0003 USD
- smoke: ≈0.012 USD
- full: ≈0.062 USD
- **összesen ≈0.075 USD** felső korlát, jóval a 0.50 USD közös keret alatt

**A megosztott `SharedCostLedger` tényleges garanciája** (ne nevezzük
ennél többnek): minden fizetős hívás előtt `check_generative`/
`check_embedding` ellenőrzi, hogy `eddig_elköltött + e_hívás_upper_bound
<= 0.50 USD` — ha nem, a hívás **nem indul el**
(`BudgetExceeded`), és a ledger perzisztens, folytatások között is
összegződik (`SharedCostLedger.load` a fájlban lévő összes korábbi
bejegyzést beszámítja). Ez **hívásonkénti, valós idejű ellenőrzés**,
nem egy előre kiszámolt, statikus plafon betartásának garanciája —
ha egy korábbi hívás tényleges fogyasztása a becsültnél nagyobb volt,
a KÖVETKEZŐ hívás ellenőrzése ezt már figyelembe veszi, de egyetlen
hívás sem állhat meg menet közben a keret miatt.

Minden konkrét API-wrapper (`drift_runner.build_real_call_chat`, a
bírófaktorik, `build_index.py`) `max_retries=0`-t használ.
