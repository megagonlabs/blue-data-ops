from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest

from blue_data_ops.operator_skills.loader import snapshot_attribute_specs
from blue_data_ops.operators import active_registry
from blue_data_ops.operators.types import Attributes, DataBundle, Properties


def test_shared_vector_instance_with_all_metadata_readers(monkeypatch: pytest.MonkeyPatch):
    operator = active_registry().resolve("vector_search@3.0.0")
    data = [
        [
            {"embedding": [1.0, 0.0], "embed.model": "all-MiniLM-L6-v2", "id": 1},
            {"embedding": [0.0, 1.0], "embed.model": "all-MiniLM-L6-v2", "id": 2},
        ]
    ]
    attrs = {"query": {"embedding": [1.0, 0.0]}}
    expected = operator.run(data, attrs)
    assert not expected[2].errors
    alias = operator.attributes

    def forbidden():
        raise AssertionError("read refreshed shared alias")

    monkeypatch.setattr(operator, "_refresh_attribute_projection", forbidden)
    barrier = Barrier(8)

    def reader(_: int) -> None:
        barrier.wait(timeout=5)
        for _ in range(20):
            result = operator.run(data, attrs)
            assert result[:2] == expected[:2]
            assert not result[2].errors
            assert operator.is_required("top_k") is False
            assert operator.default_of("normalize") is False
            assert snapshot_attribute_specs(operator)["top_k"].default == 10
            assert operator.attributes is alias
            assert len(alias) > 0

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(reader, range(8)))


def test_defaults_and_live_edits_use_detached_projections(monkeypatch: pytest.MonkeyPatch):
    import blue_data_ops.operators.operator as runtime
    from blue_data_ops.operators import AttributeSpec, FunctionResult, Operator

    class Mutable(Operator):
        name = "mutable"
        attributes = {"items": AttributeSpec(type="list", default=[])}

        def apply(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> DataBundle:
            return input_data

        def _execute(
            self,
            input_data: DataBundle,
            attributes: Attributes,
            properties: Properties | None = None,
        ) -> FunctionResult:
            attributes["items"].append(1)
            return FunctionResult(input_data, attributes)

    op = Mutable()
    original = runtime.apply_defaults

    def interleaved(attributes: Attributes, schema: dict[str, Any]) -> Attributes:
        # A second reader must never clear the schema currently being consumed.
        assert op.default_of("items") == []
        snapshot_attribute_specs(op)
        return original(attributes, schema)

    monkeypatch.setattr(runtime, "apply_defaults", interleaved)
    assert op.run([[{}]], {})[1] == {"items": [1]}
    assert op.run([[{}]], {})[1] == {"items": [1]}
    op.get_attributes()["items"]["default"] = [2]
    monkeypatch.setattr(runtime, "apply_defaults", original)
    assert op.run([[{}]], {})[1] == {"items": [2, 1]}
