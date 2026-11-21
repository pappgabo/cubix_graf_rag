# 6. hét — DRIFT v2 FULL eredmények és értékelés

Forrás a számokhoz: `diagnostics/2026-11-14-week6-drift/results/`
(`week6-drift-report-v2-full.md`, `results-v2.jsonl`,
`cases/v2/full/*.json`, `week6-cost-ledger.json`,
`week6-index-cost.json`) és `diagnostics/2026-11-11-week5-b/results/`
(`week5-b-report-full.md`, `results.jsonl`) — mindkettő **változatlan**,
nem futott újra ehhez a dokumentumhoz. Minden szám ezekből a mentett
fájlokból lett kiolvasva/összesítve egy helyi szkripttel; nem olvastuk be
a teljes korpuszt vagy a nyers kérésnaplókat.

## Módszer (tényleges v2 működés)

Korlátozott, saját DRIFT-adaptáció — **nem** a Microsoft DRIFT teljes
implementációja: kérdésembedding → top-3 meglévő közösségi riport →
egy primer generálás (kezdeti válasz + **1–2** célzott részkérdés,
`PRIMER_PROMPT_VERSION="drift-primer-prompt-v2"`) → a meglévő
`local_search.local_search` hívása részkérdésenként a saját,
összevont gráfon és entitásindexen → egy végső szintézis. Egy kör,
nincs HyDE, nincs rekurzív/többkörös kérdésfa.

## 1. Négy mód összehasonlítása (FULL, kérdéstípusonként, 5-5 kérdés)

Az 5. heti (naiv/lokalis/globalis) oszlopok **átvett, nem újrafuttatott**
adatok (`week5-b-report-full.md`); a `drift` oszlop a v2 FULL mérés.

| Kérdéstípus | naiv (5. hét) | lokalis (5. hét) | globalis (5. hét) | drift (v2 full) |
|---|---|---|---|---|
| simple | n=5, helyes=5<br>retrieval_avg=0.80<br>faithfulness_avg=1.00 | n=5, elutasított=1, helyes=4<br>retrieval_avg=0.60<br>faithfulness_avg=1.00 | n=5, elutasított=3, helyes=1, hiányos=1<br>retrieval_proxy_avg=0.20<br>faithfulness_avg=1.00 | n=5, elutasított=3, helyes=2<br>retrieval_avg=0.20<br>faithfulness_avg=0.50 |
| multi-hop | n=5, elutasított=1, helyes=2, hiányos=2<br>retrieval_avg=0.27<br>faithfulness_avg=1.00 | n=5, elutasított=1, helyes=2, hiányos=2<br>retrieval_avg=0.48<br>faithfulness_avg=0.81 | n=5, elutasított=1, helyes=1, hiányos=3<br>retrieval_proxy_avg=0.24<br>faithfulness_avg=1.00 | n=5, helyes=1, hiányos=3, téves=1<br>retrieval_avg=0.04<br>faithfulness_avg=1.00 |
| global | n=5, elutasított=1, helyes=2, hiányos=2<br>retrieval_avg=0.08<br>faithfulness_avg=1.00 | n=5, elutasított=2, helyes=1, hiányos=2<br>retrieval_avg=0.05<br>faithfulness_avg=1.00 | n=5, hiányos=5<br>retrieval_proxy_avg=0.30<br>faithfulness_avg=1.00 | n=5, hiányos=5<br>retrieval_avg=0.27<br>faithfulness_avg=1.00 |

**Értelmezési korlátok a táblázat alatt:**
- a drift `retrieval_avg` legfeljebb két lokális keresés **tényleges
  kontextuschunkjainak unióján** számol (`local_search` `sources`
  mezője, `text_found` chunkok — nem a teljes jelölthalmaz, lásd a
  `drift_runner.py`-javítást a `docs/week6-atadas.md`-ben);
- a drift faithfulness a **végső szintézisnek ténylegesen átadott**,
  szükség esetén levágott kontextushoz mér (`synthesis_context`), nem a
  levágás előtti teljes riport-/lokális anyaghoz;
- emiatt a drift mutatók a régi módok eltérő kontextusaihoz tartozó
  mutatókkal **csak korlátozottan** hasonlíthatók össze;
- a régi `globalis` retrieval **proxy** (reduce-nak átadott
  `candidate_source_chunk_ids` kapcsolatok), nem azonos jelentésű a
  lokális chunklefedettséggel — sem a naiv/lokalis `retrieval_avg`-gal,
  sem a drift `retrieval_avg`-gal nem átlagolható össze közvetlenül.

### Faithfulness-ellenőrzés (helyi szkripttel, esetenként)

A `simple` csoport drift faithfulness-átlaga (0.50) mentett bírói
kimeneteinek esetenkénti ellenőrzése (`cases/v2/full/Q0{1,2,3}-drift.json`,
`Q14`/`Q15`):

| Kérdés | faithfulness.score | supported/unsupported/unclear | Megjegyzés |
|---|---|---|---|
| Q01 | 1.0 | 2/0/0 | helyes válasz, minden állítás alátámasztott |
| Q02 | n/a | 0/0/0 | elutasító válasz, a bíró 0 tényszerű állítást talált |
| Q03 | 0.0 | 0/1/0 | a bíró 1 állítást talált, alátámasztatlannak minősítette — érvényes 0 |
| Q14 | n/a | 0/0/0 | elutasító válasz, 0 állítás |
| Q15 | n/a | 0/0/0 | elutasító válasz, 0 állítás |

**Eredmény: nem találtam hibát.** Egyik n/a eset sem "0 helyett n/a"
jellegű hiba — mindháromnál `supported_count=unsupported_count=unclear_count=0`,
azaz a bíró valóban nem talált tényszerű állítást (`faithfulness_judge.score_from_judgement`:
`score = supported/scored_count ha scored_count>0, különben "n/a"` —
ez a szabály változatlan, nem módosítottuk). A Q03 0.0 érvényes: a bíró
talált 1 állítást, és nem tartotta alátámasztottnak — ez a helyes
viselkedés akkor is, ha a kritérium-bíró a választ "helyes"-nek
minősítette (a két bíró független, a helyességi címke nem írja felül
a faithfulness-t). Az evaluálható simple esetek száma: **2** (Q01, Q03),
az n/a esetek száma: **3** (Q02, Q14, Q15) — a 0,50-es átlag ezen a 2
evaluálható esetből jön: (1.0 + 0.0) / 2 = 0,50. Az n/a esetek az
átlagból ki vannak zárva (ahogy a `report_mod._cell` is teszi).
A riport értékét **átvettem**, nem számoltam újra.

## 2. Jóslat-értékelés (Q07, Q09, Q10, Q11; Q01 kontroll)

A jóváhagyott jóslat (`docs/week6-atadas.md`, "Jóváhagyott jóslat (kód
előtt)") **változatlan**. Az 5. heti FULL naiv/lokalis/globalis és a
drift v2 FULL eredménye ugyanazon kérdésekre (retrieval = `ratio`, a
globalis oszlopnál proxy):

| Kérdés | naiv | lokalis | globalis (proxy) | drift v2 |
|---|---|---|---|---|
| Q01 (kontroll) | helyes, retrieval=1.00 | helyes, retrieval=1.00 | helyes, retrieval=1.00 | helyes, retrieval=1.00, faithfulness=1.00 |
| Q07 | hiányos, retrieval=0.33 | helyes, retrieval=0.00 | elutasított, retrieval=0.00 | hiányos, retrieval=0.00, faithfulness=1.00 |
| Q09 | helyes, retrieval=0.00 | helyes, retrieval=0.00 | hiányos, retrieval=0.00 | hiányos, retrieval=1.00, faithfulness=1.00 |
| Q10 | hiányos, retrieval=0.00 | hiányos, retrieval=0.17 | hiányos, retrieval=0.50 | hiányos, retrieval=0.17, faithfulness=1.00 |
| Q11 | helyes, retrieval=0.00 | elutasított, retrieval=0.00 | hiányos, retrieval=0.00 | hiányos, retrieval=0.00, faithfulness=1.00 |

**Mi teljesült:**
- Q01 kontroll: a jóslat szerint nem vártunk javulást a naivhoz képest
  a helyességi címkében — ez teljesült (mindhárom régi mód + drift is
  "helyes"). Költséget nem lehet összevetni (a naiv Q01 `cost_usd` mezője
  `None`, azaz ismeretlen, nem 0 — nem állítható költségelőny vagy
  -hátrány). Időt lehet: naiv 4.843 s, drift 16.953 s — a várt
  többletlátenciát megerősíti.
- Q09: a drift lokális kontextusa (retrieval=1.00) előre azonosított
  bizonyítékot tartalmazott. Ez a globalis mód eltérő jelentésű
  riportforrás-proxyjával (retrieval_proxy, nem valódi chunklefedettség)
  **nem vethető össze közvetlenül** — nem állítható belőle, hogy a
  drift "jobban" vagy "rosszabbul" teljesített, mint a globalis a
  retrieval tengelyén. A helyességi címke "hiányos" maradt mindkét
  módnál, tehát a jóslat **nem bizonyított** ezen a kérdésen.
  (Mellékmegfigyelés: a Q09 primer részkérdései Alonso/Button-ra
  vonatkoztak, nem a kérdésben szereplő Hamilton/Schumacher
  holtversenyre — ez dokumentált megfigyelés, nem bizonyított
  hibaforrás, és ez a kör nem vizsgálja/javítja tovább.)
- Q10, Q11: a helyességi címke mindhárom/mindkét régi módnál és a
  driftnél is "hiányos" (Q10) / "hiányos"-hoz közeli (Q11, ahol lokalis
  "elutasított" volt, drift "hiányos") — azonos vagy hasonló címke, a
  jóslat szerinti javulás **nem igazolható** a mentett kritériumeredmény
  (helyességi címke) szintjén ezen az 5 kérdésen.
- Q07: a jóslat azt várta, segít-e a részkérdés-bontás a tényösszekötésben
  — a drift "hiányos" lett (rosszabb, mint a lokalis "helyes"), tehát
  **itt a jóslat nem teljesült**.

**Összegzés:** a mentett célkérdés-összehasonlítás szerint helyességi
kategóriában **egyik célkérdésen sem igazolódott javulás**. Teljes
mintán (15 kérdés, régi módok újra nem futtatva, 5. heti mentett FULL
eredményből átvéve) a helyes válaszok száma: drift v2 FULL **3/15**,
naiv **9/15**, lokális **7/15**, globális **2/15** — kis minta, csak
tájékoztató jellegű, nem általános algoritmusrangsor. A gyenge
eredmény **dokumentált eredmény**, nem ebben a körben javítandó hiba.

## 3. Költségek

| Tétel | Összeg (USD) | Forrás/jelleg |
|---|---|---|
| Örökölt riportgenerálás (4. hét) | 0.0537 | korábban mért, `docs/week4-kozossegi-riportok-v3.md:44` |
| Új riportindex-embedding | 0.000137 | **becsült** (a langchain embeddings kliens nem ad token-usage-t), `results/week6-index-cost.json` |
| v2 smoke (3 kérdés, belső generálás+embedding+bírók) | ≈0.01166 | `0.01679893 − 0.005138` (ledger-delta, lásd lent) |
| v2 full (15 kérdés, belső generálás+embedding+bírók) | 0.056394 | `results-v2.jsonl` esetenkénti `cost_usd` összege, `week6-drift-report-v2-full.md` |
| Kumulatív week6 fogyasztás (index + v1 smoke + v2 smoke + v2 full) | 0.073196 | `week6-cost-ledger.json`, 182 bejegyzés — **nem azonos** a full lekérdezési költséggel |

Az index- és lekérdezési költség **külön sorban** szerepel fent; az
egyszeri indexköltség a full riportban is **egyetlen, nem
kérdéstípusonkénti** sorban jelenik meg (`week6-drift-report-v2-full.md`
31. sor).

A fenti 0,073196 USD a v2 full mérés **lezárásakor** rögzített,
történeti állapot (nem íródik át). Egy ezt követő, a v2 FULL mérésétől
független demó-script (`route_demo.py`, lásd 5. szakasz) további
bejegyzéseket írt ugyanabba a megosztott ledgerbe — ez a FULL mérés
saját eredményét/költségét nem módosítja, csak a kumulatív összeget
növeli tovább. A **jelenlegi** kumulatív week6 fogyasztás a mentett
`results/week6-cost-ledger.json` szerint **0,075836 USD** (190 bejegyzés).

**A full riport 0,056394 USD összege és a ledgernövekmény közti apró
eltérés tisztázása:** a konzolos kumulatív érték v2 full után
0,07319624 USD volt, v2 smoke után 0,01679893 USD — ebből a full
mérés saját fogyasztása ledger-delta alapján `0,07319624 − 0,01679893 =
0,05639731` USD. A riportban szereplő 0,056394 USD ezzel **nem
pontosan**, csak ~0,000003 USD eltéréssel egyezik. Ennek oka: a riport
értéke 15 eset × 3 lépés (generálás, helyességi bíró, faithfulness-bíró)
= 45, **egyenként már 6 tizedesjegyre kerekített** `cost_usd_*` mező
összege (`measure.py`'s `_cost_delta`/`_recompute_total_cost`), míg a
ledger-delta csak **egyetlen**, a teljes futás elejét és végét összevető
kerekítést tartalmaz. 45 apró kerekítés összege és egy nagy kerekítés
eltérhet a 6. tizedesjegy szintjén — ez **nem hiba**, hanem eltérő
számítási alap (lépésenkénti vs. futásszintű kerekítés); nem
erőltettem az egyezést, és egyik mentett pénzügyi rekordot sem
módosítottam.

Ismeretlen usage (pl. az embeddingköltség) mindig **becsült felső
korlát**, nem mért tényleges fogyasztás, és soha nem kerekített 0 —
lásd a `SharedCostLedger` `usage_known: false` jelzését az érintett
bejegyzéseken.

## 4. Korlátok és változtatási történet

- Nincs támogatott inkrementális dokumentumfrissítés; a meglévő,
  teljes újraépítési lánc szükséges lépéseit dokumentáltuk
  (`docs/week6-atadas.md`, 8. pont) — új dokumentum hozzáadásának
  költségét külön nem mértük.
- A "Loaded 95 source documents from corpus." üzenet ellenére a
  helyi ellenőrzés szerint a lokális kereséshez használt
  chunkazonosítók és szövegek **1651/1651** esetben egyeztek az 5.
  heti fagyasztott alappal (`graph/corpus/chunks-section-1200-23/chunks.jsonl`).
- A primer 1–2 részkérdésre szigorítása (`PRIMER_PROMPT_VERSION`
  v1→v2) az első valódi smoke-futás megismerése **után** történt; a
  jóváhagyott jóslat ezt megelőzte és nem változott.
- A v1 smoke-adatok (`results/cases/smoke/`, `results/results.jsonl`)
  megmaradtak a lemezen, de **nem** a végleges (v2) mérés részei.
- Az `actual_chunk_ids` mező javítása (tényleges lokális
  kontextuschunkok, nem a teljes jelölthalmaz) a v2 full mérés
  **előtt** történt és már a v2 full adatokban érvényesül.
- A lokális kontextuslefedettség (`retrieval_avg`) és a globális mód
  riportforrás-proxy (`retrieval_proxy_avg`) eltérő jelentésű mutatók.
- A faithfulness a szintézis bemenetéhez mér, nem a teljes forráslánc
  tényszerűségét ellenőrzi.
- A router negyedik ága (`"drift"`) és a vékony végrehajtási belépési
  pont (`naive_rag.answer_question.answer_question`) offline tesztelt
  (`tests/test_answer_question.py`); automatikus, 15 kérdéses
  router-újramérés **nem történt**.
- A mérés egy kis, részben fejlesztésre is használt (13 `frozen_w4` +
  2 `held_out`) golden seten készült — nem tekinthető általános
  algoritmusrangsornak.

## 5. Futtatás és bizonyítékok

- Indexépítés, smoke, full pontos parancsai:
  `diagnostics/2026-11-14-week6-drift/README.md` "Parancsok" szakasza.
- v2 full eredmény: `diagnostics/2026-11-14-week6-drift/results/week6-drift-report-v2-full.md`,
  `results-v2.jsonl`, esetenként `cases/v2/full/*.json`.
- Új indexköltség-összesítő: `diagnostics/2026-11-14-week6-drift/results/week6-index-cost.json`.
- Jóváhagyott jóslat: `docs/week6-atadas.md`, "Jóváhagyott jóslat (kód előtt) — 2026-11-14".
- Mentett Langfuse experiment/run azonosítók
  (`results/cases/v2/langfuse-markers/`):
  - smoke: `run_name=week6-drift-smoke`, `experiment_id=a225a1d8e0037bfe507111ee04e2681b`, 3 rekord.
  - full: `run_name=week6-drift-full`, `experiment_id=066741494d6c6d04781dc6a00971a117`, 15 rekord.
  (A tényleges Langfuse-feltöltés megtörténtét ez a marker igazolja; a
  Langfuse felületét ez a dokumentum nem ellenőrizte.)
- Routeres kérdezés: a **meglévő, injektálható** belépési pont
  `naive_rag.answer_question.answer_question(question_id, question_text,
  mode_fns=..., raw_caller=...)` — ez egy Python-függvény interfész, nem
  egy kész, valós szolgáltatásokra (router modell, 4 kereső) bekötött
  CLI-parancs. Ilyen, végponttól végpontig bekötött CLI jelenleg **nem
  létezik** — a drift mód FULL mérése (fent) explicit módválasztással
  (`drift_measure.py`), nem a routeren keresztül futott.
- Valós demó e belépési pontra (`diagnostics/2026-11-14-week6-drift/route_demo.py`,
  kimenet: `results/week6-route-demo.json`): az automatikus router
  érvényes `globalis` döntést adott a demó kérdésére; a demó automatikus
  hívásánál szándékosan csak a `drift` végrehajtó volt regisztrálva
  (`route_demo.py`'s `mode_fns_auto`), ezért a `globalis` ág nem futott
  le — ez a demó bekötési korlátja, **nem router-hiba**. Az explicit
  `drift` valós hívása sikeresen lefutott. **Valós automatikus router →
  drift futást ez a demó nem igazolt**; a router → drift végrehajtás
  bizonyítéka az offline teszt (lásd DoD 2. pont).

## DoD

| # | Követelmény | Teljesült? | Hivatkozás |
|---|---|---|---|
| 1 | A választott irány saját rendszerben, saját adaton fut | **Igen** | `src/naive_rag/drift_search.py` (saját gráf/riportindex), v2 full eredmény: `diagnostics/2026-11-14-week6-drift/results/cases/v2/full/` (15/15 eset) |
| 2 | Negyedik módként elérhető az útválasztón keresztül | **Igen** | a drift negyedik módként elérhető a közös kérdés–útválasztó–kereső végrehajtási felületen (`src/naive_rag/search_router.py`, `src/naive_rag/answer_question.py`); a router → drift végrehajtást offline teszt igazolja (`tests/test_answer_question.py::RouterDispatchTests::test_router_decision_actually_invokes_the_chosen_branch`) |
| 3 | Új eredmény a mérési táblázatban, költséggel | **Igen** | `docs/week6-eredmenyek.md` 1. és 3. szakasz, forrás: `results/week6-drift-report-v2-full.md`, `results-v2.jsonl` |
| 4 | Spektrum-elhelyezés és jóslatértékelés leírva | **Igen** | README.md "6. házifeladat" szakasz (spektrum-elhelyezés); jelen dokumentum 2. szakasza (jóslatértékelés) |

A 2. pont minősítése a meglévő kódra és az offline tesztre épül, nem
valós router → drift mérési futásra. A valós `route_demo.py` demó
(5. szakasz) ezt nem igazolta (a demóban a router `globalis`-t
választott, és csak a `drift` ág volt bekötve) — ez a demó szándékosan
szűk bekötési korlátja, nem cáfolja a fenti "Igen" minősítést.
