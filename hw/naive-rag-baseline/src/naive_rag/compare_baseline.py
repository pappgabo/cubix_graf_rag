"""Baseline comparison scaffold.

The baseline file is read and copied into the comparison by citation.
Local answers stay marked as not run until a result object is supplied.
This module does not call a model.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_baseline(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def render_comparison(baseline: dict, local_results: dict | None = None) -> str:
    meta = baseline.get("meta", {})
    local_results = local_results or {}
    lines = [
        "# Baseline és lokális keresés",
        "",
        "A baseline eredeti futása változatlanul a `baseline/answers.json` "
        "fájlban van. Ez a fájl nem írja felül.",
        "",
        f"- Baseline időpont: {meta.get('run_utc')}",
        f"- Baseline chat modell: {meta.get('chat_model')}",
        f"- Baseline embedding: {meta.get('embedding_model')}",
        f"- Baseline chunk: {meta.get('chunk_size')}/{meta.get('chunk_overlap')}, "
        f"top_k={meta.get('top_k')}, chunkok={meta.get('num_chunks')}",
        f"- Baseline megjegyzés: {meta.get('note')}",
        "",
        (
            "A lenti lokális válaszok a Q01–Q08 kör gráfján lefutottak. "
            "Elutasítás vagy azonos eredmény érvényes eredmény. "
            "GraphRAG-fölény nincs állítva."
            if local_results else
            "A lokális keresés válaszai csak akkor szerepelnek, ha egy külön "
            "futtatás átadja őket. Amíg ez nincs meg, az értékelés nem állít "
            "javulást."
        ),
        "",
        "A baseline futás 3832 chunkot rögzített, 23 dokumentummal. "
        "A jelenlegi `load_and_chunk` eredménye 3639 chunk, 22 dokumentum; "
        "a `driver-charles-leclerc.html` hiányzik. A 193 chunkos eltérés "
        "oka és hatása nincs tisztázva. Ez az összevetés ezért nem "
        "azonos korpuszon végzett, kontrollált összehasonlítás.",
        "",
        "## Q01–Q08",
        "",
        "Ezeknek a kérdéseknek a dokumentumai jelölték ki az extrakciós "
        "kört. A multi-hop kérdések ebben a tartományban Q04–Q08.",
        "",
    ]
    extra: list[list[str]] = []
    for item in baseline.get("results", []):
        block = _one(item, local_results.get(item.get("id")))
        if _question_number(item.get("id")) <= 8:
            lines.extend(block)
        else:
            extra.append(block)
    lines += [
        "## Q09–Q13",
        "",
        "Ezek további kérdések, amelyeket a Q01–Q08 dokumentumaiból "
        "kijelölt körön futtatunk. A saját dokumentumlistájuk szélesebb, "
        "és nincs benne a körben.",
        "",
    ]
    for block in extra:
        lines.extend(block)
    lines += [
        "## Értékelési szabály",
        "",
        (
            "A Q04–Q08 kérdések multi-hopok, a Q01–Q03 nem. A baseline "
            "ezeken a top-4 részletből gyakran olyan szezonrészletet hozott, "
            "amelyet a kérdés nem nevezett meg. A lokális lánc lefutott. "
            "Ahol a válasz az elutasító mondat, ott a részgráf nem adott "
            "elég támaszt. A kiválasztott forrásszöveg a gráf állítását "
            "csak akkor igazolja, ha a részletben benne van; az él leírása "
            "önmagában nem forrásszöveg. Fölény nincs állítva."
            if local_results else
            "A Q04–Q08 kérdések multi-hopok. A baseline ezeken a top-4 "
            "részletből gyakran olyan szezonrészletet hozott, amelyet a "
            "kérdés nem nevezett meg. Amíg a lokális válasz nem futott le, "
            "különbséget nem állítunk."
        ),
        "",
    ]
    return "\n".join(lines)


def write_comparison(baseline_path: Path, output_path: Path,
                     local_results: dict | None = None) -> None:
    text = render_comparison(load_baseline(baseline_path), local_results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def main() -> int:
    """Write the comparison with local answers marked as not run."""
    from .config import PROJECT_ROOT

    output = PROJECT_ROOT / "docs" / "osszehasonlitas.md"
    write_comparison(PROJECT_ROOT / "baseline" / "answers.json", output)
    print(f"wrote {output}")
    return 0


def _question_number(question_id: object) -> int:
    if not isinstance(question_id, str) or not question_id.startswith("Q"):
        return 99
    digits = question_id[1:]
    return int(digits) if digits.isdigit() else 99


def _one(item: dict, local: dict | None) -> list[str]:
    if local is None:
        local_answer = "Nem futott."
        local_sources = "Nincs felhasznált részgráf, mert a válaszgenerálás nem futott."
        evaluation = "Összevetés nem készült. Javulás nincs állítva."
    else:
        local_answer = local.get("answer") or ""
        local_sources = json.dumps(
            local.get("subgraph") or {}, ensure_ascii=False, indent=2)
        evaluation = local.get("evaluation") or "Futott. Külön fölény nincs állítva."
    sources = ", ".join(
        source.get("chunk_id", "") for source in item.get("sources", [])
    ) or "(nincs)"
    return [
        f"### {item.get('id')} — {item.get('type')}",
        "",
        f"Kérdés: {item.get('question')}",
        "",
        f"Baseline válasz: {item.get('answer')}",
        "",
        f"Baseline források: {sources}",
        "",
        f"Lokális válasz: {local_answer}",
        "",
        "Lokális részgráf és források:",
        "",
        local_sources if local is None else "```json\n" + local_sources + "\n```",
        "",
        f"Értékelés: {evaluation}",
        "",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
