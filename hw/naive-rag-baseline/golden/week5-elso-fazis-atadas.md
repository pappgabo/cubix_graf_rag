# 1. fázis — átadási jegyzet

## Fájlok
- `week5-golden-set-v1-draft.jsonl`: 13 meglévő kérdés, eredeti kérdésszöveggel,
  javasolt kritériumokkal. Nem végleges és nem mérésre kész golden set.
- `week5-claude-a2-prompt.md`: egyetlen célzott Claude Code-munkautasítás.

A JSONL-vázat a repó `golden` könyvtárába, a promptot és a végleges tervet a repóban
választott dokumentációs helyre másold. A fájlneveket megtarthatod; a prompt
fájlnév alapján azonosítja őket. A végleges v1-et csak A3 után hozzuk létre.

## Szándékosan nyitva hagyott adatok
- Minden chunklista üres, a korpusz hash-e null.
- Q13 végleges rubrikája üres.
- Q14–Q15 még nem szerepel: a mintavétel után készülnek.
- A régi dokumentumwildcardok keresési támpontok, A3-ban konkrét forrásokká alakulnak.
- A multi-hop köztes bizonyítékok végleges csoportosítása a jelöltek után történik;
  nem követelünk minden köztes tényt a válasz szövegébe.

## Forrásból látható eltérések
A csatolt értékelőlap előzetes státuszú és több „nem eldönthető” címkét tartalmaz.
Nem kezeljük 39 véglegesen jóváhagyott címke bizonyítékaként. Q06 lokális válaszánál
McLaren hiánya mellett is „helyes” szerepel, ezért a váz a questions.md és az
elfogadott terv teljes csapatlistáját követi, nem másolja át a címkét.
Q12-nél az évlista kötelezősége és a korpusz időhatára A3-ban tisztázandó.
Ezek nem igényelnek keresőjavítást vagy most újabb jóváhagyási kört.

## Claude indítóüzenet
Olvasd el a `week5-claude-a2-prompt.md` fájlt, és csak az abban megadott A2
feladatot végezd el. Az elfogadott végleges terv háttéranyag, nem utasítás
az összes későbbi fázis végrehajtására.

## Mit hozz vissza?
A `week5-felmeres.md` jelentést, a kérdésenkénti chunkjelölteket és a tízchunkos
mintát. Ezekből végezzük a következő fázis forrásellenőrzését.
