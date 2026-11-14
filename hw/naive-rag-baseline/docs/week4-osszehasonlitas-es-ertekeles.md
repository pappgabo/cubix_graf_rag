# 4. házifeladat — A keresési módok összehasonlítása és értékelése

## 1. Cél és értékelési módszer

A naiv RAG, a lokális GraphRAG és a globális GraphRAG ugyanazon 13 kérdésre adott válaszait hasonlítottuk össze. A kérdéskészlet 3 simple, 5 multi-hop és 5 global kérdést tartalmaz. Az értékelés a `questions.md` kérdéseinek és gold válaszainak, valamint a Phase 5 mentett válaszainak kézi összevetése.

Ez a dokumentum a projektgazda által elfogadott helyességi értékelést rögzíti. A korábbi JSON-munkalap előzetes címkéit nem vettük át automatikusan.

Besorolások:
- **Helyes:** minden lényeges kérdéselemre megfelelő választ ad.
- **Hiányos:** releváns, helyes részeket ad, de szükséges elemek kimaradnak.
- **Téves:** a kérdés megválaszolását érdemben elrontó állítást tartalmaz, akkor is, ha részben helyes vagy a végén elutasít.
- **Elutasított:** a kért választ nem adja meg, elégtelen bizonyítékra hivatkozik.

A gold többletrészleteit nem követeltük meg, ha maga a kérdés nem kérte őket. Q02-nél a „23 éves” elegendő; Q06-nál a csapatokat kellett megnevezni, a bajnoki évek felsorolása nem kötelező.

A válasz helyessége és forrásalátámasztottsága külön szempont. Ez a dokumentum nem igazolja újra mind a 39 válasz kontextusbeli alátámasztottságát. A pontos keresési vagy generálási hibaforrást a válaszszöveg önmagában nem bizonyítja.

## 2. Források és a mérés kerete

- [Kérdések és gold válaszok](../questions.md)
- [Előzetes értékelési munkalap, a 39 válasz szövegével](week4-ertekelesi-lap-kitoltott.json)
- [Naiv válaszok](../diagnostics/2026-11-10-phase5-run/results/week4-phase5-naiv-answers.json)
- [Lokális válaszok](../diagnostics/2026-11-10-phase5-run/results/week4-phase5-lokalis-answers.json)
- [Globális válaszok](../diagnostics/2026-11-10-phase5-run/results/week4-phase5-globalis-rerun.json)
- [Útválasztó döntései](../diagnostics/2026-11-10-phase5-run/results/week4-phase5-router-decisions.json)
- [Futtatási ledger](../diagnostics/2026-11-10-phase5-run/results/week4-phase5-ledger.json)
- [Közösségstatisztika](week4-kozosseg-statisztika.md)
- [Futtatási összesítés](../diagnostics/2026-11-10-phase5-run/results/week4-phase5-run-summary.json)

A hivatkozások repó-relatívak. A projektbeli eredményútvonalak a futtatási jelentésből származnak; a helyi repó tényleges fájlhelyeit ebben a környezetben nem ellenőriztük. A részletes keresési és modellbeállításokat a [Phase 5 terve](week4-phase5-terv-es-becsles.md) dokumentálja. A globális keresés a meglévő 37 v3 közösségi riportot és a normál szűrésű A reduce-ágat használta. A naiv baseline a jelenlegi 1651 chunkból külön gyűjteményben készült, top_k=4 beállítással. A régi, 500/75 chunkolású baseline történeti referencia, nem ennek az összevetésnek a naiv eredménye.

## 2/A. Hierarchiaszint és riportkészlet

A [közösségstatisztika](week4-kozosseg-statisztika.md) „Jelentési szint” szakasza a 0. szintet jelölte ki. Az előkészített vetület legnagyobb közössége 168 csúcsot, a 2645 csúcs 6,4%-át tartalmazta; a legnagyobb belső fokú csúcs a közösség többi tagjának 20,4%-ához kapcsolódott. Nem alakult ki a teljes vetületet uraló óriásközösség.

A 0. szinten 37, az 1. szinten 191 nem izolált közösség szerepelt. A kisebb riportkészlet kevesebb riportgeneráló és későbbi map-hívást igényel; ez utólagos ráfordítási értelmezés, nem az eredeti szakaszban kifejtett költségoptimalizálási bizonyítás. Különböző szintek riportjain összehasonlító válaszminőségi mérés nem történt.

Az eredeti javaslat a 10 főnél nagyobb 19 közösség összefoglalása volt, a futtatási beszámolók szerint azonban mind a 37 nem izolált 0. szintű közösséghez készült riport. Ez bevonásikör-bővítés, nem szintváltás. A bővítés eredeti indokát a statisztikai dokumentum nem rögzítette.

## 3. Kérdésenkénti értékelés

| Kérdés | Típus | Naiv | Lokális | Globális |
|---|---|---|---|---|
| Q01 | simple | helyes | helyes | helyes |
| Q02 | simple | helyes | helyes | elutasított |
| Q03 | simple | helyes | elutasított | elutasított |
| Q04 | multi-hop | elutasított | helyes | téves |
| Q05 | multi-hop | téves | elutasított | elutasított |
| Q06 | multi-hop | helyes | hiányos | hiányos |
| Q07 | multi-hop | hiányos | helyes | elutasított |
| Q08 | multi-hop | helyes | helyes | hiányos |
| Q09 | global | helyes | helyes | hiányos |
| Q10 | global | hiányos | hiányos | hiányos |
| Q11 | global | helyes | téves | elutasított |
| Q12 | global | téves | hiányos | téves |
| Q13 | global | elutasított | elutasított | hiányos* |

*Q13 globális válaszát gyenge részleges eredményként, hiányosnak soroltuk be. Megemlít csapatokat és meghatározó pilótákat, de nem fejti ki megfelelően a dominanciát magyarázó közös tényezőket, és maga is jelzi a bizonyítékhiányt. Ez nem teljes értékű szintézis. Elutasításként történő besorolása esetén a globális összesítés helyes/hiányos/téves/elutasított sorrendben 1/4/2/6, a routerrel kiválasztott válaszoké 6/3/1/3 lenne; a global kérdéscsoport globális sora 0/2/1/2 lenne. A teljesen helyes válaszok száma változatlan maradna.

## 4. A fontosabb besorolások indoklása

### Q04 — a 2016-os bajnok csapattársa

A gold szerint a bajnok Nico Rosberg, csapattársa a Mercedesnél Lewis Hamilton. A naiv mód elutasít. A lokális válasz helyes. A globális válasz megfordítja a szerepeket: Hamiltont nevezi a bajnoknak, Rosberget a csapattársnak, ezért téves.

### Q05 — a 2012-es bajnok későbbi csapatváltása

A gold Vettel Red Bulltól Ferrarihoz igazolását és a 2015-ös hatálybalépést várja. A naiv válasz Räikkönent nevezi 2012 bajnokának, ezért téves; a végén szereplő elutasítás ezt nem semlegesíti. A lokális és globális mód nem adja meg a kért választ, ezért elutasított.

### Q06 — a két hétszeres bajnok és bajnoki csapataik

A naiv válasz Schumacherhez Benettont és Ferrarit, Hamiltonhoz McLarent és Mercedest rendel, ezért helyes. A lokális válaszból Hamilton McLaren-címe kimarad. A globális válaszból ezenfelül Schumacher Benetton-címei is hiányoznak. A két gráfos válasz hiányos.

### Q07 — Alonso és Hamilton közös szezonja

A naiv válasz megnevezi a McLarent, 2007-et és a két pilóta második/harmadik helyét, de nem nevezi meg a bajnokság győztesét, Räikkönent. Ezért hiányos. Az egypontos különbséget a kérdés nem kéri kifejezetten; annak hiánya önmagában nem lenne levonási ok. A lokális válasz a szükséges elemeket tartalmazza. A globális mód elutasít.

### Q08 — Rosberg utódja és korábbi csapata

A naiv és lokális válasz Bottast és a Williamst is megnevezi. A globális válasz Bottast megadja, de a Williamst nem, ezért hiányos.

### Q09 — a legtöbb bajnoki címet nyerő pilóták

A naiv és lokális válasz Hamiltont és Schumachert is megnevezi hét-hét címmel. A globális csak Hamiltont adja meg, ezért hiányos.

### Q10 — Ferrari-pilóták

A gold hat nevet tartalmaz: Schumacher, Räikkönen, Alonso, Vettel, Leclerc és Hamilton. A naiv ötöt ad meg, Hamilton nélkül. A lokális Leclerc-t és Alonsót sorolja fel biztosként, Vettelt csak fenntartással említi. A globális Schumacher, Räikkönen és Leclerc nevét adja meg. Mindhárom válasz hiányos.

### Q11 — a legtöbb pilóta-bajnoki címet nyerő konstruktőr

A gold Ferrari, 15 pilóta-bajnoki cím. A naiv válasz ezt adja meg. A lokális Renault 12 konstruktőri címéről állítja, hogy ez a keresett rekord: nemcsak a csapat és szám téves, hanem a bajnoki kategória is eltér. A globális mód elutasít.

### Q12 — bajnokok évtizedes csoportosítása

A naiv válasz hiányos listát és téves évtizedes besorolást ad: Hamilton nem szerepel a 2000-es és 2020-as években, a teljes pályafutásra vonatkozó címszámok pedig nem helyettesítik az évtizedes bontást. Ez téves válasz.

A lokális válaszban a felsorolt bajnoki évek megfelelnek a goldnak, de több bajnok és év kimarad, ezért hiányos.

A globális válasz Schumacherhez „1996–2006”, Vettelhez „2009–2014” időszakot rendel a bajnoki csoportosításban. Ezek nem a gold bajnoki évei; a probléma ezért nem pusztán hiányos felsorolás, hanem téves válasz.

## 5. Kérdéstípusonkénti összesítés

| Kérdéstípus | Mód | Helyes | Hiányos | Téves | Elutasított |
|---|---|---:|---:|---:|---:|
| simple — 3 kérdés | Naiv | 3 | 0 | 0 | 0 |
| simple — 3 kérdés | Lokális | 2 | 0 | 0 | 1 |
| simple — 3 kérdés | Globális | 1 | 0 | 0 | 2 |
| multi-hop — 5 kérdés | Naiv | 2 | 1 | 1 | 1 |
| multi-hop — 5 kérdés | Lokális | 3 | 1 | 0 | 1 |
| multi-hop — 5 kérdés | Globális | 0 | 2 | 1 | 2 |
| global — 5 kérdés | Naiv | 2 | 1 | 1 | 1 |
| global — 5 kérdés | Lokális | 1 | 2 | 1 | 1 |
| global — 5 kérdés | Globális | 0 | 3 | 1 | 1 |
| Összesen — 13 kérdés | Naiv | 7 | 2 | 2 | 2 |
| Összesen — 13 kérdés | Lokális | 6 | 3 | 1 | 3 |
| Összesen — 13 kérdés | Globális | 1 | 5 | 2 | 5 |

A lokális mód a multi-hop csoportban adott több teljesen helyes választ. A naiv mód a simple és a global címkéjű csoportban szerepelt legeredményesebben a teljesen helyes válaszok száma alapján. A globális mód a saját típuscsoportjában nem adott teljesen helyes választ. Ezek a konkrét kérdéskészlet eredményei, nem a módszerek általános rangsora.

## 6. Útválasztó és hibás döntése

Az útválasztó zero-shot LLM-döntéssel választott a három mód közül. A mentett döntések kért modellje `gpt-4o-mini`, visszaadott modellazonosítója `gpt-4o-mini-2024-07-18`; minden döntés strukturálisan érvényes volt.

Előre rögzített feladattípus szerinti megfeleltetés:
- simple → naiv;
- multi-hop → lokális;
- global → globális.

| Kérdések | Elvárt mód | Választott mód | Egyező döntések |
|---|---|---|---:|
| Q01–Q03 | naiv | naiv | 3/3 |
| Q04–Q05 | lokális | lokális | 2/2 |
| Q06 | lokális | globális | 0/1 |
| Q07–Q08 | lokális | lokális | 2/2 |
| Q09–Q13 | globális | globális | 5/5 |

Eredmény: 12/13 egyező döntés (92,3%), 1/13 eltérés (7,7%).

A hibás döntések teljes listája: **Q06**. A router több pilóta bajnoki adatainak korpuszszintű összesítését látta a kérdésben. A kérdéskészlet ezzel szemben két konkrét rekordtartó csapatkapcsolatainak összevetéseként, multi-hop kérdésnek sorolja be. Ez a kategóriák közötti határ bizonytalanságát is mutatja, de a rögzített megfeleltetéshez képest eltérésnek számít.

### A típusfelismerés és a válaszminőség különbsége

A típusnak megfelelő útválasztás nem garantál teljesen helyes választ. Q09-et és Q11-et a router a megfeleltetés szerint helyesen a globális módhoz irányította, de az hiányos, illetve elutasító választ adott; a naiv mód mindkettőt helyesen válaszolta meg.

A mentett döntésekkel kiválasztott, már meglévő válaszok összesítése:

| Helyes | Hiányos | Téves | Elutasított |
|---:|---:|---:|---:|
| 6 | 4 | 1 | 2 |

A hat helyes kiválasztott válasz: Q01, Q02, Q03, Q04, Q07, Q08. Ez a mentett válaszok és döntések összerendelése, nem új keresési futtatás.

A 12/13 típus szerinti egyezés ebben a mérésben tehát nem jelentett több teljesen helyes választ a minden kérdésre alkalmazott naiv mód hét helyes válaszánál.

## 7. Információvesztés és hibaforrások

A korábbi Phase 4 audit a Phase 3 riportgenerálásánál konkrét információvesztést azonosított:
- Q09: a Hamilton–Schumacher holtverseny szerepelt a riportbemenetben, de a megfelelő riportból a Schumacher-utalás kimaradt.
- Q10: Alonso és Hamilton Ferrari-kapcsolatának egyes explicit bemeneti állításai nem maradtak meg a megfelelő riportokban.
- Q11: a szükséges összesítő információ nem volt elérhető a riportokban; a korábbi kiesési pont nem tisztázott.

Ezek a korábban közölt audit megállapításai, nem a mostani válaszértékelésből levezetett új bizonyítások. Q02, Q03 vagy Q07 globális elutasítása önmagában nem bizonyítja, hogy éppen a riporttömörítés volt a kiesési pont. Hasonlóképpen a lokális elutasítás önmagában nem bizonyít entitáshorgonyzási hibát.

A hibák értelmezésénél külön kell tartani:
- a szükséges tény keresési kontextusból való kimaradását;
- a korábbi reprezentációs vagy tömörítési veszteséget;
- a hiányos felsorolást vagy aggregálást;
- a válaszgenerálás téves állításait.

Pontos hibaforrást csak az érintett rétegek bizonyítékainak összevetése alapján szabad megnevezni. Ez az értékelés nem indokol új futtatást vagy javító kísérletet.

## 8. Ráfordítás és korlátok

A lezáró futtatási jelentés szerint a Phase 5 teljes OpenAI API-költsége 0,066515 USD volt a 0,15 USD keretből. Ez jelentett mérési adat, nem az értékelési munkalap sorainak újraösszegzése; nem tartalmazza a Claude fejlesztési munkamenetének saját fogyasztását.

### A feltöltött ledgerből ellenőrizhető ráfordítások

A `week4-phase5-ledger.json` 13 `globalis-rerun` sorának `map_calls` mezőit összegezve 481 map-hívás adódik, kérdésenként 37. Ez nem pusztán a 13 × 37 képletből átvett érték: a mentett kérdésszintű ledger-bejegyzések összege is 481. A ledger azonban nem tartalmaz 481 külön map-hívássort; az egyedi nyers hívásnaplókat itt nem ellenőriztük újra.

| Tétel | Generatív hívás | Embeddinghívás | Input-token | Output-token | Költség (USD) |
|---|---:|---:|---:|---:|---:|
| Naiv keresés, az ismételt Q01-gyel | 14 | 17 | 13 014 generatív + 327 embedding | 534 | 0,00227904 |
| Lokális keresés | 13, `model_called=true` | 13 | Generatív: hiányzik; embedding: 273 | Hiányzik | Teljes költség hiányzik; embedding: 0,00000546 |
| Globális keresés | 481 map a kérdésszintű ledger szerint; 11 reduce a futtatási beszámoló szerint | 0 | Hiányzik | Hiányzik | Mód szerinti összeg hiányzik |
| Útválasztó | 13 | 0 | 4455 | 544 | A feltöltött döntésekből és ledgerből közvetlenül nem kiolvasható |
| Új naiv index előállítása | 0 | 9 | 285 154 embedding-token | Nem alkalmazható | 0,00570308 |

A naiv költség a 14 válaszhívás ledgerbeli 0,00227250 USD összegéből és a 17 kérdésembedding 0,00000654 USD költségéből áll. Az indexelést külön számoltuk, nem osztottuk rá teljes egészében minden kérdésre. A hiányzó lokális generatív költség nem nulla; a helyességi munkalap kis lokális költségértékeit nem tekintjük teljes módköltségnek.

Összesen 39 embedding-bejegyzés található: 9 indexelő, 17 naiv kérdésembedding és 13 lokális kérdésembedding. Ezek összes tényleges tokenje 285 754, ledger szerinti költsége 0,00571508 USD. A teljes 571 API-hívást és az abból 532 generatív hívást a lezáró beszámoló közli. A ledger 27 válaszbejegyzése, 13 router-bejegyzése és 481-es map-összege, továbbá a beszámoló 11 reduce-hívása ezzel számszakilag összhangban van; a reduce-darabszámot a feltöltött ledgerből önállóan nem lehet ellenőrizni.

A `week4-phase5-run-summary.json` 302 generatív és 0 embedding hívást jelző számlálóit nem használjuk teljes kumulatív darabszámként, mert a folytatások során a számlálók nullázódtak. A fájl `spent_usd` értéke 0,06651518 USD; a teljes költséget a lezáró beszámolóval egyező, jelentett kumulatív összegként kezeljük, nem a hiányos ledgerből teljesen újraépített költségként.

### Kontextus és idő

| Mód | Kontextusmező a munkalapban, minimum–maximum | Átlag | Elérhető időadat |
|---|---|---:|---|
| Naiv | 708–1174 tokenként jelölve | 923,2 | A 14 válaszbejegyzés időinek összege 18,939 s |
| Lokális | 5055–5669 tokenként jelölve | 5379,7 | A 13 válaszbejegyzés időinek összege 447,657 s |
| Globális | Nem számszerű, eredményfájlra hivatkozik | Nem áll rendelkezésre | A feltöltött ledgerből nem összesíthető |
| Útválasztó | Nem visszakeresési kontextus; teljes input-usage összesen 4455 token | Nem alkalmazható | A 13 döntés időinek összege 13,907 s |

A kontextusszámok a munkalap mezőinek leíró összesítései, nem új tokenmérések. A naiv Q01 ledgerbeli teljes prompt-usage értéke például megegyezik a munkalap kontextusmezőjével; ezért a mezők pontos kontextus-only jelentése nem igazolt. A lokális karakter/3 és a korábbi karakter/4 becslést sem kezeljük egységes pontos mérésként. Az idők eltérő műveleti hatókörű bejegyzésekből származnak, ezért nem tekinthetők izolált modell-latencia-összehasonlításnak vagy a teljes futás falióraidejének.

### Q01 ismétlése és végrehajtási eltérések

A naiv Q01 a technikai helyreállítás közben kétszer kapott sikeres generatív hívást a futtatási utasítás ismétlési tilalma ellenére. Ez végrehajtási eltérés, nem pusztán adminisztratív korlát. A ledger két időbélyege: `1794342930.8721323` és `1794343012.82457`; mindkét sor költsége 0,00016860 USD. Mindkettő ugyanarra a `naive-log-naiv-Q01.json` fájlnévre és ugyanarra a kérés-hash-re hivatkozik, így a két eredeti válasz különálló megőrzését a ledger önmagában nem igazolja.

Az értékelés a kitöltött munkalapban szereplő, a futtatási beszámoló szerint később mentett választ használja:

> Lewis Hamilton has won seven World Drivers' Championships, which ties him with Michael Schumacher for the most championships in Formula One history [S2].

Nem a két válasz közül utólag kiválasztott jobbikat értékeltük. A jelentett teljes költség a futtatási beszámoló szerint mindkét hívást tartalmazza; a ledger naiv részösszegében is mindkét költség szerepel. A hiányos lokális költségmezők és a folytatáskor nullázódó belső számlálók további elszámolási korlátok. A lezáráskor nem történt új válaszgenerálás.

További értelmezési korlátok:
- A saját Phase 5-specifikáció három alátámasztottsági kategóriájának teljes bizonyítékalapú értékelése és a keresési/generálási hibák teljes szétválasztása nem készült el. Ez saját specifikációs hiány, nem a 4. heti feladatlap külön DoD-pontja. Jira-módosítás ebben a dokumentumfrissítésben nem történt; lezárási megjegyzésként ezt a korlátot ott is feltüntetendőnek tekintjük.
- Ugyanaz a 13 kérdés szolgált fejlesztésre és mérésre; ez nem független teszt.
- A kérdéstípus az előzetes besorolás, nem az adott futás legjobb keresőjének utólagos címkéje.
- Q09 és Q11 esetén a naiv keresés számára összefoglaló állítás is elérhető lehet; a global címke nem bizonyítja, hogy a válaszhoz ténylegesen minden dokumentumot össze kellett kapcsolni.
- Az eltérő kontextuskeretek és forrásreprezentációk miatt ez a három megvalósított konfiguráció összevetése, nem izolált algoritmuskísérlet.
- A lokális karakter/3 és a korábbi Phase 3–4 karakter/4 tokenbecslés nem tekinthető azonos módszerű pontos mérésnek. Az előzetes munkalap kontextusmezőiből önmagukban nem következtetünk pontos tokenarányokra.
- A közösségi riportok nem fedik le a gráf minden részletét: a korábbi audit szerint a 736 izolált csúcs nem került riportba, a legnagyobb közösség 168 tagjából pedig 89 csomópont szerepelt a riportgeneráló bemenetben.
- A Phase 4 régi teljes kérésnaplói hiányoztak; a korábbi szivárgásvizsgálat rekonstruált bemenetekre és kódellenőrzésre támaszkodott.

## 9. Következtetés

A kísérletben nem egyetlen keresési mód bizonyult minden kérdéstípuson a legeredményesebbnek. A naiv RAG hét teljesen helyes választ adott, és a közvetlen ténykérdések mellett néhány globálisnak címkézett kérdést is megoldott. A lokális GraphRAG a multi-hop csoportban szerepelt legerősebben; Q04 és Q07 esetében teljesebb választ adott a naiv keresésnél.

A globális keresés nagyobb modellhívásszáma ebben a megvalósításban nem járt következetesen jobb válaszminőséggel. A saját kérdéscsoportjában nem adott teljesen helyes választ; Q13-nál ugyanakkor a másik két mód elutasítása mellett gyenge részleges szintézist nyújtott.

Az útválasztó 13 kérdésből 12-nél követte az előre rögzített típus–mód megfeleltetést, de a kiválasztott válaszok közül csak hat volt teljesen helyes. A feladattípus szerinti útválasztás ezért ebben a kísérletben nem bizonyította a végső válaszminőség javulását a naiv baseline-hoz képest.

Az eredmények a módszerek eltérő erősségeit és korlátait mutatják ezen a kis, fejlesztéshez is használt kérdéskészleten. A hibás és hiányos válaszok a mérés eredményei: dokumentáltuk őket, nem javítottuk utólag új modellhívásokkal.
