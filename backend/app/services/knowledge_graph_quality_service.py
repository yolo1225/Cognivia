from __future__ import annotations

from collections import defaultdict
from typing import Iterable


DIRECTIONAL_RELATION_TYPES = {"prerequisite", "depends_on", "next_step"}


def evaluate_graph_quality(
    *,
    item_tags: dict[str, set[str]],
    edges: Iterable[dict[str, object]],
    directions: list[dict[str, object]],
) -> dict[str, object]:
    """Evaluate whether the projected graph is usable as a learning graph."""
    node_ids = set(item_tags)
    directional_edges: list[tuple[str, str]] = []
    related_relations = 0
    invalid_edges = 0
    duplicate_edges = 0
    evidence_missing = 0
    seen: set[tuple[str, str, str]] = set()

    for edge in edges:
        relation_type = str(edge.get("relation_type") or "")
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if relation_type == "related_to":
            related_relations += 1
            continue
        if relation_type not in DIRECTIONAL_RELATION_TYPES:
            continue
        key = (source, target, relation_type)
        if key in seen:
            duplicate_edges += 1
            continue
        seen.add(key)
        if not source or not target or source == target or source not in node_ids or target not in node_ids:
            invalid_edges += 1
            continue
        if not edge.get("evidence_complete", False):
            evidence_missing += 1
        if relation_type == "depends_on":
            source, target = target, source
        directional_edges.append((source, target))

    adjacency: dict[str, set[str]] = defaultdict(set)
    reverse: dict[str, set[str]] = defaultdict(set)
    for source, target in directional_edges:
        adjacency[source].add(target)
        reverse[target].add(source)
    participating = {node for edge in directional_edges for node in edge}
    isolated = node_ids - participating

    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_count = 0

    def visit(node: str) -> None:
        nonlocal cycle_count
        if node in visiting:
            cycle_count += 1
            return
        if node in visited:
            return
        visiting.add(node)
        for child in adjacency[node]:
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in node_ids:
        visit(node)

    def longest_path(nodes: set[str]) -> int:
        memo: dict[str, int] = {}

        def length(node: str, trail: set[str]) -> int:
            if node in trail:
                return 0
            if node in memo:
                return memo[node]
            children = adjacency[node] & nodes
            result = 1 + max((length(child, trail | {node}) for child in children), default=0)
            memo[node] = result
            return result

        return max((length(node, set()) for node in nodes), default=0)

    mapped_nodes: set[str] = set()
    deficient_nodes: set[str] = set()
    direction_metrics: list[dict[str, object]] = []
    for direction in directions:
        tags = {str(tag).casefold() for tag in direction.get("match_tags") or []}
        nodes = {
            item_id
            for item_id, values in item_tags.items()
            if tags & {str(value).casefold() for value in values}
        }
        mapped_nodes.update(nodes)
        direction_participating = nodes & participating
        direction_edges = [
            (source, target)
            for source, target in directional_edges
            if source in nodes and target in nodes
        ]
        direction_metrics.append({
            "value": str(direction.get("value") or "unknown"),
            "label": str(direction.get("label") or direction.get("value") or "未命名方向"),
            "nodes": len(nodes),
            "directional_relations": len(direction_edges),
            "path_participating_nodes": len(direction_participating),
            "path_participation_ratio": round(
                len(direction_participating) / len(nodes) if nodes else 0.0, 4
            ),
            "isolated_nodes": len(nodes - participating),
            "longest_path_nodes": longest_path(nodes),
        })
        if (
            not nodes
            or len(direction_participating) / len(nodes) < 0.8
            or (len(nodes) >= 4 and longest_path(nodes) < 3)
        ):
            deficient_nodes.update(nodes)

    total = len(node_ids)
    path_ratio = len(participating) / total if total else 0.0
    isolated_ratio = len(isolated) / total if total else 1.0
    source_traceability = (
        (len(directional_edges) - evidence_missing) / len(directional_edges)
        if directional_edges
        else 0.0
    )
    blocking_issues: list[dict[str, object]] = []

    def block(code: str, message: str, **details: object) -> None:
        blocking_issues.append({"code": code, "message": message, **details})

    if path_ratio < 0.8:
        block("PATH_PARTICIPATION_LOW", "全节点学习路径参与率低于 80%", actual=round(path_ratio, 4))
    if isolated_ratio > 0.15:
        block("ISOLATED_NODES_HIGH", "孤立知识点比例高于 15%", actual=round(isolated_ratio, 4))
    if len(mapped_nodes) < total:
        block("DIRECTION_MAPPING_INCOMPLETE", "存在未归属学习方向的知识点", count=total - len(mapped_nodes))
    for metric in direction_metrics:
        if metric["nodes"] == 0:
            block("EMPTY_DIRECTION", f"学习方向“{metric['label']}”没有匹配知识点")
        elif metric["path_participation_ratio"] < 0.8:
            block("DIRECTION_PATH_COVERAGE_LOW", f"学习方向“{metric['label']}”路径参与率低于 80%")
        if metric["nodes"] >= 4 and metric["longest_path_nodes"] < 3:
            block("DIRECTION_PATH_TOO_SHORT", f"学习方向“{metric['label']}”缺少至少 3 个节点的主路径")
    if cycle_count:
        block("DIRECTIONAL_CYCLE", "方向性关系存在环", count=cycle_count)
    if invalid_edges:
        block("INVALID_DIRECTIONAL_EDGE", "存在自环或无效端点关系", count=invalid_edges)
    if duplicate_edges:
        block("DUPLICATE_DIRECTIONAL_EDGE", "存在重复方向性关系", count=duplicate_edges)
    if evidence_missing:
        block("RELATION_EVIDENCE_INCOMPLETE", "方向性关系证据不完整", count=evidence_missing)

    return {
        "directional_relations": len(directional_edges),
        "related_relations": related_relations,
        "path_participating_nodes": len(participating),
        "path_participation_ratio": round(path_ratio, 4),
        "isolated_nodes": len(isolated),
        "isolated_node_ratio": round(isolated_ratio, 4),
        "isolated_node_ids": sorted(isolated),
        "unmapped_node_ids": sorted(node_ids - mapped_nodes),
        "deficient_node_ids": sorted(deficient_nodes | (node_ids - mapped_nodes)),
        "cycle_count": cycle_count,
        "invalid_edges": invalid_edges,
        "duplicate_edges": duplicate_edges,
        "relation_evidence_completeness": round(source_traceability, 4),
        "direction_metrics": direction_metrics,
        "blocking_issues": blocking_issues,
        "quality_gate_passed": not blocking_issues,
    }
