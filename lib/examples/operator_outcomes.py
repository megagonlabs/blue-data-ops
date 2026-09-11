from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.sql.sqlite.sqlite_sql_source import SQLiteDBSource

from blue_data_ops import RegistrySeam
from blue_data_ops.operators import versioned_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor


def materialized_pipeline(source: str, database: str, table: str) -> DataPipeline:
    plan = DataPipeline(id="persist-readings")
    incoming = plan.define_input("readings")
    inserted = plan.define_operator(
        "insert_table@3.0.0",
        attributes={"source": source, "database": database, "table": table},
    )
    average = plan.define_operator("avg@3.0.0", attributes={"avg_key": "reading"})
    outgoing = plan.define_output("mean")
    plan.set_plan_input(incoming)
    plan.set_plan_output(outgoing)
    plan.connect_nodes(incoming, inserted)
    plan.connect_nodes(inserted, average)
    plan.connect_nodes(average, outgoing)
    return DataPipeline.from_dict(plan.to_dict())


def main() -> None:
    source_name, database, table = "example_sqlite", "readings", "samples"
    with TemporaryDirectory(prefix="blue-data-ops-outcomes-") as directory:
        database_path = Path(directory) / f"{database}.db"
        with sqlite3.connect(database_path) as connection:
            connection.execute(f'CREATE TABLE "{table}" ("id" INTEGER, "reading" INTEGER)')
        source = SQLiteDBSource(
            source_name,
            properties={"connection": {"protocol": "sqlite", "database_directory": directory}},
        )
        seam = RegistrySeam(DataRegistry(name="outcome-example", rebuild=True))
        seam.register_source(source)
        executor = PipelineExecutor(versioned_registry())
        properties = {"data_registry": seam}

        empty = executor.execute(
            materialized_pipeline(source_name, database, table), [[], []], properties
        )
        assert empty.succeeded and empty.output_data == [[]]
        assert len(empty.node_runs) == 2
        expected_empty_shapes = [
            (
                {"groups": 2, "rows_per_group": [0, 0]},
                {"groups": 1, "rows_per_group": [0]},
            ),
            (
                {"groups": 1, "rows_per_group": [0]},
                {"groups": 1, "rows_per_group": [0]},
            ),
        ]
        for node, (input_shape, output_shape) in zip(
            empty.node_runs, expected_empty_shapes, strict=True
        ):
            assert not node.exec_meta.errors and node.exec_meta.is_empty
            assert node.output_data == [[]]
            assert node.exec_meta.traces["input_shape"] == input_shape
            assert node.exec_meta.traces["output_shape"] == output_shape
        assert empty.node_runs[0].output_attributes == {"num_rows_insert": 0}
        assert empty.node_runs[1].output_attributes == {"num_values_used": 0}

        rejected = executor.execute(
            materialized_pipeline(source_name, database, table),
            [[{"id": 100, "reading": 99}], [{}]],
            properties,
        )
        assert not rejected.succeeded and len(rejected.node_runs) == 1
        rejection = rejected.node_runs[0]
        assert rejection.exec_meta.errors[0].code.value == "INVALID_INPUT"
        assert rejection.output_data == [[]] and rejection.output_attributes == {}
        assert not rejection.exec_meta.is_empty
        assert rejection.exec_meta.traces["input_shape"] == {
            "groups": 2,
            "rows_per_group": [1, 1],
        }
        assert "output_shape" not in rejection.exec_meta.traces
        with sqlite3.connect(database_path) as connection:
            assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone() == (0,)

        rows = [[{"id": 101, "reading": 7}, {"id": 102, "reading": 19}, {"id": 103, "reading": 28}]]
        run = executor.execute(
            materialized_pipeline(source_name, database, table), rows, properties
        )
        if not run.succeeded:
            raise RuntimeError("Inspect the database before retrying", run.node_runs[-1].exec_meta)
        inserted, average = run.node_runs
        assert inserted.output_data == rows
        assert run.output_data == average.output_data == [[{"avg": 18.0}]]
        with sqlite3.connect(database_path) as connection:
            stored = connection.execute(
                f'SELECT "id", "reading" FROM "{table}" ORDER BY "id"'
            ).fetchall()
        assert stored == [(101, 7), (102, 19), (103, 28)]
        count = inserted.output_attributes.get("num_rows_insert")
        if count is not None:
            assert count == len(stored)
        used = average.output_attributes.get("num_values_used")
        if used is not None:
            assert used == 3
        expected_shapes = [
            (
                {"groups": 1, "rows_per_group": [3]},
                {"groups": 1, "rows_per_group": [3]},
            ),
            (
                {"groups": 1, "rows_per_group": [3]},
                {"groups": 1, "rows_per_group": [1]},
            ),
        ]
        for node, (input_shape, output_shape) in zip(run.node_runs, expected_shapes, strict=True):
            assert not node.exec_meta.errors and not node.exec_meta.is_empty
            traces = node.exec_meta.traces
            assert traces["input_shape"] == input_shape
            assert traces["output_shape"] == output_shape
            elapsed_ms = traces.get("elapsed_ms")
            assert elapsed_ms is None or elapsed_ms >= 0
            print(
                json.dumps(
                    {
                        "operator_id": node.operator_id,
                        "output_data": node.output_data,
                        "output_attributes": node.output_attributes,
                        "exec_meta": node.exec_meta._asdict(),
                        "actual_execution": {
                            "input_shape": traces.get("input_shape"),
                            "output_shape": traces.get("output_shape"),
                            "elapsed_ms": elapsed_ms,
                        },
                    },
                    sort_keys=True,
                )
            )
        print("stored rows:", stored)
        print("successful empty: two nodes; invalid input: stopped before writing")


if __name__ == "__main__":
    main()
