# 7–8. hét — végső mérési összefoglaló

Ez a dokumentum a már mentett eredményeket rendezi. Új mérés nem
készült. A week4 kézi 13 kérdéses értékelés, az 5. heti bírált 15
kérdéses FULL, a DRIFT v2 FULL, a J2/J3 naiv párok és az 5 kérdéses
M3 abláció külön sor. Eltérő mutató vagy nevező nincs összeadva.
Az n/a és a hiányzó költség nem 0. A ledgerösszegek nincsenek a
részfutásokhoz hozzáadva.

## Végső mérési táblázat

### A. Bírált golden set, 15 kérdés

Forrás: `diagnostics/2026-11-11-week5-b/results/week5-b-report-full.md`
és `diagnostics/2026-11-14-week6-drift/results/week6-drift-report-v2-full.md`.
A helyes/15 összesítés a `docs/week6-eredmenyek.md` 121. sora. A
globális retrieval proxy, nem a naiv vagy lokális `retrieval_avg`.
A DRIFT simple faithfulness-átlaga 0,50 a dokumentáltan értékelhető
2 esetre vonatkozik, nem mind az 5-re (`docs/week6-eredmenyek.md`,
70. sor).

| Futás | n | Correctness | Faithfulness | Retrieval | Költség (USD) | Futásidő |
|---|---:|---|---|---|---|---|
| week5 naiv FULL | 15 | helyes 9, hiányos 4, elutasított 2 | típusonként 1,00 | retrieval_avg 0,80 / 0,27 / 0,08 | ismert 0,00842, 13/15 eset; 2 ismeretlen | a három mód közös átlaga 23,948 s, módonként nincs |
| week5 lokális FULL | 15 | helyes 7, hiányos 4, elutasított 4 | 1,00 / 0,81 / 1,00 | retrieval_avg 0,60 / 0,48 / 0,05 | ismert 0,026113, 13/15; 2 ismeretlen | ugyanaz a közös átlag |
| week5 globális FULL | 15 | helyes 2, hiányos 9, elutasított 4 | típusonként 1,00 | proxy 0,20 / 0,24 / 0,30 | ismert 0,044536, 13/15; 1 részleges, 1 ismeretlen | ugyanaz a közös átlag |
| DRIFT v2 FULL | 15 | helyes 3, hiányos 8, elutasított 3, téves 1 | 0,50 (n=2) / 1,00 / 1,00 | retrieval_avg 0,20 / 0,04 / 0,27 | 0,056394, 15/15 ismert | 11,389 s |

A week5 ismert költségeinek összege a riportban 0,079069 USD, 39/45
teljes költségű eset. Ez nem a három mód teljes költsége, mert 6 eset
költsége hiányzik.

### B. Kézi week4-értékelés, 13 kérdés

Forrás: `docs/week4-osszehasonlitas-es-ertekeles.md`, 45–57. sor.
Ugyanaz a 13 válasz, más módszer: a projektgazda kézi címkéje, nem a
week5 bíró. Faithfulness, retrieval, költség és futásidő ebben a
dokumentumban nincs. A Q13 globális címkéje a választott besorolás
szerint hiányos.

| Mód | n | helyes | hiányos | téves | elutasított |
|---|---:|---:|---:|---:|---:|
| Naiv | 13 | 7 | 2 | 2 | 2 |
| Lokális | 13 | 6 | 3 | 1 | 3 |
| Globális | 13 | 1 | 5 | 2 | 5 |

### C. Későbbi naiv golden-set párok, 15 kérdés

Ezek nem a week5 before. Forrás: `docs/week78-javitasok.md`.
Artifact: `diagnostics/2026-11-21-week78-j2-naive-measure/results/`.

| Futás | n | Correctness | Faithfulness | Retrieval | Költség | Generálási latency |
|---|---:|---|---|---|---|---|
| J2 before, `pair-baseline-full` | 15 | 9 / 4 / 2 / 0 | 1,0; n=13; n/a Q04, Q13 | ratio 0,3822; hit 9; strict 5 | 0,009516 | 2,049 s |
| J2, `pair-j2-full` | 15 | 9 / 5 / 1 / 0 | 0,9286; n=14; n/a Q13; Q12: 1,0→0,0 | azonos | 0,009566 | 2,131 s |
| J3 before, `j3cmp-baseline` | 15 | 9 / 4 / 2 / 0 | 1,0; n=13; n/a Q04, Q13 | azonos | 0,009681 | 2,022 s |
| J3, `j3cmp-j3` | 15 | 9 / 4 / 2 / 0, címkék változatlanok | 1,0; n=13; n/a változatlan | azonos | 0,009662 | 2,138 s |

A correctness sorrendje helyes, hiányos, elutasított, téves. A J2 és
J3 párok költsége a futások saját könyvelt költsége. A közös
`j2-pair-cost-ledger.json` későbbi 0,039235 USD összege ezeken felül
pilotokat is tartalmaz, ezért nincs a sorokhoz hozzáadva.

### D. M3 abláció, 5 kérdés

Nem golden-set mérés. Kérdések: Q01, Q07, Q09, Q10, Q11. Forrás:
`docs/week6-eredmenyek.md`, M3 szakasz. Artifact:
`diagnostics/2026-11-14-week6-drift/results/m3-followup-usagefix-on/`
és `m3-followup-usagefix-off/`.

| Ág | n | Címkék | Faithfulness | Retrieval | Költség | Átlagos futásidő |
|---|---:|---|---|---|---|---|
| ON, `m3-followup-usagefix-on` | 5 | helyes 1, hiányos 4 | 1,0 mind az ötnél | scored: 1,0; 0,0; 1,0; 0,1667; 0,0 | 0,018511 | 15,669 s |
| OFF, `m3-followup-usagefix-off` | 5 | elutasított 4, hiányos 1 | 1,0 / 1,0 / 1,0 / n/a / n/a | mind `not_applicable`, ratio null | 0,002659 | 3,272 s |

Az OFF retrieval nincs retrieval-átlagban. A `m3-followup-on` előzmény
nem része a párnak. A week6 ledger 0,115482 USD a pár utáni kumulatív
fogyasztás, nem az ON+OFF összeg újabb hozzáadása.

## Összefoglaló

A korpusz 23 dokumentum, 1651 chunk, 1200 karakter és 100 karakter
átfedés (`docs/extrakcio-es-lokalis-kereses.md`). Az extrakció
`graph/corpus/extraction-reuse-1200-23`: 1651 strukturálisan sikeres
rekord, 0 hibás, 315 üres. A strukturális siker nem szemantikai
helyesség. Megnevezett, javítatlan hiba a `driver-sebastian-vettel#21`
címsorból készült Title entitás. A legnagyobb fokszám szerkezeti szám,
nem fontossági bizonyíték. Inkrementális dokumentumfrissítés nincs.

A rendszer a spektrum közepén áll. A naiv ág a 1651 chunk vektorindexe.
A lokális ág az összevont gráf és az entitásindex. A globális ág a 37
közösségi riport. A DRIFT ezekből egy korlátozott kör: top-3 riport,
primer, legfeljebb két lokális keresés, egy szintézis. Nem a Microsoft
DRIFT teljes implementációja.

Összevethető bírált mintán a naiv ág adta a legtöbb helyes választ:
9/15, a lokális 7/15, a DRIFT 3/15, a globális 2/15. A kézi 13 kérdéses
értékelés ugyanezt a sorrendet mutatja a helyes válaszok számában,
de más módszer, ezért a két táblázat nincs összeadva. Kérdésenként
van lokális nyereség is: a week4 kézi táblában a Q04 és a Q07 lokálisan
jobb, mint naivan. A DRIFT v2 a Q07, Q09, Q10 és Q11 célkérdéseken
helyességi kategóriában nem javított a mentett összevetés szerint.

Az M2 lezárt. A J1 egy közösségi riport pilotja, 0,003125 USD, sikertelen;
nem teljes golden-set mérés, és a 37 riportos J1 generálás nem futott.
A J2 Q04 pilot sikertelen összetett pilot. A J2 FULL vegyes: a helyes
válaszok száma 9 maradt, a Q12 faithfulness 1,0-ról 0,0-ra esett. A J3
Q07 pilot és a J3 FULL sem igazolt javulást; a FULL-ban egy kritérium
veszett el, faithfulness-romlás nem volt. Egyik J-ág sem alapértelmezett.

Az M3 előzetes jóslata: Q01 nem teljesült, Q07 teljesült, Q09 teljesült,
Q11 nem teljesült, Q10-re nem volt jóslat. Az ON ágon a címkék jobbak
vagy azonosak. Az OFF olcsóbb és gyorsabb, de négy címke elutasítottra
romlott. Az ON marad az alapértelmezett. Új DRIFT-verzió nincs.

Az M4 nem teljes. A futás és a riport kapcsolata a
`quality-report-section-1200-23.md` fejléce, nem hash. A deduplikációs
pár csak ennek a riportnak a `before`/`after` mezője: 10782→2761
csomópont, 6533→4326 él, komponens 30→1896. A 4325 él külön, memóriabeli
önhurok-szűrt érték. Van konkrét élpélda: `Driver:jenson button`
`TEAMMATE_OF` `Driver:nico rosberg`, forrás
`driver-jenson-button_31.json`, chunk `driver-jenson-button#31`,
dokumentum `driver-jenson-button`. A teljes él-lefedettség nem igazolt.
A 23 dokumentumos betöltés történeti parancsa és naplója hiányzik.

Az egyszeri építésből a 37 közösségi riport mért költsége 0,0537 USD
(`docs/week4-kozossegi-riportok-v3.md`). A v1 és v2 riportpilot külön
sor, 0,0064 és 0,0032 USD. A riportindex-embedding 0,000137 USD becsült,
nem mért usage. A 23 dokumentumos extrakció költsége ebben a
összefoglalóban nem volt külön mentett tételként igazolható. A
lekérdezés és a bírók költsége a táblázatsorokban van; a week5 sorok
hiányosak, a DRIFT v2 full és az M3 pár teljes. A két ledger kumulatív,
több futást tartalmaz, és nincs újra összeadva.

A következő munka, végrehajtás nélkül: először a 23 dokumentumos
betöltés naplójának és a teljes él-provenance lefedettségnek a pótlása
a meglévő gráf újraépítése nélkül, ha a mentett backup ehhez a
verzióhoz köthető. Utána a hiányzó week5 költségsorok tisztázása a már
mentett ledgerből, új hívás nélkül. A lezárt J-ágak és az M3 OFF ág
nem kerülnek újrahangolásra. Inkrementális korpuszfrissítés csak külön
döntés után mérhető.
