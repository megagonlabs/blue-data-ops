from __future__ import annotations

import os

from blue_data_ops.operators import active_registry


def main() -> None:
    if "OPENAI_API_KEY" not in os.environ:
        raise SystemExit("Set OPENAI_API_KEY before running this live-provider example.")

    operator = active_registry().resolve("semantic_filter@3.0.0")
    output, _, meta = operator.run(
        [
            [
                {"name": "chair", "description": "solid oak dining chair"},
                {"name": "lamp", "description": "small metal desk lamp"},
            ]
        ],
        {"filter_conditions": {"description": "made mostly from wood"}},
        {"openai.model": "gpt-4o-mini"},
    )
    assert operator.operator_id == "semantic_filter@3.0.0"
    if meta.errors:
        raise RuntimeError(meta.errors[0].message)
    print(output)


if __name__ == "__main__":
    main()
