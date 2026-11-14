# Globális keresés (Phase 4) -- map-reduce a 37 közösségi riportból

run_id = `week4-leiden-elokeszitett-6f05327d7d88ebf0`. Neo4j-írás nem történt, új közösségi riport nem készült, router/háromoldalú összehasonlítás nem készült. Az implementáció a `src/naive_rag/global_search.py` modulban van (paraméterezett riport- és kérdésfájl-útvonalakkal, nem függ pilot-scriptektől).

## Kérdésenkénti összevetés

### Q09

**Eredeti kérdés:** Across all the drivers covered in this corpus, who has won the most World Drivers' Championships, and how many?

**Map-eredmények:** 9 pozitív pontszámú, 28 nulla pontszámú (37-ből).

**Alapválasz (A, csak pozitív pontszámúak, hivatkozott közösségek: ['111']):**
> The partial answers indicate that Lewis Hamilton has won seven World Drivers' Championships, while Michael Schumacher's total is not specified. Therefore, based on the available information, Lewis Hamilton has the most championships with seven titles.

**Nulla pontszámúakat is beengedő válasz (B, hivatkozott közösségek: ['111']):**
> Lewis Hamilton has won the most World Drivers' Championships with a total of seven titles.

**Mi változott:** Nincs érdemi tartalmi eltérés -- mindkettő Lewis Hamiltont nevezi meg 7 címmel; B tömörebb megfogalmazású. Megjegyzés: egyik válasz sem említi, hogy a gold szerint Schumacher is 7 címmel holtversenyben áll -- ez hiányzó, nem téves információ.

### Q10

**Eredeti kérdés:** Which drivers in this corpus have driven for Scuderia Ferrari at some point in their career?

**Map-eredmények:** 6 pozitív pontszámú, 31 nulla pontszámú (37-ből).

**Alapválasz (A, csak pozitív pontszámúak, hivatkozott közösségek: ['4']):**
> The drivers who have driven for Scuderia Ferrari include Michael Schumacher, Kimi Räikkönen, and Charles Leclerc.

**Nulla pontszámúakat is beengedő válasz (B, hivatkozott közösségek: ['4']):**
> The drivers who have driven for Scuderia Ferrari include Michael Schumacher, Kimi Räikkönen, and Charles Leclerc.

**Mi változott:** A két válasz szövege szó szerint megegyezik (Schumacher, Räikkönen, Leclerc). A gold 6 pilótát sorol fel (+ Alonso, Vettel, Hamilton) -- a riportkészlet ezekre nem talált/nem pontszámozott elég közvetlen bizonyítékot.

### Q11

**Eredeti kérdés:** Which constructor has won the most Drivers' Championships according to the documents, and how many titles is that?

**Map-eredmények:** 6 pozitív pontszámú, 31 nulla pontszámú (37-ből).

**Alapválasz (A, csak pozitív pontszámúak, hivatkozott közösségek: -):**
> The documents do not provide sufficient information to determine which constructor has won the most Drivers' Championships or the exact number of titles.

**Nulla pontszámúakat is beengedő válasz (B, hivatkozott közösségek: -):**
> The partial answers do not provide sufficient information to determine which constructor has won the most Drivers' Championships or the number of titles.

**Mi változott:** Mindkét válasz elutasít, elégtelen bizonyítékra hivatkozva, gyakorlatilag azonos szöveggel. Egyik sem szintetizálta a konstruktőri összesítést, noha a gold szerint ez (Ferrari, 15 cím) a riportokból elvben levezethető lenne.

### Q12

**Eredeti kérdés:** Group the World Champions among the corpus drivers by decade (2000s, 2010s, 2020s).

**Map-eredmények:** 8 pozitív pontszámú, 29 nulla pontszámú (37-ből).

**Alapválasz (A, csak pozitív pontszámúak, hivatkozott közösségek: ['4', '15', '24', '33', '37', '60', '111']):**
> The World Champions among the corpus drivers by decade are as follows: 
- 2000s: Michael Schumacher (1996-2006), Kimi Räikkönen (2007), Sebastian Vettel (2009-2014), Jenson Button (2009), Fernando Alonso (2005). 
- 2010s: Sebastian Vettel (2009-2014), Nico Rosberg (2016), Lewis Hamilton (specific years not mentioned). 
- 2020s: Max Verstappen (active since 2016), Lewis Hamilton (2020).

**Nulla pontszámúakat is beengedő válasz (B, hivatkozott közösségek: ['4', '15', '24', '33', '37', '60', '111']):**
> The World Champions among the corpus drivers by decade are as follows: 

2000s: Michael Schumacher (1996-2006), Kimi Räikkönen (2007), Sebastian Vettel (2009-2014), Jenson Button (2009), Fernando Alonso (2005).
2010s: Sebastian Vettel (2009-2014), Nico Rosberg (2016), Lewis Hamilton (specific years not mentioned).
2020s: Lewis Hamilton (2020), Max Verstappen (active since 2016).

However, specific championship years for some drivers are not provided, leading to some ambiguity.

**Mi változott:** Tartalmilag hasonlóak; B egy explicit bizonytalansági megjegyzést told hozzá ("specific championship years ... not provided"). Mindkettő pontatlanságot tartalmaz a gold-hoz képest (pl. Schumacher éveinek rossz tartománya).

### Q13

**Eredeti kérdés:** What common factors explain why specific teams such as Ferrari, Mercedes and Red Bull dominated particular eras of Formula One?

**Map-eredmények:** 3 pozitív pontszámú, 34 nulla pontszámú (37-ből).

**Alapválasz (A, csak pozitív pontszámúak, hivatkozott közösségek: ['4', '15', '263']):**
> The partial answers highlight the historical significance of Ferrari and its notable drivers, as well as the key role of drivers like Max Verstappen and Sebastian Vettel in Red Bull's success. However, there is insufficient evidence to comprehensively explain the common factors for the dominance of Mercedes alongside Ferrari and Red Bull.

**Nulla pontszámúakat is beengedő válasz (B, hivatkozott közösségek: ['4', '15']):**
> The partial answers indicate that Ferrari's historical significance and notable drivers, such as Michael Schumacher and Kimi Räikkönen, contributed to its dominance in certain eras. For Red Bull, key drivers like Max Verstappen and Sebastian Vettel played significant roles in their success. However, there is insufficient evidence to comprehensively explain the common factors for all three teams (Ferrari, Mercedes, and Red Bull) as only Ferrari and Red Bull are mentioned, and there is no information provided about Mercedes.

**Mi változott:** Apró eltérés: A 3, B csak 2 közösségre hivatkozik (263 kimarad B-ből), miközben B szövege ennek ellenére megnevez Schumachert és Räikkönent is -- ez hivatkozás és tartalom közti kisebb következetlenség, amit észlelésként dokumentálok, nem javítok.

## Mérés, összesítve

- Tényleges hívásszám: 185 map + 10 reduce = **195** (engedélyezett felső korlát: 195 = 5x37 + 5x2).
- `usage.prompt_tokens` összesen: **106325**
- `usage.completion_tokens` összesen: **6344**
- Mért futási idő összesen: **217.3 s**
- Mért költség (0,15/0,60 USD per 1M token): **$0.0198**

10 db reduce-hívás (2 × 5 kérdés) mindegyike valódi modellhívás volt -- egyetlen kérdésnél sem egyezett a nulla pontszámúakat is beengedő (B) bemenet a csak-pozitív (A) bemenettel, ezért a B-ág sosem hivatkozott A mentett eredményére. Teljes elutasítás modellhívás nélkül sem fordult elő -- minden kérdéshez volt legalább egy pozitív pontszámú részválasz.

## Hibák / blokkolók

Egyik lépés sem hibázott, nem csonkolt (`finish_reason=length` sehol), nem hivatkozott ismeretlen azonosítóra. A futás a mind az 5 kérdésre lefutott, megállás nélkül.

## Korlátok

- Ez **nem teljes körű tartalmi audit** -- a fenti "mi változott" megjegyzések mentett válaszok puszta átolvasásán alapulnak, külön értékelő modellhívás nélkül.
- A formai hivatkozás-ellenőrzés (érvényes `evidence_ids`/`cited_statement_ids`/`cited_partial_answer_ids`) **nem bizonyítja** egyik válasz tartalmi helyességét sem.
- A **tagsági lefedettség** (a Phase 2/3 auditált 1909 nem izolált kanonikus tag) **nem azonos** a globális keresés tényleges válasz-lefedettségével: több kérdésnél (Q10, Q11) a gold válaszhoz képest hiányos a végeredmény, annak ellenére, hogy az adott tények valahol a 37 riport valamelyikében elvileg jelen lehetnek -- a riportok szelektív/rövidített bemenete és a map-pontszámozás szűrhetett ki releváns, de a modell által alacsonyra pontozott információt.
- Nem állítok globális keresési fölényt pusztán attól, hogy mindkét ág választ adott.

## Fájlok

- `src/naive_rag/global_search.py` (az implementáció), `tests/test_global_search.py` (25 offline teszt)
- `diagnostics/2026-11-10-phase4-global-search/results/map-result-<Qxx>-<path>.json`, `map-raw-...json` (185+185 db)
- `diagnostics/2026-11-10-phase4-global-search/results/reduce-result-<Qxx>-{A,B}.json`, `reduce-raw-...json`
- `diagnostics/2026-11-10-phase4-global-search/results/ledger.json` (folytathatósági nyilvántartás, 195 bejegyzés)
- `diagnostics/2026-11-10-phase4-global-search/results/phase4-aggregate.json` (ez az összegzés nyers adata)
- `docs/week4-globalis-kereses-phase4.md` (ez a dokumentum)

**Futtatási parancs:**
```
PYTHONPATH=src uv run python -m naive_rag.global_search \
  --collection diagnostics/2026-11-10-phase3-measurement/results/week4-report-v3-collection.jsonl \
  --questions questions.md \
  --out-dir diagnostics/2026-11-10-phase4-global-search/results \
  --ledger diagnostics/2026-11-10-phase4-global-search/results/ledger.json
```
