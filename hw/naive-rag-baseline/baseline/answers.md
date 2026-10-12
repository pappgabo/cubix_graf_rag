# Baseline answers (naive RAG)

```json
{
  "run_utc": "2026-10-06T06:58:59.248509+00:00",
  "chat_model": "gpt-4o-mini",
  "embedding_model": "text-embedding-3-small",
  "chunk_size": 500,
  "chunk_overlap": 75,
  "num_chunks": 3832,
  "top_k": 4,
  "note": "v2: pandoc/markdownify loaders + heading-aware sections, clean index, chunk 500/75, k=4"
}
```

> Answers are saved exactly as produced. They are NOT corrected.

## simple

### Q01 — simple

**Question:** How many World Drivers' Championships has Lewis Hamilton won?

**Answer:** Lewis Hamilton has won seven World Drivers' Championships, which ties him with Michael Schumacher for the most championships in history [S1][S3].

**Sources:**

- [S1] `driver-lewis-hamilton#0` — driver-lewis-hamilton.pdf, page 1 (score 0.6898)
- [S2] `driver-lewis-hamilton#192` — driver-lewis-hamilton.pdf, page 17 (score 0.6577)
- [S3] `reference-formula-one#112` — reference-formula-one.html, section: Formula One > Drivers (score 0.653)
- [S4] `season-2020-formula-one-world-championship#5` — season-2020-formula-one-world-championship.html, section: 2020 Formula One World Championship (score 0.6308)

### Q02 — simple

**Question:** How old was Sebastian Vettel when he became the youngest Formula One World Champion?

**Answer:** Sebastian Vettel was 23 years old when he became the youngest Formula One World Champion [S2][S3].

**Sources:**

- [S1] `driver-sebastian-vettel#32` — driver-sebastian-vettel.docx, section: 2007–2008: Maiden race win and rise to prominence (score 0.7503)
- [S2] `driver-sebastian-vettel#4` — driver-sebastian-vettel.docx, n/a (score 0.7415)
- [S3] `driver-sebastian-vettel#0` — driver-sebastian-vettel.docx, n/a (score 0.724)
- [S4] `driver-sebastian-vettel#41` — driver-sebastian-vettel.docx, section: 2010: Youngest World Champion (score 0.7012)

### Q03 — simple

**Question:** Who won the 2021 Formula One World Drivers' Championship?

**Answer:** Max Verstappen of Red Bull Racing-Honda won the 2021 Formula One World Drivers' Championship for the first time in his career, having claimed 10 race wins across the season [S3].

**Sources:**

- [S1] `season-2020-formula-one-world-championship#0` — season-2020-formula-one-world-championship.html, section: 2020 Formula One World Championship (score 0.6797)
- [S2] `season-2021-formula-one-world-championship#0` — season-2021-formula-one-world-championship.pdf, page 1 (score 0.6658)
- [S3] `season-2021-formula-one-world-championship#1` — season-2021-formula-one-world-championship.pdf, page 1 (score 0.6279)
- [S4] `season-2020-formula-one-world-championship#5` — season-2020-formula-one-world-championship.html, section: 2020 Formula One World Championship (score 0.6239)

## multi-hop

### Q04 — multi-hop

**Question:** Who was the teammate of the 2016 World Drivers' Champion at his team that season?

**Answer:** The 2016 World Drivers' Champion was Nico Rosberg, and his teammate that season at Mercedes was Lewis Hamilton [S1][S4].

**Sources:**

- [S1] `driver-lewis-hamilton#3` — driver-lewis-hamilton.pdf, page 1 (score 0.6025)
- [S2] `driver-sebastian-vettel#103` — driver-sebastian-vettel.docx, section: 2019–2020: Decline and departure from Ferrari (score 0.5993)
- [S3] `season-2021-formula-one-world-championship#9` — season-2021-formula-one-world-championship.pdf, page 2 (score 0.5911)
- [S4] `team-mercedes-benz-in-formula-one#40` — team-mercedes-benz-in-formula-one.html, section: Mercedes-Benz in Formula One > Eight consecutive Constructors' titles (2014–2021) (score 0.5902)

### Q05 — multi-hop

**Question:** Which team did the 2012 World Drivers' Champion leave his team for, and in which year did the move take effect?

**Answer:** The 2012 World Drivers' Champion, Kimi Räikkönen, returned to the sport after two seasons competing in the World Rally Championship, but the context does not specify which team he left or the year of his move. Therefore, I cannot answer from the provided documents.

**Sources:**

- [S1] `season-2021-formula-one-world-championship#9` — season-2021-formula-one-world-championship.pdf, page 2 (score 0.6365)
- [S2] `season-2008-formula-one-world-championship#17` — season-2008-formula-one-world-championship.pdf, page 2 (score 0.6268)
- [S3] `season-2012-formula-one-world-championship#21` — season-2012-formula-one-world-championship.txt, section: Teams and drivers > Driver changes (score 0.5833)
- [S4] `driver-lewis-hamilton#70` — driver-lewis-hamilton.pdf, page 6 (score 0.5784)

### Q06 — multi-hop

**Question:** Which two drivers in the corpus hold the record of seven World Championships, and with which teams did each of them win their titles?

**Answer:** The two drivers who hold the record of seven World Championships are Michael Schumacher and Lewis Hamilton. Michael Schumacher won his titles with Benetton and Ferrari, while Lewis Hamilton won his titles with McLaren and Mercedes [S1][S2].

**Sources:**

- [S1] `reference-formula-one#112` — reference-formula-one.html, section: Formula One > Drivers (score 0.6445)
- [S2] `reference-list-of-formula-one-world-drivers-champions#1` — reference-list-of-formula-one-world-drivers-champions.xlsx, section: sheet Drivers in corpus (score 0.6376)
- [S3] `season-2020-formula-one-world-championship#2` — season-2020-formula-one-world-championship.html, section: 2020 Formula One World Championship (score 0.6105)
- [S4] `season-2020-formula-one-world-championship#5` — season-2020-formula-one-world-championship.html, section: 2020 Formula One World Championship (score 0.589)

### Q07 — multi-hop

**Question:** Fernando Alonso and Lewis Hamilton were teammates once. At which team and in which season, and what was the outcome of that season's championship?

**Answer:** Fernando Alonso and Lewis Hamilton were teammates at McLaren during the 2007 season. Both drivers scored four wins each and led the Drivers' Championship for much of the year, but Alonso ultimately finished the season in third place, while Hamilton finished second, losing the championship to Kimi Räikkönen. Tensions between Alonso and Hamilton were notable throughout the season, leading to Alonso's departure from the team by mutual consent in November [S1][S3].

**Sources:**

- [S1] `team-mclaren#86` — team-mclaren.docx, section: 1995–2009: Factory Mercedes partnership (score 0.6403)
- [S2] `driver-fernando-alonso#48` — driver-fernando-alonso.docx, section: Ferrari (2010–2014) (score 0.6216)
- [S3] `driver-fernando-alonso#41` — driver-fernando-alonso.docx, section: McLaren and second stint with Renault (2007–2009) (score 0.6033)
- [S4] `team-mclaren#111` — team-mclaren.docx, section: 2015–2017: Return to Honda engines (score 0.5827)

### Q08 — multi-hop

**Question:** Which driver replaced Nico Rosberg at Mercedes after his retirement, and which team did that driver come from?

**Answer:** Valtteri Bottas replaced Nico Rosberg at Mercedes after his retirement, and he came from the Williams team [S3].

**Sources:**

- [S1] `team-mercedes-benz-in-formula-one#21` — team-mercedes-benz-in-formula-one.html, section: Mercedes-Benz in Formula One > Mercedes-AMG Petronas Formula One Team (2010–present) (score 0.6888)
- [S2] `driver-nico-rosberg#0` — driver-nico-rosberg.html, section: Nico Rosberg (score 0.663)
- [S3] `team-mercedes-benz-in-formula-one#45` — team-mercedes-benz-in-formula-one.html, section: Mercedes-Benz in Formula One > Eight consecutive Constructors' titles (2014–2021) (score 0.6467)
- [S4] `driver-nico-rosberg#3` — driver-nico-rosberg.html, section: Nico Rosberg (score 0.6449)

## global

### Q09 — global

**Question:** Across all the drivers covered in this corpus, who has won the most World Drivers' Championships, and how many?

**Answer:** The drivers who have won the most World Drivers' Championships are Michael Schumacher and Lewis Hamilton, each with seven championships [S1][S2].

**Sources:**

- [S1] `reference-formula-one#112` — reference-formula-one.html, section: Formula One > Drivers (score 0.6942)
- [S2] `reference-list-of-formula-one-world-drivers-champions#1` — reference-list-of-formula-one-world-drivers-champions.xlsx, section: sheet Drivers in corpus (score 0.6853)
- [S3] `season-2020-formula-one-world-championship#2` — season-2020-formula-one-world-championship.html, section: 2020 Formula One World Championship (score 0.6478)
- [S4] `reference-formula-one#113` — reference-formula-one.html, section: Formula One > Drivers (score 0.6292)

### Q10 — global

**Question:** Which drivers in this corpus have driven for Scuderia Ferrari at some point in their career?

**Answer:** The drivers who have driven for Scuderia Ferrari at some point in their career, according to the provided context, are:

1. Sebastian Vettel
2. Michael Schumacher
3. Kimi Räikkönen

These drivers are mentioned in the context as having been associated with Ferrari during their careers [S2].

**Sources:**

- [S1] `team-scuderia-ferrari#66` — team-scuderia-ferrari.pdf, page 6 (score 0.5895)
- [S2] `reference-list-of-formula-one-world-drivers-champions#1` — reference-list-of-formula-one-world-drivers-champions.xlsx, section: sheet Drivers in corpus (score 0.5704)
- [S3] `team-scuderia-ferrari#68` — team-scuderia-ferrari.pdf, page 7 (score 0.5454)
- [S4] `team-scuderia-ferrari#8` — team-scuderia-ferrari.pdf, page 1 (score 0.5311)

### Q11 — global

**Question:** Which constructor has won the most Drivers' Championships according to the documents, and how many titles is that?

**Answer:** I cannot answer from the provided documents.

**Sources:**

- [S1] `team-williams-racing#2` — team-williams-racing.html, section: Williams Racing (score 0.6359)
- [S2] `reference-list-of-formula-one-world-drivers-champions#1` — reference-list-of-formula-one-world-drivers-champions.xlsx, section: sheet Drivers in corpus (score 0.626)
- [S3] `team-renault-in-formula-one#161` — team-renault-in-formula-one.txt, section: Formula One results > As a chassis constructor (score 0.6141)
- [S4] `season-2020-formula-one-world-championship#2` — season-2020-formula-one-world-championship.html, section: 2020 Formula One World Championship (score 0.6107)

### Q12 — global

**Question:** Group the World Champions among the corpus drivers by decade (2000s, 2010s, 2020s).

**Answer:** Based on the provided context, the World Champions among the corpus drivers can be grouped by decade as follows:

**2000s:**
- Michael Schumacher (7 titles)
- Fernando Alonso (2 titles)

**2010s:**
- Lewis Hamilton (7 titles)
- Nico Rosberg (1 title)
- Sebastian Vettel (4 titles)

**2020s:**
- Max Verstappen (4 titles)

This grouping is based on the information from the drivers' titles in the context [S3].

**Sources:**

- [S1] `season-2020-formula-one-world-championship#2` — season-2020-formula-one-world-championship.html, section: 2020 Formula One World Championship (score 0.5283)
- [S2] `reference-formula-one#111` — reference-formula-one.html, section: Formula One > Drivers (score 0.5273)
- [S3] `reference-list-of-formula-one-world-drivers-champions#1` — reference-list-of-formula-one-world-drivers-champions.xlsx, section: sheet Drivers in corpus (score 0.5259)
- [S4] `season-2020-formula-one-world-championship#8` — season-2020-formula-one-world-championship.html, section: 2020 Formula One World Championship (score 0.5258)

### Q13 — global

**Question:** What common factors explain why specific teams such as Ferrari, Mercedes and Red Bull dominated particular eras of Formula One?

**Answer:** I cannot answer from the provided documents.

**Sources:**

- [S1] `reference-formula-one#57` — reference-formula-one.html, section: Formula One > Hybrid era (score 0.5697)
- [S2] `team-red-bull-racing#1` — team-red-bull-racing.docx, n/a (score 0.542)
- [S3] `reference-formula-one#62` — reference-formula-one.html, section: Formula One > Hybrid era (score 0.54)
- [S4] `reference-formula-one#159` — reference-formula-one.html, section: Formula One > Cost cap (score 0.5348)
