"""Compatibility evidence: 2.8.0 deprecates the refinement surface.

``refiner()``, ``refine()``, and ``PipelinePlanner.plan_refinement()`` stay callable for the
rest of 2.x and are removed in 3.0.0. This script keeps calling them so the seam stays
exercised; do not copy it into a new integration. Each ``refine()`` call below emits a
``BlueDataOpsDeprecationWarning``, and nothing here filters that warning away.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import DataPipeline, RefinableOperator


def _operator_ids(plans: Sequence[DataPipeline]) -> list[list[str]]:
    return [
        sorted(
            cast(str, cast(dict[str, Any], entity)["operator_id"])
            for entity in plan.get_entities(type="OPERATOR").values()
        )
        for plan in plans
    ]


def main() -> None:
    registry = versioned_registry()

    multipart = registry.resolve("multipart_query@2.0.0")
    assert isinstance(multipart, RefinableOperator)
    multipart_plans, multipart_meta = multipart.refine(
        [[]],
        {
            "plans": [
                [
                    {
                        "table": "orders",
                        "description": "read orders",
                        "sql": "SELECT * FROM orders",
                        "columns": [{"name": "total", "type": "float"}],
                        "dependency": [],
                        "generality": 0,
                    }
                ]
            ],
        },
    )

    routed = registry.resolve("nl2query_router@2.0.0")
    assert isinstance(routed, RefinableOperator)
    routed_plans, routed_meta = routed.refine(
        [
            [
                {
                    "name": "demo_sqlite",
                    "type": "source",
                    "scope": "/source/demo_sqlite",
                    "properties": {"connection": {"protocol": "sqlite"}},
                }
            ]
        ],
        {
            "search_query": "list orders",
            "protocol": "sqlite",
            "columns": [{"name": "total"}],
            "execute_query": False,
        },
    )

    discovered = registry.resolve("plan_discover@2.0.0")
    assert isinstance(discovered, RefinableOperator)
    discovered_plans, discovered_meta = discovered.refine(
        [[]],
        {"task": "starter", "approximate": True, "data": "rows"},
    )

    assert not any(meta.errors for meta in (multipart_meta, routed_meta, discovered_meta))
    print("multipart:", _operator_ids(multipart_plans))
    print("router:", _operator_ids(routed_plans))
    print("discovery:", _operator_ids(discovered_plans))


if __name__ == "__main__":
    main()
