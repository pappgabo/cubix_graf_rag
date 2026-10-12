"""
Downloads a Formula 1 corpus from the English Wikipedia for the Week 1
Naive RAG baseline project.

The corpus is intentionally built around interconnected entities
(drivers <-> teams <-> seasons) so that it supports:
  - multi-hop questions (facts spread across 2+ articles), and
  - global questions (answered by aggregating over the whole corpus).

Output:
  corpus/<slug>.txt        one plain-text document per article, with a
                           small source header (title, url, revision, date)
  corpus/metadata.json     machine-readable source metadata for all docs
"""

import json
import time
import urllib.parse
import urllib.request
import urllib.error
import re
import datetime
from pathlib import Path

# --- Configuration ---------------------------------------------------------

API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "GraphRAG-Course-Week1-Corpus/1.0 (educational use)"

# Articles grouped by role. The grouping is only used for metadata;
# every article is downloaded the same way.
ARTICLES = {
    "driver": [
        "Lewis Hamilton",
        "Max Verstappen",
        "Sebastian Vettel",
        "Fernando Alonso",
        "Michael Schumacher",
        "Kimi Räikkönen",
        "Nico Rosberg",
        "Jenson Button",
        "Charles Leclerc",
        "Valtteri Bottas",
    ],
    "team": [
        "Mercedes-Benz in Formula One",
        "Scuderia Ferrari",
        "Red Bull Racing",
        "McLaren",
        "Williams Racing",
        "Renault in Formula One",
    ],
    "season": [
        "2008 Formula One World Championship",
        "2012 Formula One World Championship",
        "2016 Formula One World Championship",
        "2020 Formula One World Championship",
        "2021 Formula One World Championship",
    ],
    "reference": [
        "Formula One",
        "List of Formula One World Drivers' Champions",
    ],
}

OUT_DIR = Path(__file__).resolve().parent.parent / "corpus"


# --- Helpers ---------------------------------------------------------------

def slugify(title: str) -> str:
    s = title.lower()
    s = s.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("é", "e")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def api_get(params: dict, max_retries: int = 6) -> dict:
    params = {**params, "format": "json"}
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    delay = 2.0
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < max_retries - 1:
                wait = delay * (2 ** attempt)
                print(f"    429 rate limited, waiting {wait:.0f}s ...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("exceeded retries")


def fetch_article(title: str) -> dict:
    """Return dict with resolved title, extract text, url, revision id."""
    data = api_get({
        "action": "query",
        "prop": "extracts|info|revisions",
        "explaintext": 1,
        "redirects": 1,
        "inprop": "url",
        "rvprop": "ids|timestamp",
        "titles": title,
    })
    pages = data["query"]["pages"]
    page = next(iter(pages.values()))
    if "missing" in page:
        raise RuntimeError(f"Article not found: {title}")
    rev = page.get("revisions", [{}])[0]
    return {
        "requested_title": title,
        "title": page.get("title", title),
        "pageid": page.get("pageid"),
        "url": page.get("canonicalurl") or page.get("fullurl"),
        "revid": rev.get("revid"),
        "rev_timestamp": rev.get("timestamp"),
        "extract": page.get("extract", ""),
    }


# --- Main ------------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    retrieved = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata = []

    for category, titles in ARTICLES.items():
        for title in titles:
            # Skip if already downloaded (resume support).
            pre_slug = slugify(title)
            pre_path = OUT_DIR / f"{category}-{pre_slug}.txt"
            if pre_path.exists() and pre_path.stat().st_size > 500:
                print(f"  [SKIP] {category}-{pre_slug} (already present)")
                continue

            try:
                art = fetch_article(title)
            except Exception as exc:  # noqa: BLE001
                print(f"  [FAIL] {title}: {exc}")
                continue

            slug = slugify(art["title"])
            doc_id = f"{category}-{slug}"
            filename = f"{doc_id}.txt"
            path = OUT_DIR / filename

            header = (
                f"# {art['title']}\n"
                f"doc_id: {doc_id}\n"
                f"category: {category}\n"
                f"source: Wikipedia (English)\n"
                f"url: {art['url']}\n"
                f"revision_id: {art['revid']}\n"
                f"revision_timestamp: {art['rev_timestamp']}\n"
                f"retrieved_utc: {retrieved}\n"
                f"license: CC BY-SA 4.0\n"
                f"{'=' * 70}\n\n"
            )
            path.write_text(header + art["extract"], encoding="utf-8")
            words = len(art["extract"].split())
            print(f"  [ OK ] {doc_id:45s} {words:6d} words")
            time.sleep(1.5)  # be polite to the API

    # Rebuild metadata.json from the headers of every downloaded document,
    # so resumed/skipped files are included too.
    for path in sorted(OUT_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        head, _, body = text.partition("=" * 70)
        meta = {"file": path.name}
        for line in head.splitlines():
            if ": " in line and not line.startswith("#"):
                key, _, val = line.partition(": ")
                meta[key.strip()] = val.strip()
        meta["title"] = head.splitlines()[0].lstrip("# ").strip()
        meta["word_count"] = len(body.split())
        metadata.append(meta)

    (OUT_DIR / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total_words = sum(m["word_count"] for m in metadata)
    print(f"\nDone. {len(metadata)} documents, {total_words} words total.")
    print(f"Output: {OUT_DIR}")


if __name__ == "__main__":
    main()
