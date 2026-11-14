# Golden set v1 — jóváhagyási jegyzet

## Állapot

Jóváhagyásra kész munkaváltozat, nem lefagyasztott mérce. Nincs keresőfuttatás,
modellhívás vagy rendszerkimenet alapján történő kérdéshangolás.
A 13 eredeti kérdésszöveg változatlan; Q14–Q15 új, held-out jelölt.
A kritériumok angolul szerepelnek, az elvárt tartalmat írják le, nem keresőszavakat.

## Tartalom

- 15 kérdés: 5 simple, 5 multi-hop, 5 global.
- 43 válaszértékelési kritérium, ebből 42 kötelező és egy opcionális.
- 34 egyedi, létező forráschunk; kitöltött bizonyítékcsoportok és korpuszhash.
- A bizonyítékjegyzék a használt chunkok teljes szövegét tartalmazza.

## Jóváhagyandó javaslatok — egyben eldönthetők

1. Q07: az egy pontos különbség kötelező, az azonos pontszám is kötelező;
   a 2./3. helyezés külön kiírása nem szükséges. Ez a korábbi értékelés irányát követi.
2. Q12: évtizedenként a pilóták helyes és teljes felsorolása kötelező,
   pontos bajnoki évlista nem. A korpusz Verstappennél 2021–2024-et mond;
   a régi nyitott „2021–” alakot nem értelmezzük későbbi címek ígéreteként.
3. Q13: két magyarázó téma kötelező: technikai versenyképesség és hatékony
   pilóta/technikai csapat együttműködés. Konkrét, magyarázathoz kapcsolt példa
   kell mindhárom megnevezett csapatra. Nem három azonos ok bizonyítását kérjük
   mindhárom csapatnál. Szabályváltozáshoz alkalmazkodás opcionális, erőforrás-
   és költségállítást nem követelünk bizonyíték nélkül. A szöveg megfogalmazása szabad.
4. Q14: What name did Sebastian Vettel give his Ferrari SF15-T in 2015?
   Gold: Eva. Forrás: driver-sebastian-vettel#54.
5. Q15: In which year was Renault's young driver academy rebranded as the Alpine Academy?
   Gold: 2021. Forrás: team-renault-in-formula-one#69.

## Bizonyítékcsoportok értelmezése

Az `any_of_chunk_ids` egyetlen csoportján belül a felsorolt chunkok alternatívák.
A szükséges csoportok között ÉS-kapcsolat van. Az alternatív forráslista nem
kimerítő: más chunk is tartalmazhat helyes bizonyítékot, ezért az azonosítóalapú
mérés csak az előre azonosított bizonyítékok lefedettsége.

A `required=false` kritériumhoz tartozó csoportot nem számítjuk a kötelező
lefedettség nevezőjébe. A szigorú találat minden kötelező bizonyítékcsoport
lefedését jelenti; a válaszkritériumok és csoportok száma nem mindig azonos.

Q05-nél egy külön `role=retrieval_bridge`, `criterion=null` csoport jelöli a
2012-es bajnok azonosítását. Ez a kötelező retrieval-lefedettség része, de
nem kötelező kiírni a rövid válaszban Vettel nevét, ha a célcsapat és év helyes.
Ez a sémának egy dokumentált minimális bővítése; másutt nincs külön bridge mező.
A bíró `expected_content` listájának elemei szemantikai támpontok, nem minden
szó szerinti név megismétlését kötelezővé tevő stringteszt.

Q07 Hamilton #12 a megelőző #11 szövegének folytatása. A forrásidézetet a
chunkhatár ismeretében értelmezzük; az azonosítóegyezés önmagában itt sem
igazolja a teljes bizonyítékszöveg modellhez jutását. A több chunkot átfogó
alternatív bizonyítások teljes felsorolását nem építettük meg.

Q13 csoportjai illusztratív források. A chunkazonosító-egyezés nem ellenőrzi,
hogy a válasz valóban értelmes magyarázatot ad-e; ez a rubrikabíró feladata.

## Korlátok, amelyeket nem javítunk kérdésátírással

- Q04 és Q08 teljes válasza egyetlen chunkban szerepel; a multi-hop címke eredeti.
- Q09 és Q11 közvetlen rekordállítással megválaszolható; a global címke eredeti.
- Q06-hoz a Main constructors táblázatot nem használjuk bajnoki csapatok bizonyítékaként.
- Q10 a korpusz tíz pilótájából hatot kér, nem minden történelmi Ferrari-pilótát.
- Q12 a bajnoki évtizedek szerinti tagságot kéri; egy pilóta több csoportba is kerülhet.
- A korpusz állításait mérjük, nem a tényleges mai F1-adatok aktualitását.
- A két új kérdés csak simple típusú, nem reprezentatív független teszt.
- A 13 régi tétel fejlesztési készlet; a korábbi válaszokat nem emeljük át.

## Következő lépés

A fenti öt javaslat jóváhagyása vagy célzott módosítása után a fájl verziója v1
lesz, és végleges fájlnéven kerül mentésre. Addig nem mérünk vele. A framework,
a bíróprompt teljes szövege, a telepítés és a költségkeret külön B-előkészítési
feladat; ez a csomag ezekre nem ad engedélyt.
