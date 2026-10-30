from __future__ import annotations

import inspect
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.errors import is_reply_failure
from blue_data_ops.operators import active_registry, default_registry, versioned_registry
from blue_data_ops.operators import semantic_join_operator as join


def json_provider(text: str, monkeypatch: Any) -> None:
    import litellm

    def fake(**kwargs: Any) -> Any:
        class Response:
            def model_dump(self) -> dict[str, Any]:
                return {
                    "choices": [{"message": {"role": "assistant", "content": text}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                }

        return Response()

    monkeypatch.setattr(litellm, "completion", fake)


def constant(value: Any) -> Any:
    def result(*args: Any, **kwargs: Any) -> Any:
        return value

    return result


MARKER = "SYNTHETIC_PRIVATE_SEMANTIC_PAYLOAD"
MESSAGE = "model reply did not match the operator's output format"
DATA = [[{"x": MARKER, "y": "other"}]]
PLAN = {"out": {"source_fields": ["x"], "transformation_type": "field_mapping_with_value_change"}}
CASES: dict[str, tuple[dict[str, Any], list[Any]]] = {
    "filter": (
        {"filter_conditions": {"x": "keep"}},
        [
            "",
            None,
            "I cannot answer that request",
            "maybe",
            "Yes.",
            "True.",
            1,
            0,
            1.0,
            0.0,
            {},
            [],
            MARKER,
            object(),
        ],
    ),
    "extract": (
        {"entities": [{"name": "k"}]},
        [[], {}, {"other": []}, {"k": [], "extra": []}, {"k": None}],
    ),
    "project": (
        {"projection_instructions": "rename"},
        [[], None, {"absent": "out"}, {"x": "same", "y": "same"}, {"x": " "}, {"x": 1}],
    ),
    "transform": (
        {"output_desc": {"out": {"description": "target"}}},
        [
            {},
            [],
            {"out": {}},
            {"out": {"source_fields": ["x"]}},
            {
                "out": {
                    "source_fields": "x",
                    "transformation_type": "field_mapping_with_value_change",
                }
            },
            {**PLAN, "extra": {}},
        ],
    ),
    "join": (
        {"estimate_cost": False, "left_fields": [], "right_fields": []},
        [
            {},
            [True],
            {"pair_1": "maybe"},
            {"pair_1": 1},
            {"pair_2": True},
            {"pair_1": True, "pair_2": False},
            MARKER,
        ],
    ),
}


class Replies(LLMClient):
    def __init__(self, values: list[Any]) -> None:
        self.values = list(values)
        self.calls = 0

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def operator(family: str, selection: str) -> Any:
    name = f"semantic_{family}"
    if selection == "default":
        return default_registry().resolve(f"{name}@1.0.0")
    if selection == "active":
        return active_registry().resolve(f"{name}@3.0.0")
    if selection == "selected-v3":
        return default_registry(**{name: "3.0.0"}).resolve(f"{name}@3.0.0")
    return versioned_registry().resolve(f"{name}@{selection}")


def data_for(family: str) -> Any:
    return deepcopy(DATA if family != "join" else [DATA[0], [{"z": MARKER}]])


def assert_failure(result: Any) -> None:
    output, attrs, meta = result
    assert output == [[]] and attrs == {} and meta.is_empty is False
    assert len(meta.errors) == 1
    error = meta.errors[0]
    assert (error.category.name, error.code.name, error.stage.name) == (
        "FAILED",
        "EXECUTION_FAILED",
        "EXECUTE",
    )
    assert error.message == MESSAGE and error.suggestion
    assert MARKER not in str(meta)


@pytest.mark.parametrize("selection", ["default", "1.0.0", "2.0.0", "active", "selected-v3"])
@pytest.mark.parametrize(
    "family,index", [(f, i) for f, (_, bad) in CASES.items() for i in range(len(bad))]
)
def test_bad_reply_is_owned_contained_and_stops_calls(
    family: str, index: int, selection: str, caplog: Any
) -> None:
    attrs, bad = CASES[family]
    client = Replies([bad[index], True])
    op = operator(family, selection)
    result = op.run(data_for(family), deepcopy(attrs), {"llm_client": client})
    assert_failure(result)
    assert result[2].errors[0].operator_id == op.operator_id
    assert client.calls == 1
    assert MARKER not in caplog.text


@pytest.mark.parametrize("family", list(CASES))
@pytest.mark.parametrize("method", ["apply", "invoke"])
def test_raw_calls_raise_safe_owned_error(family: str, method: str) -> None:
    attrs, bad = CASES[family]
    with pytest.raises(ValueError) as caught:
        getattr(operator(family, "2.0.0"), method)(
            data_for(family), deepcopy(attrs), {"llm_client": Replies([bad[0]])}
        )
    error = caught.value
    assert is_reply_failure(error)
    assert error.__context__ is None and error.__cause__ is None
    assert MARKER not in str(error.args)
    assert not getattr(error, "doc", "")


VALID_EMPTY_CONTROLS: list[tuple[str, Any, Any, bool]] = [
    ("filter", False, [[]], True),
    ("filter", "false", [[]], True),
    ("extract", {"k": []}, [[{"k": []}]], False),
    ("project", {}, [[]], True),
    ("join", {"pair_1": False}, [[]], True),
]


@pytest.mark.parametrize("selection", ["default", "2.0.0", "active"])
@pytest.mark.parametrize("family,reply,expected,empty", VALID_EMPTY_CONTROLS)
def test_valid_negative_and_empty_replies(
    family: str, reply: Any, expected: Any, empty: bool, selection: str
) -> None:
    result = operator(family, selection).run(
        data_for(family), deepcopy(CASES[family][0]), {"llm_client": Replies([reply])}
    )
    assert not result[2].errors
    assert result[0] == expected
    assert result[2].is_empty is empty


@pytest.mark.parametrize("reply", [None, "scalar", [1]])
def test_individual_extraction_rejects_non_string_list(reply: Any) -> None:
    attrs = {"entities": [{"name": "k"}], "extract_with_single_prompt": False}
    assert_failure(operator("extract", "2.0.0").run(DATA, attrs, {"llm_client": Replies([reply])}))


def test_individual_empty_list_and_missing_source_need_no_coercion() -> None:
    client = Replies([[]])
    result = operator("extract", "2.0.0").run(
        DATA,
        {
            "entities": [{"name": "k"}, {"name": "missing", "extract_on_fields": ["absent"]}],
            "extract_with_single_prompt": False,
        },
        {"llm_client": client},
    )
    assert not result[2].errors and client.calls == 1
    assert result[0] == [[{"k": [], "missing": []}]]
    assert result[2].is_empty is False


@pytest.mark.parametrize(
    "strategy",
    [
        "auto",
        "per_record",
        "distinct_required_values",
        "distinct_required_values_with_merged_fields",
    ],
)
@pytest.mark.parametrize("reply", [[], "bad json", {}])
def test_generated_record_validation_in_each_strategy(strategy: str, reply: Any) -> None:
    attrs = {
        "output_desc": {"out": {"description": "target", "required": True}},
        "strategy": strategy,
    }
    assert_failure(
        operator("transform", "2.0.0").run(DATA, attrs, {"llm_client": Replies([PLAN, reply])})
    )


@pytest.mark.parametrize("selection", ["2.0.0", "active"])
@pytest.mark.parametrize("required,reply", [(False, {}), ("True", {}), (True, {"out": None})])
def test_transform_optional_null_and_valid_extra_plan_parity(
    selection: str, required: Any, reply: Any
) -> None:
    plan = {**PLAN, "extra": deepcopy(PLAN["out"])}
    result = operator("transform", selection).run(
        DATA,
        {
            "output_desc": {"out": {"description": "target", "required": required}},
            "strategy": "per_record",
        },
        {"llm_client": Replies([plan, reply])},
    )
    assert not result[2].errors
    assert result[0] == [[reply]]
    assert result[2].is_empty is False


@pytest.mark.parametrize("family", ["filter", "extract", "project", "join"])
def test_later_reply_failure_discards_partial_output(family: str) -> None:
    good_replies: dict[str, Any] = {
        "filter": True,
        "extract": {"k": []},
        "project": {"x": "out"},
        "join": {"pair_1": True},
    }
    good = good_replies[family]
    data = [DATA[0] * 3] if family != "join" else [DATA[0] * 3, [{"z": "other"}]]
    if family == "project":
        data = DATA * 3
    client = Replies([good, CASES[family][1][0], good])
    props = {"llm_client": client}
    attrs: dict[str, Any] = {**CASES[family][0], "batch_size": 1, "use_cache": False}
    assert_failure(operator(family, "2.0.0").run(data, attrs, props))
    assert client.calls == 2


@pytest.mark.parametrize("family", list(CASES))
@pytest.mark.parametrize("text", [MARKER, "[]"])
def test_actual_llm_client_extraction_rejects_bad_text(
    family: str, text: str, monkeypatch: Any
) -> None:
    json_provider(text, monkeypatch)
    assert_failure(operator(family, "2.0.0").run(data_for(family), deepcopy(CASES[family][0])))


@pytest.mark.parametrize("mode,rows", [("inner", 1), ("left", 2)])
@pytest.mark.parametrize("optimize", [False, True])
def test_embedding_exception_evaluates_cartesian_batches(
    mode: str, rows: int, optimize: bool, monkeypatch: Any
) -> None:
    def unavailable(*args: Any) -> Any:
        raise RuntimeError("synthetic embedding unavailable")

    monkeypatch.setattr(join, "_get_embedding_model", unavailable)
    client = Replies([{"pair_1": True, "pair_2": False}, {"pair_1": False, "pair_2": False}])
    with pytest.warns(UserWarning, match="falling back to all pairs"):
        result = operator("join", "2.0.0").run(
            [[{"l": "a"}, {"l": "b"}], [{"r": "a"}, {"r": "c"}]],
            {
                **CASES["join"][0],
                "join_type": mode,
                "batch_size": 2,
                "keep_keys": "both",
                "use_embedding_filter": True,
                "optimize_thresholds": optimize,
            },
            {
                "llm_client": client,
                "use_embedding_filter": True,
                "optimize_thresholds": optimize,
                "batch_size": 2,
            },
        )
    assert not result[2].errors and client.calls == 2
    assert len(result[0][0]) == rows
    assert result[0][0][0] == {"l": "a", "r": "a"}
    if mode == "left":
        assert result[0][0][1] == {"l": "b"}


@pytest.mark.parametrize("kind", ["shape", "decoder", "truncated", "arbitrary"])
def test_sampling_exception_propagates_without_retry(kind: str, monkeypatch: Any) -> None:
    import numpy as np

    from blue_data_ops.llm.errors import LLMError, raise_reply_failure

    monkeypatch.setattr(join, "_get_embedding_model", constant(object()))
    monkeypatch.setattr(join, "_generate_embeddings", constant(np.array([[1.0]])))
    monkeypatch.setattr(join, "_compute_cosine_similarity_matrix", constant(np.array([[0.5]])))
    monkeypatch.setattr(join, "_importance_sampling", constant(([0], [1.0])))
    if kind == "decoder":
        try:
            raise_reply_failure("json")
        except ValueError as error:
            reply = error
    else:
        failure_replies: dict[str, Any] = {
            "shape": {},
            "truncated": LLMError("fixed", code="truncated"),
            "arbitrary": RuntimeError(MARKER),
        }
        reply = failure_replies[kind]
    client = Replies([reply, {"pair_1": True}])
    result = operator("join", "2.0.0").run(
        data_for("join"), {**CASES["join"][0], "optimize_thresholds": True}, {"llm_client": client}
    )
    assert result[2].errors and client.calls == 1
    assert MARKER not in str(result[2])


@pytest.mark.parametrize("selection", ["2.0.0", "active"])
def test_successful_low_score_embedding_pass_makes_zero_calls(
    selection: str, monkeypatch: Any
) -> None:
    import numpy as np

    monkeypatch.setattr(join, "_get_embedding_model", constant(object()))
    monkeypatch.setattr(join, "_generate_embeddings", constant(np.array([[1.0]])))
    monkeypatch.setattr(join, "_compute_cosine_similarity_matrix", constant(np.array([[-0.5]])))
    client = Replies([])
    result = operator("join", selection).run(
        data_for("join"), {**CASES["join"][0], "use_embedding_filter": True}, {"llm_client": client}
    )
    assert not result[2].errors and client.calls == 0 and result[0] == [[]]


@pytest.mark.parametrize("selection", ["2.0.0", "active"])
def test_merged_strategy_requires_only_current_output_targets(selection: str) -> None:
    plan = {
        "a": {"source_fields": ["x"], "transformation_type": "field_mapping_with_value_change"},
        "b": {"source_fields": ["y"], "transformation_type": "field_mapping_with_value_change"},
    }
    result = operator("transform", selection).run(
        DATA,
        {
            "output_desc": {key: {"description": key, "required": True} for key in plan},
            "strategy": "distinct_required_values_with_merged_fields",
        },
        {"llm_client": Replies([plan, {"a": "A"}, {"b": "B"}])},
    )
    assert not result[2].errors and result[0] == [[{"a": "A", "b": "B"}]]


def test_active_embedding_exception_propagates_without_model_calls(monkeypatch: Any) -> None:
    def unavailable(*args: Any) -> Any:
        raise RuntimeError(MARKER)

    monkeypatch.setattr(join, "_get_embedding_model", unavailable)
    client = Replies([])
    result = operator("join", "active").run(
        data_for("join"), {**CASES["join"][0], "use_embedding_filter": True}, {"llm_client": client}
    )
    assert result[2].errors and client.calls == 0 and MARKER not in str(result[2])


@pytest.mark.parametrize("mode", ["inner", "left", "right", "outer"])
def test_all_false_join_modes_and_empty_pairs_remain_valid(mode: str) -> None:
    result = operator("join", "2.0.0").run(
        data_for("join"),
        {**CASES["join"][0], "join_type": mode},
        {"llm_client": Replies([{"pair_1": False}])},
    )
    assert not result[2].errors
    expected: dict[str, Any] = {
        "inner": [],
        "left": DATA[0],
        "right": [{}],
        "outer": [*DATA[0], {}],
    }
    assert result[0] == [expected[mode]]
    assert result[2].is_empty is (mode == "inner")
    client = Replies([])
    result = operator("join", "2.0.0").run([[], []], CASES["join"][0], {"llm_client": client})
    assert not result[2].errors and client.calls == 0
    assert result[0] == [[]] and result[2].is_empty is True


def test_embedding_fallback_clears_partial_automatic_matches(monkeypatch: Any) -> None:
    class BrokenRow:
        def __getitem__(self, index: int) -> float:
            if index == 0:
                return 1.0
            raise RuntimeError("synthetic matrix read failure")

    class BrokenMatrix:
        shape = (2, 2)

        def __getitem__(self, index: int) -> BrokenRow:
            return BrokenRow()

    monkeypatch.setattr(join, "_get_embedding_model", constant(object()))
    monkeypatch.setattr(join, "_generate_embeddings", constant(object()))
    monkeypatch.setattr(join, "_compute_cosine_similarity_matrix", constant(BrokenMatrix()))
    client = Replies([{"pair_1": False, "pair_2": False}, {"pair_1": False, "pair_2": False}])
    with pytest.warns(UserWarning, match="falling back to all pairs"):
        result = operator("join", "2.0.0").run(
            [[{"l": "a"}, {"l": "b"}], [{"r": "a"}, {"r": "b"}]],
            {**CASES["join"][0], "use_embedding_filter": True, "batch_size": 2},
            {"llm_client": client},
        )
    assert not result[2].errors and result[0] == [[]] and client.calls == 2


@pytest.mark.parametrize("family", ["join", "transform"])
def test_raw_json_translation_discards_private_decoder_chain(family: str) -> None:
    values = [MARKER] if family == "join" else [PLAN, MARKER]
    with pytest.raises(ValueError) as caught:
        operator(family, "2.0.0").apply(
            data_for(family), deepcopy(CASES[family][0]), {"llm_client": Replies(values)}
        )
    error = caught.value
    assert is_reply_failure(error)
    assert error.__context__ is None and error.__cause__ is None
    assert MARKER not in str(error.args) and not getattr(error, "doc", "")


@pytest.mark.parametrize("selection", ["default", "1.0.0", "2.0.0"])
@pytest.mark.parametrize(
    "reply,include",
    [
        (True, True),
        (False, False),
        ("true", True),
        (" FALSE\t", False),
        ("yes", True),
        (" YeS\n", True),
        ("1", True),
        (" 1\t", True),
        ("include", True),
        ("\nInClUdE ", True),
    ],
)
def test_legacy_filter_recognized_decisions(selection: str, reply: Any, include: bool) -> None:
    client = Replies([reply])
    output, attrs, meta = operator("filter", selection).run(
        DATA, CASES["filter"][0], {"llm_client": client}
    )
    assert output == (DATA if include else [[]])
    assert attrs == {} and not meta.errors and meta.is_empty is (not include)
    assert client.calls == 1


@pytest.mark.parametrize("selection", ["default", "1.0.0", "2.0.0"])
@pytest.mark.parametrize("method", ["run", "apply", "invoke"])
@pytest.mark.parametrize("return_idx", [False, True])
def test_legacy_filter_mixed_decisions_across_groups(
    selection: str, method: str, return_idx: bool
) -> None:
    data = [[{"x": i} for i in range(5)], [], [{"x": 5}, {"x": 6}]]
    client = Replies([" YeS ", False, "1", "InClUdE", "true", " false\n", True])
    expected = (
        [[{"indices": [0, 2, 3, 4]}], [], [{"indices": [1]}]]
        if return_idx
        else [[data[0][i] for i in [0, 2, 3, 4]], [], [data[2][1]]]
    )
    value = getattr(operator("filter", selection), method)(
        data, {**CASES["filter"][0], "return_idx": return_idx}, {"llm_client": client}
    )
    if method == "run":
        assert not value[2].errors and value[2].is_empty is False
        value = value[0]
    assert value == expected and client.calls == 7


@pytest.mark.parametrize("selection", ["default", "1.0.0", "2.0.0"])
@pytest.mark.parametrize("method", ["run", "apply", "invoke"])
@pytest.mark.parametrize("return_idx", [False, True])
def test_legacy_filter_later_maybe_fails_whole_call(
    selection: str, method: str, return_idx: bool
) -> None:
    data = [[{"x": 0}, {"x": 1}], [{"x": 2}, {"x": 3}]]
    client = Replies(["yes", "false", "maybe", "include"])
    op = operator("filter", selection)
    attrs = {**CASES["filter"][0], "return_idx": return_idx}
    if method == "run":
        assert_failure(op.run(data, attrs, {"llm_client": client}))
    else:
        with pytest.raises(ValueError) as caught:
            getattr(op, method)(data, attrs, {"llm_client": client})
        assert is_reply_failure(caught.value)
        assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert client.calls == 3


@pytest.mark.parametrize("selection", ["active", "selected-v3", "3.0.0"])
@pytest.mark.parametrize("reply", ["yes", " YeS\n", "1", " 1 ", "include", " InClUdE "])
@pytest.mark.parametrize("method", ["run", "apply", "invoke"])
def test_v3_filter_keeps_its_strict_parser(selection: str, reply: str, method: str) -> None:
    op = operator("filter", selection)
    assert op.operator_id == "semantic_filter@3.0.0"
    assert Path(inspect.getfile(op.__class__)).name == "_semantic_filter_outcome.py"
    assert op.__class__._execute.__module__ == "blue_data_ops.operators._semantic_filter_outcome"
    client = Replies([reply, True])
    if method == "run":
        assert_failure(op.run(DATA, CASES["filter"][0], {"llm_client": client}))
    else:
        with pytest.raises(ValueError) as caught:
            getattr(op, method)(DATA, CASES["filter"][0], {"llm_client": client})
        assert is_reply_failure(caught.value)
    assert client.calls == 1


@pytest.mark.parametrize("selection", ["default", "1.0.0", "2.0.0"])
@pytest.mark.parametrize("method", ["run", "apply", "invoke"])
@pytest.mark.parametrize(
    "positive,negative",
    [("true", "false"), ("yes", "no"), ("1", "0"), ("include", "exclude"), (True, False)],
)
@pytest.mark.parametrize("return_idx", [False, True])
def test_legacy_filter_paired_nonmatches(
    selection: str, method: str, positive: Any, negative: Any, return_idx: bool
) -> None:
    data = [[{"x": label} for label in "ABCD"]]
    replies = [positive, negative, positive, negative]
    replies = [f" \t{v.upper()}\n" if isinstance(v, str) else v for v in replies]
    result = getattr(operator("filter", selection), method)(
        data, {**CASES["filter"][0], "return_idx": return_idx}, {"llm_client": Replies(replies)}
    )
    if method == "run":
        assert not result[2].errors
        result = result[0]
    assert result == ([[{"indices": [0, 2]}]] if return_idx else [[data[0][0], data[0][2]]])


@pytest.mark.parametrize("selection", ["default", "1.0.0", "2.0.0"])
@pytest.mark.parametrize("method", ["run", "apply", "invoke"])
@pytest.mark.parametrize(
    "positive,negative",
    [
        ("true", "false"),
        ("yes", "no"),
        ("match", "no"),
        ("1", "0"),
        ("join", "exclude"),
        (True, False),
    ],
)
@pytest.mark.parametrize("encoded", [False, True])
def test_legacy_join_paired_nonmatches(
    selection: str, method: str, positive: Any, negative: Any, encoded: bool
) -> None:
    import json

    data = [[{"x": label} for label in "ABCD"], [{"z": "right"}]]
    values = [positive, negative, positive, negative]
    reply = {
        f"pair_{i}": f" \t{v.upper()}\n" if isinstance(v, str) else v
        for i, v in enumerate(values, 1)
    }
    result = getattr(operator("join", selection), method)(
        data,
        {**CASES["join"][0], "keep_keys": "both"},
        {"llm_client": Replies([json.dumps(reply) if encoded else reply])},
    )
    if method == "run":
        assert not result[2].errors
        result = result[0]
    assert result == [[{"x": "A", "z": "right"}, {"x": "C", "z": "right"}]]


@pytest.mark.parametrize("selection", ["active", "selected-v3", "3.0.0"])
@pytest.mark.parametrize("method", ["run", "apply", "invoke"])
@pytest.mark.parametrize(
    "family,reply",
    [("filter", v) for v in ["no", "0", "exclude"]]
    + [
        ("join", {"pair_1": v})
        for v in ["true", "false", "yes", "no", "match", "1", "0", "join", "exclude"]
    ],
)
def test_v3_does_not_inherit_legacy_aliases(
    selection: str, method: str, family: str, reply: Any
) -> None:
    op = operator(family, selection)
    client = Replies([reply])
    if method == "run":
        assert_failure(op.run(data_for(family), CASES[family][0], {"llm_client": client}))
    else:
        with pytest.raises(ValueError) as caught:
            getattr(op, method)(data_for(family), CASES[family][0], {"llm_client": client})
        assert is_reply_failure(caught.value)
    assert client.calls == 1


@pytest.mark.parametrize(
    "reply", ["include", "maybe", "Yes.", "True.", "", None, 1, 0, [], {}, object(), MARKER]
)
@pytest.mark.parametrize("selection", ["default", "1.0.0", "2.0.0"])
@pytest.mark.parametrize("method", ["run", "apply", "invoke"])
def test_legacy_join_bad_value_after_match_fails_whole_call(
    reply: Any, selection: str, method: str, caplog: Any
) -> None:
    data = [[{"x": "A"}, {"x": "B"}], [{"z": MARKER}]]
    client = Replies([{"pair_1": "yes"}, {"pair_1": reply}])
    attrs = {**CASES["join"][0], "batch_size": 1, "use_cache": False}
    if method == "run":
        assert_failure(operator("join", selection).run(data, attrs, {"llm_client": client}))
    else:
        with pytest.raises(ValueError) as caught:
            getattr(operator("join", selection), method)(data, attrs, {"llm_client": client})
        assert is_reply_failure(caught.value)
        assert MARKER not in str(caught.value) and caught.value.__context__ is None
    assert client.calls == 2 and MARKER not in caplog.text
