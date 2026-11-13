"""Gold-derived evidence labels. Used only to score a selection, never as
an input to one.

Each hop of a Q01-Q08 gold answer is a set of alternatives. An alternative
holds when every ``s`` pattern matches inside one sentence (or one table
row) of the chunk and every ``c`` pattern matches the whole chunk or its
document id; a season page states its year in the title, and a driver page
often says "he" instead of the name. Text is casefolded and whitespace is
collapsed. The labels approximate "this chunk states the hop".
`02_evidence_audit.py` lists every accepted chunk for manual review; the
review notes are in README.md. Global questions (Q09-Q13) have no labels:
their gold is an aggregation, not a chain.

The labels were written from the gold text in questions.md before any
selection policy was scored, and they are not changed per policy.
"""

from __future__ import annotations

import re

MATE = r"team-?mates?\b|team mates?\b|team(?:ed)? up\b"
WIN = r"\b(?:won|wins?|winning|clinch\w*|secur\w*|beat|defeat\w*)\b"
TITLE_NOT_LEAD = r"(?:titles?|championships?)\b(?! lead)"
SEVEN = r"\bseven\b|\b7\b"

HOPS: dict[str, dict[str, list[dict]]] = {
    "Q01": {
        "hamilton seven titles": [
            {"s": [r"hamilton", SEVEN, r"titles|championships"]},
            {"s": [r"lewis hamilton \| british \| 7\b"]},
        ],
    },
    "Q02": {
        "vettel youngest champion at 23": [
            {"s": [r"youngest", r"champion", r"\b23\b|twenty-three"], "c": [r"vettel"]},
        ],
    },
    "Q03": {
        "verstappen won 2021 title": [
            {"s": [r"verstappen\b[^.]{0,60}" + WIN + r"[^.]{0,60}" + TITLE_NOT_LEAD],
             "c": [r"2021"]},
            {"s": [r"max verstappen \(2021"]},
        ],
    },
    "Q04": {
        "rosberg won 2016 title": [
            {"s": [r"rosberg\b[^.]{0,60}" + WIN + r"[^.]{0,80}" + TITLE_NOT_LEAD],
             "c": [r"2016"]},
            {"s": [WIN + r"[^.]{0,30}2016 (?:title|world|drivers|championship)"],
             "c": [r"rosberg"]},
            {"s": [r"nico rosberg \(2016\)|2016 \| nico rosberg"]},
        ],
        "hamilton was his 2016 teammate": [
            {"s": [r"rosberg", r"hamilton", MATE], "c": [r"2016"]},
            {"s": [r"hamilton", MATE, r"2013 (?:to|–|-) ?2016"], "c": [r"rosberg"]},
            {"s": [r"rosberg", MATE, r"2013 (?:to|–|-) ?2016"]},
        ],
    },
    "Q05": {
        "vettel won 2012 title": [
            {"s": [r"vettel\b[^.]{0,80}" + WIN + r"[^.]{0,60}" + TITLE_NOT_LEAD],
             "c": [r"2012"]},
            {"s": [r"\bwon\b[^.]{0,60}championships in 2011 and 2012"], "c": [r"vettel"]},
            {"s": [r"sebastian vettel \([0-9, ]*2012"]},
            {"s": [r"2012 \| sebastian vettel"]},
        ],
        "vettel left red bull for ferrari": [
            {"s": [r"vettel", r"ferrari", r"red bull|leav\w*|left\b", r"join\w*|sign\w*|move\w*|switch\w*"]},
        ],
        "ferrari move effective 2015": [
            {"s": [r"ferrari", r"2015"], "c": [r"vettel"],
             "s2": [r"debut|2015[–-]2020|join\w*|sign\w*|replac\w*"]},
        ],
    },
    "Q06": {
        "hamilton seven titles": [
            {"s": [r"hamilton", SEVEN, r"titles|championships"]},
            {"s": [r"lewis hamilton \| british \| 7\b"]},
        ],
        "schumacher seven titles": [
            {"s": [r"schumacher", SEVEN, r"titles|championships"]},
            {"s": [r"michael schumacher \| german \| 7\b"]},
        ],
        "schumacher benetton titles": [
            {"s": [r"benetton", r"titles?\b|champion", r"1994|1995"], "c": [r"schumacher"]},
        ],
        "schumacher ferrari titles": [
            {"s": [r"ferrari", TITLE_NOT_LEAD, r"2000|2001|2002|2003|2004|five consecutive"],
             "c": [r"schumacher"]},
        ],
        "hamilton mclaren 2008 title": [
            {"s": [r"mclaren", r"2008", r"titles?\b|champion"], "c": [r"hamilton"]},
            {"s": [r"2008 \| lewis hamilton \| mclaren"]},
        ],
        "hamilton mercedes titles": [
            {"s": [r"mercedes", WIN + r"[^.]{0,80}(?:drivers'? )?(?:world )?" + TITLE_NOT_LEAD,
                   r"2014|2015|2017|2018|2019|2020"], "c": [r"hamilton"]},
            {"s": [r"lewis hamilton \(2014"]},
        ],
    },
    "Q07": {
        "alonso and hamilton teammates at mclaren 2007": [
            {"s": [r"alonso", r"hamilton", MATE + r"|alongside|partner\w*"],
             "c": [r"mclaren", r"2007"]},
        ],
        "raikkonen won the 2007 title": [
            {"s": [r"r(?:ä|a)ikk(?:ö|o)nen", r"champion|title|\bwon\b"], "c": [r"2007"],
             "s2": [r"2007|point"]},
        ],
    },
    "Q08": {
        "bottas replaced rosberg at mercedes": [
            {"s": [r"bottas", r"rosberg", r"replac\w*|succe\w*|in place of"]},
            {"s": [r"rosberg\W*s?\b[^.]{0,40}retire\w*", r"bottas", r"sign\w*|join\w*|releas\w*"]},
        ],
        "bottas came from williams": [
            {"s": [r"williams driver valtteri bottas|williams' valtteri bottas"]},
            {"s": [r"bottas", r"williams", r"remain\w*|releas\w*|left\b|leav\w*"],
             "c": [r"mercedes"]},
            {"s": [r"bottas", r"releas\w*", r"mercedes"], "c": [r"williams"]},
        ],
    },
}

# (question, hop, chunk id) -> reason. Lexical matches that a reader of the
# matched sentence would not accept as stating the hop. Filled from the
# manual review of results/02_evidence_audit.json, before any policy score.
REJECTED: dict[tuple[str, str, str], str] = {
    ("Q04", "rosberg won 2016 title", "season-2016-formula-one-world-championship#94"):
        "conditional: 'if Hamilton won the race, Rosberg needed to finish third'",
    ("Q05", "vettel won 2012 title", "season-2012-formula-one-world-championship#219"):
        "speculation that the title was threatened",
    ("Q05", "vettel won 2012 title", "season-2012-formula-one-world-championship#98"):
        "championship lead after a race, not the title",
    ("Q06", "schumacher ferrari titles", "team-williams-racing#164"):
        "Ralf Schumacher, constructors' standings",
    ("Q06", "hamilton mclaren 2008 title", "driver-jenson-button#86"):
        "names Hamilton as 2008 champion, not the team he won it with",
    ("Q06", "hamilton mercedes titles", "reference-formula-one#57"):
        "Mercedes titles without Hamilton in the sentence",
    ("Q06", "hamilton mercedes titles", "season-2020-formula-one-world-championship#6"):
        "team championship statement, no Hamilton title",
    ("Q06", "hamilton mercedes titles", "team-mercedes-benz-in-formula-one#45"):
        "constructors' championship",
    ("Q07", "raikkonen won the 2007 title", "driver-kimi-raikkonen#243"):
        "snowmobile race in March 2007",
}

_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def flat(text: str) -> str:
    return " ".join(text.casefold().replace("\u2019", "'").split())


def sentences(text: str) -> list[str]:
    return [flat(part) for part in _SENT.split(text) if part.strip()]


def _alternative(alt: dict, text: str, doc_id: str) -> str | None:
    whole = flat(text) + " " + (doc_id or "")
    if not all(re.search(p, whole) for p in alt.get("c", [])):
        return None
    for sentence in sentences(text):
        if all(re.search(p, sentence) for p in alt["s"]) and all(
                re.search(p, sentence) for p in alt.get("s2", [])):
            return sentence
    return None


def matching_sentence(alternatives: list[dict], text: str,
                      doc_id: str) -> str | None:
    for alt in alternatives:
        found = _alternative(alt, text, doc_id)
        if found is not None:
            return found
    return None


def matches(alternatives: list[dict], text: str, doc_id: str) -> bool:
    return matching_sentence(alternatives, text, doc_id) is not None


def evidence_sets(texts: dict[str, str], meta: dict[str, dict]
                  ) -> dict[str, dict[str, set[str]]]:
    """question -> hop -> chunk ids in the whole corpus that match and were
    not rejected by the manual review."""
    return {
        qid: {
            hop: {cid for cid, text in texts.items()
                  if (qid, hop, cid) not in REJECTED
                  and matches(alts, text, meta[cid]["doc_id"])}
            for hop, alts in hops.items()
        }
        for qid, hops in HOPS.items()
    }


def coverage(selected: set[str], sets: dict[str, set[str]]) -> dict[str, bool]:
    return {hop: bool(selected & ids) for hop, ids in sets.items()}
