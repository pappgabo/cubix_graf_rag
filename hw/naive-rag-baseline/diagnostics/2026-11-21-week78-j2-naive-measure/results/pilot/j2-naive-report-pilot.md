# Week 5 B — mérési jelentés (pilot)

## Elemszámok
- összes eset: 1
- válasz mentve: 1
- helyességi kritérium pontozva: 1
- faithfulness pontozva: 1
- retrieval nem visszavezethető (untraceable, nem nulla): 0
- retrieval proxy (globális): 0

## Három mód × kérdéstípus

| Kérdéstípus | naiv | lokalis | globalis |
|---|---|---|---|
| simple | n/a (0 eset) | n/a (0 eset) | n/a (0 eset) |
| multi-hop | n=1<br>helyes=1<br>retrieval_avg=0.00<br>faithfulness_avg=1.00 | n/a (0 eset) | n/a (0 eset) |
| global | n/a (0 eset) | n/a (0 eset) | n/a (0 eset) |

## frozen_w4 / held_out bontás

| frozen_w4 / held_out | naiv | lokalis | globalis |
|---|---|---|---|
| frozen_w4 | n=1<br>helyes=1<br>retrieval_avg=0.00<br>faithfulness_avg=1.00 | n/a (0 eset) | n/a (0 eset) |
| held_out | n/a (0 eset) | n/a (0 eset) | n/a (0 eset) |

## Költség és késleltetés
- teljes (mindhárom szakasz ismert) költségű esetek: 1 / 1
- ismert teljes költség összege: 0.000646
- hiányzó költségű esetek: 0 (a keretnyilvántartás ilyenkor becsléssel számol, nem nulla fogyasztással)
- átlagos futásidő (s): 6.625

A részleges (nem mindhárom szakaszra ismert) költség nem szerepel teljes esetköltségként -- a lenti bontás külön jelzi.

### Módonként

| | teljes költségű esetek | ismert összeg (USD) | részleges | ismeretlen |
|---|---|---|---|---|
| naiv | 1 / 1 | 0.000646 | 0 | 0 |
| lokalis | 0 / 0 | None | 0 | 0 |
| globalis | 0 / 0 | None | 0 | 0 |

### Kérdéstípusonként

| | teljes költségű esetek | ismert összeg (USD) | részleges | ismeretlen |
|---|---|---|---|---|
| simple | 0 / 0 | None | 0 | 0 |
| multi-hop | 1 / 1 | 0.000646 | 0 | 0 |
| global | 0 / 0 | None | 0 | 0 |

## Megjegyzés a proxy/n-a jelölésekről
A globális mód `retrieval_proxy_avg` értéke a reduce-nak ténylegesen átadott részválaszok candidate_source_chunk_ids kapcsolataiból képzett arány, nem valódi, soronként ellenőrzött bizonyíték-lefedettség -- nem átlagolható össze a naiv/lokalis `retrieval_avg` értékekkel.