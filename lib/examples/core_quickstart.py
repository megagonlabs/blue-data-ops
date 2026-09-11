from __future__ import annotations

from blue_data_ops import AvgOperator, NormalizeTextOperator, SelectOperator, UnionOperator


def main() -> None:
    orders = [
        [
            {"id": 1, "region": " east ", "total": 42.0},
            {"id": 2, "region": "west", "total": 125.0},
            {"id": 3, "region": "east", "total": 215.0},
        ]
    ]

    selected, _, selected_meta = SelectOperator().run(
        orders,
        {"operand_key": "total", "operand": ">", "operand_val": 100},
    )
    average, _, average_meta = AvgOperator().run(selected, {"avg_key": "total"})
    normalized, _, normalized_meta = NormalizeTextOperator().run(
        orders,
        {"text_field": ["region"], "normalize_whitespace": True},
    )
    combined, _, combined_meta = UnionOperator().run(
        [selected[0], [{"id": 4, "region": "north", "total": 310.0}]],
        {},
    )

    assert not any(
        meta.errors for meta in (selected_meta, average_meta, normalized_meta, combined_meta)
    )
    print("selected:", selected)
    print("average:", average)
    print("normalized:", normalized)
    print("union:", combined)


if __name__ == "__main__":
    main()
