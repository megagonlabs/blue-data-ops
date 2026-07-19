from __future__ import annotations

import copy
from typing import Any, cast

from blue_data_ops.operators import OperatorRegistry
from blue_data_ops.plan import DataPipeline, EntityType, NodeType, PlanRecord


def operator_records(plan: PlanRecord) -> list[tuple[str, dict[str, Any], PlanRecord]]:
    """Return pinned id, attributes, and node in node insertion order."""
    records: list[tuple[str, dict[str, Any], PlanRecord]] = []
    entities = cast(dict[str, dict[str, PlanRecord]], plan["entities"])
    operators = entities.get(str(EntityType.OPERATOR), {})
    for node in cast(dict[str, PlanRecord], plan["nodes"]).values():
        if node["type"] != str(NodeType.OPERATOR):
            continue
        entity = operators[cast(str, node[str(EntityType.OPERATOR)])]
        records.append(
            (
                cast(str, entity["operator_id"]),
                cast(dict[str, Any], entity["attributes"]),
                node,
            )
        )
    return records


def operator_ids(plan: PlanRecord) -> list[str]:
    return [operator_id for operator_id, _, _ in operator_records(plan)]


def edges(plan: PlanRecord) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for node_id, node in cast(dict[str, PlanRecord], plan["nodes"]).items():
        for next_id in cast(list[str], node["next"]):
            result.add((node_id, next_id))
    return result


def edge_names(plan: PlanRecord) -> set[tuple[str, str]]:
    names: dict[str, str] = {}
    for node_id, node in cast(dict[str, PlanRecord], plan["nodes"]).items():
        names[node_id] = cast(str, node["type"])
    for operator_id, _, node in operator_records(plan):
        names[cast(str, node["id"])] = operator_id
    return {(names[source], names[target]) for source, target in edges(plan)}


def assert_roundtrip(plan: PlanRecord) -> None:
    adopted = copy.deepcopy(plan)
    assert DataPipeline.from_dict(adopted).to_dict() == plan


def assert_registry_resolves(plan: PlanRecord, registry: OperatorRegistry) -> None:
    for operator_id in operator_ids(plan):
        assert registry.resolve(operator_id).name == operator_id.partition("@")[0]


def cte(
    table: str,
    *,
    description: str | None = None,
    dependency: list[str] | None = None,
    generality: Any = 0,
    columns: Any = None,
) -> dict[str, Any]:
    return {
        "description": description or f"find {table}",
        "sql": f"select * from {table}",
        "table": table,
        "columns": [{"name": "value", "type": "str"}] if columns is None else columns,
        "dependency": [] if dependency is None else dependency,
        "generality": generality,
    }
