from __future__ import annotations

import os

from blue_data_ops import SemanticFilterOperator


def main() -> None:
    if "OPENAI_API_KEY" not in os.environ:
        raise SystemExit("Set OPENAI_API_KEY before running this live-provider example.")

    output, _, meta = SemanticFilterOperator().run(
        [
            [
                {"name": "chair", "description": "solid oak dining chair"},
                {"name": "lamp", "description": "small metal desk lamp"},
            ]
        ],
        {"filter_conditions": {"description": "made mostly from wood"}},
        {"openai.model": "gpt-4o-mini"},
    )
    if meta.errors:
        raise RuntimeError(meta.errors[0].message)
    print(output)


if __name__ == "__main__":
    main()
