# Lokális keresés – offline diagnosztika (2026-11-05)

Független, mellékhatásmentes vizsgálat a 3. heti lokális keresés mentett
futásáról (`docs/osszehasonlitas-run.json`). A szkriptek nem módosítják a
projekt kódját, adatait vagy indexét, és nem indítanak modell-, embedding-,
Neo4j- vagy Qdrant-hívást. A `.env` fájlt nem nyitják meg
(`Settings(_env_file=None)`); a 500/75-ös alapértelmezett chunkolásról a
`01_identity.py` igazolja, hogy azonos az extrakciókorival.

Írás csak ebbe a könyvtárba történik:

- `cache/` – a korpusz chunkszövegei (`chunks.json`). Gitignore-olt, nem
  commitolandó; a korpusz, a pandoc-verzió vagy a betöltő változásakor
  automatikusan újraépül.
- `results/` – a mérési eredmények JSON-ban és a bemeneti manifest.

## Futtatás

A projekt gyökeréből, a projekt saját interpreterével:

```powershell
cd diagnostics\2026-11-05-local-search
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"
..\..\.venv\Scripts\python.exe 01_identity.py
..\..\.venv\Scripts\python.exe 02_evidence_audit.py
..\..\.venv\Scripts\python.exe 03_selection_impact.py
..\..\.venv\Scripts\python.exe 04_salvage_impact.py
```

Az első futás a korpusz betöltése miatt kb. 1 perc (pandoc kell a docx
fájlokhoz); utána a cache-ből olvas.

## Bemenetek

A pontos hash-ek a `results/inputs-manifest.json` fájlban vannak; ezt az
`01_identity.py` minden futáskor újraírja, így eltérés esetén látszik, hogy
más bemenettel készült a mérés. A 2026-11-05-i futás bemenetei:

| Bemenet | Azonosító |
|---|---|
| `corpus/` (22 dokumentum + `metadata.json`) | fa-hash `8d0e629d…` |
| `graph/corpus/extraction/*.json` (1565 rekord) | fa-hash `841f82d0…` |
| `graph/corpus/entity-index.json` | `8148bb07…` |
| `docs/osszehasonlitas-run.json` (13 kérdés) | `0669921a…` |
| `questions.md` | `a02bd8a7…` |
| `src/naive_rag/*.py` (11 érintett modul) | a manifestben fájlonként |
| Python 3.11.15, pandoc 3.12, langchain-text-splitters 1.1.3, pypdf 6.19.0 | |

A git-tárolóban nincs commit, ezért a kód állapota csak hash-sel
rögzíthető.

## Szkriptek

| Fájl | Mit mér |
|---|---|
| `common.py` | közös betöltés, `.env` nélküli beállítás, cache, manifest |
| `evidence.py` | a goldból írt, mondatszintű bizonyítékcímkék (csak értékeléshez) |
| `01_identity.py` | `input_hash`-egyezés, index–gráf egyezés, a 13 prompt bájtazonos újrajátszása |
| `02_evidence_audit.py` | minden elfogadott bizonyítékchunk a találó mondattal, kézi ellenőrzéshez |
| `03_selection_impact.py` | a részletfoglalás és -rangsor hat változata, 6/8/10 részlettel |
| `04_salvage_impact.py` | a `candidate_result` szerkezetileg érvényes részének visszanyerése, memóriában |

## A bizonyítékcímkék

- A címkék a `questions.md` gold válaszaiból készültek, kérdésenként és
  lépésenként (Q01–Q08, összesen 18 lépés). A kiválasztásnak nem bemenetei;
  minden változat ugyanazokat a csomópontokat és éleket kapja a mentett
  horgonyokból.
- Egy lépés akkor teljesül egy chunkon, ha egy mondata (vagy táblázatsora)
  kimondja; az évet és a névmással hivatkozott személyt a chunk vagy a
  dokumentumazonosító is adhatja.
- Kézi felülvizsgálat: a találó mondatok alapján 9 lexikális találatot
  kizártam (`evidence.REJECTED`, indoklással: feltételes mondat, spekuláció,
  bajnokságvezetés, Ralf Schumacher, konstruktőri cím, motorosszán-verseny
  stb.). A kizárás minden szabály-változat pontozása előtt történt, és utána
  nem változott.
- Korlát: a címkéket azután írtam, hogy a Q04 adatait már láttam, tehát nem
  vakon. Lexikális közelítések; a `results/02_evidence_audit.json` minden
  elfogadott mondatot tartalmaz, így felülvizsgálhatók.
- A globális kérdések (Q09–Q13) goldja aggregálás, nem lánc; ezekre nincs
  címke, csak azt mérem, mennyire változik a kiválasztott részlethalmaz.

## Eredmények röviden (2026-11-05)

`03_selection_impact.py`, jelenlegi gráf, mentett horgonyok:

- A 18 lépésből 8-nak van gráfhoz kötött bizonyítéka, 7 van a
  részletjelöltek között; a jelenlegi szabály 6 részlettel 3-at ad át.
- A foglalás elhagyása 6 részlettel nem változtat (3/18); 8 részlettel
  +1 (Q04 csapattárs), veszteség nélkül.
- Az élforrásokat előnyben részesítő változatok (D, E, F) Q04-et
  visszahozzák, de Q01-et elveszítik.

`04_salvage_impact.py`, a szerkezetileg érvényes jelöltek hozzáadása után:

- 685 elutasított rekordból 3675 entitás és 1131 kapcsolat menne át a
  projekt saját `validate_extraction` szabályán (szerkezeti, nem
  szemantikai érvényesség). 303 kapcsolat csak a nem időbeli élen megadott
  év miatt esik ki; ezeket a visszanyerés nem javítja ki.
- Gráf: 401 → 877 csomópont, 580 → 1236 él, a gráfhoz kötött chunkok
  363 → 1043. 476 új entitásnak nincs embeddingje, 231 meglévő entitás
  indexszövege változna.
- Gráfhoz kötött bizonyíték 8 → 16, jelöltek között 7 → 14 lépés.
- Átadott részletekben: jelenlegi szabállyal 3 → 4 (+3, −2: Q01 és Q06
  „hét cím” kiesik); foglalás nélkül 6 részlettel 3 → 7, veszteség nélkül.
- Mindez a mentett horgonyokkal készült. Újraépített indexszel a horgonyok
  változhatnak; ezt offline nem lehet mérni.
