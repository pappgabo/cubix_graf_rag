# Baseline answers (naive RAG)

```json
{
  "run_utc": "2026-10-06T05:19:11.117364+00:00",
  "chat_model": "gpt-4o-mini",
  "embedding_model": "text-embedding-3-small",
  "chunk_size": 500,
  "chunk_overlap": 75,
  "num_chunks": 3576,
  "top_k": 4,
  "note": "default run: chunk 500/75, k=4"
}
```

> Answers are saved exactly as produced. They are NOT corrected.

## simple

### Q01 — simple

**Question:** How many World Drivers' Championships has Lewis Hamilton won?

**Answer:** Lewis Hamilton has won a total of seven World Drivers' Championships, tying the record with Michael Schumacher [S2][S3].

**Sources:**

- [S1] `driver-lewis-hamilton#193` — driver-lewis-hamilton.pdf, page 17 (score 0.6577)
- [S2] `driver-lewis-hamilton#1` — driver-lewis-hamilton.pdf, page 1 (score 0.6543)
- [S3] `reference-formula-one#106` — reference-formula-one.html, n/a (score 0.6531)
- [S4] `season-2020-formula-one-world-championship#5` — season-2020-formula-one-world-championship.html, n/a (score 0.6307)

### Q02 — simple

**Question:** How old was Sebastian Vettel when he became the youngest Formula One World Champion?

**Answer:** Sebastian Vettel was 23 years old when he became the youngest Formula One World Champion [S2].

**Sources:**

- [S1] `driver-sebastian-vettel#27` — driver-sebastian-vettel.docx, n/a (score 0.7503)
- [S2] `driver-sebastian-vettel#5` — driver-sebastian-vettel.docx, n/a (score 0.7415)
- [S3] `driver-sebastian-vettel#1` — driver-sebastian-vettel.docx, n/a (score 0.7236)
- [S4] `driver-sebastian-vettel#35` — driver-sebastian-vettel.docx, n/a (score 0.7012)

### Q03 — simple

**Question:** Who won the 2021 Formula One World Drivers' Championship?

**Answer:** Max Verstappen won the 2021 Formula One World Drivers' Championship after overtaking Lewis Hamilton on the final lap of the last race of the season, becoming the first World Drivers' Champion from the Netherlands [S4].

**Sources:**

- [S1] `team-red-bull-racing#136` — team-red-bull-racing.docx, n/a (score 0.6367)
- [S2] `season-2021-formula-one-world-championship#0` — season-2021-formula-one-world-championship.pdf, page 1 (score 0.63)
- [S3] `season-2020-formula-one-world-championship#5` — season-2020-formula-one-world-championship.html, n/a (score 0.6239)
- [S4] `driver-max-verstappen#4` — driver-max-verstappen.pdf, page 1 (score 0.6227)

## multi-hop

### Q04 — multi-hop

**Question:** Who was the teammate of the 2016 World Drivers' Champion at his team that season?

**Answer:** I cannot answer from the provided documents.

**Sources:**

- [S1] `season-2020-formula-one-world-championship#8` — season-2020-formula-one-world-championship.html, n/a (score 0.6111)
- [S2] `driver-sebastian-vettel#95` — driver-sebastian-vettel.docx, n/a (score 0.5992)
- [S3] `season-2021-formula-one-world-championship#10` — season-2021-formula-one-world-championship.pdf, page 2 (score 0.5911)
- [S4] `team-mercedes-benz-in-formula-one#37` — team-mercedes-benz-in-formula-one.html, n/a (score 0.5902)

### Q05 — multi-hop

**Question:** Which team did the 2012 World Drivers' Champion leave his team for, and in which year did the move take effect?

**Answer:** I cannot answer from the provided documents.

**Sources:**

- [S1] `season-2021-formula-one-world-championship#10` — season-2021-formula-one-world-championship.pdf, page 2 (score 0.6365)
- [S2] `season-2008-formula-one-world-championship#18` — season-2008-formula-one-world-championship.pdf, page 2 (score 0.6269)
- [S3] `season-2012-formula-one-world-championship#20` — season-2012-formula-one-world-championship.txt, n/a (score 0.5833)
- [S4] `driver-lewis-hamilton#71` — driver-lewis-hamilton.pdf, page 6 (score 0.5784)

### Q06 — multi-hop

**Question:** Which two drivers in the corpus hold the record of seven World Championships, and with which teams did each of them win their titles?

**Answer:** The two drivers who hold the record of seven World Championships are Lewis Hamilton and Michael Schumacher. Lewis Hamilton won his titles with McLaren and Mercedes, while Michael Schumacher won his titles with Benetton and Ferrari [S2].

**Sources:**

- [S1] `reference-formula-one#106` — reference-formula-one.html, n/a (score 0.6445)
- [S2] `reference-list-of-formula-one-world-drivers-champions#1` — reference-list-of-formula-one-world-drivers-champions.xlsx, sheet Drivers in corpus (score 0.6376)
- [S3] `season-2020-formula-one-world-championship#2` — season-2020-formula-one-world-championship.html, n/a (score 0.6106)
- [S4] `season-2020-formula-one-world-championship#5` — season-2020-formula-one-world-championship.html, n/a (score 0.589)

### Q07 — multi-hop

**Question:** Fernando Alonso and Lewis Hamilton were teammates once. At which team and in which season, and what was the outcome of that season's championship?

**Answer:** Fernando Alonso and Lewis Hamilton were teammates at McLaren during the 2007 season. That season, both drivers scored four wins each and led the Drivers' Championship for much of the year, but tensions arose between them. Ultimately, Hamilton finished runner-up in the championship, while Alonso's performance led to a mutual termination of his contract with McLaren at the end of the season due to the internal conflicts [S1][S4].

**Sources:**

- [S1] `team-mclaren#84` — team-mclaren.docx, n/a (score 0.6362)
- [S2] `driver-fernando-alonso#47` — driver-fernando-alonso.docx, n/a (score 0.6216)
- [S3] `driver-lewis-hamilton#3` — driver-lewis-hamilton.pdf, page 1 (score 0.6041)
- [S4] `driver-fernando-alonso#40` — driver-fernando-alonso.docx, n/a (score 0.6034)

### Q08 — multi-hop

**Question:** Which driver replaced Nico Rosberg at Mercedes after his retirement, and which team did that driver come from?

**Answer:** Valtteri Bottas replaced Nico Rosberg at Mercedes after his retirement, and he came from the Williams team [S2].

**Sources:**

- [S1] `team-mercedes-benz-in-formula-one#18` — team-mercedes-benz-in-formula-one.html, n/a (score 0.6888)
- [S2] `team-mercedes-benz-in-formula-one#42` — team-mercedes-benz-in-formula-one.html, n/a (score 0.6467)
- [S3] `driver-nico-rosberg#4` — driver-nico-rosberg.html, n/a (score 0.6449)
- [S4] `driver-nico-rosberg#1` — driver-nico-rosberg.html, n/a (score 0.6401)

## global

### Q09 — global

**Question:** Across all the drivers covered in this corpus, who has won the most World Drivers' Championships, and how many?

**Answer:** The drivers who have won the most World Drivers' Championships are Michael Schumacher and Lewis Hamilton, each with seven championships [S1][S2].

**Sources:**

- [S1] `reference-formula-one#106` — reference-formula-one.html, n/a (score 0.6942)
- [S2] `reference-list-of-formula-one-world-drivers-champions#1` — reference-list-of-formula-one-world-drivers-champions.xlsx, sheet Drivers in corpus (score 0.6853)
- [S3] `season-2020-formula-one-world-championship#2` — season-2020-formula-one-world-championship.html, n/a (score 0.6479)
- [S4] `season-2020-formula-one-world-championship#94` — season-2020-formula-one-world-championship.html, n/a (score 0.6369)

### Q10 — global

**Question:** Which drivers in this corpus have driven for Scuderia Ferrari at some point in their career?

**Answer:** The drivers who have driven for Scuderia Ferrari at some point in their career, according to the provided context, are:

1. Sebastian Vettel
2. Michael Schumacher
3. Kimi Räikkönen

These drivers are mentioned in the context as having been associated with Ferrari during their careers [S2].

**Sources:**

- [S1] `team-scuderia-ferrari#66` — team-scuderia-ferrari.pdf, page 6 (score 0.5895)
- [S2] `reference-list-of-formula-one-world-drivers-champions#1` — reference-list-of-formula-one-world-drivers-champions.xlsx, sheet Drivers in corpus (score 0.5704)
- [S3] `team-scuderia-ferrari#68` — team-scuderia-ferrari.pdf, page 7 (score 0.5453)
- [S4] `team-scuderia-ferrari#5` — team-scuderia-ferrari.pdf, page 1 (score 0.542)

### Q11 — global

**Question:** Which constructor has won the most Drivers' Championships according to the documents, and how many titles is that?

**Answer:** I cannot answer from the provided documents.

**Sources:**

- [S1] `team-williams-racing#3` — team-williams-racing.html, n/a (score 0.6359)
- [S2] `reference-list-of-formula-one-world-drivers-champions#1` — reference-list-of-formula-one-world-drivers-champions.xlsx, sheet Drivers in corpus (score 0.626)
- [S3] `team-renault-in-formula-one#165` — team-renault-in-formula-one.txt, n/a (score 0.6182)
- [S4] `season-2020-formula-one-world-championship#2` — season-2020-formula-one-world-championship.html, n/a (score 0.6107)

### Q12 — global

**Question:** Group the World Champions among the corpus drivers by decade (2000s, 2010s, 2020s).

**Answer:** I cannot answer from the provided documents.

**Sources:**

- [S1] `season-2020-formula-one-world-championship#94` — season-2020-formula-one-world-championship.html, n/a (score 0.5474)
- [S2] `season-2016-formula-one-world-championship#89` — season-2016-formula-one-world-championship.docx, n/a (score 0.5284)
- [S3] `season-2020-formula-one-world-championship#2` — season-2020-formula-one-world-championship.html, n/a (score 0.5283)
- [S4] `reference-formula-one#105` — reference-formula-one.html, n/a (score 0.5273)

### Q13 — global

**Question:** What common factors explain why specific teams such as Ferrari, Mercedes and Red Bull dominated particular eras of Formula One?

**Answer:** I cannot answer from the provided documents.

**Sources:**

- [S1] `reference-formula-one#55` — reference-formula-one.html, n/a (score 0.5692)
- [S2] `reference-formula-one#60` — reference-formula-one.html, n/a (score 0.54)
- [S3] `team-scuderia-ferrari#5` — team-scuderia-ferrari.pdf, page 1 (score 0.535)
- [S4] `reference-formula-one#152` — reference-formula-one.html, n/a (score 0.534)
