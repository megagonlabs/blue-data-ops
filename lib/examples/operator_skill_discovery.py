from __future__ import annotations

from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

# The retained v1 average card is searchable in the history registry but ships no skill package.
SKILL_INELIGIBLE_OPERATOR_ID = "avg@1.0.0"


def main() -> None:
    registry = versioned_registry()
    loader = OperatorSkillLoader(registry)
    eligible_ids = set(loader.available_operator_ids())

    matches = registry.find("average", tags=["domain-arithmetic"])
    selected = next(card for card in matches if card.operator_id in eligible_ids)
    skipped = next(card for card in matches if card.operator_id not in eligible_ids)
    descriptor = loader.describe(selected.operator_id)
    view = loader.load(selected.operator_id, level=max(descriptor.declared_levels))

    assert selected.name == "avg"
    assert descriptor.declared_kinds == ("guide", "examples")
    assert descriptor.declared_levels == (2, 3)
    assert view.card is selected

    assert skipped.operator_id == SKILL_INELIGIBLE_OPERATOR_ID
    assert SKILL_INELIGIBLE_OPERATOR_ID not in eligible_ids

    print("expanded:", selected.operator_id, descriptor.declared_levels)
    print("skipped without loading:", skipped.operator_id)


if __name__ == "__main__":
    main()
