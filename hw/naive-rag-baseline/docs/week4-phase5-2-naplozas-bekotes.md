# Phase 5 / 2. lépés — naplózás bekötése (offline)

Valódi modell-/embeddinghívás, indexelés, Qdrant-/Neo4j-írás **nem
történt**. Csak a hamis klienses offline tesztek futottak.

## Bekötési állapot útvonalanként

| Útvonal | Naplózó modul | Ténylegesen bekötve | Mechanizmus |
|---|---|---|---|
| Útválasztó | `call_logging.py` | **igen** (Phase 5/1. lépés óta) | `search_router.route_one` belül `logged_call` |
| Naiv | `naive_search_logging.py` | **igen** | `rag.py` minimális, engedélyezett módosítása: `NaiveRAG(chat_call=...)` opcionális injekciós pont; `make_logged_chat_call()` adja a naplózó `chat_call`-t |
| Lokális | `local_search_logging.py` | **igen** (az `answer_fn` injekción keresztül, új belépési ponttal, nem `local_search.main()`-en keresztül) | `make_logged_answer_fn()` |
| Globális map | `global_search_logging.py` | **igen** (a `call_fn` injekción keresztül) | `make_logged_call_fn()` |
| Globális reduce | `global_search_logging.py` | **igen** (ugyanaz a `call_fn`, a reduce is ugyanazt a `ModelCall` aláírást használja) | `make_logged_call_fn()` |

**Meglévő `src/` fájl módosítása egyedül a naivnál történt**
(`src/naive_rag/rag.py`): `NaiveRAG.__init__` kapott egy opcionális
`chat_call: Callable[[list], str] | None = None` paramétert; `ask()` ezt
használja, ha meg van adva, egyébként **pontosan a korábbi viselkedés**
fut (`get_chat_model().invoke(messages).content`). Nincs monkey patch.
A `get_rag()` singleton factory és minden meglévő hívó változatlan marad
(`chat_call` alapértelmezetten `None`).

A lokális és a globális map/reduce bekötése **nem igényelt** meglévő
fájl módosítást, mert `answer_fn` (`local_search.py:1037`) és `call_fn`
(`global_search.py` `ModelCall`) **már eleve injektált paraméterek**
voltak — csak egy új belépési pontnak kell ezeket a naplózó verzióval
hívnia `local_search.main()` / a jelenlegi `run_phase4()`-hívó szkript
helyett (ez utóbbi még nem készült el, mert éles futtatás nincs
engedélyezve).

## Lokális keresés — külön ellenőrzés

A kérés kifejezetten kérte, hogy ne csak a modul létét, hanem a
**ténylegesen használt kliens hívását** ellenőrizzem. `local_search()`
az `answer_fn(prompt: str)` függvényt hívja **egyetlen string**
paraméterrel (nem üzenetlistával) — ezt `make_logged_answer_fn()`
`[{"role": "user", "content": prompt}]` alakban naplózza, és a
`raw_caller` **pontosan ugyanazt a `prompt` stringet** adja át
`chat_client.invoke(...)`-nak, mint amit a meglévő
`lambda prompt: chat.invoke(prompt).content` tenne. Teszttel igazolva:
`test_local_search_logging.py::test_the_exact_prompt_string_is_what_the_client_receives`
és `::test_same_observable_behaviour_as_the_plain_lambda` (a naplózott
és a nem naplózott hívás **azonos kimenetet** ad).

## Ismert korlát — globális map/reduce hívásazonosítás

A `ModelCall` aláírás (`system, user, max_tokens -> ModelResponse`) nem
hordoz kérdés- vagy közösségazonosítót. A `make_logged_call_fn()` ezért
csak sorszám alapján különbözteti meg a naplófájlokat
(`global-log-0001.json`, ...), nem kérdés/közösség szerint. Kérdés-/
közösségazonosítóval ellátott naplózáshoz a hívási pontot
(`global_search.py` `process_one_map`/`process_one_reduce`) kellene
módosítani — **ezt nem valósítottam meg**, mert meglévő fájl módosítását
igényelné, ami ezen a ponton nincs engedélyezve. Jelzem, és itt
megállok ezzel a résszel.

## Offline tesztek

Új fájlok: `tests/test_rag.py` (3), `tests/test_naive_search_logging.py`
(4), `tests/test_local_search_logging.py` (5), `tests/test_global_search_logging.py`
(5) — összesen **17 új teszt**, mind lefutott, valódi hívás nélkül.
Ellenőrzik:
- a naplózott üzenetek pontosan egyeznek a hamis kliens által
  ténylegesen kapott tartalommal (mindhárom adapternél külön tesztelve);
- `question_id` sosem kerül a ténylegesen küldött tartalomba;
- a naiv keresés **alapértelmezett** viselkedése (`chat_call=None`)
  változatlanul `get_chat_model()`-t hívja (mock-kal igazolva, valódi
  hívás nélkül);
- az injektált `chat_call`/`answer_fn`/`call_fn` esetén **nem** hívódik
  a korábbi, nem naplózó útvonal;
- a globális adapter visszatérési értéke kompatibilis
  `global_search.process_one_map`-pel (valódi integrációs teszt hamis
  klienssel).

Teljes offline szvit: **326/326 zöld**
(`PYTHONPATH=src uv run python -m unittest discover -s tests -p "test_*.py"`).

## Maradt futtatást akadályozó hiány?

Nincs technikai akadály a modulok szintjén. **Hiányzik** egy új, önálló
futtató belépési pont (script), amely:
1. a naiv/lokális/globális módot ténylegesen meghívja a naplózó
   `chat_call`/`answer_fn`/`call_fn`-nel (ezek most külön-külön, hamis
   klienssel vannak tesztelve, de nincs egy közös "futtasd le Q01–13-at"
   szkript);
2. valódi API-kulccsal és jóváhagyással futtatná őket.

Ennek megírása **új implementáció** lenne, amit ez a lépés kifejezetten
nem engedélyezett ("ne készíts új implementációt" a korábbi, illetve
"éles futtatást még nem engedélyezek" a mostani utasításban) — ezért
**nem készítettem el**, csak jelzem, hogy ez a következő, jóváhagyandó
lépés.

## Módosított és létrehozott fájlok

**Módosítva (engedélyezett, minimális):** `src/naive_rag/rag.py`

**Létrehozva:**
- `src/naive_rag/naive_search_logging.py`
- `src/naive_rag/local_search_logging.py`
- `src/naive_rag/global_search_logging.py`
- `tests/test_rag.py`, `test_naive_search_logging.py`, `test_local_search_logging.py`, `test_global_search_logging.py`
- `docs/week4-phase5-2-naplozas-bekotes.md` (ez a dokumentum)

**Frissítve:** `docs/week4-phase5-terv-es-becsles.md` (git/napló-hiány
pontosítás a 4a. szakaszban; a költségtábla hívásszámai javítva, hogy az
embedding hívások ne szerepeljenek kétszer).
