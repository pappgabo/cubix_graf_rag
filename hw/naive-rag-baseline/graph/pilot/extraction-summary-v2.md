# Extrakciós pilot

Az alábbi lista a mentett fájlokból készült. Nem LLM-értékelés.
A strukturális validáció nem bizonyítja, hogy egy állítás szerepel a forrásszövegben. Az offline tesztek a validátort és a futtatás vezérlését ellenőrzik, nem a modell szemantikai pontosságát.

prompt_version: `f1-pilot-2`

| chunk_id | státusz | entitás | kapcsolat |
|---|---|---|---|
| `driver-lewis-hamilton#0` | siker | 3 | 2 |
| `driver-lewis-hamilton#1` | siker | 2 | 0 |
| `season-2021-formula-one-world-championship#0` | siker | 0 | 0 |
| `season-2021-formula-one-world-championship#1` | siker | 4 | 3 |
| `team-mercedes-benz-in-formula-one#1` | hiba |  |  |
| `team-mercedes-benz-in-formula-one#2` | siker | 0 | 0 |
| `team-scuderia-ferrari#0` | siker | 1 | 0 |
| `team-scuderia-ferrari#1` | siker | 1 | 0 |
| `driver-nico-rosberg#64` | siker | 0 | 0 |
| `driver-sebastian-vettel#75` | siker | 0 | 0 |

## driver-lewis-hamilton#0

- Dokumentum: Lewis Hamilton

Entitások:

- `e1` Lewis Hamilton (Driver): Sir Lewis Carl Davidson Hamilton is a British racing driver who competes in Formula One.
- `e2` Ferrari (Team): A Formula 1 team that Lewis Hamilton competes for.
- `e3` Title (Title): Seven Formula One World Drivers' Championship titles.

Kapcsolatok:

- `e1` -DROVE_FOR-> `e2`: Lewis Hamilton competes for Ferrari in Formula One.
- `e1` -WON-> `e3`: Lewis Hamilton has won seven Formula One World Drivers' Championship titles.

## driver-lewis-hamilton#1

- Dokumentum: Lewis Hamilton

Entitások:

- `e1` Lewis Hamilton (Driver): Born and raised in Stevenage, Hamilton began his career in karting at age six, winning several national titles.
- `e2` McLaren-Mercedes (Team): Signed Lewis Hamilton to their Young Driver Programme in 1998.

Kapcsolatok: nincs

## season-2021-formula-one-world-championship#0

- Dokumentum: 2021 Formula One World Championship

Entitások: nincs

Kapcsolatok: nincs

## season-2021-formula-one-world-championship#1

- Dokumentum: 2021 Formula One World Championship

Entitások:

- `e1` Max Verstappen (Driver): Driver from the Netherlands who won the Drivers' Championship in 2021.
- `e2` Red Bull Racing-Honda (Team): Formula 1 team that Max Verstappen drove for in 2021.
- `e3` 2021 (Season): The season in which Max Verstappen won the Drivers' Championship.
- `e4` World Drivers' Champion (Title): Championship title won by Max Verstappen in 2021.

Kapcsolatok:

- `e1` -DROVE_FOR-> `e2`: Max Verstappen drove for Red Bull Racing-Honda in 2021.
- `e1` -WON-> `e4`: Max Verstappen won the World Drivers' Champion title in 2021.
- `e4` -AWARDED_IN-> `e3`: The World Drivers' Champion title was awarded in the 2021 season.

## team-mercedes-benz-in-formula-one#1

- Hiba: ExtractionValidationError: DROVE_FOR does not allow Team -> Team Elutasított jelölt mentve; nem számít sikeres eredménynek.

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
