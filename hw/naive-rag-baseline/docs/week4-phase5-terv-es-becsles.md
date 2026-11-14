# Phase 5 / 1. lépés — útválasztó, naiv baseline terv, futásmátrix, költségbecslés

Modellhívás, embeddinghívás, Qdrant- és Neo4j-írás **nem történt** ebben a
lépésben (a 19 offline, hamis klienses teszten kívül). Csak olvasás + új
fájlok létrehozása; meglévő `src/` fájl nem módosult.

## 1. Meglévő keresési módok — csak olvasás

| Mód | Modul | Belépési függvény | Bemenet | Kimenet |
|---|---|---|---|---|
| naiv | `src/naive_rag/rag.py` | `NaiveRAG.ask(question: str, k: int\|None=None) -> dict` | **csak a kérdés szövege** (+opcionális `k`) | `{"question","answer","sources"}` |
| lokális | `src/naive_rag/local_search.py` | `local_search(question: str, graph, index, *, embed_query, answer_fn, k=3, min_score=0.25, chunk_texts=None, budget=None) -> LocalAnswer` | **csak a kérdés szövege** (a többi paraméter megosztott, nem kérdésspecifikus) | `LocalAnswer` (answer, refused, subgraph, prompt, ...) |
| globális | `src/naive_rag/global_search.py` | `run_phase4(questions, reports, call_fn, ...)` / egyenként `run_question(question, ...)` | `Question.text` (csak a kérdés szövege) | map/reduce eredmények, végső válasz |

**Mindhárom mód ma is kizárólag a kérdés szövegét kapja kérdésspecifikus
bemenetként.** Sehol nem találtam kérdésazonosítót, típuscímkét vagy gold
választ a modellnek ténylegesen átadott tartalomban:
- `NaiveRAG.ask` és a `PROMPT` sablon (`rag.py`) csak `{context, question}`-t formáz.
- `local_search()` és `answer_prompt(question, context)` (`local_search.py:671`) csak a kérdés szövegét és a kontextust teszi a promptba; a `question_id` csak utólag, a `search_record(question_id, found)` függvényben (`local_search.py:1012`) kerül a KIMENETI rekordba, a modellhívás **után**.
- `global_search.py`-t a Phase 4 auditban már igazoltam (0 szivárgás 185+10 rekonstruált bemeneten).

**Nincs szükség illesztő modulra a szivárgás ellen** — ez a három mód már
ma is tiszta. (Illesztésre csak az egységes futtatáshoz, a 2–4. pontokhoz
volt szükség — ezt az új `search_router.py`/`router_eval.py`/`call_logging.py`
modulok adják, meglévő fájl módosítása nélkül.)

**Lokális keresés beállításai:** modell: `get_chat_model()` (alapértelmezett
`gpt-4o-mini`, nincs explicit `max_tokens` a `local_search.main()`
`--memory`/Neo4j ágán — **a kimenet felső korlátja a meglévő kódban
nincs beállítva**, ez a meglévő kód tulajdonsága, nem ebben a lépésben
bevezetett hiányosság); `context_model_window=8192`,
`context_answer_reserve=1024`, `context_graph_share=0.5` (`config.py`);
`k=3` entitás-horgony, `min_score=0.25`. A tokenbecslés módja
`"ceil_chars_div_3"` (`local_search.py`), **ez eltér** a Phase 3/4-ben
használt karakter/4 becsléstől — ezt jelzem, nem egységesítem.

**Naiv keresés beállításai:** `top_k=4` (`config.py`), `chunk_size=1200`,
`chunk_overlap=100`; a kimenetre (`NaiveRAG.ask`) **szintén nincs explicit
`max_tokens`** a meglévő kódban.

## 2. Útválasztó — elkészült, offline tesztelve

Új modulok: `src/naive_rag/search_router.py` (zero-shot LLM-útválasztó),
`src/naive_rag/router_eval.py` (feladattípus-megfeleltetés, **csak az
értékelő oldalon**), `src/naive_rag/call_logging.py` (kötelező naplózás,
lásd 5. pont). Egyik sem módosít meglévő fájlt.

- Egyetlen kérdésspecifikus bemenet: a kérdés szövege (`router_messages`).
- `gpt-4o-mini`, `temperature=0`, `response_format={"type":"json_object"}`,
  `max_retries=0`, `max_tokens=200`.
- A rendszerutasítás a három mód **általános** jellemzését adja (mire jók,
  mik a korlátaik) — nincs benne Q01–Q13-ból vett few-shot példa, nincs a
  kérdéskészletre szabott kulcsszólista. Ezt automatizált teszt is
  ellenőrzi (`test_search_router.py::test_system_prompt_has_no_few_shot_examples_or_tailored_keywords`
  — egyik valódi kérdésszöveg sem szerepel szó szerint a promptban).
- A feladattípus-megfeleltetés (`router_eval.TASK_TYPE_TO_MODE`:
  `simple→naiv`, `multi-hop→lokalis`, `global→globalis`) **csak az
  értékelő kódban** van — a router sosem látja. A hibás döntések listáját
  (`router_eval.mismatches`) is az értékelő kód állítja elő.
- **Az útválasztó eredménye nem független teszt**: a promptot a Q01–Q13
  kérdések ismeretében, ennek a konkrét feladatnak a kontextusában
  fejlesztettem.

**Az LLM-útválasztó választásának indoklása:** 13 kérdés mellett egy
kézzel írt szabályalapú útválasztó fejlesztési ráfordítása (szabályok,
élesetek, karbantartás) nem térülne meg; egy zero-shot LLM-hívás
kérdésenként ~$0,0001–0,0002 becsült költséggel (lásd 4. pont) elenyésző.
**Kockázatként, nem bizonyosságként** jelzem: egy kézi szabály
*szükségszerűen* a tesztkérdésekre szabott lenne — ezt nem állítom, csak
a kis mintaszám miatti általánosítási kockázatot jelzem mindkét
megközelítésnél.

**Offline tesztek:** `tests/test_call_logging.py` (7), `tests/test_search_router.py`
(12) — mind lefutott, valódi hívás nélkül (lásd a teljes tesztfuttatást
a jelentés végén).

## 3. Új naiv baseline — terv, nincs indexelés

| | |
|---|---|
| Forrás | `graph/corpus/chunks-section-1200-23/chunks.jsonl` (**1651 chunk**, eredeti `chunk_id`-k, nincs újrachunkolás) |
| Tervezett Qdrant-gyűjtemény | `week4_naive_baseline_1200_23` (új név; `f1_naive_rag` érintetlen) |
| Embeddingmodell | `text-embedding-3-small` (`config.py` alapértelmezés) — ugyanaz indexeléskor és lekérdezéskor |
| Dimenzió | **1536** (a modell natív dimenziója; a kódban sehol nincs `dimensions` paraméter beállítva, tehát nem csökkentett) |
| top_k | **4** |

**Embedding API-hívásszám becslése:** a `langchain_openai.OpenAIEmbeddings`
telepített verziójának saját `chunk_size` alapértelmezése **1000**
(ellenőrizve: `OpenAIEmbeddings.model_fields['chunk_size'].default == 1000`)
→ 1651 chunk esetén **⌈1651/1000⌉ = 2** indexelő API-hívás, plusz
**13** lekérdezés-embedding hívás (Q01–Q13, egyenként) = **15 hívás
összesen** a teljes 13 kérdéses futtatáshoz.

**Embedelendő szöveg és becsült tokenszám:** 1651 chunk, összesen
1 247 246 karakter → **≈311 812 token (karakter/4 BECSLÉS, nincs helyi
tokenizer)**.

**Lekérdezésszám:** 13 (egy `similarity_search_with_score` hívás
kérdésenként, `k=4`).

Az indexelés és az embeddinghívások **csak külön jóváhagyás után**
futhatnak — ez a szakasz kizárólag terv.

## 4a. Pontosítás — Phase 5/2. lépés (utólagos, csak átrendezés)

**Git-előzmény és teljes kérésnapló hiánya:** a repóban Phase 5/2.
lépésig **nem volt egyetlen git-commit sem**
(`git log` → *"your current branch 'master' does not have any
commits yet"*), és a Phase 4 (globális Q09–13) futás **teljes,
ténylegesen elküldött kérését sosem naplóztuk** — csak a válaszokat. Ebből
következően **a globális Q09–13 fenti újrahasználhatósági igazolása
(riportkészlet/prompt/modell/küszöb/reduce-ág egyezése) kizárólag a
jelenlegi fájlállapot és a saját művelet-naplóm alapján áll**, nem
verzió-diff vagy kérés-szintű visszaellenőrzés alapján — ez korlátozza az
utólagos ellenőrizhetőséget. **Ezeket az eredményeket nem generáltuk
újra.**

## 4. Futásmátrix és költségbecslés

### Mátrix (mi futott, mi hasznosítható, mi hiányzik)

| Mód | Q01–08 (simple+multi-hop) | Q09–13 (global) |
|---|---|---|
| **naiv** | nem futott (régi baseline más korpuszon/chunkoláson — csak történeti referencia, **nem** hasznosítható kontrollált összevetéshez) | nem futott |
| **lokális** | nem futott (a `diagnostics/2026-11-05-local-search/` csak szelekciós hatásvizsgálat, nem teljes Q01–13 válaszfuttatás) | nem futott |
| **globális** | nem futott | **lefutott (Phase 4)**, feltételesen hasznosítható — lásd alább |

**A globális Q09–13 eredmény hasznosíthatósági feltétele** — mind
teljesül, fájlhivatkozással:
- riportkészlet: `diagnostics/2026-11-10-phase3-measurement/results/week4-report-v3-collection.jsonl` (változatlan, nem generáljuk újra);
- prompt: `src/naive_rag/global_search.py` `MAP_SYSTEM_PROMPT`/`REDUCE_SYSTEM_PROMPT` (változatlan);
- modell: `gpt-4o-mini` (`global_search.MODEL`, egyezik a Phase 4 futással: `docs/week4-globalis-kereses-phase4.md`);
- küszöb: `usefulness_score>0` az A ágon (`select_basis(..., include_zero=False)`), változatlan;
- reduce-ág: **A-t (csak pozitív pontszámú) választom elsődlegesnek** az összevetéshez. Indoklás: A a "alapváltozat", kevesebb, de magasabb relevanciájú bizonyítékot admit; B kifejezetten kontrollváltozatnak készült (nulla pontszámúak beengedése), nem elsődleges összevetésre. **Ezt előre rögzítem, nem kérdésenként választom utólag.**

**Korábbi naplózási hiány jelzése:** a Phase 4 futás **ténylegesen
elküldött** üzeneteit nem mentettük el (csak a válaszokat) — ezt a
2025-11-10-i audit már dokumentálta (`docs/week4-globalis-kereses-phase4.md`
nem tartalmazza, az auditválasz igen). **Ezt a hiányt nem tekintem
utólag teljesítettnek** — a mostani `call_logging.py` csak az ÚJ, Phase
5-ös hívásokra vonatkozik, a Phase 4 régi hívásait nem naplózza
visszamenőleg.

**Globális Q01–08 becslés** (a Phase 4 tényleges átlagaiból extrapolálva,
dokumentált feltételezés: a map/report-szerkezet és a kérdésenkénti
viselkedés hasonló lesz):
- map hívás: 8×37 = **296** (felső korlát, kérdésenként legfeljebb 1/riport)
- reduce hívás: legfeljebb 8×2 = **16** (tényleges kevesebb lehet, ha A=B valamelyik kérdésnél)
- becsült input: 296×523,0 (map-átlag) + 16×956,3 (reduce-átlag, felső becslés) ≈ **154 819 + 15 301 = 170 120 token**
- becsült output: 296×30,1 + 16×78,3 ≈ **8898 + 1253 = 10 151 token**
- **becsült költség (felső korlát): ≈ $0,0316**

### Lokális mód becslés (Q01–13, mind a 13) — csak generatív hívás

- hívásszám: **legfeljebb 13** válasz-hívás (az `embed_query` hívások a
  külön Embedding tételben szerepelnek, hogy ne számoljunk egy hívást
  kétszer — ha minden kérdésnél van horgony; refúzió esetén kevesebb)
- input/kérdés: **felső korlát ≈7168 token** (`context_model_window − context_answer_reserve`, a kód saját char/3 becslésével) — **a tényleges valószínűleg ennél lényegesen kisebb, de futtatás nélkül nem pontosítható**, ezért csak a konfigurált felső korlátot adom meg, kitalált "tipikus" értéket nem.
- output/kérdés: **ismeretlen, nincs explicit `max_tokens` a meglévő kódban** (ld. 1. pont) — nem becsülhető megbízhatóan, nem helyettesítem.

### Naiv mód becslés (Q01–13, az új week4 gyűjteményen) — csak generatív hívás

- hívásszám: **13** LLM-válasz (az indexelő és lekérdezés-embedding
  hívások a külön Embedding tételben vannak, hogy ne számoljunk egy
  hívást kétszer)
- input/kérdés becslés: `top_k=4` × `chunk_size=1200` karakter ≈ 4800 karakter kontextus ≈ **≈1200 token (karakter/4)** + kérdés + rendszersablon ≈ **≈1350 token/kérdés** (ez a konfigurált `top_k`/`chunk_size`-ból levezetett, nem mért becslés)
- output/kérdés: **ismeretlen, nincs explicit `max_tokens`** a `rag.py`-ban sem — nem becsülhető megbízhatóan.

### Embedding (külön tétel, naiv indexelés + naiv és lokális lekérdezés-embedding együtt)

- hívásszám: **2** indexelő (1651 chunk, ⌈1651/1000⌉) + **13** naiv lekérdezés-embedding + **13** lokális lekérdezés-embedding = **28**
- tokenszám: ≈311 812 (korpusz, karakter/4 becslés) + elhanyagolható (13 rövid kérdés × 2 mód) ≈ **≈312 000 token becslés**
- **Ár: nincs a feladatban megadva embeddingre.** Nyilvánosan ismert (ebben a lépésben **nem ellenőrzött** hivatalos forrásból) `text-embedding-3-small` ár ≈ $0,02 / 1M token — ha ez helytálló, ≈ **$0,0062**, de ezt **ellenőrizendőnek** jelölöm, nem tényleges árnak.

### Útválasztó (Q01–13, 13 hívás)

- input: rendszerutasítás (349 token becslés) + kérdés (átlag ~25 token becslés) ≈ **4863 token összesen (13 hívásra)**
- output: `max_tokens=200` felső korlát; a JSON válasz valószínűleg ennél jóval rövidebb, **tényleges nélkül nem mérhető** — nem becsülöm tovább kitalált számmal.

### Összesítő tábla (gpt-4o-mini: 0,15 input / 0,60 output USD per 1M token)

| Mód | Hívás | Inputtoken | Outputtoken | Költség |
|---|---:|---:|---:|---:|
| **Már elköltött** | | | | |
| Globális Q09–13 (Phase 4, tényleges) | 195 | 106 325 | 6 344 | $0,0198 |
| **Még várható (becslés)** | | | | |
| Globális Q01–08 | ≤312 | ~170 120 | ~10 151 | ~$0,0316 |
| Router Q01–13 | 13 | ~4 863 | ismeretlen | ismeretlen (≤200 tok/hívás felső korlát) |
| Lokális Q01–13 (csak generatív) | ≤13 | ≤~93 184 (13×7168 felső korlát) | ismeretlen | ismeretlen |
| Naiv Q01–13 (csak generatív) | 13 | ~17 550 | ismeretlen | ismeretlen |
| Embedding (index + naiv és lokális lekérdezés) | 28 | ~312 000 | — | ~$0,0062 (**ellenőrizendő ár**) |

A hívásszám-oszlopban **a generatív (LLM) és az embedding hívások
külön sorban** szerepelnek, hogy összegzéskor egy hívás ne számítódjon
kétszer (a korábbi változat tévesen beleszámította az embedding
hívásokat a naiv/lokális sor hívásszámába is). A hiányzó (output, ill.
embedding-ár) tételeket **szándékosan nem helyettesítettem** kitalált
számmal.

## 5. Naplózás — elkészült, kötelező minden jövőbeli hívásra

`src/naive_rag/call_logging.py`: minden jövőbeli generatív hívás
(útválasztó, naiv, lokális, globális map/reduce) ezen keresztül menjen.
Rögzíti: a **ténylegesen elküldött** `messages` listát szó szerint, annak
SHA-256 hash-ét (`sha256`, UTF-8 kódolás, dokumentálva), a modellazonosítót
és hívásparamétereket, a nyers választ, `usage`-ot, `finish_reason`-t,
futási időt, hiba esetén a hibát. `question_id`/címke/gold **soha** nem
kerül az üzenetlistába — külön `local_metadata` mezőben van.

**Hamis klienses teszttel igazolva**
(`test_call_logging.py::test_logged_messages_equal_exactly_what_the_client_received`):
a naplózott `messages` **pontosan** az, amit a hamis kliens ténylegesen
megkapott — nem utólagos rekonstrukció.

**Frissítés (Phase 5/2. lépés):** a bekötés elkészült mind az öt
útvonalra, lásd `docs/week4-phase5-2-naplozas-bekotes.md` a pontos
állapotért (modul kontra tényleges bekötés) és a hamis klienses
tesztekért (17 új teszt).

## 6. Értékelési lap — előkészítve

`src/naive_rag/evaluation_sheet.py` + a generált sablon:
`docs/week4-ertekelesi-lap-sablon.json` (**39 sor** = 13 kérdés × 3 mód).
Minden sor `status: "előzetes"`, minden értékelési mező `null` — **nincs
előre kitöltött javaslat**. Mezők: `answer`, `context_size_tokens` (+
`context_size_is_estimate` jelző), `call_count`, `cost_usd`,
`correctness` (helyes/hiányos/téves/elutasított), `support`
(forrásrészletben/csak gráfban/egyikben sem/nem eldönthető),
`error_category` (keresési/generálási/nem eldönthető), `justification`,
`evidence_reference`. `summarize_by_type()` kérdéstípusonkénti
összesítést ad, de üres sablonon csupa nullát — ez sem végeredmény.

## 7. Dokumentálandó korlátok

- Ugyanazon a 13 kérdésen történt a fejlesztés (router, prompt-tervezés)
  és fog történni a mérés — **az eredmény nem általános bizonyíték**.
- **Az útválasztó eredménye nem független teszt** (2. pont).
- **A régi baseline** (`baseline/answers.json`, 500/75 chunkolás, másik
  korpuszváltozat) **csak történeti referencia**, nem kontrollált
  összevetés alapja.
- **Igazolt Phase 3-as információvesztés** Q09-nél (Schumacher
  7-címes rekordja megvolt a bemenetben, kimaradt a generált riportból)
  és Q10-nél (Alonso, Hamilton Ferrari-kötődése megvolt a bemenetben,
  kimaradt a riportból) — lásd a 2025-11-10-i audit-választ.
- **Q11-nél** a szükséges összesítő tény egyik riportban és — ellenőrzött
  minta alapján — a Phase 3 bemenetben sem volt elérhető; **a korábbi
  (Phase 1/2 extrakciós) kiesési pont nem tisztázott**.
- **Az izolált csúcsok (736) egyik riportba sem kerültek** — ez a
  globális keresés lefedettségi korlátja (a Phase 2/3 auditban rögzítve:
  `docs/week4-reportbemenet-meres.md`).
- **Modellazonosító:** `gpt-4o-mini` mindenhol rögzítve a kódban
  (`search_router.MODEL`, `global_search.MODEL`). A `gpt-4o-mini`
  esetleges deprecated státuszát **ebben a lépésben nem tudtam
  hivatalos forrásból ellenőrizni** — ezt **ellenőrizendőnek** jelölöm,
  modellt nem cseréltem.

## Létrehozott fájlok

- `src/naive_rag/call_logging.py`, `search_router.py`, `router_eval.py`, `evaluation_sheet.py`
- `tests/test_call_logging.py`, `test_search_router.py`, `test_evaluation_sheet.py`
- `docs/week4-ertekelesi-lap-sablon.json`
- `docs/week4-phase5-terv-es-becsles.md` (ez a dokumentum)

Egyetlen meglévő `src/` fájl sem módosult; `docs/osszehasonlitas*` és
`baseline/answers.json` érintetlen; `f1_naive_rag` gyűjtemény érintetlen.
