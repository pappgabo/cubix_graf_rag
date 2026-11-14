# Közösségréteg mentése Neo4j-be

A `docs/week4-vetulet-leképezés.json` előkészített (`elokeszitett`) vetületének
közösségei bekerültek Neo4j-be, a `src/naive_rag/community_load.py` kapuzott
(`--preflight` / `--apply --backup`) útvonalán keresztül. A Leiden nem futott
újra; a forrás a már meglévő mapping-artifact.

## Futás azonosítója

```
run_id = week4-leiden-elokeszitett-6f05327d7d88ebf0
```

A `run_id` determinisztikus ujjlenyomat (projection hash + Leiden-paraméterek
+ a kanonikus node→path hozzárendelés hash-e); `community_id` formátuma
`"{run_id}:{path}"`, így egy másik futás soha nem írja felül ezt a réteget.

## Felhasznált backup

```
graph/corpus/extracted-layer-backup-week4-community-preflight-20261110.json
```

Az írás előtt ezzel futtatott preflight (`entity_alignment.ok=True`,
`backup_check.ok=True`, `key_sets_match=True`, `edge_count_matches=True`)
sikeres volt.

## Mért darabszámok (élőben, írás után, függetlenül ellenőrizve)

| Elem | Darabszám |
|---|---:|
| `CommunityRun` | 1 |
| `Community` összesen | 520 |
| — szint 0 / 1 / 2 / 3 | 37 / 176 / 253 / 54 |
| `HAS_COMMUNITY` | 520 |
| `MEMBER_OF` | 1909 |
| `PARENT_OF` | 483 |

## Forrásgráf-pillanatkép

Az írás előtti és utáni `:Extracted` csomópontszám és a 18 domain-reláció
típusonkénti száma (`ACHIEVED`, `AT_RACE`, `AWARDED_IN`, `CONTAINS`,
`DROVE_FOR`, `ENTERED`, `FIELDED`, `FOR_TEAM`, `HAS_DOCUMENT`, `HAS_SECTION`,
`HELD_AT`, `MENTIONS`, `NEXT_CHUNK`, `POWERED_BY`, `RACED_IN`, `ROUND_OF`,
`TEAMMATE_OF`, `WON`) **pontosan megegyezett** (2761 `:Extracted` csomópont
mindkét méréskor) — a forrásgráf a közösségréteg hozzáadása közben
változatlan maradt.
