from __future__ import annotations

import re
from collections.abc import Sequence

from blue_data_ops.operators import OperatorEmbeddingIndex, active_registry
from blue_data_ops.plan import DiscoveryQuery, PipelinePlanner, PlanningRequest, RulePlanGenerator


class KeywordEmbedder:
    """Small local embedder for this example."""

    space_id = "example-keywords-v1"
    _FILTER_WORDS = frozenset({"filter", "keep", "select", "where"})
    _AVERAGE_WORDS = frozenset({"average", "avg", "mean"})

    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]:
        vectors: list[tuple[float, float, float]] = []
        for text in texts:
            words = set(re.findall(r"[a-z0-9_]+", text.lower()))
            vectors.append(
                (
                    float(len(words & self._FILTER_WORDS)),
                    float(len(words & self._AVERAGE_WORDS)),
                    1.0,
                )
            )
        return vectors


def main() -> None:
    registry = active_registry()
    index = OperatorEmbeddingIndex.build(registry, KeywordEmbedder())
    planner = PipelinePlanner(
        registry,
        RulePlanGenerator(),
        embedding_index=index,
    )
    request = PlanningRequest(
        goal="Find the average total above 100",
        discovery_queries=(
            DiscoveryQuery("keep expensive orders", limit=1),
            DiscoveryQuery("mean order total", limit=1),
        ),
        operator_attributes={
            "select": {"operand_key": "total", "operand": ">", "operand_val": 100},
            "avg": {"avg_key": "total", "output_key": "average_total"},
        },
        allowed_operator_ids=("select@2.0.0", "avg@3.0.0", "argmax@2.0.0"),
        input_label="orders",
        output_label="answer",
    )
    orders = [
        [
            {"order_id": 1, "total": 80.0},
            {"order_id": 2, "total": 125.0},
            {"order_id": 3, "total": 210.0},
            {"order_id": 4, "total": 100.0},
        ]
    ]

    result = planner.run(request, orders)

    assert result.execution.succeeded
    assert result.planning.discovery.operator_ids == ("select@2.0.0", "avg@3.0.0")
    assert result.execution.output_data == [[{"average_total": 167.5}]]
    print("discovered:", result.planning.discovery.operator_ids)
    print("output:", result.execution.output_data)


if __name__ == "__main__":
    main()
