# Extrakciós pilot

Az alábbi lista a mentett fájlokból készült. Nem LLM-értékelés.
A strukturális validáció nem bizonyítja, hogy egy állítás szerepel a forrásszövegben. Az offline tesztek a validátort és a futtatás vezérlését ellenőrzik, nem a modell szemantikai pontosságát.

prompt_version: `f1-pilot-3`

| chunk_id | státusz | entitás | kapcsolat |
|---|---|---|---|
| `driver-lewis-hamilton#0` | siker | 2 | 1 |
| `driver-lewis-hamilton#1` | siker | 2 | 0 |
| `season-2021-formula-one-world-championship#0` | siker | 2 | 1 |
| `season-2021-formula-one-world-championship#1` | hiba |  |  |
| `team-mercedes-benz-in-formula-one#1` | hiba |  |  |
| `team-mercedes-benz-in-formula-one#2` | siker | 0 | 0 |
| `team-scuderia-ferrari#0` | siker | 1 | 0 |
| `team-scuderia-ferrari#1` | hiba |  |  |
| `driver-nico-rosberg#64` | siker | 0 | 0 |
| `driver-sebastian-vettel#75` | siker | 0 | 0 |

## driver-lewis-hamilton#0

- Dokumentum: Lewis Hamilton

Entitások:

- `e1` Lewis Hamilton (Driver): Sir Lewis Carl Davidson Hamilton is a British racing driver who competes in Formula One.
- `e2` Ferrari (Team): A Formula 1 team that Lewis Hamilton competes for.

Kapcsolatok:

- `e1` -DROVE_FOR-> `e2`: Lewis Hamilton competes for Ferrari in Formula One.

## driver-lewis-hamilton#1

- Dokumentum: Lewis Hamilton

Entitások:

- `e1` Lewis Hamilton (Driver): Born and raised in Stevenage, Hamilton began his career in karting at age six, winning several national titles.
- `e2` McLaren-Mercedes Young Driver Programme (Team): Hamilton was signed to the McLaren-Mercedes Young Driver Programme in 1998.

Kapcsolatok: nincs

## season-2021-formula-one-world-championship#0

- Dokumentum: 2021 Formula One World Championship

Entitások:

- `e1` 2021 Formula One World Championship (Season): The 2021 FIA Formula One World Championship was a motor racing championship for Formula One cars.
- `e2` Grand Prix (GrandPrix): The championship was contested over twenty-two Grands Prix.

Kapcsolatok:

- `e2` -ROUND_OF-> `e1`: Each Grand Prix is a round of the 2021 Formula One World Championship.

## season-2021-formula-one-world-championship#1

- Hiba: ExtractionValidationError: DROVE_FOR does not allow Team -> Driver Elutasított jelölt mentve; nem számít sikeres eredménynek.

## team-mercedes-benz-in-formula-one#1

- Hiba: ExtractionValidationError: ENTERED is not temporal; from_year, to_year and role must be null Elutasított jelölt mentve; nem számít sikeres eredménynek.

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

- Hiba: ExtractionValidationError: ENTERED is not temporal; from_year, to_year and role must be null Elutasított jelölt mentve; nem számít sikeres eredménynek.

## driver-nico-rosberg#64

- Dokumentum: Nico Rosberg

Entitások: nincs

Kapcsolatok: nincs

## driver-sebastian-vettel#75

- Dokumentum: Sebastian Vettel

Entitások: nincs

Kapcsolatok: nincs
