# Extrakciós pilot

Az alábbi lista a mentett fájlokból készült. Nem LLM-értékelés.
A strukturális validáció nem bizonyítja, hogy egy állítás szerepel a forrásszövegben. Az offline tesztek a validátort és a futtatás vezérlését ellenőrzik, nem a modell szemantikai pontosságát.

prompt_version: `f1-pilot-1`

| chunk_id | státusz | entitás | kapcsolat |
|---|---|---|---|
| `driver-lewis-hamilton#0` | hiba |  |  |
| `driver-lewis-hamilton#1` | siker | 0 | 0 |
| `season-2021-formula-one-world-championship#0` | hiba |  |  |
| `season-2021-formula-one-world-championship#1` | siker | 4 | 3 |
| `team-mercedes-benz-in-formula-one#1` | hiba |  |  |
| `team-mercedes-benz-in-formula-one#2` | siker | 0 | 0 |
| `team-scuderia-ferrari#0` | siker | 1 | 0 |
| `team-scuderia-ferrari#1` | siker | 1 | 0 |
| `driver-nico-rosberg#64` | siker | 0 | 0 |
| `driver-sebastian-vettel#75` | siker | 0 | 0 |

## driver-lewis-hamilton#0

- Hiba: ExtractionValidationError: AWARDED_IN does not allow Title -> Title

## driver-lewis-hamilton#1

- Dokumentum: Lewis Hamilton

Entitások: nincs

Kapcsolatok: nincs

## season-2021-formula-one-world-championship#0

- Hiba: ExtractionValidationError: ROUND_OF: unknown target_id 'e2'

## season-2021-formula-one-world-championship#1

- Dokumentum: 2021 Formula One World Championship

Entitások:

- `e1` Max Verstappen (Driver): Driver for Red Bull Racing-Honda who won the Drivers' Championship in 2021.
- `e2` Red Bull Racing-Honda (Team): Team that Max Verstappen drove for in the 2021 season.
- `e3` 2021 (Season): The season in which Max Verstappen won the Drivers' Championship.
- `e4` Drivers' Championship (Title): Title won by Max Verstappen in 2021.

Kapcsolatok:

- `e1` -DROVE_FOR-> `e2`: Max Verstappen drove for Red Bull Racing-Honda.
- `e4` -AWARDED_IN-> `e3`: Drivers' Championship awarded in 2021.
- `e2` -ENTERED-> `e3`: Red Bull Racing-Honda entered the 2021 season.

## team-mercedes-benz-in-formula-one#1

- Hiba: ExtractionValidationError: DROVE_FOR does not allow Team -> Team

## team-mercedes-benz-in-formula-one#2

- Dokumentum: Mercedes-Benz in Formula One

Entitások: nincs

Kapcsolatok: nincs

## team-scuderia-ferrari#0

- Dokumentum: Scuderia Ferrari

Entitások:

- `e1` Scuderia Ferrari (Team): The racing division of luxury Italian auto manufacturer Ferrari and the racing team that competes in Formula One racing.

Kapcsolatok: nincs

## team-scuderia-ferrari#1

- Dokumentum: Scuderia Ferrari

Entitások:

- `e1` Scuderia Ferrari (Team): oldest surviving and most successful Formula One team, having competed in every World Championship since 1950.

Kapcsolatok: nincs

## driver-nico-rosberg#64

- Dokumentum: Nico Rosberg

Entitások: nincs

Kapcsolatok: nincs

## driver-sebastian-vettel#75

- Dokumentum: Sebastian Vettel

Entitások: nincs

Kapcsolatok: nincs
