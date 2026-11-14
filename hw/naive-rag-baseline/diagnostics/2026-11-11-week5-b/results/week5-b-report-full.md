# Week 5 B — mérési jelentés (full)

## Elemszámok
- összes eset: 45
- válasz mentve: 45
- helyességi kritérium pontozva: 45
- faithfulness pontozva: 45
- retrieval nem visszavezethető (untraceable, nem nulla): 0
- retrieval proxy (globális): 15

## Három mód × kérdéstípus

| Kérdéstípus | naiv | lokalis | globalis |
|---|---|---|---|
| simple | n=5<br>helyes=5<br>retrieval_avg=0.80<br>faithfulness_avg=1.00 | n=5<br>elutasított=1, helyes=4<br>retrieval_avg=0.60<br>faithfulness_avg=1.00 | n=5<br>elutasított=3, helyes=1, hiányos=1<br>retrieval_proxy_avg=0.20 (proxy, n/a valódi lefedettség)<br>faithfulness_avg=1.00 |
| multi-hop | n=5<br>elutasított=1, helyes=2, hiányos=2<br>retrieval_avg=0.27<br>faithfulness_avg=1.00 | n=5<br>elutasított=1, helyes=2, hiányos=2<br>retrieval_avg=0.48<br>faithfulness_avg=0.81 | n=5<br>elutasított=1, helyes=1, hiányos=3<br>retrieval_proxy_avg=0.24 (proxy, n/a valódi lefedettség)<br>faithfulness_avg=1.00 |
| global | n=5<br>elutasított=1, helyes=2, hiányos=2<br>retrieval_avg=0.08<br>faithfulness_avg=1.00 | n=5<br>elutasított=2, helyes=1, hiányos=2<br>retrieval_avg=0.05<br>faithfulness_avg=1.00 | n=5<br>hiányos=5<br>retrieval_proxy_avg=0.30 (proxy, n/a valódi lefedettség)<br>faithfulness_avg=1.00 |

## frozen_w4 / held_out bontás

| frozen_w4 / held_out | naiv | lokalis | globalis |
|---|---|---|---|
| frozen_w4 | n=13<br>elutasított=2, helyes=7, hiányos=4<br>retrieval_avg=0.29<br>faithfulness_avg=1.00 | n=13<br>elutasított=3, helyes=6, hiányos=4<br>retrieval_avg=0.36<br>faithfulness_avg=0.93 | n=13<br>elutasított=2, helyes=2, hiányos=9<br>retrieval_proxy_avg=0.28 (proxy, n/a valódi lefedettség)<br>faithfulness_avg=1.00 |
| held_out | n=2<br>helyes=2<br>retrieval_avg=1.00<br>faithfulness_avg=1.00 | n=2<br>elutasított=1, helyes=1<br>retrieval_avg=0.50<br>faithfulness_avg=1.00 | n=2<br>elutasított=2<br>retrieval_proxy_avg=0.00 (proxy, n/a valódi lefedettség) |

## Költség és késleltetés
- teljes (mindhárom szakasz ismert) költségű esetek: 39 / 45
- ismert teljes költség összege: 0.079069
- hiányzó költségű esetek: 6 (a keretnyilvántartás ilyenkor becsléssel számol, nem nulla fogyasztással)
- átlagos futásidő (s): 23.948

A részleges (nem mindhárom szakaszra ismert) költség nem szerepel teljes esetköltségként -- a lenti bontás külön jelzi.

### Módonként

| | teljes költségű esetek | ismert összeg (USD) | részleges | ismeretlen |
|---|---|---|---|---|
| naiv | 13 / 15 | 0.00842 | 0 | 2 |
| lokalis | 13 / 15 | 0.026113 | 0 | 2 |
| globalis | 13 / 15 | 0.044536 | 1 | 1 |

### Kérdéstípusonként

| | teljes költségű esetek | ismert összeg (USD) | részleges | ismeretlen |
|---|---|---|---|---|
| simple | 9 / 15 | 0.018386 | 1 | 5 |
| multi-hop | 15 / 15 | 0.029494 | 0 | 0 |
| global | 15 / 15 | 0.031189 | 0 | 0 |

## Megjegyzés a proxy/n-a jelölésekről
A globális mód `retrieval_proxy_avg` értéke a reduce-nak ténylegesen átadott részválaszok candidate_source_chunk_ids kapcsolataiból képzett arány, nem valódi, soronként ellenőrzött bizonyíték-lefedettség -- nem átlagolható össze a naiv/lokalis `retrieval_avg` értékekkel.