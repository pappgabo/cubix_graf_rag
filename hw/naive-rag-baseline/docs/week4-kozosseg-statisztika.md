# Közösségstatisztika

A Leiden memóriában futott, a Neo4j és a korpusz JSON változatlan. A csomópont→csoport leképezés a `docs/week4-vetulet-leképezés.json` fájlban van.

## Verziók

Telepítés: `uv add --no-build-package igraph --no-build-package leidenalg "leidenalg==0.12.0"`. Mindkét csomag kész wheelből jött, forrásból nem fordult.

| Csomag | Verzió |
|---|---|
| leidenalg | 0.12.0 |
| igraph | 1.0.0 |
| texttable | 1.7.2 |

A `texttable` az `igraph` függősége. A Windows-wheel az `igraph-1.0.0-cp39-abi3-win_amd64`.

## Leiden-paraméterek

- Partíció: `RBConfigurationVertexPartition`
- `resolution_parameter`: 1.0
- `weights`: az él `weight` attribútuma, értéke az egyedi `source_chunk_ids` uniójának mérete
- `n_iterations`: -1
- `seed`: 42

A hierarchia ugyanezzel a seeddel ismétli a felosztást, amíg egy közösség tovább bomlik. A közösségméret küszöbe nincs rögzítve; a 10, 30 és 100 küszöb csak a jelentési vágás.

## Élösszevonás

A tárolt irányított gráf 4325 él. Önálló hurok a memóriában: 0. Irányítatlan párokra összevonva 4075 él marad; ebben a lépésben 250 párhuzamos irányított él olvad össze, még az aliasok előtt.

Az aliasok 159 kanonikus páron olvasztottak össze párhuzamos élet. Az így elnyelt többletélek száma: 176. A súly ezeken a párokon az egyedi chunk-azonosítók uniója. Alias miatti új önhurok: 0. Kizárt végpont miatt kieső irányítatlan él: 36.

Az előkészített élszám: 4075 − 176 − 36 = 3863.

## Bemenet és kétszeres futás

Mindkét vetület kétszer futott végig a teljes hierarchián. A két felosztás megegyezett.

| Vetület | Csomópont | Él | Izolált | SHA-256 |
|---|---:|---:|---:|---|
| Nyers | 2761 | 4075 | 782 | `3eedfc17cf946c5ef05c33e315ac4ef38adf4f2add3da533930f595acbc28104` |
| Előkészített | 2645 | 3863 | 736 | `938bd16dc7f08268e76de92f01aa8acddc9c4acf1b13ca4ffcbe64250cb3fdb3` |

A hash a rendezett csomópontlistából és a rendezett `forrás, cél, súly` éllistából készült, a fenti paraméterekkel együtt.

Új izolált csúcs az előkészített vetületen: 12.

- `Car:citroën ds3 wrc`
- `Car:gen3 car`
- `Car:mp4-21`
- `Car:porsche 911 gt3r hybrid`
- `GrandPrix:1946 turin grand prix`
- `GrandPrix:2012 belgian grand prix`
- `GrandPrix:goodwood festival of speed`
- `GrandPrix:petit le mans`
- `Team:emil frey racing`
- `Team:ice 1 racing`
- `Team:jaguar racing`
- `Team:lionspeed gp`

## Szintek

### Nyers

| Szint | Közösség | Min | Medián | Max | Méret-1 |
|---:|---:|---:|---:|---:|---:|
| 0 | 827 | 1 | 1 | 207 | 782 |
| 1 | 981 | 1 | 1 | 64 | 782 |
| 2 | 1176 | 1 | 1 | 58 | 782 |
| 3 | 1203 | 1 | 1 | 56 | 782 |

A tíz legnagyobb közösség a 0. szinten:

- `5`: 207 csúcs, legnagyobb fokú tag `Team:mclaren`
- `22`: 159 csúcs, legnagyobb fokú tag `Team:williams racing`
- `3`: 143 csúcs, legnagyobb fokú tag `Season:2021`
- `68`: 137 csúcs, legnagyobb fokú tag `Driver:fernando alonso`
- `4`: 136 csúcs, legnagyobb fokú tag `Team:scuderia ferrari`
- `36`: 121 csúcs, legnagyobb fokú tag `Driver:lewis hamilton`
- `40`: 114 csúcs, legnagyobb fokú tag `GrandPrix:australian grand prix`
- `105`: 107 csúcs, legnagyobb fokú tag `Season:2020`
- `28`: 103 csúcs, legnagyobb fokú tag `Driver:max verstappen`
- `39`: 101 csúcs, legnagyobb fokú tag `Season:2012`

### Előkészített

| Szint | Közösség | Min | Medián | Max | Méret-1 |
|---:|---:|---:|---:|---:|---:|
| 0 | 773 | 1 | 1 | 168 | 736 |
| 1 | 927 | 1 | 1 | 65 | 736 |
| 2 | 1106 | 1 | 1 | 65 | 736 |
| 3 | 1134 | 1 | 1 | 65 | 736 |

A tíz legnagyobb közösség a 0. szinten:

- `3`: 168 csúcs, legnagyobb fokú tag `Season:2021`
- `5`: 159 csúcs, legnagyobb fokú tag `Team:mclaren`
- `22`: 151 csúcs, legnagyobb fokú tag `Team:williams racing`
- `60`: 151 csúcs, legnagyobb fokú tag `Driver:fernando alonso`
- `37`: 133 csúcs, legnagyobb fokú tag `Season:2012`
- `33`: 131 csúcs, legnagyobb fokú tag `Driver:lewis hamilton`
- `4`: 125 csúcs, legnagyobb fokú tag `Team:scuderia ferrari`
- `38`: 117 csúcs, legnagyobb fokú tag `GrandPrix:australian grand prix`
- `15`: 111 csúcs, legnagyobb fokú tag `Driver:max verstappen`
- `111`: 107 csúcs, legnagyobb fokú tag `Season:2020`

A minimum és a medián azért 1, mert minden izolált csúcs külön egyelemű közösség, és ez a szám minden szinten pontosan a nulla fokú csúcsok száma. Az egynél nagyobb közösségek:

| Vetület | Szint | Közösség | Min | Medián | Max |
|---|---:|---:|---:|---:|---:|
| Nyers | 0 | 45 | 2 | 5 | 207 |
| Nyers | 1 | 199 | 2 | 7 | 64 |
| Nyers | 2 | 394 | 2 | 3 | 58 |
| Nyers | 3 | 421 | 2 | 3 | 56 |
| Előkészített | 0 | 37 | 2 | 20 | 168 |
| Előkészített | 1 | 191 | 2 | 6 | 65 |
| Előkészített | 2 | 370 | 2 | 3 | 65 |
| Előkészített | 3 | 398 | 2 | 3 | 65 |

## Legnagyobb közösség: Nyers

A 0. szint legnagyobb közössége `5`, 207 csúcs (7.5% a vetület csúcsai közül) és 235 belső él (5.8% a vetület élei közül).

Típusok:

- Driver: 49
- Team: 39
- Car: 37
- RaceResult: 33
- Season: 22
- GrandPrix: 14
- PowerUnit: 6
- Title: 6

Legnagyobb fokú tagok a közösségen belül:

- `Team:mclaren` (McLaren): belső szomszéd 91, teljes fok 153
- `Driver:jenson button` (Jenson Button): belső szomszéd 54, teljes fok 92
- `GrandPrix:indianapolis 500` (Indianapolis 500): belső szomszéd 15, teljes fok 19
- `Driver:emerson fittipaldi` (Emerson Fittipaldi): belső szomszéd 7, teljes fok 11
- `Season:1968` (1968): belső szomszéd 6, teljes fok 11
- `Driver:lando norris` (Lando Norris): belső szomszéd 5, teljes fok 18
- `Driver:alain prost` (Alain Prost): belső szomszéd 4, teljes fok 13
- `Driver:denny hulme` (Denny Hulme): belső szomszéd 4, teljes fok 7
- `Driver:bruce mclaren` (Bruce McLaren): belső szomszéd 4, teljes fok 5
- `GrandPrix:race of champions` (Race of Champions): belső szomszéd 4, teljes fok 5
- `Season:1966` (1966): belső szomszéd 4, teljes fok 4
- `Season:1988` (1988): belső szomszéd 3, teljes fok 6

Egy csúcs uralja-e ezt a közösséget: nem. A legnagyobb belső fokú tag `Team:mclaren`, a többi tag 44.2%-ához kapcsolódik.
Egy közösség uralja-e a vetületet: nem.

## Legnagyobb közösség: Előkészített

A 0. szint legnagyobb közössége `3`, 168 csúcs (6.4% a vetület csúcsai közül) és 212 belső él (5.5% a vetület élei közül).

Típusok:

- RaceResult: 55
- GrandPrix: 42
- Car: 18
- Driver: 15
- Team: 15
- Title: 10
- Circuit: 8
- Season: 5

Legnagyobb fokú tagok a közösségen belül:

- `Season:2021` (2021): belső szomszéd 34, teljes fok 68
- `Season:2023` (2023): belső szomszéd 25, teljes fok 47
- `Season:2022` (2022): belső szomszéd 24, teljes fok 49
- `Season:2024` (2024): belső szomszéd 22, teljes fok 49
- `GrandPrix:bahrain grand prix` (Bahrain Grand Prix): belső szomszéd 19, teljes fok 42
- `Season:2026` (2026): belső szomszéd 16, teljes fok 38
- `GrandPrix:abu dhabi grand prix` (Abu Dhabi Grand Prix): belső szomszéd 15, teljes fok 31
- `GrandPrix:emilia romagna grand prix` (Emilia Romagna Grand Prix): belső szomszéd 10, teljes fok 19
- `GrandPrix:saudi arabian grand prix` (Saudi Arabian Grand Prix): belső szomszéd 10, teljes fok 12
- `GrandPrix:dutch grand prix` (Dutch Grand Prix): belső szomszéd 9, teljes fok 14
- `GrandPrix:qatar grand prix` (Qatar Grand Prix): belső szomszéd 8, teljes fok 10
- `GrandPrix:são paulo grand prix` (São Paulo Grand Prix): belső szomszéd 8, teljes fok 10

Egy csúcs uralja-e ezt a közösséget: nem. A legnagyobb belső fokú tag `Season:2021`, a többi tag 20.4%-ához kapcsolódik.
Egy közösség uralja-e a vetületet: nem.

## Küszöbök

A 0. szint a küszöb nélküli első felosztás. A vágás addig követi a hierarchiát, amíg a közösség nagyobb a küszöbnél.

| Vetület | Küszöb | 0. szint a küszöb felett | 0. szint legnagyobb | Vágás közösségei | Vágás legnagyobb | Vágásban a küszöb felett |
|---|---:|---:|---:|---:|---:|---:|
| Nyers | 10 | 19 | 207 | 1133 | 56 | 43 |
| Nyers | 30 | 18 | 207 | 991 | 56 | 4 |
| Nyers | 100 | 10 | 207 | 934 | 97 | 0 |
| Előkészített | 10 | 19 | 168 | 1076 | 65 | 37 |
| Előkészített | 30 | 17 | 168 | 930 | 65 | 5 |
| Előkészített | 100 | 11 | 168 | 883 | 89 | 0 |

## Nyers és előkészített felosztás

A közös kanonikus csúcsok száma 2645. Ezek közül 430 került másik 0. szintű közösségbe, miután minden előkészített közösséget a legnagyobb metszetű nyers közösséghez igazítottam.

A legnagyobb előkészített eltérés a `37` közösség: 69 csúcs nem a `24` nyers közösségből jön, a közösség mérete 133.

A legnagyobb nyers oldali veszteség a `5` közösség: 64 csúcs nem fér a legnagyobb előkészített metszetbe, a közös csúcsokon mért mérete 199.

A 39 alias-forrásnév közül 26 a céljától eltérő nyers közösségben volt. Az előkészített vetületen ezek a cél közösségét kapják.

A legfinomabb szinten ugyanez az igazítás 198 közös csúcsot tesz másik levélközösségbe.

## Jelentési szint és a riportkészlet kiválasztása

### Választott hierarchiaszint

A közösségi riportokhoz az előkészített vetület hierarchiájának 0. szintjét használtuk. Ez a Leiden első, legkevésbé részletes felosztása. A mélyebb szinteken a tovább bontható közösségek kisebb részekre oszlanak.

Az izolált csúcsok egyelemű közösségeit nem számítva:

| Szint | Közösségek száma | Medián méret | Legnagyobb méret |
|---:|---:|---:|---:|
| 0 | 37 | 20 | 168 |
| 1 | 191 | 6 | 65 |
| 2 | 370 | 3 | 65 |
| 3 | 398 | 3 | 65 |

A táblázat az adott jelentési szinten megjelenő, egynél nagyobb közösségeket tartalmazza, nem kizárólag az azon a mélységen újonnan létrejött közösségcsomópontokat.

### A szintválasztás indoklása

A korabeli „Jelentési szint” szakasz a 0. szintet választotta, és a felosztás szerkezeti jellemzőivel indokolta ezt. Ezen a szinten nem alakult ki a teljes vetületet uraló óriásközösség. A legnagyobb előkészített közösség 168 csúcsból állt, ami a vetület 2645 csúcsának 6,4%-a. A vizsgált legnagyobb közösségben a legnagyobb belső fokú csúcs, a `Season:2021`, a többi tag 20,4%-ához kapcsolódott. Ennél a közösségnél tehát nem egyetlen, a tagok többségét közvetlenül összekötő csúcs magyarázta a közösség létét.

A közösségszámok alapján a választás utólagos ráfordítási indoklása is megadható: a 0. szint 37 nem izolált közössége kezelhetőbb riportkészletet jelentett, mint az 1. szint 191 vagy a mélyebb szintek több száz közössége. Ha minden bevont közösséghez külön riport és később kérdésenként külön map-hívás készül, a bevont közösségek száma közvetlenül befolyásolja a hívásszámot. Ezt a költségérvet az eredeti szakasz nem fogalmazta meg kifejezetten; itt utólagos értelmezésként rögzítjük, nem korábban dokumentált döntési indokként.

A választás a nagyobb tematikus egységek megtartása és a riport-, illetve map-hívásszám korlátozása közötti kompromisszumként értelmezhető. Nem bizonyítottuk, hogy ez a szint adja a legjobb válaszminőséget: különböző hierarchiaszinteken generált riportkészletek összehasonlító válaszminőségi mérése nem történt.

### Eredeti javaslat és tényleges riportkészlet

A statisztikai vizsgálat eredetileg a 0. szint 10 főnél nagyobb közösségeit javasolta összefoglalásra. Az előkészített vetületen 19 ilyen közösség volt.

A tényleges riportgenerálás a későbbi futtatási beszámolók szerint ennél szélesebb kört használt: mind a 37, egynél nagyobb 0. szintű közösséghez készült riport. A globális keresés ezt a 37 riportból álló v3 készletet használta.

Ez nem hierarchiaszint-váltás, hanem a bevont közösségek körének bővítése: a legfeljebb 10 tagú, de nem izolált közösségek is bekerültek. A bővítés eredeti döntési indokát ez a statisztikai dokumentum nem rögzítette; azt utólag nem tekintjük bizonyított, korábban dokumentált megfontolásnak.

### Izolált csúcsok és lefedettség

Az előkészített vetület 736 izolált csúcsa a statisztikában egyelemű közösségként szerepel, de ezekhez nem készült közösségi riport. Emiatt a 37 riport nem jelenti a teljes gráf minden csúcsának lefedését.

A közösség teljes tagsága és a riportgeneráló modellnek ténylegesen átadott bemenet szintén különbözhet. A korábbi audit szerint a legnagyobb, 168 tagú közösségből 89 csomópont került a modellbemenetbe. Ez bemeneti kiválasztási korlát; ettől külön kockázat a modell által végzett összefoglalás további információvesztése.

### A méretküszöbök értelmezése

A 10, 30 és 100 méretküszöb a meglévő hierarchián végzett jelentési vágást jelentette, nem külön Leiden-felbontási paramétert.

Az előkészített vetületen a 100-as vágás volt az első vizsgált vágás, amelyben nem maradt a küszöbnél nagyobb közösség: a legnagyobb közösség mérete 89 volt. A 10-es és 30-as vágás után is maradtak tovább nem bomló, a küszöbnél nagyobb közösségek, legfeljebb 65 taggal.

A végső 37 riportos készlet a 0. szint nem izolált közösségeire épült, nem a 100-as méretküszöb szerinti vágásra. A vágásban szereplő 89-es legnagyobb közösségméretet ezért nem szabad összekeverni a 168 tagú közösség modellbemenetében szereplő 89 csomóponttal: két külön mérőszámról van szó.
