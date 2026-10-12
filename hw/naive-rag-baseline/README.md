# Naiv RAG baseline — Formula 1 korpusz (GraphRAG kurzus, 1. hét)

Egy szándékosan egyszerű, jól dokumentált **naiv RAG baseline**, amihez a
következő hetekben a GraphRAG-os megoldást hasonlítjuk. A cél nem a jó
teljesítmény, hanem a naiv RAG korlátainak láthatóvá tétele — a rossz válaszokat
ezért **nem javítottam**.

**Stack:** Python 3.11 · `uv` · LangChain · OpenAI (`gpt-4o-mini`,
`text-embedding-3-small`) · Qdrant (helyi, lemezre perzisztáló) · FastAPI.

## Gyors indulás

```bash
uv sync                               # környezet + függőségek
cp .env.example .env                  # majd írd be az OPENAI_API_KEY-t
uv run naive-rag ingest               # korpusz -> chunkok -> embedding -> Qdrant
uv run naive-rag ask "Who won the 2021 Formula One World Drivers' Championship?"
uv run naive-rag baseline             # mind a 13 kérdés -> baseline/
uv run naive-rag serve                # FastAPI: http://127.0.0.1:8000/docs
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

## Mappaszerkezet

```
naive-rag-baseline/
├─ README.md · questions.md · pyproject.toml · uv.lock · .env.example · .gitignore
├─ run.py           belépési pont ékezetes útvonalú klónokhoz (lásd 2. pont)
├─ src/naive_rag/   config · loaders · models · vectorstore · ingest · rag · cli · api
├─ scripts/         download_corpus.py · convert_formats.py
├─ corpus/          23 dokumentum (pdf/docx/html/txt/xlsx) + metadata.json
└─ baseline/        answers.md · answers.json (v2) · v1-plain-loaders-500-75/
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
