# Claude Code — 1. fázis: célzott felmérés (A2)

Az elfogadott `week5-terv-vegleges.md` az alap. Most csak A2-t végezd el,
ne implementáld a mérési rendszert. A mellékelt `week5-golden-set-v1-draft.jsonl`
a 13 régi kérdés nem futtatható váza: az üres forráscsoportok és Q13 rubrikája
szándékosak. Ha a fájlokat máshová mentettem, keresd meg őket fájlnév alapján.

## Feladat
1. Célzottan olvasd a három meglévő kereső belépési pontját és az őket használó
   legutóbbi futtatót. Jelentsd fájl + függvény + releváns sor alapján:
   milyen választ, tényleges generálási kontextust, chunkazonosítót,
   forráskapcsolatot, használati adatot és map/reduce-résznaplót adnak vissza.
   Különítsd el a tényleges kontextust a háttérforrás-jelöltektől.
2. A meglévő függőségfájlok, telepített verziók és szükség esetén hivatalos
   dokumentáció alapján ellenőrizd a Langfuse experiment API és a Ragas
   faithfulness illeszthetőségét a meglévő modellklienshez. Függőségfeloldást
   csak nem módosító módon vizsgálj. Ne telepíts, ne módosíts lockot vagy venvet.
   Jelezd a ténylegesen ellenőrzött és még bizonytalan részleteket, különösen
   hibánál leállás, folytatás és meglévő eredmények feltöltése terén.
3. Készíts egy kis, standard library alapú helyi CLI-scriptet két alparanccsal:
   `search`: chunkjelöltek keresése a kérdések kritériumaihoz, kulcsszavasan,
   keresőrendszer, embedding és LLM nélkül; `sample`: seed=42 mellett tíz
   külön dokumentum kiválasztása, majd dokumentumonként egy chunk kiírása.
   Vizsgáld meg előbb a chunks.jsonl tényleges sémáját. A kimenet tartalmazzon
   dokumentum- és chunkazonosítót, keresésnél találati szövegkörnyezetet,
   mintavételnél a teljes chunkot, továbbá a korpusz hash-ét és a seedet.
   A keresési listákat korlátozd, jelölteket adj, ne nyilvánítsd őket goldnak.
   A véletlen mintából ne írj új kérdéseket, és ne keress rendszerkimeneteket.
4. Futtasd a scriptet helyi fájlokon, rövid offline teszttel. Írd ki a kérdésenkénti
   jelölteket és a külön mintát week5 nevű helyi kimenetekbe. A wildcard
   dokumentumjelölések csak keresési támpontok, nem konkrét forrásazonosítók.

## Korlátok és kimenet
Nincs projektmodell-API-hívás, keresőfuttatás, adatbázis-kapcsolódás/írás,
Langfuse-adatküldés, csomagtelepítés, refaktor, git-commit. .env-et és titkokat
ne olvass vagy írj ki. Csak az új scriptet, offline tesztjét és week5 jelentéseket
hozd létre; a keresők és korábbi eredmények változatlanok maradnak.

Rövid `week5-felmeres.md`: hárommódos mezőtérkép, egyetlen javasolt integráció,
kompatibilitási eredmények, hiányok/proxyk, érintett fájlok, tesztek és pontos
PowerShell-parancsok. A terminálba csak összefoglalót írj, ne teljes fájlokat.
Az A2 végén állj meg. Ne kezdd el B-t, és ne módosítsd a golden setet.
