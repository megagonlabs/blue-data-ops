from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import litellm
import pytest

from blue_data_ops.llm import LLMClient, LLMError, prepare_llm_operator_properties
from blue_data_ops.llm.client import (
    RESERVED_OPERATOR_LLM_CONTROLS,
    UsageRecord,
    validate_llm_caller_controls,
)
from blue_data_ops.llm.templating import build_message, extract_output, safe_substitute
from blue_data_ops.operators import versioned_registry
from blue_data_ops.operators.nl2llm_operator import NL2LLMOperator
from blue_data_ops.operators.semantic_filter_operator import SemanticFilterOperator
from blue_data_ops.operators.types import Attributes, DataBundle, Properties
from tests.unit.llm.test_templating import BASE
from tests.unit.operators import test_nl2llm as nl2llm_tests

_json_provider = cast(
    Callable[[str, pytest.MonkeyPatch], None], vars(nl2llm_tests)["_json_provider"]
)

FAMILIES = (
    "nl2sql",
    "nl2bn",
    "nl2llm",
    "semantic_filter",
    "semantic_project",
    "semantic_join",
    "semantic_extract",
    "semantic_transform",
)
REVIEWED_RESERVED_CONTROLS = (
    "input_template",
    "input_json",
    "input_context",
    "input_context_field",
    "input_field",
    "output_template",
    "output_path",
    "output_transformations",
    "output_strip",
    "output_cast",
    "template_syntax",
    "service_prefix",
    "openai.api",
    "openai.service_url",
)
CONTROLS = (
    *REVIEWED_RESERVED_CONTROLS,
    "openai.api_key",
    "openai.mock_response",
    "llm.api_key",
)


def _refusal(key: str) -> tuple[str, str]:
    """An unknown llm.* key is bad_override; every other control here is reserved_field."""
    if key.startswith("llm."):
        return "bad_override", (
            "unsupported llm.* override; accepted: llm.cache, llm.cache_dir, llm.max_parallel, "
            "llm.max_tokens, llm.model, llm.rate_limit, llm.reasoning_effort, llm.stream, "
            "llm.temperature"
        )
    return "reserved_field", "operator template and transport controls are reserved"


def test_reserved_control_inventory_cannot_lose_reviewed_keys():
    assert RESERVED_OPERATOR_LLM_CONTROLS == frozenset(REVIEWED_RESERVED_CONTROLS)


@pytest.mark.parametrize("key", CONTROLS)
@pytest.mark.parametrize("value", [None, "copied-default"])
def test_original_caller_validator_is_pure(key: str, value: str | None):
    properties = {key: value}
    with pytest.raises(LLMError) as raised:
        validate_llm_caller_controls(properties)
    code, message = _refusal(key)
    assert raised.value.code == code
    assert raised.value.retryable is False
    assert str(raised.value) == message
    assert properties == {key: value}


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("key", CONTROLS)
def test_raw_and_retained_paths_check_controls_even_on_noop(
    monkeypatch: pytest.MonkeyPatch, family: str, key: str
):
    registry = versioned_registry()
    for version in ("1.0.0", "2.0.0", "3.0.0"):
        try:
            op = registry.resolve(f"{family}@{version}")
        except (KeyError, ValueError):
            continue
        with pytest.raises(LLMError) as raised:
            op.apply([[]], {}, {key: None})
        assert raised.value.code == _refusal(key)[0]


@pytest.mark.parametrize(
    "data", ["$input", "$missing", "{{ 7*7 }}", "{{", "{% bad %}", 'α "quote"\r\n\n', "x\ry\nz\r\n"]
)
def test_inserted_input_context_and_output_are_literal(data: str):
    props = {**BASE, "input_template": "$topic|$input\r\n"}
    shell = copy.deepcopy(props)
    assert (
        build_message(data, props, {"topic": data})["messages"][0]["content"] == data + "|" + data
    )
    assert props == shell
    assert safe_substitute("$x", x=data) == data
    assert safe_substitute("$$ $x $unknown\r\n", x=data) == "$ " + data + " $unknown\r\n"
    assert (
        extract_output(
            {"choices": [{"message": {"content": data}}]}, {**BASE, "output_template": "[$output]"}
        )
        == "[" + data + "]"
    )


def test_host_client_prompt_and_output_wrapper_are_masked(monkeypatch: pytest.MonkeyPatch):
    _json_provider("true", monkeypatch)
    stored = {
        **NL2LLMOperator.DEFAULT_PROPERTIES,
        "openai.temperature": None,
        "output_template": "WRONG($output)",
    }
    snapshot = copy.deepcopy(stored)
    client = LLMClient("shared", stored)
    op = SemanticFilterOperator()
    data = [[{"value": "{{ 7*7 }} $context\r\n"}]]
    attrs = {"filter_conditions": {"value": "is present"}, "context": "$record {{ raw }}\n"}
    op.apply(data, attrs)
    expected = copy.deepcopy(litellm.calls[-1])
    for _ in range(2):
        assert op.apply(data, attrs, {"llm_client": client}) == data
        assert litellm.calls[-1]["messages"] == expected["messages"]
    assert client.properties == snapshot
    custom = {**op.DEFAULT_PROPERTIES, "output_template": "[$output]"}
    assert prepare_llm_operator_properties(custom, custom, {})["output_template"] == "[$output]"


def test_preimplementation_benign_cache_keys_are_preserved():
    frozen = json.loads(
        (Path(__file__).parents[2] / "fixtures/llm_benign_prompts.json").read_text()
    )
    from blue_data_ops.operators import nl2bn_operator as bn
    from blue_data_ops.operators import nl2sql_operator as sql

    defaults = {
        "nl2sql": sql.NL2SQLOperator.DEFAULT_PROPERTIES,
        "nl2bn": bn.NL2BNOperator.DEFAULT_PROPERTIES,
        "nl2llm": NL2LLMOperator.DEFAULT_PROPERTIES,
    }
    for name, case in frozen.items():
        client = LLMClient("openai", defaults[name])
        # Freeze the complete benign request and its existing key serialization independently.
        props = prepare_llm_operator_properties(dict(defaults[name]), defaults[name], {})
        msg = {key[7:]: value for key, value in props.items() if key.startswith("openai.")}
        msg["messages"] = [{"role": "user", "content": case["prompt"]}]
        kwargs = cast(Any, client)._build_call_kwargs(msg, props)
        assert kwargs == case["kwargs"]
        assert json.dumps(kwargs, sort_keys=True, default=str) == case["cache_key"]


def test_async_and_cached_output_preserve_literal_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from tests.unit.llm.test_client import OP_PROPS

    data = "{{ 7*7 }} $input\r\n"
    calls: list[dict[str, Any]] = []

    async def completion(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"choices": [{"message": {"content": data}}]}

    monkeypatch.setattr(litellm, "acompletion", completion)
    props = {
        **OP_PROPS,
        "input_template": "$input",
        "output_template": "[$output]",
        "llm.cache": True,
        "llm.cache_dir": str(tmp_path),
    }
    client = LLMClient("test", props)

    async def run():
        for _ in range(2):
            assert await client.aexecute_api_call(data) == "[" + data + "]"

    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0]["messages"][0]["content"] == data
    assert cast(UsageRecord, client.last_usage).cache_hit is True


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("version", ["1.0.0", "2.0.0", "3.0.0"])
@pytest.mark.parametrize("sampling", [{}, {"llm.temperature": None}, {"openai.temperature": None}])
def test_all_families_keep_reasoning_sampling_omission(
    monkeypatch: pytest.MonkeyPatch, family: str, version: str, sampling: Properties
):
    from tests.unit.operators.test_nl2bn import ATTRS as bn_attrs
    from tests.unit.operators.test_nl2bn import seam as bn_seam
    from tests.unit.operators.test_nl2sql import ATTRS as sql_attrs
    from tests.unit.operators.test_nl2sql import seam as sql_seam

    values: dict[str, tuple[DataBundle, Attributes, Any]] = {
        "nl2sql": ([[]], sql_attrs, {"query": "SELECT 1"}),
        "nl2bn": (
            [[]],
            {**bn_attrs, "database": "default", "protocol_variant": "pgmpy"},
            {
                "target_node": "cirrhosis",
                "target_state": "present",
                "context": {"alcoholism": "yes"},
            },
        ),
        "nl2llm": ([[]], {"query": "list records"}, []),
        "semantic_filter": (
            [[{"value": "synthetic"}]],
            {"filter_conditions": {"value": "present"}},
            "true",
        ),
        "semantic_project": (
            [[{"value": "synthetic"}]],
            {"projection_instructions": "keep value"},
            {"value": "value"},
        ),
        "semantic_join": (
            [[{"left": "synthetic"}], [{"right": "synthetic"}]],
            {
                "join_predicate": "match",
                "left_fields": ["left"],
                "right_fields": ["right"],
                "use_batch_processing": False,
                "estimate_cost": False,
                "use_embedding_filter": False,
            },
            "true",
        ),
        "semantic_extract": (
            [[{"value": "synthetic"}]],
            {"entities": [{"name": "item", "extract_on_fields": ["value"]}]},
            {"item": ["synthetic"]},
        ),
        "semantic_transform": (
            [[{"value": "synthetic"}]],
            {"output_desc": {"out": {"description": "copy value", "required": True}}},
            {
                "out": {
                    "transformation_type": "field_mapping_without_value_change",
                    "source_fields": ["value"],
                }
            },
        ),
    }
    data, attrs, response = values[family]
    if family == "semantic_join":
        response = {"pair_1": True}
    content = response if isinstance(response, str) else json.dumps(response)
    _json_provider(content, monkeypatch)
    litellm.calls.clear()
    litellm.fail_next.clear()
    op = versioned_registry().resolve(f"{family}@{version}")
    props: Properties = {"llm.model": "gpt-5-mini", "llm.reasoning_effort": "low", **sampling}
    if family in ("nl2bn", "nl2sql"):
        props["data_registry"] = cast(Any, bn_seam if family == "nl2bn" else sql_seam).__wrapped__()
    if family == "semantic_join":
        props["use_batch_processing"] = False
    _output, _, meta = op.run(data, attrs, props)
    assert meta.errors == []
    assert litellm.calls
    assert all("temperature" not in call for call in litellm.calls)
