# Értékelő kérdések — F1 korpusz (Naiv RAG baseline)

13 kérdés, típus szerint címkézve: **3 simple, 5 multi-hop, 5 global**.
Minden kérdésnél van *Indoklás* (miért tartozik az adott típusba), a szükséges
dokumentumok és egy gold (elvárt) válasz a kiértékeléshez.

Típusok:
- **simple** — egyetlen chunkból megválaszolható ténykérdés (kontrollcsoport).
- **multi-hop** — a válaszhoz legalább két *külön dokumentum* kell.
- **global** — a válasz a korpusz egészének / nagy részének aggregálásából jön.

> A kérdéseket a pipeline futtatása előtt rögzítettem; a baseline válaszokat
> nem javítom utólag.

---

## simple

### Q01 — simple
**Kérdés:** How many World Drivers' Championships has Lewis Hamilton won?
**Indoklás:** Egyetlen tény, a Hamilton-dokumentum bevezetőjében szerepel.
**Dokumentum(ok):** `driver-lewis-hamilton`
**Gold:** 7 (hét), Michael Schumacherrel holtversenyben rekord.

### Q02 — simple
**Kérdés:** How old was Sebastian Vettel when he became the youngest Formula One World Champion?
**Indoklás:** Egyetlen mondatból kiolvasható tény (a bajnoklista-dokumentum rekordokat összegző bekezdése).
**Dokumentum(ok):** `reference-list-of-formula-one-world-drivers-champions` (és `driver-sebastian-vettel`)
**Gold:** 23 éves (23 év 134 nap), 2010-ben.

### Q03 — simple
**Kérdés:** Who won the 2021 Formula One World Drivers' Championship?
**Indoklás:** A 2021-es szezon-dokumentum egyik mondata közvetlenül megadja.
**Dokumentum(ok):** `season-2021-formula-one-world-championship`
**Gold:** Max Verstappen (Red Bull Racing).

---

## multi-hop

### Q04 — multi-hop
**Kérdés:** Who was the teammate of the 2016 World Drivers' Champion at his team that season?
**Indoklás:** Két lépés két dokumentumon át: a szezon-dokumentum adja a bajnokot (Rosberg), a Rosberg-/Mercedes-dokumentum a csapattársat. Egyik dokumentum sem tartalmazza a teljes láncot.
**Dokumentum(ok):** `season-2016-formula-one-world-championship` + `driver-nico-rosberg` / `team-mercedes-benz-in-formula-one`
**Gold:** A bajnok Nico Rosberg; csapattársa a Mercedesnél Lewis Hamilton.

### Q05 — multi-hop
**Kérdés:** Which team did the 2012 World Drivers' Champion leave his team for, and in which year did the move take effect?
**Indoklás:** A 2012-es szezon-dokumentum adja a bajnokot (Vettel, Red Bull), a Vettel-dokumentum a későbbi csapatváltást. A kérdés megválaszolásához a két dokumentumot össze kell kötni a bajnok személyén keresztül.
**Dokumentum(ok):** `season-2012-formula-one-world-championship` + `driver-sebastian-vettel`
**Gold:** Sebastian Vettel a Red Bulltól a Ferrarihoz igazolt, a váltás a 2015-ös szezonra lépett életbe.

### Q06 — multi-hop
**Kérdés:** Which two drivers in the corpus hold the record of seven World Championships, and with which teams did each of them win their titles?
**Indoklás:** A rekordtartók neve a bajnoklistából/bevezetőkből jön, a csapatok a két külön pilóta-dokumentumból; két pilóta-dokumentum összevetése kell.
**Dokumentum(ok):** `driver-michael-schumacher` + `driver-lewis-hamilton`
**Gold:** Schumacher: Benetton (1994, 1995) és Ferrari (2000–2004); Hamilton: McLaren (2008) és Mercedes (2014–15, 2017–20).

### Q07 — multi-hop
**Kérdés:** Fernando Alonso and Lewis Hamilton were teammates once. At which team and in which season, and what was the outcome of that season's championship?
**Indoklás:** A közös csapat és szezon az Alonso- és a Hamilton-dokumentumból együtt áll össze, a végeredmény a két dokumentum 2007-es szakaszának összevetéséből.
**Dokumentum(ok):** `driver-fernando-alonso` + `driver-lewis-hamilton`
**Gold:** McLaren, 2007; a bajnok Kimi Räikkönen lett, Hamilton és Alonso azonos pontszámmal, egy ponttal lemaradva végzett mögötte.

### Q08 — multi-hop
**Kérdés:** Which driver replaced Nico Rosberg at Mercedes after his retirement, and which team did that driver come from?
**Indoklás:** Az utód kiléte a Rosberg-/Mercedes-dokumentumból derül ki, az előző csapata viszont a Bottas-dokumentumból.
**Dokumentum(ok):** `driver-nico-rosberg` / `team-mercedes-benz-in-formula-one` + `driver-valtteri-bottas`
**Gold:** Valtteri Bottas, aki a Williamstől érkezett.

---

## global

### Q09 — global
**Kérdés:** Across all the drivers covered in this corpus, who has won the most World Drivers' Championships, and how many?
**Indoklás:** Mind a 10 pilóta-dokumentumot át kell nézni és a címek számát összehasonlítani; egyetlen chunk nem adja meg a választ.
**Dokumentum(ok):** az összes `driver-*` dokumentum (+ xlsx összefoglaló)
**Gold:** Lewis Hamilton és Michael Schumacher, egyaránt 7 címmel (holtverseny).

### Q10 — global
**Kérdés:** Which drivers in this corpus have driven for Scuderia Ferrari at some point in their career?
**Indoklás:** Végig kell nézni az összes pilóta-dokumentumot, és gyűjteni, akik valaha Ferrarit vezettek; a válasz teljessége a korpusz nagy részének lefedésén múlik.
**Dokumentum(ok):** az összes `driver-*` dokumentum + `team-scuderia-ferrari`
**Gold:** Michael Schumacher, Kimi Räikkönen, Fernando Alonso, Sebastian Vettel, Charles Leclerc, Lewis Hamilton (6).

### Q11 — global
**Kérdés:** Which constructor has won the most Drivers' Championships according to the documents, and how many titles is that?
**Indoklás:** Az összesítés a bajnoklista-dokumentum rekord-bekezdéséből jön, de az állítás ellenőrzéséhez a csapat-dokumentumokat is össze kellene vetni; aggregáló kérdés.
**Dokumentum(ok):** `reference-list-of-formula-one-world-drivers-champions` + a `team-*` dokumentumok
**Gold:** Scuderia Ferrari, 15 pilóta-bajnoki cím (a McLaren 13-mal követi).

### Q12 — global
**Kérdés:** Group the World Champions among the corpus drivers by decade (2000s, 2010s, 2020s).
**Indoklás:** Minden pilóta bajnoki évét ki kell gyűjteni, majd évtizedekbe rendezni; a válasz a pilóta- és szezon-dokumentumok együttesére épül.
**Dokumentum(ok):** az összes `driver-*` + `season-*` dokumentum
**Gold:** 2000s: Schumacher (2000–04), Alonso (2005–06), Räikkönen (2007), Hamilton (2008), Button (2009); 2010s: Vettel (2010–13), Hamilton (2014–15, 2017–19), Rosberg (2016); 2020s: Hamilton (2020), Verstappen (2021–).

### Q13 — global
**Kérdés:** What common factors explain why specific teams such as Ferrari, Mercedes and Red Bull dominated particular eras of Formula One?
**Indoklás:** Szintézis- és trendkérdés: a válasz a csapat- és szezon-dokumentumok sok pontján szétszórt tényezők összegzése, nincs egyetlen konkrét chunk, ami megválaszolja.
**Dokumentum(ok):** `team-*` + `season-*` + `reference-formula-one`
**Gold:** Nyitott kérdés — pl. szabályozási korszakváltások (motorformula), domináns pilóta–csapat párosok, technikai fölény és erőforrások. A naiv RAG-tól itt töredékes választ várunk.
