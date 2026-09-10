from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from blue_data_ops.operators.registry import versioned_registry
from blue_data_ops.operators.types import DataBundle
from blue_data_ops.plan import DataPipeline, PipelineExecutor
from tests.unit.operators.test_v3_outcomes import persisted_rows, sqlite_registry


def pipeline() -> DataPipeline:
    plan = DataPipeline(id="persist-and-average")
    source = plan.define_input("rows")
    inserted = plan.define_operator(
        "insert_table@3.0.0",
        attributes={
            "source": "local",
            "database": "sample",
            "table": "items",
        },
    )
    average = plan.define_operator("avg@3.0.0", attributes={"avg_key": "value"})
    output = plan.define_output("mean")
    plan.set_plan_input(source)
    plan.set_plan_output(output)
    plan.connect_nodes(source, inserted)
    plan.connect_nodes(inserted, average)
    plan.connect_nodes(average, output)
    return DataPipeline.from_dict(plan.to_dict())


@pytest.mark.parametrize(
    "rows,expected,stored,count",
    [
        (
            [[{"id": 10, "value": 12}, {"id": 20, "value": 24}]],
            [[{"avg": 18.0}]],
            [(10, 12), (20, 24)],
            2,
        ),
        (cast(DataBundle, [[]]), cast(DataBundle, [[]]), [], 0),
    ],
)
def test_insert_records_reach_aggregate_and_caller(
    tmp_path: Path,
    rows: DataBundle,
    expected: DataBundle,
    stored: list[tuple[int, int]],
    count: int,
) -> None:
    registry, _source = sqlite_registry(tmp_path)
    run = PipelineExecutor(versioned_registry()).execute(
        pipeline(), rows, {"data_registry": registry}
    )
    assert run.succeeded and run.output_data == expected
    assert persisted_rows(tmp_path) == stored
    insert, average = run.node_runs
    assert insert.output_data == rows
    assert insert.output_attributes == {"num_rows_insert": count}
    assert average.output_data == expected
    assert average.output_attributes == {"num_values_used": count}
    for node in run.node_runs:
        assert not node.exec_meta.errors
        assert node.exec_meta.is_empty is (count == 0)
        assert node.exec_meta.traces["elapsed_ms"] >= 0


def test_invalid_later_record_stops_pipeline_before_write(tmp_path: Path) -> None:
    registry, _source = sqlite_registry(tmp_path)
    run = PipelineExecutor(versioned_registry()).execute(
        pipeline(), [[{"id": 10, "value": 12}], [{}]], {"data_registry": registry}
    )
    assert not run.succeeded and len(run.node_runs) == 1
    rejected = run.node_runs[0]
    assert rejected.output_data == [[]] and rejected.output_attributes == {}
    assert rejected.exec_meta.errors[0].code.value == "INVALID_INPUT"
    assert persisted_rows(tmp_path) == []
