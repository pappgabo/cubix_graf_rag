# 10 chunkos v3 pilot minőségi riport

status ok is structural validity, not semantic correctness. An empty chunk is an accepted extraction with no entities.

A gráfmutatók az extrahált szakterületi gráfra vonatkoznak. A dokumentumgráf, a seed és a MENTIONS élek nincsenek benne.

- Feldolgozott chunk: 10
- Sikeres (strukturálisan érvényes): 7
- Hibás: 3
- Üres, sikeres chunk: 3
- Más státusz: 0

## Entitások chunkonként

- `driver-lewis-hamilton#0`: status=ok, entitás=2, kapcsolat=1
- `driver-lewis-hamilton#1`: status=ok, entitás=2, kapcsolat=0
- `driver-nico-rosberg#64`: status=ok, entitás=0, kapcsolat=0
- `driver-sebastian-vettel#75`: status=ok, entitás=0, kapcsolat=0
- `season-2021-formula-one-world-championship#0`: status=ok, entitás=2, kapcsolat=1
- `season-2021-formula-one-world-championship#1`: status=error, entitás=0, kapcsolat=0
- `team-mercedes-benz-in-formula-one#1`: status=error, entitás=0, kapcsolat=0
- `team-mercedes-benz-in-formula-one#2`: status=ok, entitás=0, kapcsolat=0
- `team-scuderia-ferrari#0`: status=ok, entitás=1, kapcsolat=0
- `team-scuderia-ferrari#1`: status=error, entitás=0, kapcsolat=0

## Sűrű és ritka chunk

### Sűrű: `driver-lewis-hamilton#0`

Státusz: ok. Entitás: 2. Kapcsolat: 1. A ritka vagy üres eredmény nem hibás extrakció.

Forrásszöveg:

```
Lewis Hamilton
Sir Lewis Carl Davidson Hamilton (born 7 January 1985) is a British racing driver who competes in Formula One for
Ferrari.  Hamilton  has  won  a  joint-record  seven  Formula  One  World  Drivers'  Championship  titles—tied  with  Michael
Schumacher—and  holds  the  records  for  most  wins  (106),  pole  positions  (104),  and  podium  finishes  (208),  among
others.
```

Extrakció:

```json
{
  "entities": [
    {
      "local_id": "e1",
      "name": "Lewis Hamilton",
      "entity_type": "Driver",
      "description": "Sir Lewis Carl Davidson Hamilton is a British racing driver who competes in Formula One."
    },
    {
      "local_id": "e2",
      "name": "Ferrari",
      "entity_type": "Team",
      "description": "A Formula 1 team that Lewis Hamilton competes for."
    }
  ],
  "relationships": [
    {
      "source_id": "e1",
      "target_id": "e2",
      "relationship_type": "DROVE_FOR",
      "description": "Lewis Hamilton competes for Ferrari in Formula One.",
      "from_year": null,
      "to_year": null,
      "role": null
    }
  ]
}
```

### Ritka vagy üres: `driver-nico-rosberg#64`

Státusz: ok. Entitás: 0. Kapcsolat: 0. A ritka vagy üres eredmény nem hibás extrakció.

Forrásszöveg:

```
## 2013–2016
```

Extrakció:

```json
{
  "entities": [],
  "relationships": []
}
```


## Típusok

Entitáselőfordulások:
- Driver: 2
- GrandPrix: 1
- Season: 1
- Team: 3

Kapcsolatelőfordulások:
- DROVE_FOR: 1
- ROUND_OF: 1

Sémán kívüli típus: nincs

## Elutasított jelöltek

- `season-2021-formula-one-world-championship#1`: ExtractionValidationError: DROVE_FOR does not allow Team -> Driver
  - Jelölt típusok: Driver, Team, Season, Title, WON, ENTERED, DROVE_FOR, AWARDED_IN
  - Forrásidézet: for the titles of World Drivers' Champion and World Constructors' Champion, respectively. Max Verstappen of Red Bull Racing-Honda won the Drivers' Championship for the first time in his career, having claimed 10 race wins across the season. Verstappen became the first-ever driver from the Netherlands, the first Honda-powered driver since Ayrton Senna in 1991, the first Red Bull driver since Sebast...
- `team-mercedes-benz-in-formula-one#1`: ExtractionValidationError: ENTERED is not temporal; from_year, to_year and role must be null
  - Jelölt típusok: Team, Team, Season, ENTERED, ENTERED
  - Forrásidézet: Mercedes-Benz, a German automotive brand of the Mercedes-Benz Group, has been involved in Formula One as both team owner and engine manufacturer for various periods since 1954. The current Mercedes-Benz Grand Prix Limited, competing as Mercedes-AMG Petronas Formula One Team, is based in Brackley, England, and holds a German racing licence
- `team-scuderia-ferrari#1`: ExtractionValidationError: ENTERED is not temporal; from_year, to_year and role must be null
  - Jelölt típusok: Team, Season, ENTERED
  - Forrásidézet: oldest surviving and most successful Formula One team, having competed in every World Championship since 1950. The team was founded by Enzo Ferrari in 1929, initially to race cars produced by Alfa Romeo. By 1947, Ferrari had begun building its own cars. Among its important achievements outside Formula One are winning the FIA World Endurance Championship, World Sportscar Championship, 24 Hours of L...

## Egy chunkban előforduló entitások

Pontosan egy forráschunkban szereplő összevont entitás: 5.

## Legnagyobb fokszám

A legnagyobb fokszám 1. Ezt eléri: `Driver:lewis hamilton`, `GrandPrix:grand prix`, `Season:2021 formula one world championship`, `Team:ferrari`. Az összevont szakterületi élek iránya nélküli száma. A szám nem igazolja, hogy az extrakció szemantikailag helyes.

- Driver:lewis hamilton -DROVE_FOR-> Team:ferrari
- GrandPrix:grand prix -ROUND_OF-> Season:2021 formula one world championship

## Deduplikáció

Előtte egy csomópont egy chunk egy entitása, egy él egy chunk egy kapcsolata. Utána egy csomópont egy entity_key, egy él egy rel_key. Az aliaslista üres: `{}`.

- Előtte: csomópont 7, él 2, legnagyobb gyengén összefüggő komponens 2 csomópont.
- Utána: csomópont 6, él 2, legnagyobb gyengén összefüggő komponens 2 csomópont.

Az irányított szakterületi gráf legnagyobb gyengén összefüggő komponense: az irány nem számít, a méret a csomópontok száma. A seed, a dokumentumgráf és a MENTIONS élek nincsenek benne.
