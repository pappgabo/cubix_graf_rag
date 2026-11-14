# Közösségi riportok, v3 (rekordazonosítós hivatkozás) -- a 37, 0. szintű közösség

run_id = `week4-leiden-elokeszitett-6f05327d7d88ebf0`. Neo4j-írás nem történt; a riportok csak helyi fájlokba kerültek. A globális keresés / router ebben a lépésben nem készült el.

## Fogalmi tisztázás: "tagság" vs. "átadott rekord"

Ez a dokumentum korábbi változatában a `3` közösségnél tévesen "89
csomópont"-ot írt, ami összemosta a két fogalmat. A kettő **nem ugyanaz**:

- **Teljes kanonikus tagság** (`plan.communities[path].size`): a közösség
  összes nem izolált kanonikus tagja, függetlenül attól, bekerült-e a
  modellbemenetbe. Ez a Phase 2 óta auditált szám (`docs/week4-reportbemenet-meres.json`
  "Csomópont" oszlopa), **nem változott**.
- **Átadott csomópontrekord**: a 24 000 tokenes bemeneti keret miatt a
  modellnek ténylegesen elküldött node-ok száma -- ez lehet kevesebb a
  teljes tagságnál (lásd az adott közösség "Kihagyott node" oszlopát a
  mérési táblában).

A `3` közösségnél: teljes kanonikus tagság **168**, a v1/v2 pilotban
átadott csomópontrekord **89**, a v3-ban átadott csomópontrekord **89**
-- a v3 tehát pontosan a korábban kiválasztott 89 rekordot adta át,
nem válogatott újra és nem bővítette a bemenetet. Ezt offline
összehasonlítással (rekordazonosítók és `record_id` mezők levétele
után a maradék mezők és a rendezett chunk-megfeleltetés egyezése)
ellenőriztem, modellhívás nélkül -- az eredmény: **egyezik**, a
prompt és a hivatkozási mező (rekordazonosító vs. chunkazonosító)
engedélyezett eltérésétől eltekintve.

## Eredmény a 37-ből

- Sikeres: **37**
- Hibás/érvénytelen: **0**
- API-hiba: **0**
- Le nem futott: **0**

Mind a 37 közösség sikeresen, elsőre érvényes riportot kapott -- egyetlen hívás sem igényelt újrapróbálkozást (nem is lett volna rá engedély).

## Modellhívások és költség

| Szakasz | Hívások | `prompt_tokens` | `completion_tokens` | Idő (s) | Mért költség |
|---|---:|---:|---:|---:|---:|
| v1 pilot (3 közösség, hosszú chunk-id hivatkozás) | 3 | 39637 | 810 | -- | $0.0064 |
| v2 pilot (1 közösség -- "largest", rekordazonosító) | 1 | 20574 | 190 | 6.547 | $0.0032 |
| v3, mind a 37 közösség (rekordazonosító, max_tokens=900) | 37 | 329108 | 7237 | 161.6 | $0.0537 |
| **Phase 3 összesen** | **41** | **389319** | **8237** | -- | **$0.0633** |

Az eredeti, karakter/4-becslésen alapuló költségbecslés a mind a 37 riportra (`docs/week4-reportbemenet-meres.json`, 600 tokenes kimeneti felső korláttal, csak a JSON-bemenetet számolva) $0.0641 volt. A tényleges, mért v3 költség (900 tokenes felső korláttal, a rendszerutasítást is beleszámítva, rekordazonosítós bemenettel) **$0.0537** -- alacsonyabb, elsősorban azért, mert a tényleges kimeneti tokenszám (átlag ~196 token/riport) jóval a 900-as felső korlát alatt maradt, és a rekordazonosítós bemenet rövidebb, mint a hosszú chunk-id-listák lettek volna.

## A három mintariport ellenőrzése (modellhívás nélkül, nem teljes körű)

Összeolvastam a v3 kulcsállításokat a hivatkozott rekordok tényleges szövegével (lásd `results/week4-report-v3-report-{8,205,3}.json`). Nyilvánvalóan nem odaillő hivatkozást nem találtam; egy helyen (`205` közösség, 2. állítás) két, tartalmilag majdnem azonos rekord (`E005` és `N007`, ugyanarról a Leclerc-eredményről) került együtt hivatkozásra -- redundáns, de nem téves.

- **`8` (legkisebb):** 1 állítás, a Honda Racing Corporation -> Acura ARX-06 kapcsolatról, pontosan a hivatkozott rekord szövegét követi.
- **`205` (medián):** 3 állítás, **több témát** fed le -- a Belga Nagydíj helyszíne és több győztese (Hamilton, Schumacher, Reutemann), Leclerc vegyes eredményei, Verstappen kiesése. Ez összhangban van a v3 "fedje le a fő, egymástól eltérő témákat" utasításával.
- **`3` (legnagyobb):** **168 a teljes kanonikus tagság**, de a 24 000 tokenes
  bemeneti keret miatt (lásd `docs/week4-reportbemenet-meres.md`, "Kihagyott
  node" oszlop) a modellnek átadott csomópontrekordok száma **89** (79
  tag kimaradt) -- ez a 89 pontosan megegyezik a v1/v2 pilotban átadottal,
  a v3 **nem válogatott újra és nem egészítette ki** a rekordazonosítók
  bevezetésével felszabaduló helyet. A riport a modellnek ténylegesen
  átadott 89 rekord alapján **továbbra is kizárólag Charles Leclerc-re
  szűkül** (2021, 2022, 2023, 2024-es szezonjai) -- a v3 explicit "fedd le
  a fő, eltérő témákat" utasítása ellenére sem fedett le más, az átadott
  89 rekordban jelen lévő entitást vagy témát. Ez dokumentált korlát, nem
  javítottam újabb modellhívással.

## Szintválasztás indoka

A 0. szint mindössze 37 riporttal lefedi mind az 1909 nem izolált kanonikus tagot (1 riport/jelentős közösség), szemben az 1. szint teljes reporting level-jével (191 közösség, 191 riport ugyanazt az 1909 tagot fedné le, lényegesen több hívással és költséggel, lásd a korábbi mérési jelentést).

## Korlátok

- A bemenet válogatott és rövidített (24 000 tokenes keret, 80/50 tokenes leírás-sapka) -- lásd `docs/week4-reportbemenet-meres.md`.
- A `3` közösség esete mutatja, hogy a válogatás/rövidítés és a modell saját preferenciája (a leggyakrabban előforduló entitás felé) tematikus információvesztéshez vezethet, a kifejezett utasítás ellenére is.
- A mintariport-ellenőrzés **nem teljes körű tartalmi audit** -- csak formai (rekordazonosító-érvényesség) és egy rövid, 3 közösségre korlátozott, kézi átolvasás történt.
- **A tagsági lefedettség (mind az 1909 tag szerepel valamelyik 37 közösségben) nem azonos a riportok tartalmi lefedettségével** (hogy a riport ténylegesen megemlíti-e az adott tag szerepét) -- ezt a `3` közösség esete konkrétan is igazolja: 89 tag van benne, de a riport ezek túlnyomó részét nem említi.

## Fájlok

- `diagnostics/2026-11-10-phase3-measurement/week4-report-v3-prompt-template.md` (v3 sablon, nem futtatva külön)
- `diagnostics/2026-11-10-phase3-measurement/generate_reports_v3.py` (futtató szkript)
- `.../results/week4-report-v3-input-<path>.json`, `week4-report-v3-record-chunk-map-<path>.json` (37 db)
- `.../results/week4-report-v3-raw-<path>.json`, `week4-report-v3-report-<path>.json` (37 db)
- `.../results/week4-report-v3-attempt-ledger.json` (folytathatósági nyilvántartás)
- `.../results/week4-report-v3-collection.jsonl` (mind a 37 sikeres riport, soronként egy JSON, globális kereséshez)
- `.../results/week4-report-v3-run-summary.json` (futási összesítő)
- `docs/week4-kozossegi-riportok-v3.md` (ez a dokumentum)

## Ami nem állapítható meg

A hivatkozások formai érvényessége (mindenhol teljesült) nem bizonyítja a riportok tartalmi helyességét -- ezt sem a kód, sem ez a dokumentum nem állítja. A globális keresési használhatóság (pl. router, kereszthivatkozás riportok között) ebben a lépésben nincs vizsgálva -- az nem volt engedélyezve.
