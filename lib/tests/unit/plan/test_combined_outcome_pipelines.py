from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from blue_data_ops.operators.registry import versioned_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor
from tests.unit.operators.test_v3_outcomes import persisted_rows, sqlite_registry


def _pipeline(*steps: tuple[str, dict[str, Any]]) -> DataPipeline:
    plan = DataPipeline(id="combined-outcome-product-test")
    previous = plan.define_input("rows")
    plan.set_plan_input(previous)
    for operator_id, attributes in steps:
        current = plan.define_operator(operator_id, attributes=attributes)
        plan.connect_nodes(previous, current)
        previous = current
    output = plan.define_output("result")
    plan.connect_nodes(previous, output)
    plan.set_plan_output(output)
    return DataPipeline.from_dict(plan.to_dict())


class _Embedder:
    def __init__(self, vectors: dict[str, list[int]]) -> None:
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def encode(
        self,
        sentences: list[str],
        batch_size: int = 32,
        normalize_embeddings: bool = False,
    ) -> list[list[int]]:
        del batch_size, normalize_embeddings
        self.calls.append(list(sentences))
        return [list(self.vectors[text]) for text in sentences]


def test_later_group_predictions_reach_the_final_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from blue_data_ops.operators import _vector_embed_outcome as vector_module

    embedder = _Embedder(
        {"north": [0, 0], "south": [9, 9], "near north": [1, 1], "near south": [8, 8]}
    )

    def constructor(_model_ref: str) -> _Embedder:
        return embedder

    monkeypatch.setattr(vector_module, "_embedder_constructor", lambda: constructor)
    pipeline = _pipeline(
        ("vector_embed@3.0.0", {"text_field": ["text"], "append": True}),
        (
            "classify@3.0.0",
            {
                "vector_key": "embedding",
                "label_key": "label",
                "output_key": "prediction",
                "random_state": 11,
            },
        ),
        ("union@2.0.0", {}),
        ("project@3.0.0", {"kept_keys": ["item", "label", "prediction"]}),
    )
    run = PipelineExecutor(versioned_registry()).execute(
        pipeline,
        [
            [
                {"item": "fir", "text": "north", "label": "cool"},
                {"item": "palm", "text": "south", "label": "warm"},
            ],
            [
                {"item": "pine", "text": "near north"},
                {"item": "mango", "text": "near south"},
            ],
        ],
    )

    assert run.succeeded
    assert run.output_data == [
        [
            {"item": "fir", "label": "cool", "prediction": "cool"},
            {"item": "palm", "label": "warm", "prediction": "warm"},
            {"item": "pine", "prediction": "cool"},
            {"item": "mango", "prediction": "warm"},
        ]
    ]
    assert [str(node.status) for node in run.node_runs] == ["EXECUTED"] * 4
    assert embedder.calls == [["north", "south"], ["near north", "near south"]]


def test_invalid_project_stops_before_database_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_registry, source = sqlite_registry(tmp_path)
    connect_calls: list[str] = []
    original_connect = cast(Callable[[str], sqlite3.Connection], getattr(source, "_db_connect"))

    def recording_connect(database: str) -> sqlite3.Connection:
        connect_calls.append(database)
        return original_connect(database)

    monkeypatch.setattr(source, "_db_connect", recording_connect)
    pipeline = _pipeline(
        ("project@3.0.0", {"kept_keys": []}),
        (
            "insert_table@3.0.0",
            {"source": "local", "database": "sample", "table": "items"},
        ),
    )
    executor = PipelineExecutor(versioned_registry())
    preflight = executor.preflight(pipeline, {"data_registry": data_registry})
    run = executor.execute(
        pipeline,
        [[{"id": 72, "value": 5}]],
        {"data_registry": data_registry},
    )

    assert preflight.operator_ids == ("project@3.0.0", "insert_table@3.0.0")
    assert not run.succeeded and len(run.node_runs) == 1
    error = run.node_runs[0].exec_meta.errors[0]
    assert (error.code.value, error.stage.value, error.operator_id) == (
        "INVALID_INPUT",
        "VALIDATE",
        "project@3.0.0",
    )
    assert connect_calls == []
    assert persisted_rows(tmp_path) == []


def test_successful_empty_similarity_continues_to_projection() -> None:
    pipeline = _pipeline(
        ("vector_similarity@3.0.0", {"comparison_mode": "pairwise"}),
        ("project@3.0.0", {"kept_keys": ["id"]}),
    )
    run = PipelineExecutor(versioned_registry()).execute(pipeline, [[], []])

    assert run.succeeded and run.output_data == [[]]
    assert [str(node.status) for node in run.node_runs] == ["EXECUTED", "EXECUTED"]
    assert [node.exec_meta.is_empty for node in run.node_runs] == [True, True]
    assert all(not node.exec_meta.errors for node in run.node_runs)


def test_insert_and_average_attributes_remain_on_their_nodes(tmp_path: Path) -> None:
    data_registry, _source = sqlite_registry(tmp_path)
    pipeline = _pipeline(
        (
            "insert_table@3.0.0",
            {
                "source": "local",
                "database": "sample",
                "table": "items",
                "batch_size": 2,
            },
        ),
        ("avg@3.0.0", {"avg_key": "value", "output_key": "mean"}),
    )
    executor = PipelineExecutor(versioned_registry())
    preflight = executor.preflight(pipeline, {"data_registry": data_registry})
    run = executor.execute(
        pipeline,
        [[{"id": 81, "value": 4}, {"id": 82, "value": 10}]],
        {"data_registry": data_registry},
    )

    assert preflight.operator_ids == ("insert_table@3.0.0", "avg@3.0.0")
    assert run.succeeded and run.output_data == [[{"mean": 7.0}]]
    assert [node.output_attributes for node in run.node_runs] == [
        {"num_rows_insert": 2},
        {"num_values_used": 2},
    ]
    assert all(not node.exec_meta.errors for node in run.node_runs)
    assert persisted_rows(tmp_path) == [(81, 4), (82, 10)]
