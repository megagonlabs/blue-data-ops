from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from blue_data_ops import ErrorCode, ErrorStage
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import _semantic_join_outcome as outcome_module
from blue_data_ops.operators import versioned_registry

INPUT_DATA = [[{"name": "Ada"}], [{"name": "Ada"}]]
COMMON_ATTRIBUTES: dict[str, Any] = {
    "join_type": "inner",
    "keep_keys": "both",
    "left_fields": [],
    "right_fields": [],
}


class RecordingClient(LLMClient):
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any] | None, dict[str, Any] | None]] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append((input, properties, additional_data))
        return {"pair_1": True}


class BoundaryRecorder:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.client = RecordingClient()
        self.cost_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.resolver_calls: list[dict[str, Any] | None] = []

        def record_cost(*args: object, **kwargs: object) -> dict[str, int | float]:
            self.cost_calls.append((args, kwargs))
            return {
                "max_cost_usd": 0.0,
                "max_llm_calls": 1,
                "n_left": 1,
                "n_right": 1,
                "total_pairs": 1,
            }

        def record_resolver(
            properties: dict[str, Any] | None,
            provider: object | None = None,
        ) -> LLMClient:
            del provider
            self.resolver_calls.append(properties)
            return self.client

        monkeypatch.setattr(outcome_module, "_estimate_join_cost", record_cost)
        monkeypatch.setattr(outcome_module, "resolve_llm_client", record_resolver)

    @property
    def properties(self) -> dict[str, Any]:
        return {"llm_client": self.client}

    def assert_no_work(self) -> None:
        assert self.cost_calls == []
        assert self.resolver_calls == []
        assert self.client.calls == []


def _operator(operator_id: str = "semantic_join@3.0.0") -> Any:
    return versioned_registry().resolve(operator_id)


def _attributes(extra: dict[str, Any]) -> dict[str, Any]:
    return {**deepcopy(COMMON_ATTRIBUTES), **deepcopy(extra)}


def _assert_invalid(result: tuple[Any, Any, Any]) -> None:
    output_data, output_attributes, meta = result
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert len(meta.errors) == 1
    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert meta.errors[0].stage is ErrorStage.VALIDATE


@pytest.mark.parametrize(
    "join_suffix",
    [
        ["_only"],
        "xy",
        "",
        ["_left", 7],
        ("_left", "_right"),
        ["_left", "_middle", "_right"],
    ],
    ids=[
        "wrong-length",
        "non-list",
        "falsey-non-list",
        "non-string-element",
        "tuple",
        "three-elements",
    ],
)
def test_structured_invalid_suffix_is_rejected_before_work(
    join_suffix: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = BoundaryRecorder(monkeypatch)
    result = _operator().run(
        deepcopy(INPUT_DATA),
        _attributes({"join_suffix": join_suffix}),
        recorder.properties,
    )

    recorder.assert_no_work()
    _assert_invalid(result)


@pytest.mark.parametrize(
    "attributes",
    [
        {"estimate_cost": False},
        {"estimate_cost": False, "join_suffix": None},
        {"estimate_cost": False, "join_suffix": []},
    ],
    ids=["omitted", "none", "empty-list"],
)
def test_structured_suffix_fallbacks_remain_valid(
    attributes: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = BoundaryRecorder(monkeypatch)
    result = _operator().run(
        deepcopy(INPUT_DATA),
        _attributes(attributes),
        recorder.properties,
    )

    output_data, output_attributes, meta = result
    assert output_data == [[{"name_left": "Ada", "name_right": "Ada"}]]
    assert output_attributes == {}
    assert meta.is_empty is False
    assert meta.errors == []
    assert len(recorder.resolver_calls) == len(recorder.client.calls) == 1


def test_join_suffix_does_not_select_output_names(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = BoundaryRecorder(monkeypatch)
    result = _operator().run(
        deepcopy(INPUT_DATA),
        _attributes(
            {
                "estimate_cost": False,
                "join_suffix": ["compatibility-left", "compatibility-right"],
                "left_suffix": "_chosen_left",
                "right_suffix": "_chosen_right",
            }
        ),
        recorder.properties,
    )

    assert result[0] == [[{"name_chosen_left": "Ada", "name_chosen_right": "Ada"}]]
    assert result[2].errors == []
    assert len(recorder.resolver_calls) == len(recorder.client.calls) == 1


def test_invoke_rejects_invalid_suffix_before_work(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = BoundaryRecorder(monkeypatch)
    output = _operator().invoke(
        deepcopy(INPUT_DATA),
        _attributes({"join_suffix": ["_only"]}),
        recorder.properties,
    )

    recorder.assert_no_work()
    assert output is None


def test_raw_apply_keeps_wrong_length_result(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = BoundaryRecorder(monkeypatch)
    output = _operator().apply(
        deepcopy(INPUT_DATA),
        _attributes({"estimate_cost": False, "join_suffix": ["_only"]}),
        recorder.properties,
    )

    assert output == []
    recorder.assert_no_work()


@pytest.mark.parametrize("operator_id", ["semantic_join@1.0.0", "semantic_join@2.0.0"])
def test_old_exact_ids_keep_wrong_length_compatibility(operator_id: str) -> None:
    client = RecordingClient()
    attributes = _attributes({"estimate_cost": False, "join_suffix": ["_only"]})
    properties = {"llm_client": client}
    operator = _operator(operator_id)

    output_data, output_attributes, meta = operator.run(
        deepcopy(INPUT_DATA), deepcopy(attributes), properties
    )
    assert output_data == [[]]
    assert output_attributes == {}
    assert meta.is_empty is True
    assert meta.errors == []
    assert operator.invoke(deepcopy(INPUT_DATA), deepcopy(attributes), properties) == []
    assert operator.apply(deepcopy(INPUT_DATA), deepcopy(attributes), properties) == []
    assert client.calls == []


def test_empty_equal_compatibility_strings_work_through_apply_and_invoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = BoundaryRecorder(monkeypatch)
    attributes = _attributes({"estimate_cost": False, "join_suffix": ["", ""]})

    assert _operator().apply(deepcopy(INPUT_DATA), deepcopy(attributes), recorder.properties) == [
        [{"name_left": "Ada", "name_right": "Ada"}]
    ]
    assert _operator().invoke(deepcopy(INPUT_DATA), deepcopy(attributes), recorder.properties) == [
        [{"name_left": "Ada", "name_right": "Ada"}]
    ]
    assert len(recorder.resolver_calls) == len(recorder.client.calls) == 2
