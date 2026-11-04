from __future__ import annotations

import argparse
import os
from tempfile import TemporaryDirectory

from _sqlite_demo import build_demo_data_registry

from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import NL2SQLOperator as HostSQL
from blue_data_ops.operators import OperatorRegistry


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

    with TemporaryDirectory(prefix="blue-data-ops-") as directory:
        data_registry = build_demo_data_registry(directory)
        executor = (
            ReadOnlySQLExecutor(data_registry, frozenset({("demo_sqlite", "shop", "public")}))
            if args.execute
            else None
        )
        operators = OperatorRegistry()
        operators.register(HostSQL(read_only_executor=executor), version="4.0.0")
        operator = operators.resolve("nl2sql@4.0.0")
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
                **({} if args.execute else {"data_registry": data_registry}),
                "execute_query": args.execute,
                "validate_query_prefixes": ["SELECT"],
                "openai.model": "gpt-4o-mini",
            },
        )
        if meta.errors:
            raise RuntimeError(meta.errors[0].message)
        assert operator.operator_id == "nl2sql@4.0.0"
        print(output)


if __name__ == "__main__":
    main()
