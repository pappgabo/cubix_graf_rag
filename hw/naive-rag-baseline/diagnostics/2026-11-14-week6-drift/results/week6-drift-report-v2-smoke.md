# Week 6 — DRIFT mérési jelentés (smoke)

## Elemszámok
- összes eset: 3
- válasz mentve: 3
- helyességi kritérium pontozva: 3
- faithfulness pontozva: 3
- retrieval nem visszavezethető (untraceable, nem nulla): 0

## DRIFT × kérdéstípus (a 3-mód táblába illeszthető formátum, egy oszloppal)

| Kérdéstípus | drift |
|---|---|
| simple | n=1<br>helyes=1<br>retrieval_avg=1.00<br>faithfulness_avg=1.00 |
| multi-hop | n=1<br>hiányos=1<br>retrieval_avg=0.00<br>faithfulness_avg=1.00 |
| global | n=1<br>hiányos=1<br>retrieval_avg=0.17<br>faithfulness_avg=1.00 |

## frozen_w4 / held_out bontás

| frozen_w4 / held_out | drift |
|---|---|
| frozen_w4 | n=3<br>helyes=1, hiányos=2<br>retrieval_avg=0.39<br>faithfulness_avg=1.00 |
| held_out | n/a (0 eset) |

## Költség és késleltetés -- ennek a futásnak (smoke) a fogyasztása, a másik run_phase fogyasztását NEM tartalmazza
- teljes (generálás + mindkét bíró ismert) költségű esetek: 3 / 3
- ismert teljes költség összege (smoke): 0.011661
- hiányzó költségű esetek: 0 (a keretnyilvántartás ilyenkor becsléssel számol, nem nulla fogyasztással)
- átlagos futásidő (s): 14.219

- riportindex-embedding költsége (EGYSZERI, nem kérdéstípusonkénti sor): 0.000137 USD, 37 riport, forrás: diagnostics\2026-11-14-week6-drift\results\week6-cost-ledger.json
- kumulatív week6 ledger-fogyasztás (indexépítés + smoke + full együtt, folytatások között is összegződik): 0.016798929999999997 USD
- kumulatív hátralévő keret: 0.48320107 USD (ez csak az eddigi fogyasztást ellenőrzi az adott hívás előtt -- nem garantálja, hogy a teljes futás végig a kereten belül marad, mert az upper-bound becslés a válasz megérkezése előtt történik)

## Retrieval-proxy a riportforrásokból (jelölt, nem ellenőrzött bizonyíték)
- esetek jelölt riport-chunk kapcsolattal: 3 / 3
- átlagos jelölt chunk-szám esetenként: 139.67
Ez a mutató a primer által kiválasztott riportok key_statements.candidate_source_chunk_ids kapcsolataiból képzett arány -- jelölt/proxy, nem a local_search által ténylegesen visszahozott és citált chunk. A fenti DRIFT × kérdéstípus táblában szereplő `retrieval_avg` kizárólag a lokális keresésben ténylegesen visszahozott chunkokból számol, a kettő nem keverendő össze.

## Megjegyzés a primer/lokális résztől a tényszerűségig
A primer riport-alapú kezdeti válasza és egy-egy lokális részválasz önmagában nem igazolja a végső szintézis minden állításának tényszerűségét -- a faithfulness-bíró a szintézisnek ténylegesen átadott, már korlátozott (`actual_context`, a `synthesis_context_truncation` szerint esetleg levágott) kontextust kapja, nem a levágás előtti teljes riport- és lokális anyagot.