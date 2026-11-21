# Week 5 B — mérési jelentés (pair-j2-full)

## Elemszámok
- összes eset: 15
- válasz mentve: 15
- helyességi kritérium pontozva: 15
- faithfulness pontozva: 15
- retrieval nem visszavezethető (untraceable, nem nulla): 0
- retrieval proxy (globális): 0

## Három mód × kérdéstípus

| Kérdéstípus | naiv | lokalis | globalis |
|---|---|---|---|
| simple | n=5<br>helyes=5<br>retrieval_avg=0.80<br>faithfulness_avg=1.00 | n/a (0 eset) | n/a (0 eset) |
| multi-hop | n=5<br>helyes=2, hiányos=3<br>retrieval_avg=0.27<br>faithfulness_avg=1.00 | n/a (0 eset) | n/a (0 eset) |
| global | n=5<br>elutasított=1, helyes=2, hiányos=2<br>retrieval_avg=0.08<br>faithfulness_avg=0.75 | n/a (0 eset) | n/a (0 eset) |

## frozen_w4 / held_out bontás

| frozen_w4 / held_out | naiv | lokalis | globalis |
|---|---|---|---|
| frozen_w4 | n=13<br>elutasított=1, helyes=7, hiányos=5<br>retrieval_avg=0.29<br>faithfulness_avg=0.92 | n/a (0 eset) | n/a (0 eset) |
| held_out | n=2<br>helyes=2<br>retrieval_avg=1.00<br>faithfulness_avg=1.00 | n/a (0 eset) | n/a (0 eset) |

## Költség és késleltetés
- teljes (mindhárom szakasz ismert) költségű esetek: 15 / 15
- ismert teljes költség összege: 0.009569
- hiányzó költségű esetek: 0 (a keretnyilvántartás ilyenkor becsléssel számol, nem nulla fogyasztással)
- átlagos futásidő (s): 2.131

A részleges (nem mindhárom szakaszra ismert) költség nem szerepel teljes esetköltségként -- a lenti bontás külön jelzi.

### Módonként

| | teljes költségű esetek | ismert összeg (USD) | részleges | ismeretlen |
|---|---|---|---|---|
| naiv | 15 / 15 | 0.009569 | 0 | 0 |
| lokalis | 0 / 0 | None | 0 | 0 |
| globalis | 0 / 0 | None | 0 | 0 |

### Kérdéstípusonként

| | teljes költségű esetek | ismert összeg (USD) | részleges | ismeretlen |
|---|---|---|---|---|
| simple | 5 / 5 | 0.002594 | 0 | 0 |
| multi-hop | 5 / 5 | 0.00342 | 0 | 0 |
| global | 5 / 5 | 0.003555 | 0 | 0 |

## Megjegyzés a proxy/n-a jelölésekről
A globális mód `retrieval_proxy_avg` értéke a reduce-nak ténylegesen átadott részválaszok candidate_source_chunk_ids kapcsolataiból képzett arány, nem valódi, soronként ellenőrzött bizonyíték-lefedettség -- nem átlagolható össze a naiv/lokalis `retrieval_avg` értékekkel.