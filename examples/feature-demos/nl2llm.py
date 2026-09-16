from __future__ import annotations

import os

from blue_data_ops.operators import active_registry


def main() -> None:
    if "OPENAI_API_KEY" not in os.environ:
        raise SystemExit("Set OPENAI_API_KEY before running this live-provider example.")

    operator = active_registry().resolve("nl2llm@3.0.0")
    output, _, meta = operator.run(
        [[]],
        {
            "query": "Return two example products",
            "attrs": [
                {"name": "name", "type": "string"},
                {"name": "price", "type": "float"},
            ],
        },
        {"openai.model": "gpt-4o-mini"},
    )
    assert operator.operator_id == "nl2llm@3.0.0"
    if meta.errors:
        raise RuntimeError(meta.errors[0].message)
    print(output)


if __name__ == "__main__":
    main()
