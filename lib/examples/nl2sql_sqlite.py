from __future__ import annotations

import argparse
import os
from tempfile import TemporaryDirectory

from _sqlite_demo import build_demo_registry

from blue_data_ops.operators import active_registry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="execute the generated SELECT against the temporary database",
    )
    args = parser.parse_args()
    if "OPENAI_API_KEY" not in os.environ:
        raise SystemExit("Set OPENAI_API_KEY before running this live-provider example.")

    operator = active_registry().resolve("nl2sql@3.0.0")
    with TemporaryDirectory(prefix="blue-data-ops-") as directory:
        seam = build_demo_registry(directory)
        output, _, meta = operator.run(
            [[]],
            {
                "question": "Which region has the highest total order value?",
                "source": "demo_sqlite",
                "protocol": "sqlite",
                "database": "shop",
                "collection": "public",
            },
            {
                "data_registry": seam,
                "execute_query": args.execute,
                "validate_query_prefixes": ["SELECT"],
                "openai.model": "gpt-4o-mini",
            },
        )
        if meta.errors:
            raise RuntimeError(meta.errors[0].message)
        assert operator.operator_id == "nl2sql@3.0.0"
        print(output)


if __name__ == "__main__":
    main()
