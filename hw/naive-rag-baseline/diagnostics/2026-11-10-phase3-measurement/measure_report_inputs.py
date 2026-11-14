"""Phase 3, step 1: offline measurement of community-report inputs.

No model call, no Neo4j connection, no Leiden run. Only local processing of
already-saved artifacts:
  - graph/corpus/extraction-reuse-1200-23 (the same extraction snapshot
    week4_leiden.py used) via naive_rag.quality_report.load_records +
    naive_rag.graph_merge.merged_graph -- pure, in-memory, no side effects.
  - docs/week4-vetulet-leképezés.json -- canonical membership, alias map,
    excluded list (the source of truth for all three; nothing here is
    re-derived independently of it).

The only reused "week4_leiden" code is the PRE-PARTITION edge preparation
(undirected(), canon(), build_forward()) -- never leidenalg.find_partition.
That module does `import igraph` / `import leidenalg` at the top; importing
it does not run the partitioning algorithm, so this is not "re-running
Leiden".

Token counts are a character/4 ceiling estimate throughout (a prior
tiktoken availability check accidentally triggered a one-time network
download of the o200k_base BPE file in this environment -- see the final
report -- so, per instruction, no tiktoken result is used here at all;
every count in this script's output is explicitly an estimate).
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "diagnostics" / "2026-11-07-phase0"))

import week4_leiden as w4  # pre-partition helpers only; find_partition is never called
from naive_rag import community_load as cl
from naive_rag.extraction_identity import make_rel_key, merge_descriptions, merge_source_ids
from naive_rag.graph_merge import merged_graph
from naive_rag.quality_report import load_records

MAPPING_PATH = ROOT / "docs" / "week4-vetulet-leképezés.json"
OUT_DIR = Path(__file__).resolve().parent
RESULTS_DIR = OUT_DIR / "results"
DOCS_JSON_OUT = ROOT / "docs" / "week4-reportbemenet-meres.json"
DOCS_MD_OUT = ROOT / "docs" / "week4-reportbemenet-meres.md"
PROMPT_TEMPLATE_PATH = OUT_DIR / "riportprompt-sablon-v1.md"

NODE_DESC_CAP_TOKENS = 80
EDGE_DESC_CAP_TOKENS = 50
COMMUNITY_TOKEN_BUDGET = 24_000
PLANNED_MODEL = "gpt-4o-mini"
INPUT_PRICE_PER_MTOK = 0.15
OUTPUT_PRICE_PER_MTOK = 0.60
PILOT_OUTPUT_TOKEN_CAP = 1800
COST_ESTIMATE_OUTPUT_TOKENS_PER_REPORT = 600


# --------------------------------------------------------------------------
# Token estimate (character/4, ceiling; never an actual tokenizer count)
# --------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)


# --------------------------------------------------------------------------
# Sentence-boundary-aware truncation. The truncated TEXT is a field on its
# own; source_chunk_ids is a separate structured field next to it, never
# interleaved into the prose -- so truncation can never separate a claim
# from its source identifiers.
# --------------------------------------------------------------------------


def truncate_to_tokens(text: str, cap_tokens: int) -> tuple[str, bool]:
    """(possibly-shortened text, was_it_shortened)."""
    if estimate_tokens(text) <= cap_tokens:
        return text, False
    cap_chars = cap_tokens * 4
    # Prefer a sentence boundary ('. ' or newline) at or before the cap.
    window = text[:cap_chars]
    best_cut = -1
    for marker in (". ", ".\n", "\n"):
        pos = window.rfind(marker)
        if pos > best_cut:
            best_cut = pos + len(marker.rstrip())
    if best_cut > 0:
        return text[:best_cut].rstrip(), True
    return window.rstrip(), True


# --------------------------------------------------------------------------
# Load the audited plan (membership, communities, alias/excluded sets) --
# this is the single source of truth for canonical membership and the
# alias/exclusion mapping, per the task's explicit instruction.
# --------------------------------------------------------------------------


def load_plan() -> tuple[dict, "cl.CommunityPlan"]:
    mapping = cl.load_mapping(MAPPING_PATH)
    plan = cl.build_plan(mapping, expected=cl.EXPECTED_COUNTS_WEEK4_PREPARED)
    return mapping, plan


def level_membership(plan: "cl.CommunityPlan") -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """path -> member entity_keys, for the level-0 and the full level-1
    reporting view (level==1 OR a level-0 leaf), using community_load's own
    reporting_level_paths so this matches the already-audited model."""
    level0_paths = cl.reporting_level_paths(plan, 0)
    level1_paths = cl.reporting_level_paths(plan, 1)

    def community_of(path: str, level: int) -> str:
        parts = path.split("/")
        prefix = "/".join(parts[: level + 1]) if len(parts) > level else path
        return prefix

    level0_members: dict[str, list[str]] = defaultdict(list)
    level1_members: dict[str, list[str]] = defaultdict(list)
    for entity_key, path in plan.member_of.items():
        level0_members[community_of(path, 0)].append(entity_key)
        level1_members[community_of(path, 1)].append(entity_key)

    assert set(level0_members) == level0_paths, (
        "level-0 coverage mismatch", set(level0_members) ^ level0_paths
    )
    assert set(level1_members) == level1_paths, (
        "level-1 coverage mismatch", set(level1_members) ^ level1_paths
    )
    return dict(level0_members), dict(level1_members)


# --------------------------------------------------------------------------
# Projection edges (undirected, canonical, chunk-union weight) -- reusing
# ONLY the pre-partition preparation from week4_leiden.py, against the
# CURRENT in-memory merged_graph (never leidenalg).
# --------------------------------------------------------------------------


def build_prepared_pairs(
    graph, forward: dict[str, str], excluded: frozenset[str]
) -> dict[tuple[str, str], set[str]]:
    pairs, _loops = w4.undirected(graph)
    grouped: dict[tuple[str, str], list[set[str]]] = defaultdict(list)
    for (left, right), chunks in pairs.items():
        if left in excluded or right in excluded:
            continue
        canonical = tuple(sorted((w4.canon(left, forward), w4.canon(right, forward))))
        if canonical[0] == canonical[1]:
            continue
        grouped[canonical].append(chunks)
    return {pair: set().union(*chunk_sets) for pair, chunk_sets in grouped.items()}


# --------------------------------------------------------------------------
# Domain relationships, re-consolidated at the week4 alias granularity.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsolidatedEdge:
    rel_key: str
    rel_type: str
    source: str
    target: str
    from_year: int | None
    to_year: int | None
    role: str | None
    description: str
    source_chunk_ids: tuple[str, ...]


def consolidate_domain_edges(
    graph, forward: dict[str, str], excluded: frozenset[str]
) -> dict[str, ConsolidatedEdge]:
    """Re-key graph.edges (already merged once, at the base ALIAS_MAP layer)
    by the week4-level canonical endpoints, merging only edges that remain
    the SAME semantic relationship (same rel_type/direction/from_year/
    to_year/role) after that resolution -- not every edge sharing a
    canonical endpoint pair."""
    groups: dict[str, list] = defaultdict(list)
    for edge in sorted(graph.edges, key=lambda e: e.edge_id):
        canon_source = w4.canon(edge.source_id, forward)
        canon_target = w4.canon(edge.target_id, forward)
        if canon_source in excluded or canon_target in excluded:
            continue
        new_key = make_rel_key(
            canon_source, edge.rel_type, canon_target, edge.from_year, edge.to_year, edge.role
        )
        groups[new_key].append((edge, canon_source, canon_target))

    consolidated: dict[str, ConsolidatedEdge] = {}
    for rel_key, items in groups.items():
        chunk_ids: list[str] = []
        description = ""
        for edge, _cs, _ct in items:
            for chunk_id in edge.source_chunk_ids:
                chunk_ids = merge_source_ids(chunk_ids, chunk_id)
            description = merge_descriptions(description, edge.description)
        first_edge, canon_source, canon_target = items[0]
        consolidated[rel_key] = ConsolidatedEdge(
            rel_key=rel_key,
            rel_type=first_edge.rel_type,
            source=canon_source,
            target=canon_target,
            from_year=first_edge.from_year,
            to_year=first_edge.to_year,
            role=first_edge.role,
            description=description,
            source_chunk_ids=tuple(chunk_ids),
        )
    return consolidated


# --------------------------------------------------------------------------
# Text builders
# --------------------------------------------------------------------------


def node_raw_text(node) -> str:
    if node.description:
        return f"{node.entity_key} ({node.name}): {node.description}"
    return f"{node.entity_key} ({node.name})"


def edge_raw_text(edge: ConsolidatedEdge) -> str:
    qualifiers = []
    if edge.from_year is not None:
        qualifiers.append(f"from_year={edge.from_year}")
    if edge.to_year is not None:
        qualifiers.append(f"to_year={edge.to_year}")
    if edge.role is not None:
        qualifiers.append(f"role={edge.role}")
    qual_text = f" ({', '.join(qualifiers)})" if qualifiers else ""
    base = f"{edge.source} -[{edge.rel_type}]-> {edge.target}{qual_text}"
    if edge.description:
        return f"{base}: {edge.description}"
    return base


# --------------------------------------------------------------------------
# Per-community measurement
# --------------------------------------------------------------------------


@dataclass
class CommunityMeasurement:
    path: str
    level: int
    canonical_node_count: int
    internal_projection_edge_count: int
    internal_domain_relationship_count: int
    raw_description_token_estimate: int
    constrained_input_token_estimate: int
    omitted_nodes: int
    omitted_domain_relationships: int
    omitted_descriptions: int
    truncated_descriptions: int
    included_node_count: int
    included_domain_relationship_count: int
    input_payload: dict[str, Any] = field(repr=False)


def prompt_skeleton(community_id: str, reporting_level: int) -> dict[str, Any]:
    return {
        "prompt_version": "riportprompt-v1",
        "community_id": community_id,
        "reporting_level": reporting_level,
        "nodes": [],
        "domain_relationships": [],
    }


def measure_community(
    path: str,
    level: int,
    members: list[str],
    nodes_by_key: dict,
    prepared_pairs: dict[tuple[str, str], set[str]],
    domain_edges: dict[str, ConsolidatedEdge],
) -> CommunityMeasurement:
    member_set = set(members)

    # internal projection edges + within-community degree (for node order)
    degree: dict[str, int] = {m: 0 for m in members}
    internal_pairs: list[tuple[tuple[str, str], int]] = []
    for (a, b), chunks in prepared_pairs.items():
        if a in member_set and b in member_set:
            weight = len(chunks)
            internal_pairs.append(((a, b), weight))
            degree[a] += 1
            degree[b] += 1
    internal_pairs.sort(key=lambda item: (-item[1], item[0]))

    # internal domain relationships (already consolidated at module scope)
    internal_edges = [
        edge for edge in domain_edges.values()
        if edge.source in member_set and edge.target in member_set
    ]

    def edge_priority(edge: ConsolidatedEdge) -> tuple[int, str]:
        pair = tuple(sorted((edge.source, edge.target)))
        weight = len(prepared_pairs.get(pair, ()))
        return (-weight, edge.rel_key)

    internal_edges.sort(key=edge_priority)

    ordered_nodes = sorted(members, key=lambda key: (-degree[key], key))

    raw_node_texts = {key: node_raw_text(nodes_by_key[key]) for key in ordered_nodes}
    raw_edge_texts = {edge.rel_key: edge_raw_text(edge) for edge in internal_edges}
    raw_description_tokens = sum(estimate_tokens(t) for t in raw_node_texts.values())
    raw_description_tokens += sum(estimate_tokens(t) for t in raw_edge_texts.values())

    skeleton = prompt_skeleton(community_id=path, reporting_level=level)
    overhead_tokens = estimate_tokens(json.dumps(skeleton, ensure_ascii=False))
    remaining = max(COMMUNITY_TOKEN_BUDGET - overhead_tokens, 0)
    node_budget = remaining // 2
    edge_budget = remaining - node_budget

    included_nodes: list[dict[str, Any]] = []
    omitted_nodes = 0
    truncated = 0
    omitted_descriptions = 0
    used = 0
    for key in ordered_nodes:
        node = nodes_by_key[key]
        text, was_cut_by_cap = truncate_to_tokens(raw_node_texts[key], NODE_DESC_CAP_TOKENS)
        node_entry = {
            "entity_key": key,
            "text": text,
            "source_chunk_ids": sorted(node.source_chunk_ids),
        }
        # the budget check must cost the EXACT dict that gets appended below,
        # source_chunk_ids included -- a node cited in many chunks is not
        # free just because its description is short.
        cost = estimate_tokens(json.dumps(node_entry, ensure_ascii=False))
        if used + cost > node_budget:
            omitted_nodes += 1
            if node.description:
                omitted_descriptions += 1
            continue
        used += cost
        if was_cut_by_cap:
            truncated += 1
        included_nodes.append(node_entry)

    included_edges: list[dict[str, Any]] = []
    omitted_edges = 0
    used_edge = 0
    for edge in internal_edges:
        text, was_cut_by_cap = truncate_to_tokens(raw_edge_texts[edge.rel_key], EDGE_DESC_CAP_TOKENS)
        entry = {
            "source": edge.source,
            "rel_type": edge.rel_type,
            "target": edge.target,
            "from_year": edge.from_year,
            "to_year": edge.to_year,
            "role": edge.role,
            "text": text,
            "source_chunk_ids": sorted(edge.source_chunk_ids),
        }
        cost = estimate_tokens(json.dumps(entry, ensure_ascii=False))
        if used_edge + cost > edge_budget:
            omitted_edges += 1
            if edge.description:
                omitted_descriptions += 1
            continue
        used_edge += cost
        if was_cut_by_cap:
            truncated += 1
        included_edges.append(entry)

    payload = prompt_skeleton(community_id=path, reporting_level=level)
    payload["nodes"] = included_nodes
    payload["domain_relationships"] = included_edges
    constrained_tokens = estimate_tokens(json.dumps(payload, ensure_ascii=False))

    return CommunityMeasurement(
        path=path,
        level=level,
        canonical_node_count=len(members),
        internal_projection_edge_count=len(internal_pairs),
        internal_domain_relationship_count=len(internal_edges),
        raw_description_token_estimate=raw_description_tokens,
        constrained_input_token_estimate=constrained_tokens,
        omitted_nodes=omitted_nodes,
        omitted_domain_relationships=omitted_edges,
        omitted_descriptions=omitted_descriptions,
        truncated_descriptions=truncated,
        included_node_count=len(included_nodes),
        included_domain_relationship_count=len(included_edges),
        input_payload=payload,
    )


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    mapping, plan = load_plan()
    forward = dict(mapping["alias"])
    excluded = frozenset(mapping["kizart"])
    assert forward == w4.build_forward(), "mapping['alias'] must equal week4_leiden.build_forward()"

    records = load_records(w4.CORPUS)
    graph = merged_graph(records)
    nodes_by_key = {node.entity_key: node for node in graph.nodes}

    prepared_pairs = build_prepared_pairs(graph, forward, excluded)
    assert len(prepared_pairs) == 3863, f"prepared_pairs count drifted: {len(prepared_pairs)}"

    domain_edges = consolidate_domain_edges(graph, forward, excluded)

    level0_members, level1_members = level_membership(plan)
    assert len(level0_members) == 37, f"expected 37 level-0 communities, got {len(level0_members)}"
    total_members = sum(len(v) for v in level0_members.values())
    assert total_members == 1909, f"expected 1909 non-isolated members, got {total_members}"
    large_level0 = {p: m for p, m in level0_members.items() if len(m) > 10}
    assert len(large_level0) == 19, f"expected 19 level-0 communities >10 nodes, got {len(large_level0)}"

    level0_singletons = {p: m for p, m in level0_members.items() if len(m) == 1}
    level1_singletons = {p: m for p, m in level1_members.items() if len(m) == 1}

    level0_results = {
        path: measure_community(path, 0, members, nodes_by_key, prepared_pairs, domain_edges)
        for path, members in level0_members.items()
    }
    level1_results = {
        path: measure_community(path, 1, members, nodes_by_key, prepared_pairs, domain_edges)
        for path, members in level1_members.items()
    }

    # --- pilot selection: 37 level-0 communities, sorted by (size, path-as-int-tuple) ---
    def path_tuple(path: str) -> tuple[int, ...]:
        return tuple(int(seg) for seg in path.split("/"))

    ordered_level0 = sorted(
        level0_members.items(), key=lambda item: (len(item[1]), path_tuple(item[0]))
    )
    pilot_paths = [ordered_level0[0][0], ordered_level0[18][0], ordered_level0[36][0]]
    pilot_labels = ["smallest", "median", "largest"]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"pilots": []}
    for label, path in zip(pilot_labels, pilot_paths):
        measurement = level0_results[path]
        safe_path = path.replace("/", "-")
        out_path = RESULTS_DIR / f"pilot-{label}-{safe_path}.json"
        content = json.dumps(measurement.input_payload, ensure_ascii=False, indent=1) + "\n"
        out_path.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        manifest["pilots"].append({
            "label": label,
            "community_id": path,
            "file": str(out_path.relative_to(ROOT)),
            "canonical_node_count": measurement.canonical_node_count,
            "constrained_input_token_estimate": measurement.constrained_input_token_estimate,
            "sha256": digest,
        })
    manifest_path = RESULTS_DIR / "pilot-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # --- cost estimate (gpt-4o-mini assumed prices; no retries) ---
    def cost_estimate(input_tokens: int, output_tokens_per_report: int, n_reports: int) -> dict[str, float]:
        total_input = input_tokens
        total_output = output_tokens_per_report * n_reports
        input_cost = total_input / 1_000_000 * INPUT_PRICE_PER_MTOK
        output_cost = total_output / 1_000_000 * OUTPUT_PRICE_PER_MTOK
        return {
            "reports": n_reports,
            "total_input_tokens": total_input,
            "total_output_tokens_cap": total_output,
            "input_cost_usd": round(input_cost, 4),
            "output_cost_usd": round(output_cost, 4),
            "total_cost_usd": round(input_cost + output_cost, 4),
        }

    level0_input_sum = sum(r.constrained_input_token_estimate for r in level0_results.values())
    level0_cost = cost_estimate(level0_input_sum, COST_ESTIMATE_OUTPUT_TOKENS_PER_REPORT, 37)

    large19_input_sum = sum(level0_results[p].constrained_input_token_estimate for p in large_level0)
    large19_cost = cost_estimate(large19_input_sum, COST_ESTIMATE_OUTPUT_TOKENS_PER_REPORT, 19)

    level1_input_sum = sum(r.constrained_input_token_estimate for r in level1_results.values())
    level1_cost = cost_estimate(level1_input_sum, COST_ESTIMATE_OUTPUT_TOKENS_PER_REPORT, len(level1_results))

    pilot_input_sum = sum(level0_results[p].constrained_input_token_estimate for p in pilot_paths)
    pilot_cost = cost_estimate(pilot_input_sum, PILOT_OUTPUT_TOKEN_CAP, 3)

    covered_members = set()
    for p in large_level0:
        covered_members.update(level0_members[p])
    excluded_by_alt = total_members - len(covered_members)

    # --- full detail JSON ---
    def row(measurement: CommunityMeasurement) -> dict[str, Any]:
        return {
            "path": measurement.path,
            "level": measurement.level,
            "canonical_node_count": measurement.canonical_node_count,
            "internal_projection_edge_count": measurement.internal_projection_edge_count,
            "internal_domain_relationship_count": measurement.internal_domain_relationship_count,
            "raw_description_token_estimate": measurement.raw_description_token_estimate,
            "constrained_input_token_estimate": measurement.constrained_input_token_estimate,
            "included_node_count": measurement.included_node_count,
            "included_domain_relationship_count": measurement.included_domain_relationship_count,
            "omitted_nodes": measurement.omitted_nodes,
            "omitted_domain_relationships": measurement.omitted_domain_relationships,
            "omitted_descriptions": measurement.omitted_descriptions,
            "truncated_descriptions": measurement.truncated_descriptions,
        }

    detail = {
        "token_counting_method": "character/4 ceiling ESTIMATE (no tiktoken result used)",
        "level0": [row(level0_results[p]) for p, _ in ordered_level0],
        "level1": [row(level1_results[p]) for p in sorted(level1_results, key=path_tuple)],
        "level0_large_gt10": sorted(large_level0.keys(), key=path_tuple),
        "level0_singletons_non_isolated": sorted(level0_singletons.keys(), key=path_tuple),
        "level1_singletons_non_isolated": sorted(level1_singletons.keys(), key=path_tuple),
        "pilot_selection": manifest["pilots"],
        "cost_estimates": {
            "level0_all_37": level0_cost,
            "level0_large19_alternative": large19_cost,
            "level1_full_reporting_level": level1_cost,
            "pilot_3": pilot_cost,
        },
        "coverage": {
            "level0_members_total": total_members,
            "level0_communities": len(level0_members),
            "level1_members_total": sum(len(v) for v in level1_members.values()),
            "level1_communities": len(level1_members),
        },
    }
    DOCS_JSON_OUT.write_text(json.dumps(detail, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print("wrote:", DOCS_JSON_OUT.relative_to(ROOT))
    print("wrote:", manifest_path.relative_to(ROOT))
    for p in manifest["pilots"]:
        print("wrote:", p["file"])
    print()
    print("level0 communities:", len(level0_members), "members:", total_members)
    print("level0 >10 nodes:", len(large_level0))
    print("level0 singletons (non-isolated):", len(level0_singletons))
    print("level1 communities:", len(level1_members), "singletons (non-isolated):", len(level1_singletons))
    print("pilots:", [(p["label"], p["community_id"], p["canonical_node_count"]) for p in manifest["pilots"]])
    print("level0 cost:", level0_cost)
    print("large19 cost:", large19_cost)
    print("level1 cost:", level1_cost)
    print("pilot cost:", pilot_cost)
    print("members not covered by the 19-large alternative:", excluded_by_alt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
