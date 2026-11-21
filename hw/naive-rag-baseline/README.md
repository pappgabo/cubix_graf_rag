# 6. házifeladat — Modern irány

Korlátozott, **saját** DRIFT-adaptáció — nem a Microsoft DRIFT teljes
implementációja. Részletes eredmények, táblázatok és a jóslat kiértékelése:
[`docs/week6-eredmenyek.md`](docs/week6-eredmenyek.md); a tervezés/jóváhagyás
és a fázislezárások (A–E) előzménye: [`docs/week6-atadas.md`](docs/week6-atadas.md);
a futtatási parancsok és a mért/becsült mentett adatok:
[`diagnostics/2026-11-14-week6-drift/README.md`](diagnostics/2026-11-14-week6-drift/README.md).
Az 5. heti szakasz (lent) és számai **változatlanok** — ez a rész nem
írja felül azokat.

## 6.1 Módszer

Kérdésembedding → top-3 meglévő közösségi riport (`graph_merge`/
`global_search`-ből, saját riportindex-cache) → egy primer generálás
(kezdeti válasz + **1–2** célzott részkérdés) → a meglévő
`naive_rag.local_search.local_search` hívása részkérdésenként a saját
összevont gráfon és entitásindexen → egy végső szintézis. Egy kör,
nincs HyDE, nincs rekurzív/többkörös kérdésfa, nincs második modern
módszer. Implementáció: [`src/naive_rag/drift_search.py`](src/naive_rag/drift_search.py).

## 6.2 Eredmény röviden

A v2 FULL mérés (15/15 kérdés) lefutott: 4-módos összehasonlító tábla,
célkérdés-szintű jóslatértékelés és faithfulness-ellenőrzés
[`docs/week6-eredmenyek.md`](docs/week6-eredmenyek.md)-ben. Helyes
válaszok száma (kis minta, 15 kérdés; a régi módokat nem futtattuk
újra, az 5. heti mentett FULL eredményből átvéve): **drift v2 FULL:
3/15; naiv: 9/15; lokális: 7/15; globális: 2/15.** Q09-nél a drift
lokális kontextusa tartalmazott előre azonosított bizonyítékot; ez a
globális mód eltérő jelentésű riportforrás-proxyjával **nem vethető
össze közvetlenül**. A mentett célkérdés-összehasonlítás szerint
helyességi kategóriában **egyik célkérdésen sem igazolódott javulás**.
Költség: a v2 full mérés 0,056394 USD-t fogyasztott; a jelenlegi
kumulatív week6 fogyasztás (index + próbák + full + a route_demo
demó együtt, a mentett ledger szerint) **0,075836 USD** a 0,50 USD
keretből.

## 6.3 Spektrum-elhelyezés

A gráf és a közösségi riportok a korábbi heti munkából származnak: a
korpusz azonos chunkolt szövegbázisából (`graph/corpus/chunks-section-1200-23/`,
helyileg ellenőrizve: 1651/1651 chunk egyezik) kinyert, összevont
entitás-gráfból és a rá épített Leiden-közösségi riportokból (4. hét) —
a drift nem épít új gráfot vagy riportot. A közösségi szint a kérdés
globális, korpuszszintű kontextusát adja (melyik 1-3 riport releváns),
a lokális keresés pedig ezen belül 1-2 konkrét entitásra élesít, a
riport-összegzés által esetleg elvesztett részletet próbálva pótolni.
Indexeléskor csak egyszeri, olcsó riportindex-embedding történik (a
gráf/entitásindex/chunkok újrahasznosítottak, nincs újraépítés);
kérdezéskor kérdésenként legfeljebb 4 generálás és 3 embedding fut. A
mért helyes-válasz arány (3/15) a 15 kérdésből álló, kis mintán
elmarad a naiv (9/15) és a lokális (7/15) módtól, és csak a globálist
(2/15) előzi meg — ez dokumentált mérési eredmény, nem javítási
feladat ebben a körben. A jóváhagyott jóslat iránya (riport-szintű
proxy helyett valódi lokális kontextus egy célkérdésen, Q09) megfigyelhető,
de helyességi kategóriában egyik célkérdésen sem igazolódott javulás;
nem bizonyított hibaforrást (pl. a primer entitás-horgonyzása) nem
állítok tényként. Ezt az adaptációt akkor választanám, ha a kérdés
jellemzően korpuszszintű, de a válasz egy-két konkrét entitás
részletén is múlik, és a többlet késleltetés/költség elfogadható; a
mért eredmények alapján **nem** választanám olyan kérdéshalmazra, ahol
a lokális vagy naiv mód már önmagában is jobban teljesít.

## 6.4 DoD

| # | Követelmény | Teljesült? | Hivatkozás |
|---|---|---|---|
| 1 | A választott irány saját rendszerben, saját adaton fut | **Igen** | `src/naive_rag/drift_search.py`; v2 full: `diagnostics/2026-11-14-week6-drift/results/cases/v2/full/` (15/15) |
| 2 | Negyedik módként elérhető az útválasztón keresztül | **Igen** | a drift negyedik módként elérhető a közös kérdés–útválasztó–kereső végrehajtási felületen (`src/naive_rag/search_router.py`, `src/naive_rag/answer_question.py`); a router → drift végrehajtást offline teszt igazolja (`tests/test_answer_question.py::RouterDispatchTests::test_router_decision_actually_invokes_the_chosen_branch`) |
| 3 | Új eredmény a mérési táblázatban, költséggel | **Igen** | [`docs/week6-eredmenyek.md`](docs/week6-eredmenyek.md) 1., 3. szakasz |
| 4 | Spektrum-elhelyezés és jóslatértékelés leírva | **Igen** | fenti 6.3 szakasz; [`docs/week6-eredmenyek.md`](docs/week6-eredmenyek.md) 2. szakasz |

**A valós route_demo eredménye ettől külön** (`diagnostics/2026-11-14-week6-drift/results/week6-route-demo.json`):
az automatikus router érvényes `globalis` döntést adott; a demó
automatikus hívásánál csak a `drift` végrehajtó volt regisztrálva, ezért
a `globalis` ág nem futott le — ez a szándékosan szűk demó bekötési
korlátja, nem router-hiba. Az explicit `drift` valós hívása sikeresen
lefutott. **Valós automatikus router → drift futást ez a demó nem
igazolt** — a 2. DoD-pont "Igen" minősítése az offline tesztre épül, nem
erre a demóra.

# 5. házifeladat — Mérés

**Állapot (5. hét):** a teljes mérés (`--full`, 45 eset) lefutott és mentve
van. A 4. heti "Állapot"/eredmény-sorok lent **4. heti, történeti**
jelölésűek — azokat ez a szakasz nem írja felül.

## 5.1 Mit mértünk és hogyan

A jóváhagyott golden set 15 kérdésből áll: 5 simple, 5 multi-hop, 5 global;
ebből 13 `frozen_w4` (a 4. heti, fejlesztési készletből átvett kérdés) és 2
`held_out` (Q14, Q15). Verzió: `v1-approval-draft`
([`golden/week5-golden-set-v1-approval-draft.jsonl`](golden/week5-golden-set-v1-approval-draft.jsonl)).
A korpusz hash-e és chunkszáma a golden set saját
metaadat-mezőjéből (nem újraszámolva): `chunks_sha256
79d46d6291bc07924ddc13703f9b4804f8cf9c86de9de3ebaf435248f04e012e`, `chunk_count
1651`.

Három mód, a 4. heti Phase 5 konfigurációjával: naiv, lokális, globális. A
keresők (`src/naive_rag/*`) változatlanok; a naiv mód a mérésben a Phase 5
futtató kódútját használja (`diagnostics/2026-11-10-phase5-run/run_phase5.py`
`run_naiv`), **nem** a `NaiveRAG.ask`-ot
([`docs/week5-felmeres.md`](docs/week5-felmeres.md) 1. táblázat, Naiv sor).

Három metrika:
1. **Retrieval** — azonosított bizonyíték-lefedettség (arány és szigorú
   találat) az előre rögzített bizonyítékcsoportokhoz mérve.
2. **Generálás, helyesség** — saját kritérium-bíró (helyes / hiányos / téves /
   elutasított, a golden set rubrikájához mérve).
3. **Generálás, megalapozottság** — saját, claim-szintű faithfulness-bíró.

Ez **nem Ragas**. A Ragas kimaradt, mert a telepítése visszahúzná az `openai`
csomagot ([`docs/week5-felmeres.md`](docs/week5-felmeres.md) 2. szakasz).

Egy CLI-belépési pont, két futásmérettel:

```powershell
uv run python diagnostics/2026-11-11-week5-b/measure.py run --smoke
uv run python diagnostics/2026-11-11-week5-b/measure.py run --full
```

A futás folytatható, szakaszonként mentett állapottal. Langfuse Cloud EU,
módonként egy run a teljes golden seten; a feltöltés utólagos, a mentett
eredményekből épül, nem élő generálási trace. A helyi `results.jsonl` az
elsődleges archívum.

## 5.2 Eredmények

Forrás a táblákhoz:
[`diagnostics/2026-11-11-week5-b/results/week5-b-report-full.md`](diagnostics/2026-11-11-week5-b/results/week5-b-report-full.md)
(kizárólag a teljes, 45 esetes futás — a füstpróba nincs beleszámítva).

**Három mód × kérdéstípus** (típusonként és módonként 5-5 kérdés; a
kategóriaösszegek egyeznek a cella elemszámával):

| Kérdéstípus | naiv | lokalis | globalis |
|---|---|---|---|
| simple | n=5, helyes=5 | n=5, elutasított=1, helyes=4 | n=5, elutasított=3, helyes=1, hiányos=1 |
| multi-hop | n=5, elutasított=1, helyes=2, hiányos=2 | n=5, elutasított=1, helyes=2, hiányos=2 | n=5, elutasított=1, helyes=1, hiányos=3 |
| global | n=5, elutasított=1, helyes=2, hiányos=2 | n=5, elutasított=2, helyes=1, hiányos=2 | n=5, hiányos=5 |

**frozen_w4 / held_out bontás** (ugyanabból a riportból):

| | naiv | lokalis | globalis |
|---|---|---|---|
| frozen_w4 (n=13) | elutasított=2, helyes=7, hiányos=4 | elutasított=3, helyes=6, hiányos=4 | elutasított=2, helyes=2, hiányos=9 |
| held_out (n=2) | helyes=2 | elutasított=1, helyes=1 | elutasított=2 |

**Retrieval módonként** (átlagos lefedettségi arány a riportból; a szigorú
találat darabszáma a riport nem tartalmazza, ezért a `results.jsonl` teljes
futásra szűrt sorain számolva). „Szigorú találat” a metrikát számító kód
tényleges feltétele szerint: a kérdés **összes kötelező** bizonyítékcsoportjára
van legalább egy egyező chunk-azonosító (`hit_count == group_count`,
[`diagnostics/2026-11-11-week5-b/retrieval_eval.py`](diagnostics/2026-11-11-week5-b/retrieval_eval.py)
90. sor) — nem azonos a részleges (nem minden csoportra meglévő) találattal.

| Mód | n | átlagos lefedettségi arány | szigorú találat |
|---|---|---|---|
| naiv (valódi lefedettség) | 15 | 0,38 | 5 / 15 |
| lokalis (valódi lefedettség) | 15 | 0,38 | 5 / 15 |
| globalis — **proxy, nem valódi lefedettség** | 15 | 0,25 | 2 / 15 |

A globalis sor értékei **proxyk**: a reduce-nak ténylegesen átadott
részválaszok forráskapcsolataiból képzett arány, nem valódi,
soronként ellenőrzött bizonyíték-lefedettség. A fenti táblázat három sora
emiatt **nem** egy közös átlag három bontása — a globalis proxy-értéket sem a
naiv, sem a lokalis valódi lefedettségi mutatójával nem szabad összeátlagolni
vagy azonos jelentésűként kezelni. Hiányzó visszavezetés (amit a mérés nem
nullaként, hanem külön "untraceable" állapotként kezel) egy esetben sem
fordult elő
(`diagnostics/2026-11-11-week5-b/results/week5-b-report-full.md`: "retrieval
nem visszavezethető: 0").

**Faithfulness módonként** (`results.jsonl`, teljes futás):

| Mód | számítható eset | átlag | n/a |
|---|---|---|---|
| naiv | 13 | 1,00 | 2 |
| lokalis | 11 | 0,93 | 4 |
| globalis | 8 | 1,00 | 7 |

Az n/a (nincs tényszerű állítás, pl. elutasítás) nem nulla pontszám.

**Költség és idő**
(`diagnostics/2026-11-11-week5-b/results/week5-b-report-full.md` és
`diagnostics/2026-11-11-week5-b/results/week5-b-cost-ledger.json`):

- A teljes futás 45 esetéből **39-nél mindhárom szakasz (generálás, két bíró)
  költsége ismert**; ezekre az ismert, teljes költség összege **0,079069
  USD**. A maradék 6 eset nem egyforma: **5 teljesen ismeretlen** költségű
  (`cost_usd_generation`/`_correctness_judge`/`_faithfulness_judge` mind
  `null`, nem nulla fogyasztás) — Q01 mindhárom módban (naiv, lokalis,
  globalis) és Q02 naiv, lokalis módban —, plusz **1 részleges**: Q02
  globalis, ahol a két bírói lépés költsége ismert
  (`cost_usd_correctness_judge`/`_faithfulness_judge`), csak a generálásé
  (`cost_usd_generation`) `null`
  (`diagnostics/2026-11-11-week5-b/results/cases/full/Q02-globalis.json`,
  illetve a `results.jsonl` megfelelő sora). Ez összesen 5+1=6, egyezik a
  riport "hiányzó költségű esetek: 6" sorával.
- Ez **nem azonos** a megosztott `week5-b-cost-ledger.json` kumulatív
  összegével: az a füstpróbát és a korábbi próbálkozások rögzített
  fogyasztását is tartalmazza. A ledger mind a 747 bejegyzése ténylegesen mért
  (`usage_known: true`) usage-adat, összesen **0,107356 USD** a közös 0,50
  USD-s heti keretből — ez a teljes, kumulatív fogyasztás, nem kizárólag a
  teljes futásé.
- Az átlagos futásidő a riport szerint **23,948 s** — ez a `duration_seconds`
  mező átlaga, azaz a generálási lépés ideje; a két bíró ideje külön,
  esetenként (`duration_seconds_correctness_judge`,
  `duration_seconds_faithfulness_judge`) van mentve, a riport ezt nem adja
  össze a generálási idővel.

Csak a teljes futás sorai szerepelnek fent (a `run_phase == "full"` sorok,
`results.jsonl`); a 4. heti 39 választ és a füstpróba eseteit nem emeltük be
— kivétel a fent külön jelölt, kumulatív költségkeret.

## 5.3 Mit mondanak a számok

Típusonként 5 kérdés van, ezért egy kérdés 20 százalékpont — az alábbiak
irányt mutatnak, nem statisztikailag szignifikáns vagy általános
algoritmus-rangsor:

- **Simple** kérdéseken a naiv mód adott minden esetben helyes választ (5/5);
  a lokalis 4/5, a globalis csak 1/5 (3 elutasítás) — egy globalis elutasítás
  már 20 százalékpontot jelent.
- **Multi-hop**-on a naiv és a lokalis azonos elosztást mutat (2 helyes, 2
  hiányos, 1 elutasított); a globalis itt is gyengébb (1 helyes, 3 hiányos).
- **Global** típuson egyik mód sem domináns; a globalis mind az 5 esetben
  "hiányos"-at kapott.
- **Konkrét szakadék-példa (teljes futásból):** Q08/lokalis esetében a
  retrieval szigorú találatot adott (arány 1,0, minden kötelező
  bizonyítékcsoport lefedve), a válasz a bíró szerint "helyes" (Bottas váltotta
  Rosberget, Williamstől érkezett), **mégis faithfulness=0,5** (1
  alátámasztott, 1 alá nem támasztott tényszerű állítás,
  `results.jsonl`, Q08/lokalis sor). Ez azt mutatja, hogy a teljes,
  előre azonosított bizonyíték megléte sem garantálja, hogy a válasz minden
  állítása a kontextusból vezethető le.
- A füstpróbában korábban megfigyelt, hasonló (alacsony retrieval + alacsony
  faithfulness) Q07/lokalis-mintázat a teljes futásban **nem reprodukálódott**
  — az újonnan generált Q07/lokalis válasz faithfulness-értéke a teljes
  futásban 1,00 (`results.jsonl`); a korábbi megfigyelést nem vettük át
  ellenőrzés nélkül.
- Több "helyes" besorolású esetnél a retrieval-arány 0,0 (pl. Q09/naiv,
  Q11/naiv), miközben a faithfulness 1,00 — ez nem feltétlenül keresési hiba:
  azt jelenti, hogy "az előre azonosított bizonyíték nem szerepelt a
  kontextusban", miközben más, a kontextusban ténylegesen jelen lévő forrás
  alátámasztotta a választ.
- A magas faithfulness-érték önmagában nem jelent teljesen helyes vagy teljes
  választ — pl. Q09/globalis faithfulness=1,00, miközben a besorolása
  "hiányos".

## 5.4 Mit nem mér ez a mérés

- A retrieval-lefedettség előre azonosított bizonyítékcsoportokra mér; az
  alternatív forrásokat nem soroltuk fel teljes körűen. Nem mutatja, hogy a
  modell ténylegesen felhasználta-e a chunkot. A sokcsoportos kérdéseken
  (pl. Q10, Q12, Q13) a szigorú találat strukturálisan alacsony lehet.
- A globális retrieval proxy a reduce-ba jutó részválaszok
  forráskapcsolataiból készül, nem szövegmegmaradást igazol; a valódi
  bizonyíték-lefedettség n/a.
- A faithfulness-bíró és a helyesség-bíró ugyanaz a modell (`gpt-4o-mini`),
  mint a generáló — saját-modell torzítás lehetséges
  ([`docs/week5-b-megvalositas.md`](docs/week5-b-megvalositas.md), "Azonos
  generáló/bíró modell torzítása"). A helyesség-bíró a rubrikához mér; a
  rubrikán kívüli téves állítást nem feltétlenül veszi észre. A bírók
  megbízhatóságát nem validáltuk emberi címkékkel.
- Kérdéstípusonként egy kérdés 20 százalékpont; a golden set kicsi. A 13
  `frozen_w4` kérdés fejlesztési készlet volt; a 2 `held_out` kérdés könnyű,
  egy-chunkos tétel
  ([`golden/week5-golden-set-jovahagyas.md`](golden/week5-golden-set-jovahagyas.md)). A
  teljes 15 kérdéses eredmény nem tekinthető független tesztkészleten mért
  eredménynek.
- A rubrika a kézzel rögzített szabályokat követi
  ([`golden/week5-golden-set-jovahagyas.md`](golden/week5-golden-set-jovahagyas.md)). A
  "helyes" a rubrika szerinti helyességet jelenti, nem teljes
  tényellenőrzést.
- Három konkrét konfigurációt hasonlítottunk össze, eltérő kontextusmérettel
  és reprezentációval, nem izolált algoritmusokat. A kontextusméret
  karakteralapú becslés, nincs külön tokenmérés.
- A globális mód a 4. heti közösségi riportokból dolgozik; ezek tömörítése
  információt veszíthet, az izolált csúcsok nem kerültek riportba — ezt a
  mérés nem javítja.
- A Langfuse-feltöltés utólagos; a Hobby csomag 30 napos történeti
  hozzáférést ad (forrás: https://langfuse.com/pricing), ezért a helyi
  `results.jsonl` az elsődleges archívum.
- A generálás és a két bíró költsége a közös nyilvántartásban szerepel, de
  esetenként teljes költségadat csak a javítás után megfelelően rögzített
  szakaszokból áll rendelkezésre — lásd fent, 39/45 teljes, 6 részleges vagy
  ismeretlen. A hiányzó esetenkénti adatot ne tekintsd nulla költségnek.

## 5.5 Újrafuttatás és fájlok

```powershell
uv run python diagnostics/2026-11-11-week5-b/measure.py run --smoke
uv run python diagnostics/2026-11-11-week5-b/measure.py run --full
```

A megfelelő parancs ismételt kiadása a mentett állapotból folytatja az adott
futást; a kész szakaszokat nem futtatja újra. A smoke és a full külön
állapotot és esetfájlokat használ, ezért a full nem használja újra
automatikusan a smoke válaszait.

A futás **fizetős OpenAI-hívásokat indít, és Langfuse-ba is feltölt**. A közös
0,50 USD heti keret a
[`results/week5-b-cost-ledger.json`](diagnostics/2026-11-11-week5-b/results/week5-b-cost-ledger.json)-ból
követhető; a korábbi fogyasztás új futás indításakor nem nullázódik.

Fő fájlok:
- [`diagnostics/2026-11-11-week5-b/`](diagnostics/2026-11-11-week5-b/) — mérési
  kód és bírópromptok (`judges/`);
- a ténylegesen használt golden set:
  [`golden/week5-golden-set-v1-approval-draft.jsonl`](golden/week5-golden-set-v1-approval-draft.jsonl);
- [`diagnostics/2026-11-11-week5-b/results/`](diagnostics/2026-11-11-week5-b/results/)
  — `results.jsonl`, riportok, `week5-b-cost-ledger.json`;
- `diagnostics/2026-11-11-week5-b/state/` — folytatási állapot;
- [`docs/week5-b-megvalositas.md`](docs/week5-b-megvalositas.md) —
  megvalósítási jegyzetek és korlátok.

---

# 4. házifeladat — Közösségek és globális keresés

Ez a repó a GraphRAG kurzus 4. heti projektfeladatának megvalósítását
tartalmazza, az előző három hét eredményeire építve. A feladat
Leiden-közösségdetekciót, közösségi riportgenerálást, globális map–reduce
keresést, útválasztást és a naiv, lokális, globális keresés összehasonlítását
foglalja magában.

A 4. heti megvalósítást és mérést **lezárt munkaként** mutatjuk be. Ez nem
jelenti a rendszer hibamentességét, és nem jelenti azt, hogy a saját,
szigorúbb Phase 5-specifikáció minden eleme (pl. a teljes körű
alátámasztottság/hibaforrás-szétválasztás) teljesült — lásd a Korlátok
szakaszt.

## A 4. házifeladat eredménye

### Rövid teljesítési áttekintés

| Feladatrész | Bizonyíték (repó-relatív) |
|---|---|
| Közösségek a gráfban, hierarchiaszintekkel, rögzített seeddel (42) | [`docs/week4-neo4j-mentes.md`](docs/week4-neo4j-mentes.md) — 520 `:Community`, szintenként 37/176/253/54, `:CommunityRun` provenance-szal |
| Közösségstatisztika | [`docs/week4-kozosseg-statisztika.md`](docs/week4-kozosseg-statisztika.md) |
| Generált közösségi riportok + előállítás mért ráfordítása | [`docs/week4-kozossegi-riportok-v3.md`](docs/week4-kozossegi-riportok-v3.md) (37/37 riport, $0,0537, 161,6 s); offline bemenetmérés: [`docs/week4-reportbemenet-meres.md`](docs/week4-reportbemenet-meres.md) |
| Működő globális keresés | [`src/naive_rag/global_search.py`](src/naive_rag/global_search.py); első futás: [`docs/week4-globalis-kereses-phase4.md`](docs/week4-globalis-kereses-phase4.md) |
| Phase 4 A/B vizsgálat (nulla pontos részválaszok bevonása, Q09–Q13) | [`docs/week4-globalis-kereses-phase4.md`](docs/week4-globalis-kereses-phase4.md) |
| Útválasztó + hibás döntés(ek) listája | [`src/naive_rag/search_router.py`](src/naive_rag/search_router.py), [`src/naive_rag/router_eval.py`](src/naive_rag/router_eval.py); eredmény lent, az Útválasztó szakaszban |
| Háromoldalú, kérdéstípusonkénti összehasonlítás | [`docs/week4-osszehasonlitas-es-ertekeles.md`](docs/week4-osszehasonlitas-es-ertekeles.md) *(hivatkozott dokumentum; a jelen lezáráskor nem található a repóban — lásd a Záró jelentést)*; nyers futási eredmények: [`diagnostics/2026-11-10-phase5-run/results/`](diagnostics/2026-11-10-phase5-run/results/) |

**A Phase 4 A/B vizsgálat** (csak Q09–Q13-on, két reduce-ág összevetése:
csak pozitív pontszámú vs. nulla pontszámúakat is beengedő részválaszok) **nem
azonos** a **Phase 5 háromoldalú összehasonlító futásával** (mind a 13
kérdés, mindhárom mód, kizárólag a normál szűrésű A ággal — B ág Phase 5-ben
nem készült).

### Hierarchiaszint és riportkészlet

A [`docs/week4-kozosseg-statisztika.md`](docs/week4-kozosseg-statisztika.md)
„Jelentési szint és a riportkészlet kiválasztása" szakaszának összefoglalása:

- A riportok az előkészített vetület **0. szintjére** épültek.
- A 0. szinten **37** nem izolált közösség volt; az 1. szinten **191**.
- A legnagyobb 0. szintű közösség **168** csúcsot tartalmazott, a vetület
  **6,4%-át**.
- Ebben a közösségben a legnagyobb belső fokú csúcs a többi tag
  **20,4%-ához** kapcsolódott.
- Az eredeti statisztikai javaslat a 10 főnél nagyobb **19** közösség
  összefoglalása volt; ténylegesen **mind a 37** nem izolált 0. szintű
  közösséghez készült riport. Ez a bevonási kör **bővítése**, nem
  hierarchiaszint-váltás.
- A kevesebb riport/map-hívás költségelőnye **utólagos értelmezés**, nem
  korábban bizonyított szintoptimalizálás.
- Más hierarchiaszintek riportjain végzett összehasonlító válaszminőségi
  mérés **nem történt**.

Részletes indoklás: [`docs/week4-kozosseg-statisztika.md`](docs/week4-kozosseg-statisztika.md#jelentési-szint-és-a-riportkészlet-kiválasztása).

### A lezárt összehasonlítás eredménye

A Phase 5-ben elkészült és mentve: **13 naiv**, **13 lokális**, **13
globális** válasz, **13 útválasztási döntés** — fájlhivatkozások:
[`diagnostics/2026-11-10-phase5-run/results/`](diagnostics/2026-11-10-phase5-run/results/).
A szabályos elutasítás (pl. "a rendelkezésre álló rész nem támasztja alá a
választ") **mentett eredménynek** számít, nem hiányzó adatnak.

A projektgazda által elfogadott besorolások összesítése:

| Mód | Helyes | Hiányos | Téves | Elutasított |
|---|---:|---:|---:|---:|
| Naiv | 7 | 2 | 2 | 2 |
| Lokális | 6 | 3 | 1 | 3 |
| Globális | 1 | 5 | 2 | 5 |

Két megjegyzés a besoroláshoz: a **Q07 naiv** válasza azért hiányos, mert a
bajnokot nem nevezi meg (az egypontos különbség kimaradása önmagában nem
lenne levonási ok); a **Q13 globális** válaszát gyenge, részleges
szintézisként hiányosnak értékeltük.

Rövid következtetések:
- A **naiv** mód a *simple* és a *global* címkéjű kérdéscsoportban adott
  több teljesen helyes választ.
- A **lokális** mód a *multi-hop* csoportban szerepelt legerősebben,
  különösen Q04 és Q07 esetében.
- A **globális** mód nagyobb feldolgozási ráfordítása ebben a
  megvalósításban **nem** járt következetesen jobb válaszminőséggel.
- Ez **három konkrét konfiguráció** összevetése egy kis kérdéskészleten, nem
  általános algoritmusrangsor.

Részletes dokumentum: [Összehasonlítás és értékelés](docs/week4-osszehasonlitas-es-ertekeles.md).
Az előzetes, kódból generált munkalap
([`docs/week4-ertekelesi-lap-kitoltott.json`](docs/week4-ertekelesi-lap-kitoltott.json))
**nem** az elfogadott végső besorolások elsődleges forrása.

### Útválasztó

Előre rögzített feladattípus szerinti megfeleltetés (nem a legjobb választ
jósolja, csak egy kiindulási elvárást):

| Típuscímke | Elvárt mód |
|---|---|
| simple | naiv |
| multi-hop | lokális |
| global | globális |

Eredmény: **12/13** egyező döntés, **1/13** eltérés — a hibás döntés **Q06**
(lokális helyett globálisat választott).

A routerrel kiválasztott (azaz a feladattípus-megfeleltetés szerint ténylegesen
használt) mentett válaszok besorolása: **6 helyes, 4 hiányos, 1 téves, 2
elutasított**.

A típus szerinti egyezés **nem azonos** a helyes végső válasszal: a router
ebben a mérésben **nem** adott több teljesen helyes választ, mint a minden
kérdésen egységesen alkalmazott naiv mód. A router döntése miatt **nem**
történt külön, újabb válaszgenerálás — az összevetés a már mentett keresési
eredményekből készült.

### Aktuális és történeti adatok

| | Régi naiv baseline (1–3. hét) | Jelenlegi Phase 5 összehasonlítás |
|---|---|---|
| Chunkolás | 500/75 | 1200/100 |
| Chunkszám | 3832 | 1651 |
| Qdrant-gyűjtemény | `f1_naive_rag` (érintetlen, történeti referencia) | `week4_naive_baseline_1200_23` (új) |
| Embeddingmodell | `text-embedding-3-small` | `text-embedding-3-small`, 1536 dimenzió |
| top_k | 4 | 4 |

Az eredeti `chunk_id`-k megmaradtak, **nem történt újrachunkolás** az új
gyűjteményhez. A `baseline/answers.json` és az `f1_naive_rag` gyűjtemény
**történeti referencia** marad, nem módosult.

### Költség és végrehajtási eltérések

A Phase 5 **jelentett** teljes OpenAI API-költsége a lezáró futtatási
jelentés szerint: **0,066515 USD** a 0,15 USD keretből
([`diagnostics/2026-11-10-phase5-run/results/week4-phase5-run-summary.json`](diagnostics/2026-11-10-phase5-run/results/week4-phase5-run-summary.json)).
Ez a futtatási jelentés szerinti adat, nem egy utólag mindenre kiterjedően
újraauditált könyvelés. Nem tartalmazza a fejlesztői (Claude) munkamenet
fogyasztását. A közösségi riportgenerálás (Phase 3) költségmérése ettől
külön dokumentum: [`docs/week4-kozossegi-riportok-v3.md`](docs/week4-kozossegi-riportok-v3.md).

Végrehajtási eltérések:
- A **naiv Q01** a technikai helyreállítás (resume) közben **kétszer**
  kapott sikeres generatív hívást a futtatási utasítás ellenére — ez
  **végrehajtási eltérés**, nem pusztán adminisztratív korlát. A jelentett
  teljes költség **mindkét hívás díját tartalmazza**. Az értékelés a
  kitöltött munkalapban a futtatási beszámoló szerint **később mentett**
  választ használta.
- Egyes ledger-mezők hiányosak, és a belső hívásszámlálók folytatáskor
  (resume) nullázódtak — ez **nem teljes körű ledger-audit**, a dollár
  összeg maga a megbízható forrás.
- A globális mód map-hívásainak száma (**13 × 37 = 481**) a futtatási
  beszámolóban közölt, számított darabszám; külön dokumentummal nem
  tétel-szintűen újraauditált ledger-szám.

### Korlátok és tanulságok

- Az audit **Q09 és Q10** egyes elemeinél igazolt információvesztést talált
  a riportgenerálás során (a Phase 3 bemenetben megvolt, a generált
  riportból kimaradt).
- **Q11-nél** az összesítő információ hiányzott a riportokból, de a korábbi
  (extrakciós) kiesési pont **nem tisztázott**.
- A **736 izolált csúcs** egyike sem került riportba — ez a globális
  keresés lefedettségi korlátja.
- A legnagyobb közösség **168** tagjából **89** csomópont szerepelt a
  riportgeneráló modell bemenetében (a 24 000 tokenes keret miatt).
- A Phase 4 **teljes kérésnaplói hiányoztak**; az akkori ellenőrzés
  rekonstruált bemenetekre és kódellenőrzésre épült.
- A Phase 5 új generatív hívásaihoz **kérés- és válasznaplózás** készült,
  a futtatási beszámoló szerint.
- A három alátámasztottsági kategória és a keresési/generálási hibák
  **teljes, bizonyítékalapú szétválasztása nem készült el** — ez a saját,
  szigorúbb Phase 5-specifikáció **részleges** teljesítése, nem a házi
  feladat Definition of Done-jának külön pontja.
- A fejlesztés és a mérés **ugyanazon a 13 kérdésen** történt: az eredmény
  **nem független teszt**.
- A hibás válaszokat **eredményként dokumentáltuk**, nem javítottuk
  utólag új modellhívásokkal.
- A `gpt-4o-mini` esetleges deprecated státuszát **nem ellenőriztük**
  hivatalos forrásból; ezt nem állítjuk sem úgy, sem úgy.

---

## Korábbi hetek (1–3. hét) — történeti háttér

A lenti szakaszok a GraphRAG kurzus 1–3. heti feladatait írják le (naiv RAG
baseline, gráfréteg, extrakció és lokális keresés). Ezek a 4. heti munka
alapjai, és változatlanul megmaradnak — a baseline válaszait és a korábbi
méréseket utólag nem javítottuk.

### A 3. házifeladat eredménye

Részletes kötés fájlokhoz: [`docs/extrakcio-es-lokalis-kereses.md`](docs/extrakcio-es-lokalis-kereses.md).
A jelenlegi minőségi riport: [`graph/corpus/quality-report-section-1200-23.md`](graph/corpus/quality-report-section-1200-23.md).

A korpusz 23 dokumentum, benne a visszahelyezett `corpus/driver-charles-leclerc.html`.
A GraphRAG-chunkok 1200 karakteresek, 100 karakteres átfedéssel: 544 section,
1651 chunk.
Az extrakció: `graph/corpus/extraction-reuse-1200-23`, 1651 sikeres rekord, 0 hibás,
315 üres siker. Modell: `gpt-4o-mini`, embedding: `text-embedding-3-small`,
prompt: `f1-pilot-3`.

| Lépés | Eredmény |
|---|---|
| Extrakció | 1651 rekord, mind strukturálisan sikeres; 315 üres |
| Összevont gráf | előtte 10782 csomópont / 6533 él / legnagyobb komponens 30; utána 2761 / 4326 / 1896 |
| Neo4j | 2761 `:Extracted` csomópont, 10782 `MENTIONS`, 4326 szakterületi él, 29 `:Seed` |
| Entitásindex | 2761 vektor, név és leírás együtt, `text-embedding-3-small`, 1536 dimenzió |
| Lokális keresés | Q01–Q13 lefutott a jelenlegi gráfon: 13 kérdésembedding, 13 válaszhívás, üres horgonylista nem volt |

Az előtte az előfordulási gráf, az utána az ugyanazon 1651 rekordból készült
összevont gráf. A részletek és a megnevezett hiba a minőségi riportban vannak.
A hiba: `driver-sebastian-vettel#21` címsorából `Title` nevű Title entitás lett.
A ritka chunk `driver-charles-leclerc#14`, üres címsor. A legnagyobb fokszám 194,
`Team:mclaren`; a szám nem jelent fontosságot.

A jelenlegi Q01–Q13 összevetés: [`docs/osszehasonlitas-section-1200-23.md`](docs/osszehasonlitas-section-1200-23.md),
naplója [`docs/osszehasonlitas-section-1200-23-run.json`](docs/osszehasonlitas-section-1200-23-run.json).
Mind a 13 kérdés lefutott. Üres horgonylista nem volt, ezért 13 válaszhívás készült.
A modell a Q04, Q05, Q09 és Q13 kérdésnél az elutasító mondatot adta. A Q04–Q08
multi-hop kérdések külön szakaszban vannak. A régi összevetés történeti:
[`docs/osszehasonlitas.md`](docs/osszehasonlitas.md) és
[`docs/osszehasonlitas-run.json`](docs/osszehasonlitas-run.json), a 401 entitásos
gráf válaszai. A korábbi futások szintén történetiek:
`docs/osszehasonlitas-elso-futas.md`, `docs/osszehasonlitas-masodik-futas.md`,
`docs/osszehasonlitas-harmadik-futas.md`. A régi minőségi riport:
`graph/corpus/quality-report.md`.

A baseline `baseline/answers.json` az eredeti 2026-10-06-i futás, 13 kérdéssel.
Újragenerálni nem kell. Az új gráfon a kérdések futtatása külön kimenetbe ír,
és fizetős hívás: 13 kérdésembedding, valamint legfeljebb 13 válaszhívás.
Üres horgonylista esetén az adott kérdésre nincs válaszhívás. Entitás-embedding
nem készül.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m naive_rag.local_search `
  --baseline baseline\answers.json `
  --out docs\osszehasonlitas-section-1200-23.md `
  --run
```

`--run` nélkül a parancs csak a 13 kérdést számolja, modellt nem hív.
A chatmodell `gpt-4o-mini`, a kérdésembedding `text-embedding-3-small`.
A keresés a Neo4j-ben lévő jelenlegi gráfot olvassa.
A `diagnostics/2026-11-05-local-search/04_salvage_impact.py` a 3. fázisban változott: a mentett jelölt önhurokját külön okkal ejti ki, a rekord többi éle megmarad.

**Stack:** Python 3.11 · `uv` · LangChain · OpenAI (`gpt-4o-mini`,
`text-embedding-3-small`) · Qdrant (helyi, lemezre perzisztáló) · Neo4j 5.26
(Docker Compose) · FastAPI.

## Gyors indulás

```bash
uv sync                               # környezet + függőségek
cp .env.example .env                  # majd írd be az OPENAI_API_KEY-t

# 1. hét — naiv RAG
uv run naive-rag ingest               # korpusz -> chunkok -> embedding -> Qdrant
uv run naive-rag ask "Who won the 2021 Formula One World Drivers' Championship?"
uv run naive-rag baseline             # mind a 13 kérdés -> baseline/
uv run naive-rag serve                # FastAPI: http://127.0.0.1:8000/docs

# 2. hét — gráf (nem kell hozzá OPENAI_API_KEY)
uv run naive-rag graph up             # Neo4j indítása compose-ból, egészségesre várva
uv run naive-rag graph init           # megszorítások + indexek
uv run naive-rag graph seed           # kitalált szakterületi gráf
uv run naive-rag graph load           # a valódi korpusz: Document / Section / Chunk
uv run naive-rag graph query          # 8 Cypher -> graph/query-results.md
uv run naive-rag graph stats          # mi van bent (címkék, élek, alakzatok)
```

Chunk-méret kipróbálása kódszerkesztés nélkül:
`uv run naive-rag ingest --chunk-size 800 --chunk-overlap 120`, majd
`uv run naive-rag baseline --tag c800` (a válaszok a `baseline/c800/` alá kerülnek).

Ha a klón útvonala ékezetes karaktert tartalmaz (pl. Windows-on `...\1_hét\...`)
és `uv run naive-rag ...` `ModuleNotFoundError: No module named 'naive_rag'`-ot
dob, használd helyette `uv run python run.py ...`-t (lásd lent, *Hibaelhárítás*).

## 1. A korpusz

- **Téma:** Formula 1 — pilóták, csapatok, szezonok, alapfogalmak.
- **Forrás:** angol Wikipédia (`action=query&prop=extracts` API), CC BY-SA 4.0.
  Minden dokumentumhoz tárolva: cím, URL, revízió-azonosító, letöltés ideje.
- **Méret:** 23 dokumentum, ~205 000 szó.
- **Formátumok:** 6× PDF, 6× HTML, 5× DOCX, 5× TXT, 1× XLSX (lásd a szorgalmi A-t).
- **Összetétel:** 10 pilóta (Hamilton, Verstappen, Vettel, Alonso, Schumacher,
  Räikkönen, Rosberg, Button, Leclerc, Bottas), 6 csapat (Mercedes, Ferrari,
  Red Bull, McLaren, Williams, Renault), 5 szezon (2008, 2012, 2016, 2020, 2021),
  2 referencia (Formula One, a világbajnokok listája).
- **Újraelőállítás:** `scripts/download_corpus.py` (letöltés), majd
  `scripts/convert_formats.py` (átalakítás vegyes formátumra).

**Miért ez a korpusz?** Az entitások (pilóta ↔ csapat ↔ szezon) több
dokumentumban is megjelennek, ezért vannak valódi multi-hop kérdések (két
dokumentum összekötése) és globális kérdések (az egész korpusz aggregálása).

### Tapasztalatok a próba-betöltéskor

- A Wikipédia plaintext-kinyerés a **táblázatokat elhagyja** (pl. a bajnoklista
  „by season" táblázata nem jön át), ezért a bajnoklistát külön XLSX-ként
  állítottam elő. **Fontos következmény:** ez az XLSX egy „összefoglaló
  lap", amin keresztül egyes kérdések (Q06, Q09) könnyebben megválaszolhatók,
  mint a korpusz többi részéből — lásd a kiértékelésnél.
- A **PDF**-ekből a szöveg ékezethelyesen kinyerhető, oldalszámmal.
- **Első változat (v1): DOCX/HTML-ben nincs oldal/szekció.** A `Docx2txtLoader` és
  a `BSHTMLLoader` kimenetéből a címsorok elvesztek, így ezeknél a
  forrás-megjelölés csak fájl szintű volt. A PDF-ek első oldalán a
  forrás-metaadat fejléc is bekerült a chunkokba (zaj).
- **Javítás (v2):** DOCX → `pandoc` Markdown, HTML → `markdownify`, TXT →
  `== Cím ==` sorokból Markdown címsor; a chunkolás előtt
  `MarkdownHeaderTextSplitter` szekciókra bont. Mérés (API nélkül): a chunkok
  96–100%-a kapott oldal- vagy szekció-metaadatot (HTML 100%, PDF 100%,
  XLSX 100%, TXT 97%, DOCX 96%); a hiányzók a címsor előtti bevezető
  szakaszok. A fejlécsorokat kiszűrtem a szövegből (0 chunk tartalmaz ilyet);
  az adat a `metadata.json`-ban és a chunk-metaadatban megmarad.
- A korpusz 2026-os Wikipédia-állapotot tükröz (pl. Hamilton már a Ferrarinál).

## 2. A pipeline és a döntések

`src/naive_rag/`: `loaders.py` (betöltés) → `ingest.py` (chunkolás + indexelés) →
`vectorstore.py` (Qdrant) → `rag.py` (lekérdezés) → `cli.py` / `api.py`.

- **Betöltés:** formátumonként más loader (lásd A); minden chunk megtartja a
  fájlnevet, `doc_id`-t, URL-t, formátumot, PDF-nél az oldalszámot, DOCX/HTML/TXT-nél
  a szekció útvonalát (`section`), XLSX-nél a munkalapot, és kap egy stabil
  `chunk_id`-t (`<doc_id>#<n>`). A DOCX-hez a `pandoc` külső
  program kell (nem pip-csomag). Az `ingest` az elején, a betöltés előtt
  ellenőrzi, és ha hiányzik, platformnak megfelelő telepítési tanáccsal áll le
  (Windows: `winget install JohnMacFarlane.Pandoc`, utána új terminál;
  macOS: `brew install pandoc`; Linux: `apt install pandoc`).
- **Chunkolás: `RecursiveCharacterTextSplitter`, 500 karakter, 75 overlap.**
  Indoklás a korpuszon **mért** adatokból: a bekezdések rövidek (4525 bekezdés,
  medián 121 karakter, p90 721, 83%-uk ≤ 500 karakter). A 500 karakter így a
  bekezdések többségét egyben tartja, és néhány rövidet összevon, ami fókuszált
  embeddinget ad. Az overlap ~15%, hogy a határon átnyúló mondat mindkét oldalról
  megtalálható legyen. Ez **kiinduló érték**, nem bizonyított optimum: a
  `ingest --chunk-size/--chunk-overlap` kapcsolókkal más méretek is
  összehasonlíthatók (500/75 → 3832 chunk; a v1 betöltőkkel mérve 300→6091,
  500→3576, 1000→1843). Várható hátrány:
  a kis chunkok szétszabdalják a kontextust, ami a multi-hop és globális
  kérdéseknek nem kedvez.
- **Vektoradatbázis: Qdrant** (helyi, lemezre perzisztáló mód, Docker nélkül;
  `QDRANT_URL`-lel szerverre is átállítható). Azért Qdrant, mert ez a
  választott irány; a vektorstore-réteg különálló modul (`vectorstore.py`), így
  egy későbbi pgvector-váltás ide korlátozódik. **Hibatanulság:** a
  `langchain-qdrant` `force_recreate=True` beállítása helyi módban *nem* törölte
  a régi pontokat, ezért egy újraindexelés összeadta a régi és az új chunkokat
  (7408 pont 3832 helyett), és minden találat duplikálva jött vissza. Ma az
  `ingest` az index tárolómappáját törli újraépítés előtt, a végén pedig
  ellenőrzi, hogy a pontok száma egyezik a chunkokéval (eltérésnél hibát dob).
  Ez a chunk-méret összehasonlítást is érinti: enélkül minden próba az előző
  indexre rakódott volna.
- **top-k = 4:** tipikus naiv beállítás; egyszerű ténykérdéshez bőven elég
  (némi redundanciával), több dokumentumból összerakandó válaszhoz viszont
  kevés — ez a baseline szándékos jellemzője.
- **Lekérdező út:** kérdés → embedding → hasonlósági keresés (top-4) → prompt a
  címkézett (`[S1]`…) chunkokból → `gpt-4o-mini` (temperature 0) → válasz.
  A modell csak a kontextusból válaszolhat, különben jelzi, hogy nem tud.
- **Forrásmegjelölés:** minden válasz mellé visszaadjuk a chunkok azonosítóját,
  fájlját, oldalát/munkalapját és a hasonlósági pontszámot.
- **TLS megjegyzés:** céges hálózaton a Python `certifi` CA-listája
  `CERTIFICATE_VERIFY_FAILED`-et adott; ezt a `truststore` csomaggal (OS
  tanúsítványtár) oldottam meg, az ellenőrzés kikapcsolása nélkül
  (`src/naive_rag/__init__.py`).
- **Ékezetes útvonal megjegyzés (Windows):** ha a projekt útvonala ékezetes
  karaktert tartalmaz (nálam `...\1_hét\...`), `uv run naive-rag ...`
  `ModuleNotFoundError: No module named 'naive_rag'`-ot dob. Oka: a CPython
  `site` modulja a `.pth` fájlok *tartalmát* mindig `encoding="locale"`-lel
  olvassa (ez a kódolás szándékosan figyelmen kívül hagyja a
  `PYTHONUTF8`/UTF-8-módot), így a Windows ANSI kódlapján az „é" rosszul
  dekódolódik, a kapott útvonal nem létezik, és a `src/` sosem kerül a
  `sys.path`-ra. A `run.py` ezt kerüli meg: `pathlib`/`__file__` alapján,
  kódlap-függetlenül teszi fel a `src/`-et — használd `uv run python run.py
  ...` formában, ha ezt a hibát kapod.

## 3. Kérdések és baseline

- A 13 kérdés a [`questions.md`](questions.md)-ben (3 simple, 5 multi-hop,
  5 global), típus szerint címkézve, indoklással, a szükséges dokumentumokkal
  és gold válasszal.
- A baseline válaszok: [`baseline/answers.md`](baseline/answers.md) (típus szerint
  csoportosítva) és [`baseline/answers.json`](baseline/answers.json) (gépi,
  a kinyert chunk-szövegekkel és a futtatási paraméterekkel). Utólag nem
  javítottam őket.
- **Két futás van, mindkettő megőrizve:** a `baseline/v1-plain-loaders-500-75/`
  az első változat (sima loaderek, 3576 chunk, tiszta index), a `baseline/`
  gyökerében lévő pedig a **v2** (pandoc/markdownify + szekciók, 3832 chunk,
  tiszta index). A v2 első futását kidobtam, mert az index duplikált pontokat
  tartalmazott (lásd Qdrant hibatanulság), ezért érvénytelen volt.
- Egyetlen utólagos módosítás a kérdéseken: a `questions.md` Q07 *gold* sorából
  kivettem egy korpuszban nem szereplő pontszámot. A kérdések szövege nem változott.

## 4. Szorgalmi feladatok

- **A) Többféle fájltípus — megvalósítva.** Formátumonként: PDF → `PyPDFLoader`
  (oldalszám-metaadat), DOCX → `pandoc` (Markdown, címsorokkal), HTML →
  `markdownify` (BeautifulSoup + Markdown), TXT → Markdown-címsorrá alakított
  `== Cím ==` sorok, XLSX → saját `openpyxl` loader, ami munkalaponként
  olvasható, `|` jelekkel tagolt szöveggé alakítja a sorokat.
  Miért így: a DOCX/HTML esetén a címsorok megőrzése volt a cél, mert abból lesz
  szekció-szintű forrásmegjelölés; a `pandoc`/`markdownify` páros a kurzus
  `rag_basics` példáját követi. A nehéz `unstructured`/`Docling` csomagot
  szándékosan kerültem. Korlátok: a táblázatos tudás szöveggé laposítása
  információt veszít; a `pandoc` külső függőség (nem pip-csomag); a DOCX/HTML
  szekciók szintje a konvertáló szkriptben egységesen `h2` lett, ezért a DOCX-nél
  a `section` csak egy szint, a HTML-nél `cím > szekció`, a TXT-nél viszont megmarad
  a teljes hierarchia.
- **D) FastAPI — megvalósítva.** `POST /api/chat` `{"question": "...", "k": 4,
  "stream": false}` → `{question, answer, sources[]}`. `stream: true`-nál
  NDJSON: az első sor a források, utána soronként egy token (ez a B) szorgalmi
  egy változata). Indítás: `uv run naive-rag serve`. A CLI párhuzamosan
  működik. Tesztelve (FastAPI `TestClient`): `/health`, `/api/chat` normál és
  streaming módban, üres kérdésre 422. Szándékosan nincs hitelesítés és rate
  limit (baseline).

## 5. Kiértékelés — melyik típuson bukott a baseline?

*(v2 futás: 2026-10-06, chunk 500/75, k=4, `gpt-4o-mini`, 3832 chunk, tiszta
index. A besorolás az én értékelésem a gold válaszok alapján, nem automatikus
metrika. Minden „helyes" minősítést a visszakapott chunkok szövegével vetettem
össze, nem csak a gold válasszal.)*

| Típus | Helyes és megalapozott | Helyes, de a kontextus nem támasztja alá | Hibás / részleges | Elutasítás |
|---|---|---|---|---|
| simple (3) | 3 | 0 | 0 | 0 |
| multi-hop (5) | 1* | 3 | 1 | 0 |
| global (5) | 1* | 0 | 2 | 2 |

\* Q06 és Q09 az XLSX összefoglaló lapnak (és a `reference-formula-one`
„Drivers" szekciójának) köszönhetően sikerült, nem a pilóta-dokumentumok
összekapcsolásából. Ez nem valódi multi-hop láncolás.

**„Helyes, de nem megalapozott" (Q04, Q07, Q08).** A végső válasz tényszerűen
helyes, de a visszakapott 4 chunk nem tartalmazza a szükséges állítást, a modell
a saját tudásából írta, miközben forrást hivatkozott:
- **Q04:** a kontextusban nincs „2016", és az sem, hogy Rosberg 2016-ban lett
  bajnok. A válasz (Rosberg bajnok, csapattárs Hamilton) a modell tudása.
- **Q07:** a kontextusban nem szerepel Räikkönen, sem Hamilton második és Alonso
  harmadik helye; a helyes végeredményt a modell tette hozzá.
- **Q08:** Bottas utódlása megalapozott, de a „Williamstől jött" nem: a
  „Williams" csak Rosberg saját pályafutásánál és Barrichello igazolásánál áll.

**Hibás / részleges.** *Q05:* a modell a Lotus 2012-es pilótaváltásáról szóló
chunkot félreolvasta, és Räikkönent nevezte „a 2012-es bajnoknak" (a szöveg
„2007 World Drivers' Champion Kimi Räikkönen"-t mond); a valódi 2012-es bajnokot
(Vettel) nem is találta meg, és a válasz végén mégis elutasított. *Q10:* 3 pilótát
sorolt fel 6-ból. *Q12:* magabiztos, de **kitalált csoportosítás**: a kontextusban
nincs évtizedes bontás, a modell az XLSX „összes cím" oszlopát osztotta
évtizedekbe (pl. Hamilton 7 cím a 2010-es években, pedig 2008-as és 2020-as
címe is van).

**A baseline a multi-hop és a global kérdéseken bukott el, a simple
kontrollcsoport mindkét futásban hibátlan volt (3/3, megalapozottan).** A hiba
jellege: (1) **a láncolás első lépése nem találja meg a megfelelő dokumentumot** —
a Q04 („a 2016-os bajnok csapattársa") és Q05 („a 2012-es bajnok") kérdésnél a
kérdés nem tartalmazza a *bajnok nevét*, az embedding pedig az évszámot gyengén
különbözteti meg, ezért a keresés a 2008/2020/2021-es szezon-dokumentumokat
hozta a 2016/2012-es helyett; a második ugrás így már el sem indulhatott;
(2) **hiányos aggregálás** — a Q10 csak 3 pilótát sorolt fel a 6-ból (Leclerc
nem is szerepelt a kontextusban, és Alonso sem került a listára), mert a top-4
chunk nem fedi le a korpusz többi részét; (3) **a globális/szintézis kérdések**
(Q11, Q13) elutasítást kaptak, mert a válasz nem egy chunkban van, a top-4
viszont lokális találatokat ad; (4) **nem megalapozott válasz** — a Q04, Q07 és
Q08 végső válasza helyes, de a hiányzó lépéseket a modell a saját tudásából
töltötte ki, miközben forrást hivatkozott; (5) **kitalált/téves válasz** — a Q12
a kontextus nélkül, az XLSX „összes cím" oszlopából gyártott évtizedes
csoportosítást, a Q05 pedig Räikkönent nevezte 2012-es bajnoknak. A GraphRAG
szempontjából ez a fő tanulság: a naiv RAG-nál a forrásmegjelölés **nem
garantálja**, hogy az állítás a hivatkozott szövegből következik, és a hiányzó
kontextust a modell csendben pótolja.

**v1 és v2 összevetése (ugyanazok a kérdések, 500/75, k=4).** A betöltők
cseréje (szekciók, fejléczaj kiszűrése; 3576 → 3832 chunk) után az elutasítások
száma 5-ről 2-re csökkent, de ez **nem jobb keresést jelent**: a három korábbi
elutasítás (Q04, Q05, Q12) helyén most egy nem megalapozott (Q04) és két hibás
válasz (Q05, Q12) áll; a Q07 részlegesből „helyes, de nem megalapozott"-ra
változott, a Q08 ugyanaz maradt. A kevesebb elutasítás tehát itt főleg több
magabiztos, de nem alátámasztott válaszot jelent. Az eredmény érzékeny a
chunk-összetételre; 13 kérdéses, egyszeri futásnál a különbségeket nem szabad
statisztikailag megbízhatónak tekinteni.

## 6. A gráfréteg (2. hét)

### Neo4j a projektben

A [`compose.yaml`](compose.yaml) egy Neo4j 5.26 Community konténert indít
(APOC-kal, Browser a 7474-en, Bolt a 7687-en, named volume-okkal). A
hitelesítő adatokat és a portokat **ugyanabból a `.env`-ből** olvassa, amit a
Python is (`NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_URI`, `NEO4J_*_PORT`), így a
konténer és a driver nem tud szétcsúszni egymástól. Indítás: `docker compose up
-d neo4j`, vagy `uv run naive-rag graph up`, ami meg is várja, amíg a
healthcheck zöld lesz (ezt a `graph init` utáni azonnali `MERGE`-ök megkívánják).

A kód a [`src/naive_rag/graph.py`](src/naive_rag/graph.py)-n keresztül éri el az
adatbázist, és **minden lekérdezés paraméterezett**: a `query()` és a
`write_batched()` csak Cypher + paraméterszótár párt fogad, érték soha nem
kerül f-stringgel a lekérdezésbe. Ez ugyanaz a felállás, mint a
`vectorstore.py`-nál: egy modul birtokolja a tárat.

### Séma-terv

A teljes séma-terv indoklásokkal: [`docs/graph-schema.md`](docs/graph-schema.md).
Röviden, a korpusz saját fogalmaival (nem `PERSON/ORG/GEO`):

- **Dokumentum-gráf (valódi adat, extrakció nélkül):** `Corpus`, `Document`,
  `Section`, `Chunk`, köztük `HAS_DOCUMENT`, `CONTAINS`, `HAS_SECTION`,
  `NEXT_CHUNK`.
- **Szakterületi gráf (kitalált seed):** `Driver`, `Team`, `Season`,
  `GrandPrix`, `Circuit`, `Car`, `PowerUnit`, `Title`, `RaceResult`, köztük
  `DROVE_FOR`, `TEAMMATE_OF`, `FIELDED`, `POWERED_BY`, `RACED_IN`, `ENTERED`,
  `ROUND_OF`, `HELD_AT`, `ACHIEVED`, `AT_RACE`, `FOR_TEAM`, `WON`, `AWARDED_IN`.

A három legfontosabb modellezési döntés:

1. **`RaceResult` külön csomópont (reifikált n-áris kapcsolat).** Egy helyezés
   a *pilóta × futam × csapat* hármas tulajdonsága, éllel nem leírható. Ettől
   lesz a Q8 aggregálás egyáltalán lehetséges.
2. **`Section` külön csomópont, pedig az 1. héten chunk-tulajdonság volt.**
   Sok chunk osztozik rajta. A 3. házifeladat az extrahált entitást nem a
   `Section`-höz, hanem a `Chunk`-hoz köti `MENTIONS` éllel. A `section` útvonal
   **a chunkon is megmarad**, mert a forrásmegjelölés (`rag.py`) egyetlen mezőt
   vár — tudatos redundancia.
3. **`DROVE_FOR` éltulajdonsággal, nem `Contract` csomóponttal.** Csak két
   dolgot köt össze, tehát elfér élen; de a `from_year` **része a kulcsnak**,
   mert egy pilóta visszatérhet egy csapathoz, és az új szerepvállalás, nem a
   régi felülírása.

Az él iránya ott hordoz jelentést, ahol a reláció aszimmetrikus:
`(:Chunk)-[:NEXT_CHUNK]->(:Chunk)` sorrend, `(:Driver)-[:DROVE_FOR]->(:Team)`
„versenyez neki". A szimmetrikus `TEAMMATE_OF` egy irányban van tárolva (kisebb
`driver_id` → nagyobb), és a lekérdezés **nyíl nélkül** járja be.

### Seed adat

[`graph/seed/f1-seed.json`](graph/seed/f1-seed.json) — 21 fogalmi csomópont
(4 pilóta, 3 csapat, 2 szezon, 3 nagydíj, 2 pálya, 3 autó, 2 erőforrás,
2 bajnoki cím) + 8 reifikált `RaceResult`, egyetlen összefüggő komponensben.
Minden név kitalált, és minden seed-csomópont **extra `:Seed` címkét** kap:
a 3. heti extrakció ugyanezekre a címkékre fog *valódi* entitásokat tenni, és a
kettőt meg kell tudni különböztetni (`graph clear seed`).

Az adat JSON-ban van, a sémára képezés a
[`src/naive_rag/graph_seed.py`](src/naive_rag/graph_seed.py)-ben — így a JSON
adatként marad átnézhető, a Cypher pedig paraméterezett. A `TEAMMATE_OF` és az
`ENTERED` él **levezetett** (a `DROVE_FOR` idősávok metszetéből, illetve a
`FIELDED`+`RACED_IN` párosból), és minden `graph seed` újraszámolja.

**Idempotencia:** minden címkének pontosan egy üzleti kulcsa van
(`graph_schema.py :: UNIQUE_KEYS`), és minden betöltő erre `MERGE`-öl, tehát a
duplikálást nem a szkript ellenőrzése, hanem az adatbázis-megszorítás zárja ki.
Ellenőrizve: a `graph seed` és a `graph load` kétszer lefuttatva **betűre
ugyanazokat a számokat** adja.

### Dokumentum-gráf

`graph load` ugyanazt a `ingest.load_and_chunk()`-ot hívja, mint a vektoros
indexelés, tehát **ugyanaz a splitter és ugyanazok a `chunk_id`-k** kerülnek a
gráfba, mint a Qdrantba (3832 chunk mindkettőben). Ez szándékos: egy
vektortalálat `chunk_id`-ja leképezési tábla nélkül megkereshető a gráfban, ami
a későbbi hibrid visszakeresés előfeltétele.

Betöltve: **1 `Corpus`, 23 `Document`, 691 `Section`, 3832 `Chunk`**, és
3809 `NEXT_CHUNK` él (= 3832 − 23, dokumentumonként egy lánc). A chunk
metaadata: `source` (URL vagy fájlnév), `page` (PDF), `section` (DOCX/HTML/TXT/
XLSX), `ordinal` (sorszám a dokumentumon belül), `start_index`, `n_chars`,
`n_words`.

A `Document.n_chars` a **forrásszövegen** mért hossz, nem a chunkok összege —
különben a 75 karakteres overlap duplán számolna (a Q2 `overlap_overhead_pct`
oszlopa épp ezt a különbséget mutatja).

**Elavult adat kezelése:** a `graph load` *mark-and-sweep* — minden csomópont
megkapja a futás `run_id`-ját, és a végén törlődik minden régi bélyegű
`Document`/`Section`/`Chunk`. Erre azért van szükség, mert más chunk-mérettel
újratöltve a `chunk_id`-k halmaza *megváltozik*, és a puszta `MERGE` a régieket
bent hagyná — pontosan az a hiba, ami az 1. héten a Qdranttal megtörtént.
Ellenőrizve: `graph load --chunk-size 1000 --chunk-overlap 150` után 2146 chunk
maradt és **1686 elavult csomópont törlődött** (3832 − 2146 = 1686).

### Cypher a saját adaton

8 lekérdezés, a kimenetükkel együtt:
[`graph/query-results.md`](graph/query-results.md) (generált), a statement-ek
[`graph/cypher/queries.cypher`](graph/cypher/queries.cypher)-ben (paraméterezve,
Neo4j Browserbe beilleszthető formában). Futtatás: `graph query`, egy darab:
`graph query --only Q4`.

| # | Mit kérdez | Mit adott |
|---|---|---|
| Q1 | formátumonkénti áttekintés + hely-metaadat lefedettség (**aggregáló**) | 3832 chunk; HTML/PDF/XLSX 100%, TXT 96,5%, DOCX 95,9% — ez a gráfból **visszaigazolja** az 1. heti 96–100%-os mérést |
| Q2 | hány chunk tartozik a leghosszabb dokumentumhoz | `driver-kimi-raikkonen` (88 573 karakter) → **282 chunk** |
| Q3 | a legrövidebb dokumentumok | az XLSX bajnoklista (1403 karakter, 5 chunk); két dokumentumban **1 karakteres** a legrövidebb chunk |
| Q4 | üres vagy szemét chunkok a betöltés után | **415 chunk (10,8%)**: 31 betű nélküli, 263 ötnél kevesebb szavas, 121 csak címsor |
| Q5 | ép-e a `NEXT_CHUNK` olvasási sorrend | 23/23 dokumentum ép (3809 él, mindegyik lánc egy fejnél kezdődik) |
| Q6 | seed, **2 hop**: kik voltak a csapattársak | `Driver -> Team <- Driver`, a közös évek metszetével; egyezik a levezetett `TEAMMATE_OF` éllel |
| Q7 | seed, **3 hop**: pilótától az erőforrásig | `Driver -> Team -> Car -> PowerUnit`, 7 út |
| Q8 | seed, **aggregáló**: konstruktőri tabella az eredményekből | Vertex Racing 83 pont — pontosan annyi, amennyi a `Title` csomóponton áll |

A legtanulságosabb a **Q4**: a chunkok 10,8%-a önmagában megválaszolhatatlan
(üres sor, táblázat-maradék, magányos címsor), és ezek a betöltés után
ugyanúgy benne vannak a vektorindexben, tehát **elfoglalnak egy top-k helyet**.
Ez az 1. heti kiértékelés „hiányos aggregálás" tünetének (Q10: 6-ból 3 pilóta)
egy mérhető, strukturális oka — a naiv futásból ez nem látszott, a gráfból egy
lekérdezéssel kijött.

### Hibatanulságok

- A Neo4j konténer némán újraindult körben, amíg a healthcheck el nem bukott.
  Ok: a compose környezeti változó `NEO4J_server_memory_pagecache__size` volt,
  ami a `server.memory.pagecache_size` **nem létező** beállításra képződik le.
  A szabály: `.` → `_`, a *valódi* `_` → `__`; helyesen
  `NEO4J_server_memory_pagecache_size` (viszont `heap_initial__size`, mert ott
  az alsóvonás valódi). A `docker compose logs neo4j` mondta ki.
- A `graph query --only Q6` eleinte felülírta a teljes riportot egyetlen
  lekérdezés kimenetével. Ma a `--only` csak a terminálra ír, a
  `graph/query-results.md`-t kizárólag a teljes futás írja újra.

## Mappaszerkezet

```
naive-rag-baseline/
├─ README.md · questions.md · pyproject.toml · uv.lock · .env.example · .gitignore
├─ compose.yaml     Neo4j 5.26 (2. hét) — ugyanabból a .env-ből konfigurálva
├─ run.py           belépési pont ékezetes útvonalú klónokhoz (lásd 2. pont)
├─ src/naive_rag/   a 3. házifeladat: extraction_* · extract_pilot · graph_merge
│                   quality_report · entity_index · local_search · compare_baseline
│                   valamint a korábbi ingest · rag · graph_* modulok
├─ scripts/         download_corpus.py · convert_formats.py
├─ corpus/          a manifest 23 dokumentuma, benne a driver-charles-leclerc.html
├─ docs/            extrakcio-es-lokalis-kereses.md · osszehasonlitas-section-1200-23.md; az osszehasonlitas.md történeti
│                   osszehasonlitas-run.json · a három korábbi futás · graph-schema.md
├─ graph/           pilot/ (10 chunk) · corpus/ (Q01–Q08 extrakció, riport, index)
│                   seed/ · cypher/ · query-results.md
└─ baseline/        answers.md · answers.json (v2, 3832 chunk) · v1-plain-loaders-500-75/
```

## Ismert korlátok

- A DOCX/HTML `section` metaadat egy–két szintű, a DOCX/HTML címsorszintek
  egységesek; a címsor előtti bevezető szakaszok chunkjai nem kapnak szekciót.
- Két futás, mindkettő 500/75 chunkkal; más chunk-méretek összehasonlítása még
  hátravan (`ingest --chunk-size ...`, majd `baseline --tag ...`).
- Az értékelés kézi, 13 kérdésen — irányt mutat, nem statisztikailag megbízható.
- A „helyes, de nem megalapozott" besorolás azon alapul, hogy a kulcs-állítás
  szövege (pl. évszám, név) nem szerepel a visszakapott chunkokban; ez szövegkeresés,
  nem teljes szemantikai ellenőrzés.
- A helyi Qdrant egyszerre egy folyamatot enged; a `serve` és az `ingest`
  ne fusson egyszerre (szerver módhoz állítsd be a `QDRANT_URL`-t).
- A kitalált `:Seed` réteg és az extrahált `:Extracted` réteg külön marad.
  `MENTIONS` csak a 880 sikeres rekord chunkjait köti az extrahált entitásokhoz.
- A `graph load` 3832 chunkot ír Neo4j-be, teljes szöveggel; a `graph query`
  ennek megfelelően pár másodperc. Nagyobb korpusznál a `Chunk.text`
  tárolását újra kellene gondolni.
- A `graph query` a riportot mindig felülírja; nincs `--tag`-elt verziózás,
  mint a `baseline`-nál.
- A gráf adatai Docker named volume-ban élnek (`docker compose down -v`
  törli). A repóból csak a *betöltés* reprodukálható, maga az adat nincs
  verziózva.

### A betöltő (`loaders.py`) a saját korpuszunkra van szabva

A betöltés megbízhatóan működik ezen a korpuszon, mert minden feltevése igaz
rá: **mi generáltuk a fájlokat**, ezért tudjuk, milyen fejlécek és jelölések
vannak bennük. **Idegen dokumentumokra ez nem általánosítható**: ott forrásonként
meg kell nézni (profilozni), mi a boilerplate és milyen a szerkezet, és ahhoz
kell tisztítást írni. A konkrét pontok:

*A korpusz saját konvencióira épül:*
- **TXT fejlécvágás (`_HEADER_SEP`, 70 db `=`):** a `download_corpus.py` által a
  fájlok elejére írt fejléc határolója. A kód nem ellenőrzi, hogy tényleg fejléc
  áll-e a vonal fölött, ezért egy idegen szövegben lévő 70 `=` jeles vonal
  **a fölötte lévő valódi tartalmat is eldobná**. A `70` három fájlban külön
  szerepel (`loaders.py`, `download_corpus.py`, `convert_formats.py`).
- **Fejléc-sorok kiszűrése (`_PROVENANCE`, első 25 sor):** a `doc_id:`, `url:`,
  `license:` stb. sorokat dobja el DOCX/HTML/PDF(1. oldal) elejéről. Egy idegen
  dokumentum, amely véletlenül `source:` vagy `url:` sorral kezdődik, ezeket
  elveszítené.
- **HTML `.source-metadata` szűrő:** a `convert_formats.py` saját HTML-sablonjának
  CSS-osztálya; idegen HTML-ben nincs ilyen.
- **`== Cím ==` → `## Cím` átalakítás:** a Wikipédia plaintext-kimenet
  címsor-jelölése. **Idegen szövegen hibázik:** egy „aláhúzott" cím
  (`Title` + `=====` sor) a kipróbálás szerint `### =` címsorrá alakul.
- **Manifest-függés (`metadata.json`):** csak a manifestben szereplő fájlokat tölti
  be; egy bemásolt új fájlt figyelmen kívül hagy. A metaadat-kulcsok (`file`,
  `format`, `doc_id`, `url`, …) a mi szkriptjeink konvenciói.
- **`MARKDOWN_FORMATS`:** azt feltételezi, hogy a txt/docx/html-ből Markdown
  címsorok lettek, ami csak az itteni átalakítás miatt igaz.

*Egy konkrét gépre szabott:*
- **`dependencies.find_pandoc`:** a `%LOCALAPPDATA%\Pandoc\pandoc.exe` tartalék
  útvonal csak Windowson él (winget-telepítés, még nem frissült PATH); más
  platformon a `PATH`-ra hagyatkozik.

*Általános, de naiv (idegen forrásnál romlik):*
- **XLSX:** a loader eldobja az üres cellákat (`if c is not None`), ezért ritka
  táblázatban az oszlop-igazítás elvész; az oszlopneveket sem rendeli az
  értékekhez. A mi XLSX-ünk teljesen kitöltött, ezért itt ez nem látszik.
- **HTML:** az egész `<body>`-t veszi, a navigációt és a láblécet nem szűri.
- **PDF:** a `PyPDFLoader` nem kezeli az oszlopokat, táblázatokat, élőfejet,
  élőlábat.
- **Ismeretlen kiterjesztés:** minden ismeretlen formátum szövegként töltődik be
  (`_load_txt` tartalék), bináris fájlnál (pl. `.pptx`) hibát vagy szemetet adna.

*Tisztább irány (nem valósítottam meg):* a fejlécet ne a fájlba írjuk, hanem a
provenance maradjon a `metadata.json`-ban, így a loadernek nem kell a szövegből
levágnia semmit. Ehhez újra kellene generálni a korpuszt, és újra kellene futtatni
az indexelést és a baseline-t.
