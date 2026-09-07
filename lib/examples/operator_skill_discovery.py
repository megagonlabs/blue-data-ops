from __future__ import annotations

from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry


def main() -> None:
    registry = versioned_registry()
    loader = OperatorSkillLoader(registry)
    eligible_ids = set(loader.available_operator_ids())

    matches = registry.find("average", tags=["domain-arithmetic"])
    selected = next(card for card in matches if card.operator_id in eligible_ids)
    descriptor = loader.describe(selected.operator_id)
    view = loader.load(selected.operator_id, level=max(descriptor.declared_levels))

    assert selected.operator_id == "avg@2.0.0"
    assert descriptor.declared_kinds == ("guide", "examples")
    assert descriptor.declared_levels == (2, 3)
    assert view.card is selected

    plan_matches = registry.find("plan_discover", tags=["domain-plan"])
    top_plan_match = plan_matches[0]
    assert top_plan_match.operator_id == "plan_discover@2.0.0"
    assert top_plan_match.operator_id not in eligible_ids

    print("expanded:", selected.operator_id, descriptor.declared_levels)
    print("skipped without loading:", top_plan_match.operator_id)


if __name__ == "__main__":
    main()
