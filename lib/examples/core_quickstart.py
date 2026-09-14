from __future__ import annotations

from blue_data_ops.operators import active_registry


def main() -> None:
    registry = active_registry()
    select = registry.resolve("select@2.0.0")
    average_operator = registry.resolve("avg@3.0.0")
    normalize = registry.resolve("normalize_text@2.0.0")
    union = registry.resolve("union@2.0.0")
    orders = [
        [
            {"id": 1, "region": " east ", "total": 42.0},
            {"id": 2, "region": "west", "total": 125.0},
            {"id": 3, "region": "east", "total": 215.0},
        ]
    ]

    selected, _, selected_meta = select.run(
        orders,
        {"operand_key": "total", "operand": ">", "operand_val": 100},
    )
    average, _, average_meta = average_operator.run(selected, {"avg_key": "total"})
    normalized, _, normalized_meta = normalize.run(
        orders,
        {"text_field": ["region"], "normalize_whitespace": True},
    )
    combined, _, combined_meta = union.run(
        [selected[0], [{"id": 4, "region": "north", "total": 310.0}]],
        {},
    )

    assert not any(
        meta.errors for meta in (selected_meta, average_meta, normalized_meta, combined_meta)
    )
    assert tuple(
        operator.operator_id for operator in (select, average_operator, normalize, union)
    ) == ("select@2.0.0", "avg@3.0.0", "normalize_text@2.0.0", "union@2.0.0")
    print("selected:", selected)
    print("average:", average)
    print("normalized:", normalized)
    print("union:", combined)


if __name__ == "__main__":
    main()
