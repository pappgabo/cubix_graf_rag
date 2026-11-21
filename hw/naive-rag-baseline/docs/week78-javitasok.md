# Záróprojekt (7–8. hét) — javítások

Ez a dokumentum a záróprojekt M2 munkacsomagjában kiválasztott,
bizonyítékos javítási jelölteket és a ténylegesen implementált
javítás(ok) állapotát rögzíti. Nem írja felül a korábbi heti
dokumentációt, eredményeket, a golden setet vagy a korábbi ledgereket.

## J1 — numerikus eredményállítások megőrzése a közösségi riportokban

**Állapot: Lezárt, sikertelen kísérlet.** A path="4" pilot ténylegesen
lefutott (valós modellhívással) és technikailag sikeres volt (érvényes
riportszerkezet), de **nem igazolta** a célzott információvesztés
megszűnését — lásd "Pilot eredménye" lent. J1 ezzel **lezárt**: nem
minősül a záróprojekt két mért javítása közé tartozó, teljes
golden-seten mért javításnak. Nincs tervezett J1-v2 vagy további
tuning.

### Kiinduló bizonyíték

Az 5. heti Q09/globalis FULL eset
(`diagnostics/2026-11-11-week5-b/results/cases/full/Q09-globalis.json`):
a végső válasz ("Lewis Hamilton has won the most World Drivers'
Championships with a total of seven titles.") nem említi, hogy Michael
Schumacher is hét címmel áll holtversenyben — a bíró ezt "hiányos"-nak
minősítette (Q09-c1 kritérium, "not_met").

### Bizonyított elvesztési pont

A lánc nyomon követése (riportgenerálási bemenet → generált riport →
map-részválasz → reduce-bemenet → végső válasz) a következőt mutatta:

- **Riportgenerálási bemenet** (`diagnostics/2026-11-10-phase3-measurement/
  results/week4-report-v3-input-4.json`, `Driver:michael schumacher`
  node, `record_id: N002` — **javítva, korábban tévesen N001-ként
  szerepelt itt**): **TÉNY MEGVAN** — "A German racing driver who is a
  seven-time Formula One World Champion."
- **Generált közösségi riport** (`diagnostics/2026-11-10-phase3-measurement/
  results/week4-report-v3-collection.jsonl`, `path="4"`,
  `key_statements`): **TÉNY NINCS** — csak "Michael Schumacher drove for
  Scuderia Ferrari from 1996 to 2006, achieving significant success
  during this period." A teljes riport-JSON-ban nincs "seven" szó vagy
  címszám.
- A Q09 map bemenete maga ez a riport, ezért a map-részválasz, a
  reduce-bemenet és a végső válasz is öröklődően nélkülözi a tényt
  (`Q09-globalis.json` `raw.reduce_a.citation_chain`, `raw.basis_paths`).

**Az első bizonyított információvesztési pont a közösségi
riportgenerálás lépése** (`diagnostics/2026-11-10-phase3-measurement/
generate_reports_v3.py`, `riportprompt-v3`, community `"4"` hívása) — a
bemenet→kimenet pár közvetlenül összekapcsolható, nem csak intervallum.
Mechanizmus (hipotézis): a bemeneti node-szöveg több rövid, önálló
állítást tartalmaz (pályafutás-tények + 1 számszerű cím-állítás); a
riport csak 1 `key_statement`-et generált Schumacherhez, és egy
narratív (csapat/évek) mondatot választott a számszerű állítás helyett.
Hogy ez más közösségeknél is rendszeresen előfordul, **nincs igazolva**
— csak ezen az egy közösségen ellenőrzött.

### Mérés előtti hipotézis (J1)

A riportgeneráló prompt egy explicit, számszerű eredményállítások
megőrzésére vonatkozó szabálya csökkentheti ezt az
információvesztést. **A javulás nem bizonyított** — ezt egy külön,
később jóváhagyandó pilot (path="4") és teljes golden-seten mért
before/after összevetés dönti el.

### Pontos változtatás

Új, önállóan reprodukálható promptverzió:
[`diagnostics/2026-11-21-week78-j1-report-prompt/
week4-report-j1-prompt-template.md`](../diagnostics/2026-11-21-week78-j1-report-prompt/week4-report-j1-prompt-template.md)
— a v3 sablonból (`diagnostics/2026-11-10-phase3-measurement/
week4-report-v3-prompt-template.md`, **változatlan, külön reprodukálható
alap marad**) **egyetlen új bekezdéssel** bővítve:

> If the supplied records state an explicit, factual, quantitative
> result or aggregate performance for an entity — for example a title
> count, a win count, a record, a podium or points count, a duration, or
> another clearly quantitative result or aggregate-performance figure —
> preserve that fact as its own key statement. Keep the entity, the
> number, the measured category, and any explicit time or validity
> qualifier the source states; none of these may be dropped, changed, or
> replaced by a general career, team, or success summary that omits the
> number. Do not calculate a missing figure, infer a new number, turn a
> year into a result count, or merge different categories of number
> together.

A promptszabály **nem** tartalmaz kérdésazonosítót, golden választ,
rubrikakritériumot, pilótanevet vagy konkrét címszámot.

### Általánosíthatóság

A szabály bármely entitásra/közösségre vonatkozik, amelynek bemeneti
szövege explicit, számszerű eredményt vagy összesített teljesítményt
állít — nem Q09-, Schumacher- vagy pilóta-specifikus.

### Változatlan feltételek

Modell (`gpt-4o-mini`), `temperature=0`, `max_retries=0`,
`max_output_tokens=900`, a bemeneti riportgenerálási adatok (37
közösség, `nodes`/`domain_relationships`, `record_id`-séma), a
riportséma (`summary`/`key_statements`/`evidence_ids`), a
forráshivatkozási séma és minden más promptutasítás szó szerint azonos
a v3-mal — ezt offline teszt is igazolja (lásd lent).

### Új promptverzió és artifact-azonosítás

Implementáció:
[`diagnostics/2026-11-21-week78-j1-report-prompt/`](../diagnostics/2026-11-21-week78-j1-report-prompt/)
(`j1_bootstrap.py`, `week4-report-j1-prompt-template.md`,
`generate_reports_j1.py`, `tests/test_generate_reports_j1.py`). A v3
riportgeneráló kódot (`generate_reports_v3.py`) **nem módosítottam** —
csak három tiszta, meglévő függvényét hasznosítja újra importtal
(`validate_report`, `resolve_statements`, `extract_system_prompt`).

- **Promptverzió:** `riportprompt-j1`.
- **Prompt SHA-256:** a tényleges rendszerüzenet szövegéből számolva
  futáskor (`generate_reports_j1.prompt_sha256`), nem hardkódolt.
- **Bemenet:** a már mentett, fagyasztott v3 bemeneti fájlok
  (`week4-report-v3-input-<path>.json` / `...-record-chunk-map-<path>.json`)
  — **nem újraszámolt**, csak a `prompt_version` mező cserélődik
  (`build_j1_payload`).
- **Input run id:** `week4-leiden-elokeszitett-6f05327d7d88ebf0`
  (változatlan, a v3-mal azonos Leiden-particionálás).
- **Riportséma-verzió:** `v3-schema-unchanged`.
- **Artifact-elkülönítés:** a J1 ledger/collection/run-summary/run-
  metadata/report fájlok saját `results/{pilot,full}/` alkönyvtárban
  élnek, a v3 `results/` könyvtárától fizikailag elkülönítve
  (`paths_for_run_kind`); egy strukturális védelem
  (`assert_no_v3_path_overlap`) megállítja a futást, ha bármelyik J1
  kimeneti útvonal mégis a v3 `RESULTS_DIR` alá mutatna.
- **Identitás-védelem:** minden futás elé egy run-metadata ellenőrzés
  (`assert_identity_matches_or_record`) kerül, amely a promptverziót, a
  prompt hash-ét, az input run id-t és a közösséglistát rögzíti az első
  híváskor, és **megállítja** a futást (nem folytatja csendben), ha egy
  későbbi hívás ugyanabba a run-kind könyvtárba eltérő identitással
  próbálna írni. Meglévő riport fájl felülírása explicit tiltott
  (`run_j1_reports`).

### Offline tesztek

`cd diagnostics/2026-11-21-week78-j1-report-prompt && ../../.venv/Scripts/python.exe -m unittest discover -s tests`
— **11/11 ok**. Fedi: v3/J1 promptverzió külön választhatósága; a
numerikus szabály kizárólag J1-ben szerepel; a J1 rendszerüzenet a v3
+ pontosan ez az egy új bekezdés (szó szerinti egyezés-ellenőrzéssel); a
modell/beállítások/tokenkeret/bemenet/séma azonossága; a `call_fn`-nek
ténylegesen elküldött szövegben benne van a szabály; régi/új kimeneti
útvonalak nem keverednek; eltérő identitású metaadat esetén nincs
csendes folytatás és nincs modellhívás; meglévő riport fájl nem
írható felül.

**Az offline teszt nem bizonyítja, hogy a modell a numerikus tényt
ténylegesen megőrzi** — ezt kizárólag a tervezett, valós path="4" pilot
bemenet–kimenet összevetése igazolhatja vagy cáfolhatja.

### Pilot eredménye (path="4", valós futás megtörtént)

Parancs, ahogy ténylegesen lefutott:

```powershell
cd diagnostics\2026-11-21-week78-j1-report-prompt
uv run python generate_reports_j1.py --run-kind pilot
```

**Mentett kimenet:** [`diagnostics/2026-11-21-week78-j1-report-prompt/
results/pilot/week4-report-j1-pilot-report-4.json`](../diagnostics/2026-11-21-week78-j1-report-prompt/results/pilot/week4-report-j1-pilot-report-4.json)
(`v3_input_hash` mező egyezik a fagyasztott `week4-report-v3-input-4.json`
tartalmával).

- **Technikai eredmény:** sikeres — `valid_json: true`,
  `validation.valid_structure: true`, 0 ismeretlen rekordazonosító.
- **Tartalmi eredmény:** a Schumacher hét világbajnoki címéről szóló tény
  (`N002`) **nem jelenik meg** egyetlen `key_statement`-ben sem — a
  Schumacherről szóló egyetlen állítás változatlanul csak a Ferrari-
  tenure (1996–2006, `evidence_ids: ["E012"]`). **A célzott
  tényvesztés megszüntetését a pilot nem igazolta.**
- **A szabály nem általánosan hatástalan:** a riport egy ÚJ, érvényes
  számszerű állítást is megőrzött, amit a v3 riport nem tartalmazott —
  Kimi Räikkönen 2007-es címe és "21 Grands Prix across 19 seasons"
  (`key_statements[3]`, `evidence_ids: ["N003"]`, a `week4-report-v3-input-4.json`
  `N003` node szövege ezt ténylegesen tartalmazza). A szabály tehát
  helyenként működött, csak nem ezen a céleseten.
- **Költség:** `measured_cost_usd: 0.003125` USD — **mért**, nem becsült
  (`usage_prompt_tokens: 19745`, `usage_completion_tokens: 272`, mindkettő
  tényleges API-usage, nem ismeretlen/upper-bound). Megegyező bejegyzés a
  saját ledgerben: [`results/pilot/week4-report-j1-pilot-cost-ledger.json`](../diagnostics/2026-11-21-week78-j1-report-prompt/results/pilot/week4-report-j1-pilot-cost-ledger.json)
  (`usage_known: true`).
- **Minősítés: PILOT SIKERTELEN — J1 hipotézis nem igazolódott** erre a
  céleseten.

A 37 riportos J1 full generálás és a globalis FULL after-mérés
**nem indult el** — a lenti két parancs továbbra sem futtatott.

### Tervezett 37 riportos J1 full generálás (nem futtatva, valós belépési pont)

```powershell
cd diagnostics\2026-11-21-week78-j1-report-prompt
uv run python generate_reports_j1.py --run-kind full
```

Ugyanaz a valós belépési pont, mind a 37, v3 run-summaryból kiolvasott
közösségre (`community_paths_for_run_kind("full")`), saját
`results/full/` könyvtárba, saját `week4-report-j1-full-cost-ledger.json`
költségőrön keresztül. **Nem futtattam ebben a körben.**

### Globalis FULL before/after — mérési bekötés elkészült

**Állapot: Mérési bekötés elkészült; fizetős futás még nem történt.**

**A bekötés módja:** vékony, külön J1-globalis mérőbelépési pont
([`diagnostics/2026-11-21-week78-j1-globalis-measure/
j1_globalis_measure.py`](../diagnostics/2026-11-21-week78-j1-globalis-measure/j1_globalis_measure.py)),
a legkisebb megoldásként — nem a `measure.py` átparaméterezése, hanem
ugyanaz a mintázat, amit `drift_measure.py` már bevezetett a drift
módhoz: a `measure.py` per-eset lépésgépét (`process_case`,
`CaseContext`), valós generálás-/bírókészítőit
(`build_real_gen_fns`, `build_real_judge_call_fn_factory`) és a
`state_store`/`golden_set`/`report` modulokat **változatlanul**
importtal hasznosítja újra; csak a kimenő hurkot (`run_j1_globalis_cases`,
egyetlen "globalis" módra, a `drift_measure.run_drift_cases` mintájára)
és a riportgyűjtemény forrását cseréli. A `measure.py` kódja, `CONFIG`-ja
és alapértelmezett viselkedése **nem módosult** — ezt offline teszt is
igazolja (`test_week5measure_defaults_untouched`).

**Collection teljességellenőrzés:** az elvárt community/path ID-halmazt
a v3 TELJES collectionből (`week4-report-v3-collection.jsonl`, a
kontrollált baseline alapja) olvassa ki — nem hardkódolt "37". A
vizsgált J1 collection akkor fogadható el, ha a path-halmaza **pontosan**
megegyezik (nincs hiányzó, nincs többlet, nincs duplikált id) —
`verify_collection_completeness`, fájllétezésen/méreten/sorszámon túli,
tényleges ID-összevetéssel. Egy path="4" pilot-only collection ezen
elbukik (hiányzó 36 id).

**Collection-hash:** a teljes collection fájl nyers bájtjainak SHA-256-ja
(`collection_sha256`, `hashlib.sha256(path.read_bytes())`) — az útvonal
önmagában nem azonosít. A futásazonosság (`build_run_signature` →
`state_store.RunSignature.config_sha256`) ezt a hash-t, a collectionben
talált egységes `prompt_version`-t (`verify_single_prompt_version` —
kevert verzió esetén megáll), a golden hash-t, a `global_run_id`/
`global_reporting_level`-t és a correctness/faithfulness bíróprompt-
verziókat tartalmazza (`effective_config`), a `week5measure.CONFIG`-ból
változatlanul átvéve. Azonos állapot-útvonalon eltérő collection-tartalom
(eltérő hash) `state_store.StateError`-t vált ki — nem folytat csendben
(`test_state_store_refuses_resume_on_changed_collection_content`).

**Elkülönítés:** saját `diagnostics/2026-11-21-week78-j1-globalis-measure/
{state,results}/` útvonalak (state: `state/week78-j1-globalis-state-
j1-globalis-full.json`; eredmények: `results/results-j1-globalis-full.jsonl`
+ `results/week78-j1-globalis-report-j1-globalis-full.md`); **saját**
költségőr (`results/week78-j1-globalis-cost-ledger.json`) és kérésnapló
(`results/week78-j1-globalis-request-log.json`) — egyik sem azonos a
path="4" J1 pilot, a 37 riportos J1 generálás, az 5. heti globalis mérés
vagy a week6 drift mérés ledgerével. A week5-b `results.jsonl`,
state-fájlok, esetfájlok és ledgerek útvonala nem szerepel az új modul
egyetlen írási útvonalában sem.

**Langfuse:** saját, `"week78-j1-globalis-"` prefixű experiment/run-
névtér ([`langfuse_week78.py`](../diagnostics/2026-11-21-week78-j1-globalis-measure/langfuse_week78.py),
a `langfuse_week6.py` mintájára, a generikus `langfuse_sync.py`-részek
újrahasznosításával). A szinkronizáló függvény (`build_real_langfuse_sync_fn`)
minden hívásnál a lemezről olvassa vissza mind a 15 elvárt esetet, és
csak akkor szinkronizál, ha mindegyiknél megvan a correctness ÉS a
faithfulness eredmény is — részleges futás nem kerül feltöltésre
(`test_sync_is_a_noop_while_the_group_is_incomplete`). Egy már
szinkronizált, változatlan csoport újraindításkor nem duplikálódik
(`sync_j1_globalis_group_once` jel-alapú védelme, a week5-b/week6
mintájára). A régi Langfuse experimenteket nem írja felül (külön
experiment-/run-név).

**Offline tesztek:**
`cd diagnostics/2026-11-21-week78-j1-globalis-measure && ../../.venv/Scripts/python.exe -m unittest discover -s tests`
— **17/17 ok**. Fedi: csak globalis mód, nincs smoke-részhalmaz; az
explicit J1 collection ténylegesen eljut a valós végrehajtóhoz
(`reports` paraméteren át); minden más beállítás megegyezik a régi FULL
configgal; a régi `measure.py` alapértelmezése érintetlen; útvonal-
elkülönítés; hiányzó/hibás/pilot-only/hiányzó-id/többlet-id/duplikált-id
collection mind fizetős hívás nélkül hibázik; eltérő collection-tartalom
esetén resume tiltott; saját ledger; Langfuse-sync csak 15/15, mindkét
bírós eredménnyel. Valós API-/DB-hívás, riportgenerálás vagy
Langfuse-feltöltés a tesztek alatt nem történt — szintetikus
fixture-collectionekkel (projektadat módosítása nélkül), a gyökér
`tests/` (352/352) és a J1 riportgenerálási szuit (11/11) érintetlen.

**Pontos, későbbi PowerShell-parancs (MOST NEM FUTTATVA):**

```powershell
cd diagnostics\2026-11-21-week78-j1-globalis-measure
uv run python j1_globalis_measure.py run --collection ..\2026-11-21-week78-j1-report-prompt\results\full\week4-report-j1-full-collection.jsonl
```

Ez explicit a J1 collectiont használja, kizárólag globalis módot futtat,
mind a 15 golden kérdést méri, saját state/results/ledger útvonalra ír,
elvégzi a collection-hash/konfiguráció-azonosítást, és nem generál
riportot, nem épít indexet, nem futtat driftet.

### Driftre gyakorolt hatókör

A J1 riportgyűjtemény a drift primer bemenetét is megváltoztatná. Ha a
rendszer véglegesen J1 riportokra állna át:
- elavulna a meglévő riportindex-cache
  (`diagnostics/2026-11-14-week6-drift/results/report-index-cache.json`,
  jelenleg a v3 `week4-report-v3-collection.jsonl` tartalmára épül) —
  pontosan azért, mert a cache a riporttartalom hash-éhez van kötve
  (`reports_content_hash`, `naive_rag/drift_search.py`), és a J1
  collection tartalma (eltérő `collection_sha256`, eltérő riportszöveg)
  ezt a hash-t megváltoztatná;
- új, explicit riportindex-építés kellene a J1 collectionre
  (`diagnostics/2026-11-14-week6-drift/build_index.py`, a J1 collection
  útvonalára mutatva);
- a meglévő drift v2 FULL eredmény (`results/week6-drift-report-v2-full.md`,
  `results-v2.jsonl`) **a v3 riportokra vonatkozó, változatlan történeti
  eredmény marad**;
- egy új, teljes 15 kérdéses drift FULL mérés kellene a J1 riportokkal,
  külön verziójelöléssel (pl. `CODE_VERSION="v3-j1-reports"`), saját
  state/cases/ledger útvonalakkal.

Ezt **ebben a körben nem implementáltam, nem mértem és nem építettem
újra** — ez egy külön, később jóváhagyandó lépés.

## J2 — évszámtudatos naiv retrieval

**Állapot: A Q04 pilot lezárt, sikertelen összetett pilot.**
J2 nem alapértelmezett. Nincs J2-v2 és nincs további tuning. A pilot
után készült egy kontrollált baseline/J2 FULL hatásvizsgálat; összesített
minőségi javulás nem igazolt.

Mentett pilot:
[`diagnostics/2026-11-21-week78-j2-naive-measure/results/pilot/cases/Q04-naiv.json`](../diagnostics/2026-11-21-week78-j2-naive-measure/results/pilot/cases/Q04-naiv.json).

- A week5 before correctness címkéje `elutasított` volt; a J2 pilot
  címkéje `helyes`. A retrieval ratio **0 maradt**.
- `season-2016-formula-one-world-championship#1`: `original_rank=11`,
  `year_match=false`, a tényleges generálási kontextusból kimaradt.
- Az előre rögzített mechanizmus-siker és az összetett pilotsiker nem
  teljesült.
- Költség: **0,000646 USD, mért** (`cost_usd` a mentett pilotfájlban).

**Minősítés: sikertelen összetett pilot, helyes végső válasszal.**
Ez a minősítés a későbbi FULL-tól független, és változatlan.

### Kontrollált baseline/J2 FULL

A történeti week5 FULL nem a before. A friss before a
`j2_enabled=False` baseline FULL. A J2 FULL ugyanaz a pipeline,
`j2_enabled=True`. Mindkét oldal 15/15: válasz, correctness és
faithfulness kész, futási hiba nincs.

Eredmények:
[`results/pair-baseline-full/`](../diagnostics/2026-11-21-week78-j2-naive-measure/results/pair-baseline-full/),
[`results/pair-j2-full/`](../diagnostics/2026-11-21-week78-j2-naive-measure/results/pair-j2-full/).
State:
[`j2-pair-state-baseline-full.json`](../diagnostics/2026-11-21-week78-j2-naive-measure/state/j2-pair-state-baseline-full.json),
[`j2-pair-state-j2-full.json`](../diagnostics/2026-11-21-week78-j2-naive-measure/state/j2-pair-state-j2-full.json).
Közös ledger:
[`j2-pair-cost-ledger.json`](../diagnostics/2026-11-21-week78-j2-naive-measure/results/pair-shared/j2-pair-cost-ledger.json).

- Költség: baseline **0,009516 USD**, J2 **0,009566 USD**.
- Correctness, baseline: helyes 9, hiányos 4, elutasított 2, téves 0.
  J2: helyes 9, hiányos 5, elutasított 1, téves 0.
- Q04 címkéje `elutasított` → `hiányos`. Egyértelmű javulásnak vagy
  romlásnak nem minősíthető. Q05-c1 újonnan `met`; a Q05 címke
  `hiányos` maradt. Elvesztett, korábban teljesült kritérium nincs.
- Retrieval-mutatók változatlanok: átlagos ratio 0,3822, hit összesen 9,
  strict 5 mindkét oldalon.
- Faithfulness, értékelhető esetek: baseline átlag 1,0 (13 eset; n/a:
  Q04, Q13), J2 átlag 0,9286 (14 eset; n/a: Q13). Q12: 1,0 → 0,0.
  Az n/a nem 0. A Q12 regresszió oka nincs megállapítva.
- Generálási latency átlaga: baseline 2,049 s, J2 2,131 s.

**FULL minősítés: teljes golden-seten mért változtatás, vegyes
eredménnyel és faithfulness-regresszióval. Összesített minőségi
javulás nem igazolt.**

## J3 — chunkhatáron töredékes mondat

**Állapot: Kontrollált, sikertelen célzott pilot. A FULL javulást nem igazol.**
J3 nem alapértelmezett. Nincs további tuning.

A Q07/naiv pilot a mentett baseline `actual_context` byte-azonos
`saved_context_replay` visszajátszása volt: embedding és retrieval
nélkül, J2 kikapcsolva. A modellkérés csak a J3 promptszabályban tért
el a baseline-tól.

Mentett eredmény:
[`diagnostics/2026-11-21-week78-j2-naive-measure/results/j3-q07-pilot/cases/Q07-naiv.json`](../diagnostics/2026-11-21-week78-j2-naive-measure/results/j3-q07-pilot/cases/Q07-naiv.json).

- Q07-c2: `not_met`. Correctness: `hiányos`.
- Faithfulness: 1,0 → 1,0.
- Pilotköltség: **0,000810 USD**. Közös ledger: **0,019892 USD**,
  maradék **0,480108 USD**.

**Minősítés: kontrollált, de sikertelen célzott pilot. A hipotézis
szerinti minőségi javulás ezen az eseten nem igazolódott.**
Ez a minősítés a későbbi FULL-tól független, és változatlan.

### Kontrollált baseline/J3 FULL

A before a friss `j3cmp-baseline` FULL, normál retrievallel,
`actual_context_override=None`, `j2_enabled=False`. A J3 FULL ugyanaz
a pipeline; csak a J3 promptszabály tér el. Mindkét oldal 15/15:
válasz, correctness és faithfulness kész, futási hiba nincs.

Eredmények:
[`results/j3cmp-baseline/`](../diagnostics/2026-11-21-week78-j2-naive-measure/results/j3cmp-baseline/),
[`results/j3cmp-j3/`](../diagnostics/2026-11-21-week78-j2-naive-measure/results/j3cmp-j3/).
State:
[`j3cmp-baseline.json`](../diagnostics/2026-11-21-week78-j2-naive-measure/state/j3cmp-baseline.json),
[`j3cmp-j3.json`](../diagnostics/2026-11-21-week78-j2-naive-measure/state/j3cmp-j3.json).
Közös ledger:
[`j2-pair-cost-ledger.json`](../diagnostics/2026-11-21-week78-j2-naive-measure/results/pair-shared/j2-pair-cost-ledger.json).

- Költség: baseline **0,009681 USD**, J3 **0,009662 USD**, együtt
  **0,019343 USD**. A futás után a közös ledger **0,039235 USD**,
  maradék **0,460765 USD** a 0,50 USD keretből.
- Correctness mindkét oldalon: helyes 9, hiányos 4, elutasított 2,
  téves 0. Mind a 15 címke változatlan.
- Nyert kritérium: 0. Elvesztett kritérium: 1, a Q12-c9
  `met` → `not_met`. A Q12 címke `hiányos` maradt.
- Retrieval azonos: átlagos ratio 0,3822, hit összesen 9, strict 5.
- Faithfulness mindkét oldalon 1,0 a 13 értékelhető esetben; n/a:
  Q04, Q13. Faithfulness-romlás nem történt. Az n/a nem 0.
- Generálási latency átlaga: baseline 2,022 s, J3 2,138 s.

**FULL minősítés: teljes golden-seten mért, javulást nem igazoló
változtatás, egy kritériumszintű regresszióval. Faithfulness-romlás
nem történt. Oksági magyarázat nincs.**
