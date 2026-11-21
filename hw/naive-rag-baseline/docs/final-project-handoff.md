Aktuális feladat: M2/J2
J1 lezárva sikertelen kísérletként. Nem nyitjuk újra.

J2 célzott diagnózis: Q04 / naiv.

Bizonyított:

a kérdés explicit 2016-os évszámot tartalmaz;
baseline correctness: elutasított;
baseline retrieval ratio: 0;
a gold chunkok nem kerültek a tényleges top-4-be;
a top-4 helyette 2021-es és Bottas/Mercedes tartalmat hozott;
a baseline mérési kódút: run_phase5.run_naiv.
J2 hipotézis: pontosan egy 1000–2999 közötti explicit évszám esetén:

egyetlen vector retrieval;
candidate_k=12;
exact-year match alapján stabil reranking;
original score változatlan;
végső kontextus továbbra is top_k=4. Nulla vagy több különböző évszámnál baseline top-4 változatlan.
J2 offline implementáció a következő feladat. Fizetős Q04 pilot csak külön felhasználói engedéllyel indulhat.

Stop-szabály: egy hipotézis → egy implementáció → egy pilot → siker esetén egy full. Sikertelen pilot után nincs top-20/top-50, új boost vagy tuningkör.