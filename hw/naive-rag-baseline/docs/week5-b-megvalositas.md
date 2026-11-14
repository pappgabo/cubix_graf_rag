# Week 5 B — implementáció (csak offline tesztelve, fizetős hívás nincs)

Kód: `diagnostics/2026-11-11-week5-b/`. A keresők (`src/naive_rag/*`) és a
Phase 5 futtató (`diagnostics/2026-11-10-phase5-run/run_phase5.py`) nem
módosultak; a `run_phase5.LOG_DIR` modulattribútumot futásidőben
átirányítjuk (nem fájltartalom-módosítás), hogy az új logok ne a megőrzött
Phase 5 mappába írjanak.

## Fájlok
- `golden_set.py` — a jóváhagyott 15 kérdéses golden set betöltése, korpuszhash-ellenőrzés.
- `retrieval_eval.py` — determinisztikus bizonyítékcsoport-lefedettség (any_of/ÉS, bridge, proxy jelölés).
- `judges/correctness_judge_prompt_v1.md`, `judges/faithfulness_judge_prompt_v1.md` — verziózott bíróprompt-fájlok.
- `correctness_judge.py`, `faithfulness_judge.py` — prompt-építés, válaszvalidáció, címkézés/pontszámítás.
- `cost_guard.py` — megosztott, lemezre írt költségkeret (0,50 USD/hét), füstpróba+teljes+folytatás között közös.
- `state_store.py` — per-eset lépésállapot (`answer_saved/criteria_scored/faithfulness_scored/langfuse_synced`), konfiguráció+golden set hash alapú azonosítással.
- `generation_runner.py` — a három mód vékony wrapperje a meglévő Phase 5 kódúton, második retrieval nélkül.
- `langfuse_sync.py` — Langfuse `run_experiment` szinkron, csak már kész helyi eredményt olvas (nincs új modellhívás).
- `report.py` — `results.jsonl` írás/olvasás, három mód × kérdéstípus Markdown-tábla, frozen_w4/held_out bontás, költség/késleltetés összegzés.
- `measure.py` — a CLI (`run --smoke` / `run --full`), folytatható, megosztott költségkeret, nincs automatikus retry.
- `tests/` — 67 offline teszt, csak fake hívásokkal.

## Azonos generáló/bíró modell torzítása (dokumentálva, nem oldva meg)

Mindhárom válaszoló mód (naiv, lokális, globális) és mindkét bíró
(helyesség, faithfulness) ugyanazt a `gpt-4o-mini` modellt használja
temperature=0 mellett. Ez azt jelenti:
- a bíró szisztematikusan hajlamos lehet a saját modellcsalád stílusában
  megfogalmazott válaszokat kedvezőbben értékelni (self-preference bias),
- a bíró ugyanazokat a nyelvi/ténybeli vakfoltokat örökölheti, mint a
  válaszoló (pl. ha a modell egy adott téves asszociációt rendszeresen
  elkövet, a bíró ugyanazt hajlamos lehet "ésszerűnek" találni),
- ez NEM feleltethető meg egy független, nagyobb/más modellcsaládú
  bírálónak; a mérés eredményeit ennek fényében relatív (módok közötti),
  nem abszolút minőségi mércének kell tekinteni.
Enyhítés (amit a prompt megtesz): a bíró csak a megadott kritériumok és
kontextus alapján ítélhet, külső tudást nem használhat, és a
`rubric_conflicts` mezőt csak a rubrikával bizonyítható ellentmondásra
korlátozzuk — ez csökkenti, de nem szünteti meg a torzítást.

## Telepített csomagok, meglévő verziók változatlansága

`uv add langfuse` (valódi telepítés, nem dry-run) lefutott:
`langfuse==5.2.0` + 10 függősége települt, **egyetlen meglévő csomag
verziója sem változott** (`openai==3.24.0`, `langchain-openai==1.6.7`
stb. változatlan — ellenőrizve `uv.lock`-ból és a venv-ből importálással).
A Langfuse `run_experiment`/`Evaluation`/`LocalExperimentItem` API-ját a
ténylegesen telepített csomagból (`inspect.getsource`) olvastuk ki, nem
dokumentációs emlékezetből.

## Ismert akadályok / a Langfuse experiment API korlátai

- A `run_experiment` `task` függvénye a Langfuse SDK dokumentációja
  szerint bármilyen értéket visszaadhat (nem kötelező modellhívás) —
  ezt kihasználva a `langfuse_sync.py` `task`-ja csak a már elmentett
  választ olvassa vissza, így a feltöltés nem indít új modellhívást. Ezt
  **nem futtattuk valódi Langfuse Cloud ellen** ebben a menetben (csak
  fake klienssel, offline) — a tényleges szinkront a felhasználó indítja.
- A `run_experiment` kérdésenkénti/módonkénti granularitású hívása
  (`sync_records` egy rekordra) azt jelenti, hogy minden egyes eset külön
  "experiment run"-t indít a Langfuse oldalon ugyanazon `name` alatt —
  ez működik, de nem egyetlen batch-feltöltés; ha a felhasználó egyetlen,
  15×3-as batch kísérletet szeretne egy `run_experiment`-hívásban, ehhez
  a `sync_records`-ot kellene minden rekordra egyszerre hívni (jelenleg
  `measure.py` kérdésenként/módonként szinkronizál, hogy a
  `langfuse_synced` lépésállapot esetenként legyen folytatható).
