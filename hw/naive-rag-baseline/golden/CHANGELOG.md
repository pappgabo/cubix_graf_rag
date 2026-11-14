# Golden set — changelog

## v1 — 2026-11-11

- **Jóváhagyott verzió:** v1 (a fájl neve és a benne lévő
  `golden_set_version` mező szerint: `v1-approval-draft`). Az
  „approval-draft” a fájlnévben a **jóváhagyott v1 tartalmat** jelöli, nem
  szerkesztés alatt álló változatot.
- **Fájl:** [`week5-golden-set-v1-approval-draft.jsonl`](week5-golden-set-v1-approval-draft.jsonl)
- **A teljes fájl SHA-256-ja (bájtszintű, a jelenlegi tartalomra számolva):**
  `cfda4a0afc1ca25162a296ef3b4d14cc68e800ebc3603ac6faacdf9f67bf4390`
  — ez a `mérési állapot` (`diagnostics/2026-11-11-week5-b/state/`) által is
  rögzített, azonos módon (`hashlib.sha256(path.read_bytes())`, a fájl teljes
  bájtjaira) képzett azonosítóval egyezik (lásd a mérési program megfelelő
  jegyzetét).
- **Kérdésszám:** 15 kérdés — ebből 13 `frozen_w4` és 2 `held_out` (Q14, Q15),
  a fájlból közvetlenül ellenőrizve (`status` mező soronként).
- **Korpusz hash (a golden fájl saját metaadatából, nem a golden fájl
  hash-e):** `corpus.chunks_sha256 =
  79d46d6291bc07924ddc13703f9b4804f8cf9c86de9de3ebaf435248f04e012e`,
  `corpus.chunk_count = 1651`. Ez a `graph/corpus/chunks-section-1200-23/chunks.jsonl`
  korpuszfájl hash-e, **nem azonos** a fenti, a golden fájl saját tartalmára
  számolt SHA-256-tal — a kettőt nem szabad összekeverni.
- **Korábbi példány összehasonlítása:** [TODO: a fájl korábban az átadási
  könyvtárban (`D:\PET\CUBIX\cubix_GraphRAG\6.hét\HW\`) volt; az a példány a
  `golden/` mappába költöztetéskor áthelyezésre (nem másolásra) került, így
  jelenleg nincs ott külön példány, amivel a hash összehasonlítható lenne —
  ezt nem állítjuk úgy, mintha megtörtént volna az összevetés].
- **Innentől a v1 fájl változatlan:** tartalmi módosítás új verziófájlt (pl.
  `week5-golden-set-v2-....jsonl`) és új changelog-bejegyzést igényel ebben a
  fájlban; a meglévő v1 tartalmat utólag nem szerkesztjük.
