# Week 6 — DRIFT mérési jelentés (full)

## Elemszámok
- összes eset: 15
- válasz mentve: 15
- helyességi kritérium pontozva: 15
- faithfulness pontozva: 15
- retrieval nem visszavezethető (untraceable, nem nulla): 0

## DRIFT × kérdéstípus (a 3-mód táblába illeszthető formátum, egy oszloppal)

| Kérdéstípus | drift |
|---|---|
| simple | n=5<br>elutasított=3, helyes=2<br>retrieval_avg=0.20<br>faithfulness_avg=0.50 |
| multi-hop | n=5<br>helyes=1, hiányos=3, téves=1<br>retrieval_avg=0.04<br>faithfulness_avg=1.00 |
| global | n=5<br>hiányos=5<br>retrieval_avg=0.27<br>faithfulness_avg=1.00 |

## frozen_w4 / held_out bontás

| frozen_w4 / held_out | drift |
|---|---|
| frozen_w4 | n=13<br>elutasított=1, helyes=3, hiányos=8, téves=1<br>retrieval_avg=0.20<br>faithfulness_avg=0.92 |
| held_out | n=2<br>elutasított=2<br>retrieval_avg=0.00 |

## Költség és késleltetés -- ennek a futásnak (full) a fogyasztása, a másik run_phase fogyasztását NEM tartalmazza
- teljes (generálás + mindkét bíró ismert) költségű esetek: 15 / 15
- ismert teljes költség összege (full): 0.056394
- hiányzó költségű esetek: 0 (a keretnyilvántartás ilyenkor becsléssel számol, nem nulla fogyasztással)
- átlagos futásidő (s): 11.389

- riportindex-embedding költsége (EGYSZERI, nem kérdéstípusonkénti sor): 0.000137 USD, 37 riport, forrás: diagnostics\2026-11-14-week6-drift\results\week6-cost-ledger.json
- kumulatív week6 ledger-fogyasztás (indexépítés + smoke + full együtt, folytatások között is összegződik): 0.07319623999999995 USD
- kumulatív hátralévő keret: 0.42680376000000003 USD (ez csak az eddigi fogyasztást ellenőrzi az adott hívás előtt -- nem garantálja, hogy a teljes futás végig a kereten belül marad, mert az upper-bound becslés a válasz megérkezése előtt történik)

## Retrieval-proxy a riportforrásokból (jelölt, nem ellenőrzött bizonyíték)
- esetek jelölt riport-chunk kapcsolattal: 15 / 15
- átlagos jelölt chunk-szám esetenként: 168.47
Ez a mutató a primer által kiválasztott riportok key_statements.candidate_source_chunk_ids kapcsolataiból képzett arány -- jelölt/proxy, nem a local_search által ténylegesen visszahozott és citált chunk. A fenti DRIFT × kérdéstípus táblában szereplő `retrieval_avg` kizárólag a lokális keresésben ténylegesen visszahozott chunkokból számol, a kettő nem keverendő össze.

## Megjegyzés a primer/lokális résztől a tényszerűségig
A primer riport-alapú kezdeti válasza és egy-egy lokális részválasz önmagában nem igazolja a végső szintézis minden állításának tényszerűségét -- a faithfulness-bíró a szintézisnek ténylegesen átadott, már korlátozott (`actual_context`, a `synthesis_context_truncation` szerint esetleg levágott) kontextust kapja, nem a levágás előtti teljes riport- és lokális anyagot.