from __future__ import annotations

import re
from collections.abc import Sequence

from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import OperatorEmbeddingIndex, versioned_registry
from blue_data_ops.plan import DiscoveryQuery, PipelinePlanner, PlanningRequest, RulePlanGenerator


class KeywordEmbedder:
    space_id = "operator-skill-example-v1"
    _AVERAGE_WORDS = frozenset({"average", "avg", "mean"})

    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]:
        vectors: list[tuple[float, float]] = []
        for text in texts:
            words = set(re.findall(r"[a-z0-9_]+", text.casefold()))
            vectors.append((float(len(words & self._AVERAGE_WORDS)), 1.0))
        return vectors


def main() -> None:
    registry = versioned_registry()
    loader = OperatorSkillLoader(registry)
    eligible_ids = set(loader.available_operator_ids())

    embedding_index = OperatorEmbeddingIndex.build(registry, KeywordEmbedder())
    embedding_matches = embedding_index.find("average values", tags=["domain-arithmetic"])
    embedding_selected = next(
        card for card in embedding_matches if card.operator_id in eligible_ids
    )
    embedding_descriptor = loader.describe(embedding_selected.operator_id)
    assert embedding_selected.name == "avg"
    assert embedding_descriptor.card is embedding_selected

    planner = PipelinePlanner(registry, RulePlanGenerator())
    request = PlanningRequest(
        goal="average values",
        discovery_queries=(DiscoveryQuery("average", tags=("domain-arithmetic",), limit=1),),
    )
    snapshot = planner.discover(request)
    planner_selected = snapshot.one("avg")
    assert planner_selected.operator_id in eligible_ids
    planner_descriptor = loader.describe(planner_selected.operator_id)
    assert planner_descriptor.card is planner_selected

    print("embedding caller selected:", embedding_selected.operator_id)
    print("planner caller expanded:", planner_selected.operator_id)


if __name__ == "__main__":
    main()
