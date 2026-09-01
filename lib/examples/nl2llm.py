from __future__ import annotations

import os

from blue_data_ops import NL2LLMOperator


def main() -> None:
    if "OPENAI_API_KEY" not in os.environ:
        raise SystemExit("Set OPENAI_API_KEY before running this live-provider example.")

    output, _, meta = NL2LLMOperator().run(
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
    if meta.errors:
        raise RuntimeError(meta.errors[0].message)
    print(output)


if __name__ == "__main__":
    main()
