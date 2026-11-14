# Közösségi riportbemenetek mérése (Phase 3, offline)

Modellhívás és Neo4j-írás nem történt. A mérés a `docs/week4-vetulet-leképezés.json` előkészített vetületén és a memóriában újraépített `merged_graph`-on fut (`graph/corpus/extraction-reuse-1200-23`), a Leiden particionálás meghívása nélkül. A tokenszámok karakter/4 becslések, nem tényleges tokenizer-mérések (lásd a jegyzetet a dokumentum végén).

Futtató szkript: `diagnostics/2026-11-10-phase3-measurement/measure_report_inputs.py`. A teljes, közösségenkénti táblázat: `docs/week4-reportbemenet-meres.json`.

## Ellenőrzött darabszámok

- 0. szint, nem egyelemű közösség: **37** (elvárt 37) -- OK
- ebből 10 csomópontnál nagyobb: **19** (elvárt 19) -- OK
- nem izolált kanonikus tag összesen: **1909** (elvárt 1909) -- OK
- 1. szint (teljes reporting level) közösség: **191**, tag összesen: **1909**

## Tagsági lefedettség

Minden nem izolált kanonikus tag pontosan egyszer szerepel a 0. szintű és az 1. szintű (teljes reporting level) tagsági lefedettségben is: **igen** (a mérőszkript `level_membership()` függvénye ezt explicit assert-tel ellenőrzi -- `set(level0_members) == reporting_level_paths(plan, 0)`, ugyanígy 1. szintre -- a szkript mindkétszer hiba nélkül lefutott).

Egyelemű, de **nem izolált** tagú közösség:
- 0. szinten: **0**
- 1. szinten (teljes reporting level): **0**

(Mindkettő 0 -- konzisztens a Phase 2 auditban mért ténnyel: ezen az adathalmazon a méret-1 közösségek minden szinten pontosan a globálisan izolált csúcsokkal esnek egybe, újabb bomlás sosem termel új egyelemű közösséget. Riportkészítési státusz ezért most tárgytalan -- nincs ilyen közösség, amiről dönteni kellene.)

## 0. szint -- mind a 37 közösség mérési táblája

Rendezve csökkenő csomópontszám szerint. "Nyers tok." a teljes, vágatlan leírás-szöveg becsült tokenszáma; "Bemenet tok." a 24 000 tokenes keretbe illesztett, teljes szerializált modellbemenet (prompt-vázzal együtt) becsült mérete.

| Közösség | Csomópont | Vetületi él | Domain-kapcsolat | Nyers tok. (becslés) | Bemenet tok. (becslés) | Kihagyott node | Kihagyott kapcsolat | Rövidített |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `3` | 168 | 212 | 213 | 23004 | 23975 | 79 | 93 | 54 |
| `5` | 159 | 184 | 201 | 14825 | 24018 | 9 | 51 | 21 |
| `22` | 151 | 207 | 229 | 17759 | 24042 | 30 | 95 | 37 |
| `60` | 151 | 172 | 197 | 17244 | 24018 | 38 | 62 | 30 |
| `37` | 133 | 151 | 153 | 16016 | 23961 | 34 | 30 | 42 |
| `33` | 131 | 158 | 194 | 22853 | 23944 | 66 | 78 | 41 |
| `4` | 125 | 143 | 178 | 19942 | 23961 | 49 | 56 | 40 |
| `38` | 117 | 129 | 129 | 14189 | 23901 | 1 | 0 | 34 |
| `15` | 111 | 146 | 177 | 22548 | 24015 | 56 | 51 | 40 |
| `111` | 107 | 112 | 112 | 11451 | 21609 | 0 | 0 | 28 |
| `24` | 105 | 105 | 111 | 9621 | 17885 | 0 | 0 | 16 |
| `63` | 89 | 98 | 98 | 10530 | 18015 | 0 | 0 | 24 |
| `34` | 88 | 94 | 94 | 9684 | 17093 | 0 | 0 | 22 |
| `12` | 43 | 42 | 42 | 4217 | 7525 | 0 | 0 | 7 |
| `179` | 42 | 41 | 41 | 4426 | 8152 | 0 | 0 | 14 |
| `44` | 41 | 43 | 43 | 2755 | 6460 | 0 | 0 | 2 |
| `162` | 35 | 34 | 34 | 3849 | 6978 | 0 | 0 | 11 |
| `168` | 30 | 29 | 29 | 3619 | 6194 | 0 | 0 | 10 |
| `205` | 20 | 19 | 19 | 2946 | 4605 | 0 | 0 | 15 |
| `263` | 10 | 9 | 9 | 457 | 1215 | 0 | 0 | 0 |
| `331` | 10 | 9 | 9 | 563 | 1323 | 0 | 0 | 0 |
| `275` | 7 | 6 | 6 | 431 | 953 | 0 | 0 | 0 |
| `370` | 5 | 4 | 4 | 227 | 614 | 0 | 0 | 0 |
| `377` | 4 | 3 | 3 | 250 | 591 | 0 | 0 | 0 |
| `320` | 3 | 2 | 2 | 188 | 431 | 0 | 0 | 0 |
| `8` | 2 | 1 | 1 | 78 | 211 | 0 | 0 | 0 |
| `62` | 2 | 1 | 1 | 101 | 251 | 0 | 0 | 0 |
| `114` | 2 | 1 | 1 | 64 | 194 | 0 | 0 | 0 |
| `127` | 2 | 1 | 1 | 103 | 241 | 0 | 0 | 0 |
| `135` | 2 | 1 | 1 | 113 | 273 | 0 | 0 | 0 |
| `237` | 2 | 1 | 1 | 111 | 273 | 0 | 0 | 0 |
| `259` | 2 | 1 | 1 | 105 | 251 | 0 | 0 | 0 |
| `334` | 2 | 1 | 1 | 159 | 334 | 0 | 0 | 1 |
| `365` | 2 | 1 | 1 | 68 | 197 | 0 | 0 | 0 |
| `430` | 2 | 1 | 1 | 76 | 209 | 0 | 0 | 0 |
| `654` | 2 | 1 | 1 | 85 | 222 | 0 | 0 | 0 |
| `730` | 2 | 1 | 1 | 77 | 213 | 0 | 0 | 0 |

## Összesített tábla: 0. és 1. (teljes reporting level) szint

| Szint | Közösségek | Tagok | Vetületi él (össz.) | Domain-kapcsolat (össz.) | Bemenet tok. össz. (becslés) |
|---|---:|---:|---:|---:|---:|
| 0 | 37 | 1909 | 2164 | 2339 | 338347 |
| 1 (teljes) | 191 | 1909 | 1750 | 1848 | 365629 |

## 19 nagy közösség -- lefedettségi alternatíva

A 19 db, 10 csomópontnál nagyobb 0. szintű közösség összesen **1846** kanonikus csúcsot fed le az 1909-ből -- **63** csúcs marad lefedetlen, ha csak ezekre a 19-re készül riport.

Kimaradó (legfeljebb 10 csomópontos) közösségek: `8`, `62`, `114`, `127`, `135`, `237`, `259`, `263`, `275`, `320`, `331`, `334`, `365`, `370`, `377`, `430`, `654`, `730`

## Pilot -- 3 közösség (legkisebb / medián / legnagyobb)

A 37, nem egyelemű 0. szintű közösség (csomópontszám, path mint egésztuple) szerint rendezve; a pilot az 1., 19. és 37. elem.

| Pozíció | Közösség | Csomópont | Bemenet tok. (becslés) | Fájl | SHA-256 |
|---|---|---:|---:|---|---|
| smallest | `8` | 2 | 211 | `diagnostics\2026-11-10-phase3-measurement\results\pilot-smallest-8.json` | `e4481f4eaa39058a...` |
| median | `205` | 20 | 4605 | `diagnostics\2026-11-10-phase3-measurement\results\pilot-median-205.json` | `f08b7c81be0ff2ec...` |
| largest | `3` | 168 | 23975 | `diagnostics\2026-11-10-phase3-measurement\results\pilot-largest-3.json` | `fa660be3c388c77d...` |

A teljes hash-ek: `diagnostics/2026-11-10-phase3-measurement/results/pilot-manifest.json` (a hash a ténylegesen elmentett bemenet UTF-8 tartalmából készült, külön manifestben, nem a hashelt fájlon belül).

## Riportprompt-sablon v1

Mentve, nem futtatva: `diagnostics/2026-11-10-phase3-measurement/riportprompt-sablon-v1.md`.

## Költségbecslés

Feltételezett gpt-4o-mini árazás: input 0,15 USD / 1M token, output 0,60 USD / 1M token. Egy sikeres hívás riportonként, retry nélkül; a kimeneti tokenkorlát felső becslés, nem tényleges fogyasztás.

| Tétel | Riport | Bemenet tok. (becslés) | Kimenet-felső-korlát | Becsült költség |
|---|---:|---:|---:|---:|
| 0. szint, mind a 37 | 37 | 338347 | 22200 (600 tok./riport) | $0.0641 |
| 19 nagy közösség (alternatíva) | 19 | 330351 | 11400 (600 tok./riport) | $0.0564 |
| 1. szint, teljes reporting level | 191 | 365629 | 114600 (600 tok./riport) | $0.1236 |
| Pilot (3 közösség) | 3 | 28791 | 5400 (legfeljebb 1800 tok./riport) | $0.0076 |

## Létrehozott fájlok

- `diagnostics/2026-11-10-phase3-measurement/measure_report_inputs.py` (mérőszkript)
- `diagnostics/2026-11-10-phase3-measurement/make_markdown_summary.py` (ez a jelentés generátora)
- `diagnostics/2026-11-10-phase3-measurement/riportprompt-sablon-v1.md` (prompt, nem futtatva)
- `diagnostics/2026-11-10-phase3-measurement/results/pilot-smallest-8.json`
- `diagnostics/2026-11-10-phase3-measurement/results/pilot-median-205.json`
- `diagnostics/2026-11-10-phase3-measurement/results/pilot-largest-3.json`
- `diagnostics/2026-11-10-phase3-measurement/results/pilot-manifest.json` (hash-ek)
- `docs/week4-reportbemenet-meres.json` (teljes, közösségenkénti mérési adat)
- `docs/week4-reportbemenet-meres.md` (ez a dokumentum)

## Ami nem állapítható meg / megjegyzés

- **Tokenszámlálás**: minden tokenszám karakter/4 felfelé kerekített becslés. Egy korábbi, ezt a lépést megelőző ellenőrzés véletlenül letöltötte a tiktoken o200k_base BPE-fájlját (hálózati hívással) -- emiatt, az utasítás szellemének megfelelően, ebben a mérésben sehol nem használtam tiktoken-eredményt, mindenhol a becslés szerepel.
- A modellhívással kapott tényleges usage (bemeneti/kimeneti tokenszám) és a generálási idő ismeretlen -- nincs modellhívás ebben a fázisban, és ezt sehol nem helyettesítettem kitalált vagy nullázott értékkel.
- A 24 000 tokenes keretet 4 közösség lépi túl, legfeljebb kb. 0,2%-kal (pl. a legnagyobbak JSON-tömbjeiben az elemek közötti vesszők száma nem volt külön betervezve a keretszámításba, csak az egyes elemek saját mérete) -- ez a becslés pontosságán belüli eltérés, nem tartalmi hiba, és nem indokolja a megoldás további bővítését.
- A bemenet-összeállítási szabályok (keretfelosztás node és domain-kapcsolat között, a domain-kapcsolatok rendezési prioritása) ebben a mérésben konkrét, dokumentált alapértelmezés szerint lettek megvalósítva (50/50 keretmegosztás a vázon felüli maradék tokenen; a domain-kapcsolatok prioritása a mögöttes vetületi élsúly, majd a stabil rel_key) -- ezek javasolt (PROPOSED) döntések, nem az eredeti instrukcióból egyértelműen levezethető egyetlen helyes megoldás.
