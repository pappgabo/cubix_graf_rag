"""In-memory Leiden on the raw and prepared projections. No Neo4j, no corpus writes."""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import igraph as ig
import leidenalg
from naive_rag.graph_merge import merged_graph
from naive_rag.quality_report import load_records

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "graph" / "corpus" / "extraction-reuse-1200-23"
STATS = ROOT / "docs" / "week4-kozosseg-statisztika.md"
MAPPING = ROOT / "docs" / "week4-vetulet-leképezés.json"

SEED = 42
RESOLUTION = 1.0
N_ITERATIONS = -1
PARTITION = "RBConfigurationVertexPartition"

TEAM_ALIASES = {
    "Team:williams racing": [
        "Team:williams",
        "Team:williams f1",
        "Team:williams f1 team",
        "Team:williams grand prix engineering",
        "Team:williams-bmw",
        "Team:williams-honda",
        "Team:williams-renault",
    ],
    "Team:mercedes-amg petronas formula one team": [
        "Team:mercedes amg petronas f1 team",
        "Team:mercedes-amg petronas f1 team",
    ],
    "Team:red bull racing": [
        "Team:oracle red bull racing team",
        "Team:infiniti red bull racing",
        "Team:red bull racing-honda",
        "Team:infiniti red bull",
    ],
    "Team:mclaren": [
        "Team:mclaren f1",
        "Team:mclaren racing",
        "Team:mclaren-mercedes",
        "Team:west mclaren mercedes",
        "Team:vodafone mclaren mercedes",
        "Team:team mclaren mercedes",
        "Team:mercedes-benz mclaren",
        "Team:teammbm.com (mercedes-benz mclaren)",
        "Team:mclaren mastercard f1 team",
    ],
    "Team:renault": [
        "Team:renault f1",
        "Team:renault f1 team",
        "Team:renault sport formula one team",
        "Team:lotus renault gp",
        "Team:équipe renault elf",
    ],
}
SEASON_ALIASES = {
    "Season:2007 constructors' championship": "Season:2007",
    "Season:2008 fia formula one world championship": "Season:2008",
    "Season:2008 formula one world championship": "Season:2008",
    "Season:2012 fia formula one world championship": "Season:2012",
    "Season:2012 formula one world championship": "Season:2012",
    "Season:2016 fia formula one world championship": "Season:2016",
    "Season:2016 formula one world championship": "Season:2016",
    "Season:2016 season": "Season:2016",
    "Season:2020 formula one world championship": "Season:2020",
    "Season:2021 constructors' championship": "Season:2021",
    "Season:2021 formula one world championship": "Season:2021",
    "Season:2022 world drivers' championship": "Season:2022",
}
TITLE_EXCLUSIONS = ("Title:9", "Title:10", "Title:seventh title")
RESULT_EXCLUSIONS = ("RaceResult:142 points",)


def build_forward() -> dict[str, str]:
    forward: dict[str, str] = {}
    for target, sources in TEAM_ALIASES.items():
        for source in sources:
            forward[source] = target
    for source, target in SEASON_ALIASES.items():
        forward[source] = target
    return forward


def canon(key: str, forward: dict[str, str]) -> str:
    seen: set[str] = set()
    while key in forward and key not in seen:
        seen.add(key)
        key = forward[key]
    return key


def is_pure_season(key: str) -> bool:
    if not key.startswith("Season:"):
        return False
    year = key[len("Season:") :]
    return len(year) == 4 and year.isdigit() and year.startswith(("19", "20"))


def undirected(graph) -> dict[tuple[str, str], set[str]]:
    pairs: dict[tuple[str, str], set[str]] = {}
    loops = 0
    for edge in graph.edges:
        if edge.source_id == edge.target_id:
            loops += 1
            continue
        pair = tuple(sorted((edge.source_id, edge.target_id)))
        pairs.setdefault(pair, set()).update(edge.source_chunk_ids)
    return pairs, loops


def adjacency(pairs: dict[tuple[str, str], set[str]]) -> dict[str, dict[str, int]]:
    adj: dict[str, dict[str, int]] = defaultdict(dict)
    for (left, right), chunks in pairs.items():
        weight = len(chunks)
        adj[left][right] = weight
        adj[right][left] = weight
    return adj


def make_igraph(nodes: list[str], pairs: dict[tuple[str, str], set[str]]) -> ig.Graph:
    names = sorted(nodes)
    index = {name: position for position, name in enumerate(names)}
    graph = ig.Graph(n=len(names), directed=False)
    graph.vs["name"] = names
    edges = []
    weights = []
    for (left, right), chunks in sorted(pairs.items()):
        edges.append((index[left], index[right]))
        weights.append(float(len(chunks)))
    if edges:
        graph.add_edges(edges)
        graph.es["weight"] = weights
    return graph


def payload(nodes: list[str], pairs: dict[tuple[str, str], set[str]]) -> str:
    lines = [
        f"leidenalg {leidenalg.__version__}",
        f"igraph {ig.__version__}",
        PARTITION,
        f"resolution_parameter={RESOLUTION}",
        f"n_iterations={N_ITERATIONS}",
        f"seed={SEED}",
        "nodes",
        *sorted(nodes),
        "edges",
    ]
    for (left, right), chunks in sorted(pairs.items()):
        lines.append(f"{left}\t{right}\t{len(chunks)}")
    return "\n".join(lines) + "\n"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def induced(graph: ig.Graph, members: list[str]) -> ig.Graph:
    wanted = set(members)
    indexes = [vertex.index for vertex in graph.vs if vertex["name"] in wanted]
    indexes.sort(key=lambda index: graph.vs[index]["name"])
    return graph.subgraph(indexes)


def partition_graph(graph: ig.Graph) -> list[list[str]]:
    names = list(graph.vs["name"])
    if graph.vcount() <= 1:
        return [names] if names else []
    kwargs = {
        "n_iterations": N_ITERATIONS,
        "resolution_parameter": RESOLUTION,
        "seed": SEED,
    }
    if graph.ecount():
        kwargs["weights"] = "weight"
    part = leidenalg.find_partition(
        graph,
        leidenalg.RBConfigurationVertexPartition,
        **kwargs,
    )
    groups: dict[int, list[str]] = defaultdict(list)
    for name, member in zip(names, part.membership):
        groups[member].append(name)
    return sorted((sorted(members) for members in groups.values()), key=lambda item: item[0])


def hierarchy(graph: ig.Graph) -> dict[str, list[int]]:
    paths = {name: [0] for name in graph.vs["name"]}

    def walk(sub: ig.Graph, prefix: list[int]) -> None:
        groups = partition_graph(sub)
        if len(groups) <= 1:
            return
        if max(len(group) for group in groups) == sub.vcount():
            return
        for index, members in enumerate(groups):
            child = prefix + [index]
            for name in members:
                paths[name] = child
            if len(members) > 1:
                walk(induced(sub, members), child)

    walk(graph, [])
    return paths


def path_key(path: list[int]) -> str:
    return "/".join(str(part) for part in path)


def labels_at(paths: dict[str, list[int]], level: int) -> dict[str, str]:
    return {name: path_key(path[: level + 1]) for name, path in paths.items()}


def prefix_sizes(paths: dict[str, list[int]]) -> dict[tuple[int, ...], int]:
    counts: dict[tuple[int, ...], int] = Counter()
    for path in paths.values():
        for length in range(1, len(path) + 1):
            counts[tuple(path[:length])] += 1
    return counts


def cut_labels(paths: dict[str, list[int]], threshold: int) -> dict[str, str]:
    counts = prefix_sizes(paths)
    labels = {}
    for name, path in paths.items():
        chosen = tuple(path[:1])
        for length in range(1, len(path) + 1):
            chosen = tuple(path[:length])
            if counts[chosen] <= threshold:
                break
        labels[name] = "/".join(str(part) for part in chosen)
    return labels


def size_rows(label_map: dict[str, str]) -> list[tuple[str, list[str]]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for name, label in label_map.items():
        groups[label].append(name)
    return sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))


def fmt_median(sizes: list[int]) -> str:
    if not sizes:
        return "0"
    value = statistics.median(sizes)
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def degree_of(adj: dict[str, dict[str, int]], name: str) -> int:
    return len(adj.get(name, {}))


def hub(members: list[str], adj: dict[str, dict[str, int]]) -> str:
    return max(members, key=lambda name: (degree_of(adj, name), name))


def distribution(rows: list[tuple[str, list[str]]], adj, limit: int = 10) -> dict:
    sizes = [len(members) for _, members in rows]
    top = []
    for label, members in rows[:limit]:
        top.append(
            {
                "id": label,
                "meret": len(members),
                "kozep": hub(members, adj),
            }
        )
    return {
        "kozossegek": len(rows),
        "min": min(sizes) if sizes else 0,
        "median": fmt_median(sizes),
        "max": max(sizes) if sizes else 0,
        "egyes": sum(1 for size in sizes if size == 1),
        "top": top,
    }


def community_content(members: list[str], adj, pairs, names: dict[str, str]) -> dict:
    member_set = set(members)
    internal = 0
    for (left, right), chunks in pairs.items():
        if left in member_set and right in member_set:
            internal += 1
    touch = []
    for name in members:
        neighbours = sum(1 for other in adj.get(name, {}) if other in member_set)
        touch.append((neighbours, degree_of(adj, name), name))
    touch.sort(key=lambda item: (-item[0], -item[1], item[2]))
    types = Counter(name.split(":", 1)[0] for name in members)
    hub_touch, hub_degree, hub_name = touch[0]
    others = max(len(members) - 1, 1)
    return {
        "meret": len(members),
        "belso_el": internal,
        "tipusok": types.most_common(),
        "hub": hub_name,
        "hub_nev": names.get(hub_name, hub_name),
        "hub_fok": hub_degree,
        "hub_belso": hub_touch,
        "hub_arany": hub_touch / others,
        "tagok_fokonkent": [
            {"kulcs": name, "nev": names.get(name, name), "belso": inside, "fok": degree}
            for inside, degree, name in touch[:12]
        ],
    }


def moved_nodes(raw_labels: dict[str, str], prepared_labels: dict[str, str], shared: list[str]) -> dict:
    raw_groups: dict[str, set[str]] = defaultdict(set)
    prepared_groups: dict[str, set[str]] = defaultdict(set)
    for name in shared:
        raw_groups[raw_labels[name]].add(name)
        prepared_groups[prepared_labels[name]].add(name)
    alignment = {}
    for label, members in prepared_groups.items():
        best = max(raw_groups, key=lambda raw: (len(members & raw_groups[raw]), raw))
        alignment[label] = best
    moved = [name for name in shared if raw_labels[name] != alignment[prepared_labels[name]]]
    by_prepared = Counter(prepared_labels[name] for name in moved)
    largest_label, largest_count = ("", 0)
    if by_prepared:
        largest_label, largest_count = max(by_prepared.items(), key=lambda item: (item[1], item[0]))
    raw_loss = []
    for label, members in raw_groups.items():
        best_overlap = max((len(members & other) for other in prepared_groups.values()), default=0)
        raw_loss.append((len(members) - best_overlap, len(members), label))
    raw_loss.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return {
        "kozos_csucs": len(shared),
        "mas_kozosseg": len(moved),
        "elokeszitett_eltérés": {
            "id": largest_label,
            "mozgott": largest_count,
            "meret": len(prepared_groups.get(largest_label, ())),
            "nyers_par": alignment.get(largest_label),
        },
        "nyers_eltérés": {
            "id": raw_loss[0][2] if raw_loss else "",
            "kiesett": raw_loss[0][0] if raw_loss else 0,
            "meret": raw_loss[0][1] if raw_loss else 0,
        },
    }


def markdown(report: dict) -> str:
    check = report["ellenorzes"]
    lines = [
        "# Közösségstatisztika",
        "",
        "A Leiden memóriában futott, a Neo4j és a korpusz JSON változatlan. A csomópont→csoport leképezés a `docs/week4-vetulet-leképezés.json` fájlban van.",
        "",
        "## Verziók",
        "",
        "Telepítés: `uv add --no-build-package igraph --no-build-package leidenalg \"leidenalg==0.12.0\"`. Mindkét csomag kész wheelből jött, forrásból nem fordult.",
        "",
        "| Csomag | Verzió |",
        "|---|---|",
        f"| leidenalg | {leidenalg.__version__} |",
        f"| igraph | {ig.__version__} |",
        "| texttable | 1.7.2 |",
        "",
        "A `texttable` az `igraph` függősége. A Windows-wheel az `igraph-1.0.0-cp39-abi3-win_amd64`.",
        "",
        "## Leiden-paraméterek",
        "",
        f"- Partíció: `{PARTITION}`",
        f"- `resolution_parameter`: {RESOLUTION}",
        "- `weights`: az él `weight` attribútuma, értéke az egyedi `source_chunk_ids` uniójának mérete",
        f"- `n_iterations`: {N_ITERATIONS}",
        f"- `seed`: {SEED}",
        "",
        "A hierarchia ugyanezzel a seeddel ismétli a felosztást, amíg egy közösség tovább bomlik. A közösségméret küszöbe nincs rögzítve; a 10, 30 és 100 küszöb csak a jelentési vágás.",
        "",
        "## Élösszevonás",
        "",
        f"A tárolt irányított gráf {check['iranyított_el']} él. Önáló hurok a memóriában: {check['nyers_hurkok']}. Irányítatlan párokra összevonva {check['nyers_el']} él marad.",
        "",
        f"Az aliasok {check['osszeolvadt_par']} kanonikus páron olvasztottak össze párhuzamos élet. Az így elnyelt többletélek száma: {check['elnyelt_el']}. A súly ezeken a párokon az egyedi chunk-azonosítók uniója. Alias miatti új önhurok: {check['alias_hurkok']}. Kizárt végpont miatt kieső irányítatlan él: {check['kizart_el']}.",
        "",
        f"Az előkészített élszám: {check['elokeszitett_el']}.",
        "",
        "## Bemenet és kétszeres futás",
        "",
        "Mindkét vetület kétszer futott végig a teljes hierarchián. A két felosztás megegyezett.",
        "",
        "| Vetület | Csomópont | Él | Izolált | SHA-256 |",
        "|---|---:|---:|---:|---|",
        f"| Nyers | {check['nyers_csucs']} | {check['nyers_el']} | {check['nyers_izolalt']} | `{report['hash']['nyers']}` |",
        f"| Előkészített | {check['elokeszitett_csucs']} | {check['elokeszitett_el']} | {check['elokeszitett_izolalt']} | `{report['hash']['elokeszitett']}` |",
        "",
        f"A hash a rendezett csomópontlistából és a rendezett `forrás, cél, súly` éllistából készült, a fenti paraméterekkel együtt.",
        "",
        f"Új izolált csúcs az előkészített vetületen: {len(check['uj_izolalt'])}.",
        "",
    ]
    for name in check["uj_izolalt"]:
        lines.append(f"- `{name}`")
    lines.extend(["", "## Szintek", ""])
    for projection in ("nyers", "elokeszitett"):
        title = "Nyers" if projection == "nyers" else "Előkészített"
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| Szint | Közösség | Min | Medián | Max | Méret-1 |")
        lines.append("|---:|---:|---:|---:|---:|---:|")
        for level in report["szintek"][projection]:
            lines.append(
                f"| {level['szint']} | {level['kozossegek']} | {level['min']} | {level['median']} | {level['max']} | {level['egyes']} |"
            )
        lines.append("")
        lines.append("A tíz legnagyobb közösség a 0. szinten:")
        lines.append("")
        for item in report["szintek"][projection][0]["top"]:
            lines.append(f"- `{item['id']}`: {item['meret']} csúcs, legnagyobb fokú tag `{item['kozep']}`")
        lines.append("")
    for projection in ("nyers", "elokeszitett"):
        title = "Nyers" if projection == "nyers" else "Előkészített"
        content = report["legnagyobb"][projection]
        share = content["meret"] / report["ellenorzes"][f"{projection}_csucs"]
        edge_share = content["belso_el"] / report["ellenorzes"][f"{projection}_el"]
        lines.extend(
            [
                f"## Legnagyobb közösség: {title}",
                "",
                f"A 0. szint legnagyobb közössége `{content['id']}`, {content['meret']} csúcs ({share:.1%} a vetület csúcsai közül) és {content['belso_el']} belső él ({edge_share:.1%} a vetület élei közül).",
                "",
                "Típusok:",
                "",
            ]
        )
        for kind, count in content["tipusok"][:8]:
            lines.append(f"- {kind}: {count}")
        lines.extend(["", "Legnagyobb fokú tagok a közösségen belül:", ""])
        for item in content["tagok_fokonkent"]:
            lines.append(
                f"- `{item['kulcs']}` ({item['nev']}): belső szomszéd {item['belso']}, teljes fok {item['fok']}"
            )
        verdict = "igen" if content["hub_arany"] >= 0.5 else "nem"
        graph_verdict = "igen" if share >= 0.5 or edge_share >= 0.5 else "nem"
        lines.extend(
            [
                "",
                f"Egy csúcs uralja-e ezt a közösséget: {verdict}. A legnagyobb belső fokú tag `{content['hub']}`, a többi tag {content['hub_arany']:.1%}-ához kapcsolódik.",
                f"Egy közösség uralja-e a vetületet: {graph_verdict}.",
                "",
            ]
        )
    lines.extend(
        [
            "## Küszöbök",
            "",
            "A 0. szint a küszöb nélküli első felosztás. A vágás addig követi a hierarchiát, amíg a közösség nagyobb a küszöbnél.",
            "",
            "| Vetület | Küszöb | 0. szint a küszöb felett | 0. szint legnagyobb | Vágás közösségei | Vágás legnagyobb | Vágásban a küszöb felett |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for projection in ("nyers", "elokeszitett"):
        title = "Nyers" if projection == "nyers" else "Előkészített"
        for row in report["kuszob"][projection]:
            lines.append(
                f"| {title} | {row['kuszob']} | {row['szint0_felett']} | {row['szint0_max']} | {row['vagas_kozosseg']} | {row['vagas_max']} | {row['vagas_felett']} |"
            )
    diff = report["osszevetes"]
    lines.extend(
        [
            "",
            "## Nyers és előkészített felosztás",
            "",
            f"A közös kanonikus csúcsok száma {diff['kozos_csucs']}. Ezek közül {diff['mas_kozosseg']} került másik 0. szintű közösségbe, miután minden előkészített közösséget a legnagyobb metszetű nyers közösséghez igazítottam.",
            "",
            f"A legnagyobb előkészített eltérés a `{diff['elokeszitett_eltérés']['id']}` közösség: {diff['elokeszitett_eltérés']['mozgott']} csúcs nem a `{diff['elokeszitett_eltérés']['nyers_par']}` nyers közösségből jön, a közösség mérete {diff['elokeszitett_eltérés']['meret']}.",
            "",
            f"A legnagyobb nyers oldali veszteség a `{diff['nyers_eltérés']['id']}` közösség: {diff['nyers_eltérés']['kiesett']} csúcs nem fér a legnagyobb előkészített metszetbe, a közös csúcsokon mért mérete {diff['nyers_eltérés']['meret']}.",
            "",
            f"A {diff['alias_forras']} alias-forrásnév közül {diff['alias_mas_nyers']} a céljától eltérő nyers közösségben volt. Az előkészített vetületen ezek a cél közösségét kapják.",
            "",
            "A legfinomabb szinten ugyanez az igazítás "
            f"{diff['finom_mas_kozosseg']} közös csúcsot tesz másik levélközösségbe.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    forward = build_forward()
    records = load_records(CORPUS)
    graph = merged_graph(records)
    names = {node.entity_key: node.name for node in graph.nodes}
    node_keys = set(names)
    excluded = {
        key
        for key in node_keys
        if key.startswith("Season:") and key not in SEASON_ALIASES and not is_pure_season(key)
    }
    excluded.update(key for key in TITLE_EXCLUSIONS + RESULT_EXCLUSIONS if key in node_keys)
    missing_alias = sorted(source for source in forward if source not in node_keys)
    missing_target = sorted(target for target in set(forward.values()) if target not in node_keys)
    pairs, loops = undirected(graph)
    raw_adj = adjacency(pairs)
    for key in node_keys:
        raw_adj.setdefault(key, {})

    grouped: dict[tuple[str, str], list[tuple[tuple[str, str], set[str]]]] = defaultdict(list)
    dropped_excluded = 0
    dropped_loops = 0
    for pair, chunks in pairs.items():
        left, right = pair
        if left in excluded or right in excluded:
            dropped_excluded += 1
            continue
        canonical = tuple(sorted((canon(left, forward), canon(right, forward))))
        if canonical[0] == canonical[1]:
            dropped_loops += 1
            continue
        grouped[canonical].append((pair, chunks))
    prepared_pairs = {
        pair: set().union(*(chunks for _, chunks in items)) for pair, items in grouped.items()
    }
    collapsed = [items for items in grouped.values() if len(items) > 1]
    absorbed = sum(len(items) - 1 for items in collapsed)
    prepared_nodes = {canon(key, forward) for key in node_keys if key not in excluded}
    raw_isolates = sorted(key for key in node_keys if not raw_adj[key])
    prepared_adj = adjacency(prepared_pairs)
    for key in prepared_nodes:
        prepared_adj.setdefault(key, {})
    prepared_isolates = sorted(key for key in prepared_nodes if not prepared_adj[key])
    new_isolates = []
    for key in prepared_isolates:
        members = [key, *[source for source, target in forward.items() if target == key]]
        members = [member for member in members if member in node_keys]
        if any(raw_adj[member] for member in members):
            new_isolates.append(key)

    check = {
        "iranyított_el": len(graph.edges),
        "nyers_hurkok": loops,
        "nyers_csucs": len(node_keys),
        "nyers_el": len(pairs),
        "nyers_izolalt": len(raw_isolates),
        "elokeszitett_csucs": len(prepared_nodes),
        "elokeszitett_el": len(prepared_pairs),
        "elokeszitett_izolalt": len(prepared_isolates),
        "osszeolvadt_par": len(collapsed),
        "elnyelt_el": absorbed,
        "alias_hurkok": dropped_loops,
        "kizart_el": dropped_excluded,
        "kizart_csucs": len(excluded),
        "alias_forras": len(forward),
        "hianyzo_forras": missing_alias,
        "hianyzo_cel": missing_target,
        "uj_izolalt": new_isolates,
        "peldak": [
            {
                "cel": list(pair),
                "forrasok": [list(source) for source, _ in items],
                "unio": len(set().union(*(chunks for _, chunks in items))),
            }
            for pair, items in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))[:12]
            if len(items) > 1
        ],
    }
    print(json.dumps({k: v for k, v in check.items() if k != "peldak"}, ensure_ascii=False))
    print("EXAMPLES", json.dumps(check["peldak"], ensure_ascii=False))
    expected = {
        "nyers_csucs": 2761,
        "nyers_el": 4075,
        "elokeszitett_csucs": 2645,
        "elokeszitett_el": 3863,
        "kizart_csucs": 77,
        "alias_forras": 39,
        "nyers_izolalt": 782,
        "elokeszitett_izolalt": 736,
    }
    bad = {key: (check[key], value) for key, value in expected.items() if check[key] != value}
    if bad or len(new_isolates) != 12 or missing_alias or missing_target:
        print("ELTERES", json.dumps({"bad": bad, "uj": len(new_isolates)}, ensure_ascii=False))
        return 2

    raw_graph = make_igraph(sorted(node_keys), pairs)
    prepared_graph = make_igraph(sorted(prepared_nodes), prepared_pairs)
    hashes = {
        "nyers": digest(payload(sorted(node_keys), pairs)),
        "elokeszitett": digest(payload(sorted(prepared_nodes), prepared_pairs)),
    }
    raw_first = hierarchy(raw_graph)
    raw_second = hierarchy(raw_graph)
    prepared_first = hierarchy(prepared_graph)
    prepared_second = hierarchy(prepared_graph)
    if raw_first != raw_second or prepared_first != prepared_second:
        print("A ket futas elter")
        return 3
    print("HASH", hashes["nyers"], hashes["elokeszitett"])
    print(
        "DEPTH",
        max(len(path) for path in raw_first.values()),
        max(len(path) for path in prepared_first.values()),
    )

    def level_report(paths, adj):
        depth = max(len(path) for path in paths.values())
        rows = []
        for level in range(depth):
            info = distribution(size_rows(labels_at(paths, level)), adj)
            info["szint"] = level
            rows.append(info)
        return rows

    levels = {
        "nyers": level_report(raw_first, raw_adj),
        "elokeszitett": level_report(prepared_first, prepared_adj),
    }
    largest = {}
    for projection, paths, adj, edge_pairs in (
        ("nyers", raw_first, raw_adj, pairs),
        ("elokeszitett", prepared_first, prepared_adj, prepared_pairs),
    ):
        rows = size_rows(labels_at(paths, 0))
        label, members = rows[0]
        content = community_content(members, adj, edge_pairs, names)
        content["id"] = label
        largest[projection] = content

    thresholds = {}
    for projection, paths in ("nyers", raw_first), ("elokeszitett", prepared_first):
        level0 = size_rows(labels_at(paths, 0))
        sizes = [len(members) for _, members in level0]
        rows = []
        for threshold in (10, 30, 100):
            cut = size_rows(cut_labels(paths, threshold))
            cut_sizes = [len(members) for _, members in cut]
            rows.append(
                {
                    "kuszob": threshold,
                    "szint0_felett": sum(1 for size in sizes if size > threshold),
                    "szint0_max": max(sizes),
                    "vagas_kozosseg": len(cut),
                    "vagas_max": max(cut_sizes),
                    "vagas_felett": sum(1 for size in cut_sizes if size > threshold),
                }
            )
        thresholds[projection] = rows

    shared = sorted(prepared_nodes)
    comparison = moved_nodes(labels_at(raw_first, 0), labels_at(prepared_first, 0), shared)
    fine_raw = {name: path_key(path) for name, path in raw_first.items()}
    fine_prepared = {name: path_key(path) for name, path in prepared_first.items()}
    fine = moved_nodes(fine_raw, fine_prepared, shared)
    alias_split = 0
    for source, target in forward.items():
        if raw_first[source][:1] != raw_first[target][:1]:
            alias_split += 1
    comparison["finom_mas_kozosseg"] = fine["mas_kozosseg"]
    comparison["alias_forras"] = len(forward)
    comparison["alias_mas_nyers"] = alias_split

    prepared_assignment = {name: path_key(path) for name, path in prepared_first.items()}
    for source, target in forward.items():
        prepared_assignment[source] = prepared_assignment[target]
    mapping = {
        "parameterek": {
            "particio": PARTITION,
            "resolution_parameter": RESOLUTION,
            "weights": "egyedi source_chunk_ids unioja",
            "n_iterations": N_ITERATIONS,
            "seed": SEED,
            "leidenalg": leidenalg.__version__,
            "igraph": ig.__version__,
        },
        "hash": hashes,
        "ketszer_azonos": True,
        "alias": dict(sorted(forward.items())),
        "kizart": sorted(excluded),
        "nyers": {name: path_key(path) for name, path in sorted(raw_first.items())},
        "elokeszitett": dict(sorted(prepared_assignment.items())),
    }
    MAPPING.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    report = {
        "ellenorzes": check,
        "hash": hashes,
        "szintek": levels,
        "legnagyobb": largest,
        "kuszob": thresholds,
        "osszevetes": comparison,
    }
    STATS.write_text(markdown(report), encoding="utf-8")
    summary = {
        "szintek": {
            name: [{k: row[k] for k in ("szint", "kozossegek", "min", "median", "max", "egyes")} for row in rows]
            for name, rows in levels.items()
        },
        "legnagyobb": {
            name: {
                "id": content["id"],
                "meret": content["meret"],
                "belso_el": content["belso_el"],
                "hub": content["hub"],
                "hub_arany": round(content["hub_arany"], 4),
                "tipusok": content["tipusok"][:6],
            }
            for name, content in largest.items()
        },
        "kuszob": thresholds,
        "osszevetes": comparison,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
