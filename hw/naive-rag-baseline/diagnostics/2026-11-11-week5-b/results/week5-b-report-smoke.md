# Week 5 B — mérési jelentés (smoke)

## Elemszámok
- összes eset: 9
- válasz mentve: 9
- helyességi kritérium pontozva: 9
- faithfulness pontozva: 9
- retrieval nem visszavezethető (untraceable, nem nulla): 0
- retrieval proxy (globális): 3

## Három mód × kérdéstípus

| Kérdéstípus | naiv | lokalis | globalis |
|---|---|---|---|
| simple | n=1<br>helyes=1<br>retrieval_avg=1.00<br>faithfulness_avg=1.00 | n=1<br>helyes=1<br>retrieval_avg=1.00<br>faithfulness_avg=1.00 | n=1<br>helyes=1<br>retrieval_proxy_avg=1.00 (proxy, n/a valódi lefedettség)<br>faithfulness_avg=1.00 |
| multi-hop | n=1<br>hiányos=1<br>retrieval_avg=0.33<br>faithfulness_avg=1.00 | n=1<br>helyes=1<br>retrieval_avg=0.00<br>faithfulness_avg=0.20 | n=1<br>elutasított=1<br>retrieval_proxy_avg=0.00 (proxy, n/a valódi lefedettség) |
| global | n=1<br>helyes=1<br>retrieval_avg=0.00<br>faithfulness_avg=1.00 | n=1<br>hiányos=1<br>retrieval_avg=0.00<br>faithfulness_avg=1.00 | n=1<br>hiányos=1<br>retrieval_proxy_avg=0.00 (proxy, n/a valódi lefedettség) |

## frozen_w4 / held_out bontás

| frozen_w4 / held_out | naiv | lokalis | globalis |
|---|---|---|---|
| frozen_w4 | n=3<br>helyes=2, hiányos=1<br>retrieval_avg=0.44<br>faithfulness_avg=1.00 | n=3<br>helyes=2, hiányos=1<br>retrieval_avg=0.33<br>faithfulness_avg=0.73 | n=3<br>elutasított=1, helyes=1, hiányos=1<br>retrieval_proxy_avg=0.33 (proxy, n/a valódi lefedettség)<br>faithfulness_avg=1.00 |
| held_out | n/a (0 eset) | n/a (0 eset) | n/a (0 eset) |

## Költség és késleltetés
- ismert költségű esetek: 0 / 9
- ismert költség összege: None
- hiányzó költségű esetek: 9 (a keretnyilvántartás ilyenkor becsléssel számol, nem nulla fogyasztással)
- átlagos futásidő (s): 24.773

## Megjegyzés a proxy/n-a jelölésekről
A globális mód `retrieval_proxy_avg` értéke a reduce-nak ténylegesen átadott részválaszok candidate_source_chunk_ids kapcsolataiból képzett arány, nem valódi, soronként ellenőrzött bizonyíték-lefedettség -- nem átlagolható össze a naiv/lokalis `retrieval_avg` értékekkel.