# Week 5 — A2 célzott felmérés

Scope: csak A2 (felmérés + helyi script + offline teszt + jelentés). Nincs
keresőfuttatás, nincs projektmodell-API-hívás, nincs adatbázis-írás,
nincs Langfuse-adatküldés, nincs csomagtelepítés. A keresők és a golden
set változatlanok.

## 1. Hárommódos mezőtérkép

| Mód | Belépési pont (fájl:függvény) | Legutóbbi futtató | Válasz | Tényleges generálási kontextus | Chunkazonosító a kontextusban | Forráskapcsolat | Használati adat (usage) | Map/reduce résznapló |
|---|---|---|---|---|---|---|---|---|
| **Naiv** | `src/naive_rag/rag.py:75 NaiveRAG.ask` (retrieve → `rag.py:70`, prompt → `rag.py:20 PROMPT`/`rag.py:54 format_context`) | `diagnostics/2026-11-10-phase5-run/run_phase5.py:340 run_naiv` | `results/week4-phase5-naiv-answers.json` — csak `{question_id, answer, error}`; a forráslista nincs perzisztálva ide | `logs/naive-log-naiv-Q*.json`-ban a teljes `messages` mező (system+user, a ténylegesen elküldött szöveg) | **Hiányzik a renderelt kontextusból.** `format_context` (`rag.py:54`) csak `[S{rank}] (file, location)`-t ír ki; a Qdrant payload (`run_phase5.py:312`, a `chunks-section-1200-23/chunks.jsonl` sorai) nem tartalmaz `file` mezőt → a logban ténylegesen `(None, page 1)` jelenik meg. A `chunk_id` a `source_of()` (`rag.py:39`) visszatérési dict-jében megvan, de a prompt szövegébe nem kerül bele, és a `sources` lista önmagában sosem kerül fájlba íratásra | a `source_of()` dict futásidejű mezői (`chunk_id`, `doc_id`, `score`) — csak memóriában, a futás végén elvesznek | `naive_search_logging.py:42 make_logged_chat_call` → `call_logging.logged_call`; a log fájl és a ledger-bejegyzés (`week4-phase5-ledger.json`) tartalmazza: `usage_prompt_tokens`, `usage_completion_tokens`, `duration_seconds`, `cost_usd`, `messages_sha256` | nincs (map/reduce a naiv módban nem értelmezett) |
| **Lokális** | `src/naive_rag/local_search.py:1036 local_search` (kontextus: `select_context`:211, `fit_context`:791, `context_text`:589) | ugyanaz, `run_phase5.py:410 run_lokalis` | `results/week4-phase5-lokalis-answers.json` — `{answer, refused, model_called, context_budget}` (a `context_budget` csak darabszámokat ad: `selected_sources`, `omitted_sources`, stb., konkrét chunk-id-t nem) | `logs/local-log-lokalis-Q*.json`-ban a teljes renderelt prompt (`answer_prompt`+`context_text`) | **Megvan, explicit.** `context_text()` (`local_search.py:589`) a forrásszakaszban `"- [{chunk_id}] {text}"` formában írja ki az eredeti dokumentumrészleteket (pl. `driver-lewis-hamilton#79`); ellenőrizve: `logs/local-log-lokalis-Q01.json`-ban 15 db `doc_id#ordinal` alakú tag található | `subgraph_payload()` (`local_search.py:296`): `nodes[].source_chunk_ids`, `edges[].source_chunk_ids`, `chunk_ids` lista — entitás/él → chunk visszavezetés megvan a `fitted` subgraph-ban, de ez a `context_budget` mezőben *nem* kerül fájlba a Phase 5 futtatónál (csak a számosságok) | `local_search_logging.py:37 make_logged_answer_fn` → ugyanaz a `call_logging.logged_call`; log fájl + ledger: `usage_prompt_tokens/completion_tokens`, `duration_seconds`, `model_called`, `refused` | nincs (helyi keresésnek nincs map/reduce lépése) |
| **Globális** | `src/naive_rag/global_search.py:715 run_question` (map: `process_one_map`:518, reduce: `process_one_reduce`:606) | `run_phase5.py:479 run_globalis_rerun` (A-ág only, `gs_run_question_a_only`:524) | `results/week4-phase5-globalis-rerun.json` — teljes `reduce_a` rekord: `answer`, `cited_partial_answer_ids`, **`citation_chain`** | a map/reduce rendszerüzenetek és felhasználói JSON-ok (`map_user_message`:228, `reduce_user_message`:326) nincsenek a végeredmény-fájlban, csak a `logs/global-rerun/global-rerun-log-NNNN.json` sorszámozott fájlokban (lásd korlát alább) | **Megvan, lánc formájában.** `resolve_citation_chain()` (`global_search.py:376`) minden idézett közösségi jelentéshez felsorolja a `statement_id`, `evidence_ids`, **`candidate_source_chunk_ids`** mezőket; ellenőrizve `results/week4-phase5-globalis-rerun.json` Q09 `reduce_a.citation_chain[0]` → `candidate_source_chunk_ids: ["driver-lewis-hamilton#79"]` | `community_path → partial_answer/usefulness_score → statement → evidence_ids → candidate_source_chunk_ids` — ez a projekt saját dokumentációja szerint is **retrieval hint, nem soronként ellenőrzött bizonyíték** (`global_search.py` modul docstring, 16–19. sor) | `global_search_logging.py:45 make_logged_call_fn`; minden map/reduce hívás saját log fájlt kap (`global-rerun-log-0001.json` …), ledger-bejegyzés kérdésenként (`map_calls`, `status`) | **Megvan, per hívás.** 37 map-hívás + 1 reduce-A hívás kérdésenként; mind a `map_results` (37 elem/kérdés), mind a `reduce_a` validációs mezői (`valid_json`, `validation.valid_structure`, `finish_reason`) a végeredmény-fájlban vannak |

**Tényleges kontextus vs. háttérforrás-jelölt, módonként:**
- **Naiv:** a `top_k` (`TOP_K=4`, `run_phase5.py:68`) Qdrant-találat *mind* ténylegesen a promptba kerül (nincs külön "jelölt" fogalom) — de a chunk-azonosító maga nem kerül a promptba, csak page/section.
- **Lokális:** a `cited_chunks()` (`local_search.py:337`) állítja elő a *jelölt* forráspoolt (egy teljes entitás/él-halmazhoz tartozó összes chunk, rangsorolva); ebből a `fit_context()` (`local_search.py:791`) vágja ki a budget szerint ténylegesen renderelt alhalmazt. A Q01 futásban 268 jelöltből 15 tényleges forrás ment be a promptba (`context_budget.selected_sources=15`, `omitted_sources=253`).
- **Globális:** minden `CommunityReport.statements[].candidate_source_chunk_ids` háttérjelölt (a riport saját dokumentációja szerint sosem ellenőrzött egyenként); a `citation_chain` csak azokat a jelölteket sorolja fel, amelyeket a reduce lépés ténylegesen idézett (`cited_partial_answer_ids` → `cited_statement_ids`).

## 2. Egyetlen javasolt integráció + kompatibilitási eredmények

**Javaslat:** a már meglévő `call_logging.logged_call` / `CallParams` köré egy új, nem módosító Langfuse `@observe`-szerű wrapper (hasonlóan a meglévő `naive_search_logging.py` / `global_search_logging.py` mintához), amely a *már elkészült* log-bejegyzést (üzenetek, usage, hiba) továbbítja egy Langfuse experiment run-ba — a modellhívás maga (`ChatOpenAI`/`openai` kliens) változatlan marad.

**Ellenőrzött tények (nem feltételezve, hanem a repóból/dry-run-ból):**
- `pyproject.toml` / `uv.lock`: a projekt jelenleg **nem** deklarál sem `langfuse`-t, sem `ragas`-t. Telepítve van viszont `openai==3.24.0` (a `langchain-openai>=1.6.7` tranzitív függősége), `langchain>=1.4.3`, `langchain-openai>=1.6.7`.
- Nem módosító függőségfeloldás: `uv pip install --dry-run langfuse ragas --python .venv/Scripts/python.exe` (csak feloldás, nincs tényleges telepítés/lock-/venv-módosítás) →
  - felold 106 csomagra, `langfuse==5.2.0`, `ragas==0.4.3` telepíthető lenne,
  - **de visszahúzná** `openai`-t `3.24.0` → `3.3.0`-ra, és `jiter`-t `0.17.0` → `0.14.0`-ra (a `ragas` → `instructor==1.17.0` lánc szűkebb `openai` tartományt kér).
  - Kontroll: `uv pip install --dry-run "langchain-openai>=1.6.7" "openai==3.24.0"` önmagában **nem** okoz változást — tehát a downgrade-et kifejezetten a `ragas`/`instructor` lánc kényszeríti ki, nem a meglévő stack.
- A chat kliens (`models.py:26 get_chat_model` → `langchain_openai.ChatOpenAI`) és az embedding kliens (`models.py:49 get_embeddings` → `langchain_openai.OpenAIEmbeddings`) mindkettő szabványos LangChain `BaseChatModel`/`Embeddings` — dokumentáció szerint ez közvetlenül illeszthető a Ragas `LangchainLLMWrapper` / `LangchainEmbeddingsWrapper` elvárásához, de ez **nincs ténylegesen kipróbálva** (telepítés nélkül nem futtatható).
- Langfuse experiment API dokumentáció szerint provider-agnosztikus (egy tetszőleges Python callable-t futtat egy datasetre); a meglévő `logged_call`/`CallParams` absztrakció (már injektált `chat_call`/`answer_fn`/`call_fn` mindhárom módban) elvileg kompatibilis integrációs pont — **ez is csak dokumentáció alapú, nem telepítéssel igazolt** állítás.

**Bizonytalan, külön tisztázandó pontok (explicit):**
- Nem ellenőrzött: a `ragas==0.4.3` ténylegesen működik-e a leszállított `openai==3.3.0`-val a projekt tényleges hívási mintájával (JSON-mode response_format, max_retries=0) — ez csak telepítéssel derülne ki.
- Hiba esetén leállás/folytatás: a meglévő három modul (`global_search.py`, `local_search.py`, naiv réteg) mindegyike **egyedi, saját** hibakezeléssel rendelkezik (ledger `in_progress`/`success`/`error`/`context_overflow` státuszok, `global_search.py:470-476` dokumentált "soha nem hív újra" elv). Egy Langfuse-integrációnak ehhez a már meglévő, kérdésenkénti leállási sémához kellene illeszkednie — ez tervezési döntés, A2-ben nem dőlt el.
- Meglévő eredmények feltöltése: a Phase 5 futás eredményei (`results/week4-phase5-*.json`) már a lemezen vannak, kérdésenkénti `request_hash`/`messages_sha256` azonosítóval — egy utólagos Langfuse-feltöltő szkript ezekből replay módban dolgozhatna (nincs új modellhívás), de ez **nem history-rekonstrukció**, hanem a már meglévő A2 feladaton túli, B-fázisbeli implementáció, amit itt nem kezdtem el.

## 3. Script és offline teszt

Új fájlok (a keresők és a golden set nem módosultak):
- `diagnostics/2026-11-11-week5-a2/survey_candidates.py` — stdlib-only CLI, két alparancs: `search`, `sample`.
- `diagnostics/2026-11-11-week5-a2/test_survey_candidates_offline.py` — 21 unittest teszt, csak szintetikus fixture-ökön (nem a valódi korpuszon/golden seten).

A chunks.jsonl séma (`graph/corpus/chunks-section-1200-23/chunks.jsonl`, ellenőrizve az első soron): `chunk_id, doc_id, ordinal, section, page, n_chars, text, chunk_size, chunk_overlap`. 1651 sor, 23 egyedi `doc_id` — egyezik a golden set draft `corpus.chunk_count: 1651` mezőjével.

`search`: minden kérdéshez a `criteria[].expected_content` szavaiból (Q13-nál, ahol a rubrika szándékosan üres, a kérdésszövegből, jelölve) kulcsszó-egyezés alapján rangsorolja a chunkokat, és top-5 *jelöltet* ad vissza doc_id + chunk_id + pontszám + kontextusablak formában. Nincs embedding, nincs keresőrendszer, nincs LLM-hívás.

`sample`: `random.Random(42)` — 10 különböző `doc_id` kiválasztása a rendezett doc_id-univerzumból, majd dokumentumonként egy chunk (szintén a 42-es seedből húzva), a teljes chunk-rekorddal.

Mindkét kimenet tartalmazza a `corpus_sha256`-ot (a ténylegesen beolvasott `chunks.jsonl` sha256-ja) és a seedet/módszert.

## 4. Hiányok / proxyk

- A naiv mód tényleges generálási kontextusából hiányzik a chunk-azonosító (lásd 1. táblázat) — ez nem A2-ben javítandó hiba, csak megfigyelés.
- A golden set draft `chunks_sha256: null` és üres `any_of_chunk_ids` listái szándékos vázelemek (az átadási jegyzet szerint), ezeket a felmérés és a script sem egészíti ki.
- Q02 kulcsszavas keresése a draft `expected_content: ["23 éves"]` magyar kifejezése miatt gyenge találatot ad az angol nyelvű korpuszon (30 jelölt, de a magyar "éves" szótöredék miatt zajos) — ez a draft nyelvi vázlatjellegéből fakad, nem a script hibája.
- A map/reduce részlog a globális módban *kérdésenként* 38 fájlra bomlik (`logs/global-rerun/global-rerun-log-NNNN.json`); ezekben nincs kérdés/közösség-azonosító visszakötés (csak sorszám) — ezt a `global_search_logging.py` modul docstringje is dokumentált korlátként jelzi.

## 5. Érintett fájlok

Csak olvasva (nem módosítva): `src/naive_rag/rag.py`, `naive_search_logging.py`, `local_search.py`, `local_search_logging.py`, `global_search.py`, `global_search_logging.py`, `search_router.py`, `models.py`, `pyproject.toml`, `uv.lock`, `graph/corpus/chunks-section-1200-23/chunks.jsonl`, `diagnostics/2026-11-10-phase5-run/run_phase5.py` és a `results/`/`logs/` kimenetei.

Újonnan létrehozva: `diagnostics/2026-11-11-week5-a2/survey_candidates.py`, `.../test_survey_candidates_offline.py`, `.../results/week5-chunk-candidates.json`, `.../results/week5-sample-10docs.json`, `docs/week5-felmeres.md` (ez a fájl).

## 6. Tesztek és pontos PowerShell-parancsok

```powershell
cd "D:\PET\CUBIX\cubix_GraphRAG\6.hét\HW\naive-rag-baseline\diagnostics\2026-11-11-week5-a2"
python -m unittest test_survey_candidates_offline -v
python survey_candidates.py search --out results/week5-chunk-candidates.json
python survey_candidates.py sample --out results/week5-sample-10docs.json
```

Eredmény: 21/21 teszt zöld; `search` 13 kérdést dolgozott fel; `sample` 10 dokumentumot mintázott (seed=42).
