"""Offline transport, retry, usage-ledger, and cache tests for LLMClient."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import litellm  # the tests/stubs deterministic fake (conftest inserts the stub path)
import pytest

from blue_data_ops.llm import LLMClient, LLMError, prepare_llm_operator_properties
from tests.optional_integrations import real_litellm_paths

OP_PROPS: dict[str, Any] = {
    "service_prefix": "openai",
    "openai.api": "ChatCompletion",
    "openai.model": "gpt-4o",
    "openai.temperature": 0,
    "service_url": "ws://localhost:8001",
    "openai.service_url": "ws://elsewhere:9",
    "input_template": "Say $input",
    "input_json": '[{"role": "user"}]',
    "input_context": "$[0]",
    "input_context_field": "content",
    "input_field": "messages",
    "output_path": "$.choices[0].message.content",
}


def _prepared(defaults: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    merged = {**defaults, **supplied}
    return prepare_llm_operator_properties(merged, defaults, supplied)


@pytest.fixture(autouse=True)
def _reset_fake(  # pyright: ignore[reportUnusedFunction] — autouse
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(litellm, "provider_list", list(_REVIEWED_PROVIDER_NAMES))
    litellm.calls.clear()
    litellm.fail_next.clear()
    # Dispatch configuration is the deployment's, so every test states its own rather
    # than inheriting whatever the shell that started the run happened to export.
    monkeypatch.delenv("BLUE_DATA_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("BLUE_DATA_LLM_ALLOWED_MODELS", raising=False)


def test_operator_defaults_reach_the_provider() -> None:
    client = LLMClient("test", OP_PROPS)
    out = client.execute_api_call({}, additional_data={})
    assert out == "echo:Say {}"
    call = litellm.calls[-1]
    assert call["model"] == "gpt-4o"
    assert call["temperature"] == 0
    assert call["messages"] == [{"role": "user", "content": "Say {}"}]


@pytest.mark.parametrize(
    ("model", "effort", "keeps_temperature"),
    [
        ("gpt-4o", None, True),
        ("gpt-4o-mini", None, True),
        ("gpt-4.1", None, True),
        ("gpt-4-turbo", None, True),
        ("gpt-5-mini", "low", False),
        ("gpt-5.1", None, True),
        ("gpt-5.1", "low", False),
        ("gpt-5.6-sol", None, False),
        ("gpt-5.6-sol", "none", True),
        ("gpt-6-astra", None, False),
        ("gpt-6-astra", "none", False),
        ("gpt-6-sol", None, False),
        ("gpt-6-sol", "none", False),
        ("gpt-6-luna", "medium", False),
        ("unlisted-gpt-model", None, True),
    ],
)
def test_operator_default_temperature_follows_model(
    model: str, effort: str | None, keeps_temperature: bool
) -> None:
    supplied: dict[str, Any] = {"llm.model": model}
    if effort is not None:
        supplied["llm.reasoning_effort"] = effort
    merged = _prepared(OP_PROPS, supplied)
    assert ("openai.temperature" in merged) is keeps_temperature
    assert OP_PROPS["openai.temperature"] == 0  # no mutation of class defaults


@pytest.mark.parametrize("key", ["openai.temperature", "llm.temperature"])
def test_operator_merge_preserves_explicit_temperature(key: str) -> None:
    merged = _prepared(OP_PROPS, {"llm.model": "gpt-6-sol", key: 0.4})
    assert merged[key] == 0.4
    if key == "llm.temperature":
        assert "openai.temperature" not in merged


def test_operator_merge_replaces_inherited_token_cap() -> None:
    defaults = {**OP_PROPS, "openai.max_tokens": 1024}
    merged = _prepared(defaults, {"llm.model": "gpt-6-sol", "openai.max_completion_tokens": 8192})
    assert "openai.max_tokens" not in merged
    assert merged["openai.max_completion_tokens"] == 8192


def test_other_provider_keeps_its_operator_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", "anthropic")
    merged = _prepared(OP_PROPS, {"llm.model": "gpt-6-sol"})
    assert merged["openai.temperature"] == 0


def test_other_provider_replaces_inherited_token_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", "azure")
    defaults = {**OP_PROPS, "openai.max_tokens": 1024}
    merged = _prepared(defaults, {"openai.max_completion_tokens": 2048})
    assert "openai.max_tokens" not in merged
    assert merged["openai.max_completion_tokens"] == 2048


def test_injected_client_model_selects_default_filter() -> None:
    injected = LLMClient("injected", {"llm.model": "gpt-6-sol"})
    merged = _prepared(OP_PROPS, {"llm_client": injected})
    assert "openai.temperature" not in merged
    injected.execute_api_call({}, properties=merged, additional_data={})
    assert litellm.calls[-1]["model"] == "gpt-6-sol"
    assert "temperature" not in litellm.calls[-1]


def test_injected_client_prefixed_model_overrides_operator_default() -> None:
    injected = LLMClient("injected", {"openai.model": "gpt-6-sol"})
    merged = _prepared(OP_PROPS, {"llm_client": injected})
    assert "openai.model" not in merged
    assert "openai.temperature" not in merged
    injected.execute_api_call({}, properties=merged, additional_data={})
    assert litellm.calls[-1]["model"] == "gpt-6-sol"
    assert "temperature" not in litellm.calls[-1]


def test_injected_client_zero_is_explicit_even_when_it_matches_operator_default() -> None:
    injected = LLMClient("injected", {**OP_PROPS, "llm.model": "gpt-6-sol"})
    merged = _prepared(OP_PROPS, {"llm_client": injected})
    with pytest.raises(LLMError, match="does not accept"):
        injected.execute_api_call({}, properties=merged, additional_data={})


def test_injected_client_explicit_sampling_conflict_is_not_hidden() -> None:
    injected = LLMClient("injected", {"llm.model": "gpt-6-sol", "openai.temperature": 0.3})
    merged = _prepared(OP_PROPS, {"llm_client": injected})
    assert "openai.temperature" not in merged
    with pytest.raises(LLMError) as raised:
        injected.execute_api_call({}, properties=merged, additional_data={})
    assert raised.value.code == "unsupported_parameter"
    assert litellm.calls == []


def test_explicit_prefixed_operator_model_overrides_injected_neutral_model() -> None:
    injected = LLMClient("injected", {"llm.model": "gpt-6-sol"})
    merged = _prepared(OP_PROPS, {"llm_client": injected, "openai.model": "gpt-4o-mini"})
    injected.execute_api_call({}, properties=merged, additional_data={})
    assert litellm.calls[-1]["model"] == "gpt-4o-mini"
    assert litellm.calls[-1]["temperature"] == 0


def test_explicit_prefixed_operator_temperature_overrides_injected_neutral() -> None:
    injected = LLMClient("injected", {"llm.temperature": 0.3})
    merged = _prepared(OP_PROPS, {"llm_client": injected, "openai.temperature": 0.4})
    injected.execute_api_call({}, properties=merged, additional_data={})
    assert litellm.calls[-1]["temperature"] == 0.4


def test_injected_prefixed_generation_settings_replace_operator_defaults() -> None:
    defaults = {**OP_PROPS, "openai.max_tokens": 1024, "openai.stream": False}
    injected = LLMClient(
        "injected",
        {
            **defaults,
            "openai.model": "gpt-5-mini",
            "openai.max_tokens": 16000,
            "openai.temperature": None,
            "openai.stream": True,
        },
    )
    merged = _prepared(defaults, {"llm_client": injected})
    injected.execute_api_call({}, properties=merged, additional_data={})
    call = litellm.calls[-1]
    assert call["model"] == "gpt-5-mini"
    assert call["max_completion_tokens"] == 16000
    assert call["stream"] is True
    assert "temperature" not in call


def test_injected_prefixed_temperature_replaces_operator_default() -> None:
    injected = LLMClient("injected", {**OP_PROPS, "openai.temperature": 0.3})
    merged = _prepared(OP_PROPS, {"llm_client": injected})
    injected.execute_api_call({}, properties=merged, additional_data={})
    assert litellm.calls[-1]["temperature"] == 0.3


@pytest.mark.parametrize("stored_key", ["openai.max_tokens", "llm.max_tokens"])
def test_injected_client_native_cap_replaces_stored_limit(stored_key: str) -> None:
    defaults = {**OP_PROPS, "openai.max_tokens": 1024}
    injected = LLMClient("injected", {**defaults, stored_key: 2048})
    merged = _prepared(
        defaults,
        {"llm_client": injected, "openai.max_completion_tokens": 8192},
    )
    injected.execute_api_call({}, properties=merged, additional_data={})
    call = litellm.calls[-1]
    assert call["max_completion_tokens"] == 8192
    assert "max_tokens" not in call


def test_explicit_neutral_cap_replaces_injected_native_limit() -> None:
    injected = LLMClient("injected", {**OP_PROPS, "openai.max_completion_tokens": 8192})
    merged = _prepared(OP_PROPS, {"llm_client": injected, "llm.max_tokens": 2048})
    injected.execute_api_call({}, properties=merged, additional_data={})
    call = litellm.calls[-1]
    assert call["max_tokens"] == 2048
    assert "max_completion_tokens" not in call


@pytest.mark.parametrize("copy_defaults", [False, True])
@pytest.mark.parametrize(
    ("default_key", "stored_key", "sent_key"),
    [
        ("openai.max_tokens", "openai.max_completion_tokens", "max_completion_tokens"),
        ("llm.max_tokens", "openai.max_completion_tokens", "max_completion_tokens"),
        ("openai.max_completion_tokens", "openai.max_tokens", "max_tokens"),
        ("openai.max_completion_tokens", "llm.max_tokens", "max_tokens"),
    ],
)
def test_injected_client_cap_replaces_equivalent_operator_default(
    default_key: str, stored_key: str, sent_key: str, copy_defaults: bool
) -> None:
    defaults = {**OP_PROPS, default_key: 1024}
    stored: dict[str, Any] = {**defaults} if copy_defaults else {"openai.model": "gpt-4o"}
    stored[stored_key] = 8192
    injected = LLMClient("injected", stored)
    merged = _prepared(defaults, {"llm_client": injected})
    injected.execute_api_call({}, properties=merged, additional_data={})
    call = litellm.calls[-1]
    assert call[sent_key] == 8192
    assert ({"max_tokens", "max_completion_tokens"} & call.keys()) == {sent_key}


def test_distinct_caps_stored_on_one_client_still_conflict() -> None:
    defaults = {**OP_PROPS, "openai.max_tokens": 1024}
    injected = LLMClient(
        "injected",
        {
            "openai.model": "gpt-4o",
            "openai.max_tokens": 2048,
            "openai.max_completion_tokens": 8192,
        },
    )
    merged = _prepared(defaults, {"llm_client": injected})
    with pytest.raises(LLMError) as raised:
        injected.execute_api_call({}, properties=merged, additional_data={})
    assert raised.value.code == "conflicting_token_limits"
    assert litellm.calls == []


@pytest.mark.parametrize("model", ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5-mini"])
def test_reasoning_model_call_omits_inherited_temperature_and_uses_chat_cap(
    model: str,
) -> None:
    defaults = {**OP_PROPS, "openai.max_tokens": 1024}
    client = LLMClient("test", _prepared(defaults, {"llm.model": model}))
    client.execute_api_call({}, additional_data={})
    call = litellm.calls[-1]
    assert "temperature" not in call
    assert call["max_completion_tokens"] == 1024
    assert "max_tokens" not in call


@pytest.mark.parametrize(
    "key",
    [
        "openai.temperature",
        "llm.temperature",
        "openai.top_p",
        "openai.logprobs",
        "openai.top_logprobs",
    ],
)
def test_explicit_sampling_conflict_fails_before_provider_call(key: str) -> None:
    props = _prepared(
        OP_PROPS, {"llm.model": "gpt-6-sol", "llm.reasoning_effort": "medium", key: 0}
    )
    with pytest.raises(LLMError) as raised:
        LLMClient("test", props).execute_api_call({}, additional_data={})
    assert raised.value.code == "unsupported_parameter"
    assert raised.value.retryable is False
    assert key.split(".")[-1] in str(raised.value)
    assert litellm.calls == []


@pytest.mark.parametrize(
    ("model", "effort"),
    [
        ("gpt-5-mini", "none"),
        ("gpt-5.1", "low"),
        ("gpt-5.6-sol", "high"),
        ("gpt-6-astra", None),
        ("gpt-6-astra", "none"),
        ("gpt-6-sol", None),
    ],
)
def test_other_reasoning_profiles_refuse_explicit_temperature(
    model: str, effort: str | None
) -> None:
    supplied: dict[str, Any] = {"llm.model": model, "llm.temperature": 0.2}
    if effort is not None:
        supplied["llm.reasoning_effort"] = effort
    props = _prepared(OP_PROPS, supplied)
    with pytest.raises(LLMError) as raised:
        LLMClient("test", props).execute_api_call({}, additional_data={})
    assert raised.value.code == "unsupported_parameter"
    assert litellm.calls == []


def test_null_effort_uses_model_default_in_sampling_check() -> None:
    props = _prepared(
        OP_PROPS,
        {
            "llm.model": "gpt-6-sol",
            "llm.reasoning_effort": None,
            "llm.temperature": 0.2,
        },
    )
    with pytest.raises(LLMError) as raised:
        LLMClient("test", props).execute_api_call({}, additional_data={})
    assert raised.value.code == "unsupported_parameter"
    assert litellm.calls == []


def test_default_none_effort_allows_sampling_for_gpt_5_1() -> None:
    props = _prepared(OP_PROPS, {"llm.model": "gpt-5.1", "llm.temperature": 0.2})
    LLMClient("test", props).execute_api_call({}, additional_data={})
    assert litellm.calls[-1]["model"] == "gpt-5.1"
    assert litellm.calls[-1]["temperature"] == 0.2


def test_prefixed_null_sampling_does_not_reach_provider() -> None:
    client = LLMClient(
        "test",
        {**OP_PROPS, "llm.model": "gpt-6-sol", "openai.temperature": None},
    )
    client.execute_api_call({}, additional_data={})
    assert "temperature" not in litellm.calls[-1]


def test_neutral_null_sampling_clears_unknown_model_default() -> None:
    props = _prepared(OP_PROPS, {"llm.model": "unlisted-gpt-model", "llm.temperature": None})
    LLMClient("test", props).execute_api_call({}, additional_data={})
    assert "temperature" not in litellm.calls[-1]


def test_reasoning_model_async_call_has_the_same_kwargs() -> None:
    props = _prepared(OP_PROPS, {"llm.model": "gpt-6-luna"})
    asyncio.run(LLMClient("test", props).aexecute_api_call({}, additional_data={}))
    assert litellm.calls[-1]["model"] == "gpt-6-luna"
    assert "temperature" not in litellm.calls[-1]


def test_two_explicit_token_caps_are_rejected() -> None:
    props = {
        **OP_PROPS,
        "llm.model": "gpt-6-sol",
        "openai.temperature": None,
        "openai.max_tokens": 1024,
        "openai.max_completion_tokens": 2048,
    }
    with pytest.raises(LLMError) as raised:
        LLMClient("test", props).execute_api_call({}, additional_data={})
    assert raised.value.code == "conflicting_token_limits"
    assert litellm.calls == []


def test_reserved_fields_never_reach_the_provider() -> None:
    client = LLMClient("test", OP_PROPS)
    client.execute_api_call({}, additional_data={})
    call = litellm.calls[-1]
    assert "api" not in call
    assert "service_url" not in call  # root + prefixed spellings both ignored


@pytest.mark.parametrize("key", ["llm.api", "llm.service_url", "llm.api_key", "llm.bogus"])
def test_unknown_llm_overrides_rejected(key: str) -> None:
    client = LLMClient("test", {**OP_PROPS, key: "x"})
    with pytest.raises(LLMError, match="unknown adapter override"):
        client.execute_api_call({}, additional_data={})
    assert litellm.calls == []  # rejected before any provider call


def test_accepted_llm_override_wins() -> None:
    client = LLMClient("test", {**OP_PROPS, "llm.model": "gpt-4o-mini"})
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1]["model"] == "gpt-4o-mini"


def test_neutral_reasoning_effort_wins_over_the_prefixed_value() -> None:
    client = LLMClient(
        "test",
        {
            **OP_PROPS,
            "openai.reasoning_effort": "high",
            "llm.reasoning_effort": "low",
        },
    )
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1]["reasoning_effort"] == "low"


def test_omitted_reasoning_effort_is_not_added_to_the_provider_call() -> None:
    client = LLMClient("test", OP_PROPS)
    client.execute_api_call({}, additional_data={})
    assert "reasoning_effort" not in litellm.calls[-1]


def test_neutral_null_reasoning_effort_clears_an_inherited_value() -> None:
    client = LLMClient(
        "test",
        {
            **OP_PROPS,
            "openai.reasoning_effort": "high",
            "llm.reasoning_effort": None,
        },
    )
    client.execute_api_call({}, additional_data={})
    assert "reasoning_effort" not in litellm.calls[-1]


def test_neutral_reasoning_effort_reaches_the_async_provider_call() -> None:
    client = LLMClient("test", {**OP_PROPS, "llm.reasoning_effort": "medium"})
    asyncio.run(client.aexecute_api_call({}, additional_data={}))
    assert litellm.calls[-1]["reasoning_effort"] == "medium"


@pytest.mark.parametrize(
    "model", ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-6-luna-2026-09-22"]
)
def test_gpt6_effort_passes_through_older_openai_adapter(model: str) -> None:
    props = _prepared(OP_PROPS, {"llm.model": model, "llm.reasoning_effort": "low"})
    LLMClient("test", props).execute_api_call({}, additional_data={})
    assert litellm.calls[-1]["reasoning_effort"] == "low"
    assert litellm.calls[-1]["allowed_openai_params"] == ["reasoning_effort"]


def test_gpt6_effort_reaches_async_provider() -> None:
    props = _prepared(OP_PROPS, {"llm.model": "gpt-6-luna", "llm.reasoning_effort": "low"})
    asyncio.run(LLMClient("test", props).aexecute_api_call({}, additional_data={}))
    assert litellm.calls[-1]["allowed_openai_params"] == ["reasoning_effort"]


@pytest.mark.parametrize("effort", [None, "low"])
def test_gpt6_effort_pass_through_is_not_caller_controlled(effort: str | None) -> None:
    props = _prepared(OP_PROPS, {"llm.model": "gpt-6-luna", "llm.reasoning_effort": effort})
    LLMClient("test", props).execute_api_call({}, additional_data={})
    assert ("allowed_openai_params" in litellm.calls[-1]) is (effort is not None)

    with pytest.raises(LLMError, match="outside the generation set"):
        LLMClient("test", {**props, "openai.allowed_openai_params": ["api_key"]}).execute_api_call(
            {}, additional_data={}
        )


def test_other_model_does_not_get_gpt6_pass_through() -> None:
    props = _prepared(OP_PROPS, {"llm.model": "gpt-5.6-sol", "llm.reasoning_effort": "low"})
    LLMClient("test", props).execute_api_call({}, additional_data={})
    assert "allowed_openai_params" not in litellm.calls[-1]


def test_no_model_is_an_error() -> None:
    props = {k: v for k, v in OP_PROPS.items() if k != "openai.model"}
    client = LLMClient("test", props)
    with pytest.raises(LLMError, match="no model"):
        client.execute_api_call({}, additional_data={})


def test_per_call_properties_override_instance() -> None:
    client = LLMClient("test", OP_PROPS)
    client.execute_api_call(
        {}, properties={**OP_PROPS, "openai.model": "gpt-x"}, additional_data={}
    )
    assert litellm.calls[-1]["model"] == "gpt-x"


def test_provider_error_wrapped_and_retried() -> None:
    client = LLMClient("test", OP_PROPS)
    litellm.fail_next.extend([RuntimeError("blip"), RuntimeError("blip2")])
    out = client.execute_api_call({}, additional_data={})  # third attempt succeeds
    assert out.startswith("echo:")
    assert len(litellm.calls) == 3


def test_provider_error_exhausts_retries() -> None:
    client = LLMClient("test", OP_PROPS)
    litellm.fail_next.extend([RuntimeError("x")] * 3)
    with pytest.raises(LLMError, match="x"):
        client.execute_api_call({}, additional_data={})


def test_unsupported_generation_parameter_is_safe_and_not_retried() -> None:
    client = LLMClient("test", {**OP_PROPS, "llm.reasoning_effort": "high"})
    private_detail = "provider-private-unsupported-detail"
    litellm.fail_next.append(litellm.UnsupportedParamsError(private_detail))

    with pytest.raises(LLMError) as raised:
        client.execute_api_call({}, additional_data={})

    assert raised.value.code == "unsupported_parameter"
    assert raised.value.retryable is False
    assert private_detail not in str(raised.value)
    assert len(litellm.calls) == 1


def test_server_unsupported_generation_parameter_is_safe_and_not_retried() -> None:
    client = LLMClient("test", {**OP_PROPS, "llm.reasoning_effort": "high"})
    private_detail = "provider-private-server-detail"
    litellm.fail_next.append(
        litellm.BadRequestError(
            private_detail,
            body={
                "error": {
                    "message": private_detail,
                    "type": "invalid_request_error",
                    "param": "reasoning_effort",
                    "code": "unsupported_parameter",
                }
            },
        )
    )

    with pytest.raises(LLMError) as raised:
        client.execute_api_call({}, additional_data={})

    assert raised.value.code == "unsupported_parameter"
    assert raised.value.retryable is False
    assert private_detail not in str(raised.value)
    assert len(litellm.calls) == 1


def test_server_unsupported_value_is_safe_and_not_retried() -> None:
    client = LLMClient("test", OP_PROPS)
    private_detail = "provider-private-value-detail"
    litellm.fail_next.append(
        litellm.BadRequestError(
            private_detail,
            body={"error": {"code": "unsupported_value", "message": private_detail}},
        )
    )
    with pytest.raises(LLMError) as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "unsupported_parameter"
    assert raised.value.retryable is False
    assert private_detail not in str(raised.value)
    assert len(litellm.calls) == 1


def test_length_limited_response_is_not_treated_as_an_answer() -> None:
    class PayloadProbe(LLMClient):
        def reject(self, response: dict[str, Any]) -> None:
            self._reject_truncated(self._materialize_payload(response))

    response = {"choices": [{"finish_reason": "length", "message": {"content": ""}}]}
    client = PayloadProbe("test", OP_PROPS)
    with pytest.raises(LLMError) as raised:
        client.reject(response)
    assert raised.value.code == "truncated_response"
    assert raised.value.retryable is False


def test_truncated_provider_response_records_usage_without_caching(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = str(tmp_path / "llm-cache")
    client = LLMClient("test", {**OP_PROPS, "llm.cache": True, "llm.cache_dir": cache_dir})

    def truncated(**kwargs: Any) -> dict[str, Any]:
        litellm.calls.append(kwargs)
        return {
            "choices": [{"finish_reason": "length", "message": {"content": ""}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 100},
        }

    monkeypatch.setattr(litellm, "completion", truncated)

    def fixed_cost(**kwargs: Any) -> float:
        return 0.4

    monkeypatch.setattr(litellm, "completion_cost", fixed_cost)
    with pytest.raises(LLMError) as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "truncated_response"
    assert len(litellm.calls) == 1
    assert client.last_usage is not None
    assert client.last_usage.prompt_tokens == 12
    assert client.last_usage.completion_tokens == 100
    assert client.last_usage.cost == 0.4
    assert len(client.ledger.records) == 1
    assert len(client._caches[cache_dir]) == 0  # pyright: ignore[reportPrivateUsage]


def test_async_truncated_response_records_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LLMClient("test", OP_PROPS)

    async def truncated(**kwargs: Any) -> dict[str, Any]:
        litellm.calls.append(kwargs)
        return {
            "choices": [{"finish_reason": "length", "message": {"content": ""}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 8},
        }

    monkeypatch.setattr(litellm, "acompletion", truncated)

    def fixed_cost(**kwargs: Any) -> float:
        return 0.2

    monkeypatch.setattr(litellm, "completion_cost", fixed_cost)
    with pytest.raises(LLMError) as raised:
        asyncio.run(client.aexecute_api_call({}, additional_data={}))
    assert raised.value.code == "truncated_response"
    assert len(litellm.calls) == 1
    assert client.last_usage is not None
    assert client.last_usage.prompt_tokens == 4
    assert client.last_usage.completion_tokens == 8
    assert client.last_usage.cost == 0.2


def test_cached_length_limited_response_is_not_treated_as_an_answer(
    tmp_path: Any,
) -> None:
    cache_dir = str(tmp_path / "llm-cache")
    client = LLMClient("test", {**OP_PROPS, "llm.cache": True, "llm.cache_dir": cache_dir})
    client.execute_api_call({}, additional_data={})
    cache = client._caches[cache_dir]  # pyright: ignore[reportPrivateUsage]
    key = next(iter(cache))
    cache[key] = {"choices": [{"finish_reason": "length", "message": {"content": ""}}]}
    with pytest.raises(LLMError) as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "truncated_response"
    assert len(litellm.calls) == 1
    assert client.last_usage is not None and client.last_usage.cache_hit is True
    assert client.last_usage.cost == 0.0
    assert len(client.ledger.records) == 2


def test_other_bad_request_codes_keep_the_ordinary_retry_policy() -> None:
    client = LLMClient("test", {**OP_PROPS, "llm.reasoning_effort": "high"})
    failures = [
        litellm.BadRequestError(
            "other bad request",
            body={"error": {"code": "invalid_request_error"}},
        )
        for _ in range(3)
    ]
    litellm.fail_next.extend(failures)

    with pytest.raises(LLMError) as raised:
        client.execute_api_call({}, additional_data={})

    assert raised.value.code == "provider_error"
    assert raised.value.retryable is True
    assert len(litellm.calls) == 3


def test_async_unsupported_generation_parameter_is_not_retried() -> None:
    client = LLMClient("test", {**OP_PROPS, "llm.reasoning_effort": "high"})
    litellm.fail_next.append(litellm.UnsupportedParamsError("private async detail"))

    with pytest.raises(LLMError) as raised:
        asyncio.run(client.aexecute_api_call({}, additional_data={}))

    assert raised.value.code == "unsupported_parameter"
    assert raised.value.retryable is False
    assert len(litellm.calls) == 1


def test_usage_ledger_accumulates() -> None:
    client = LLMClient("test", OP_PROPS)
    client.execute_api_call({}, additional_data={})
    client.execute_api_call({}, additional_data={})
    assert len(client.ledger.records) == 2
    assert client.last_usage is not None
    assert client.last_usage.model == "gpt-4o"
    assert client.ledger.total_cost == pytest.approx(0.000246)
    assert client.last_usage.latency_seconds >= 0


def test_cache_roundtrip(tmp_path: Any) -> None:
    props = {**OP_PROPS, "llm.cache": True, "llm.cache_dir": str(tmp_path / "c")}
    client = LLMClient("test", props)
    first = client.execute_api_call({}, additional_data={})
    second = client.execute_api_call({}, additional_data={})
    assert first == second
    assert len(litellm.calls) == 1  # the second call was served from the cache


def test_cache_requested_without_diskcache_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import builtins

    monkeypatch.chdir(tmp_path)

    real_import = builtins.__import__

    def no_diskcache(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "diskcache":
            raise ImportError("gone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_diskcache)
    client = LLMClient("test", {**OP_PROPS, "llm.cache": True})
    with pytest.raises(LLMError, match="diskcache is not installed"):
        client.execute_api_call({}, additional_data={})
    assert not (tmp_path / ".blue-data-ops-cache").exists()


# --- what a call property may set on the provider request ----------------------------
# `properties` is an ordinary tool argument on the MCP surface, so every property below
# is reachable by any caller of the LLM-backed tools. The values are literals written
# here to be recognisable in an assertion; this suite reads no credential and sets none.
SENTINEL = "not-a-credential"
ELSEWHERE = "https://elsewhere.invalid/v1"

# The named parameters of `litellm.completion` in the pinned 1.98.0, recorded here so the
# allowlist can be checked against the surface it was derived from. The stub in
# tests/stubs stands in for litellm during this suite, so the real signature cannot be
# read at test time; regenerate with
#
#     python -c "import inspect, litellm; print(sorted(
#         p.name for p in inspect.signature(litellm.completion).parameters.values()
#         if p.kind is not p.VAR_KEYWORD))"
COMPLETION_SIGNATURE: frozenset[str] = frozenset(
    {
        "api_key",
        "api_version",
        "audio",
        "base_url",
        "deployment_id",
        "enable_json_schema_validation",
        "extra_headers",
        "frequency_penalty",
        "function_call",
        "functions",
        "include_server_side_tool_invocations",
        "logit_bias",
        "logprobs",
        "max_completion_tokens",
        "max_tokens",
        "messages",
        "modalities",
        "model",
        "model_list",
        "n",
        "parallel_tool_calls",
        "prediction",
        "presence_penalty",
        "reasoning_effort",
        "response_format",
        "safety_identifier",
        "seed",
        "service_tier",
        "shared_session",
        "stop",
        "stream",
        "stream_options",
        "temperature",
        "thinking",
        "timeout",
        "tool_choice",
        "tools",
        "top_logprobs",
        "top_p",
        "user",
        "verbosity",
        "web_search_options",
    }
)

# What the client removes from that signature, and why each one is the deployment's to set.
WITHHELD_FROM_CALLERS: dict[str, str] = {
    "api_key": "the credential the request authenticates with.",
    "api_version": "which API surface of which account the request is made against.",
    "base_url": "the endpoint the prompt is sent to.",
    "deployment_id": "which provider-side deployment answers.",
    "extra_headers": "carries a credential, and can re-address the request.",
    "model_list": "a routing table, so it chooses the provider as well as the model.",
    "shared_session": "an already-authenticated HTTP session object.",
    "safety_identifier": "the end-user identity the deployment asserts to the provider. "
    "A caller that varies it per call defeats the per-end-user safety enforcement the "
    "field exists to enable, on the deployment's account.",
    "user": "the same identity under the older spelling: an abuse-tracking label written "
    "into the deployment's provider-side record, not a control over what is asked.",
}

# What the client adds from LiteLLM's **kwargs surface, and what each one does. The
# signature is 42 names; `litellm.utils.all_litellm_params` carries 236 more that arrive
# only through **kwargs, and a set derived from the signature alone refused every one of
# them regardless of effect. These five change the request body or the shape of the
# returned content and nothing else.
KWARGS_GENERATION_CONTROLS: dict[str, str] = {
    "assistant_continue_message": "the assistant turn inserted when a provider requires "
    "strictly alternating roles.",
    "enable_prompt_caching": "installs the provider's prompt-cache annotations.",
    "ensure_alternating_roles": "whether to repair a non-alternating message sequence.",
    "merge_reasoning_content_in_choices": "where reasoning text lands in the returned choice.",
    "user_continue_message": "the user turn inserted under the same alternating rule.",
}


def test_the_allowlist_is_the_signature_half_plus_the_reviewed_kwargs_half() -> None:
    """The membership rule, checked rather than described.

    Two halves, each re-derivable: LiteLLM's named parameters with the routing, credential
    and end-user-identity fields removed, plus the `**kwargs` controls that were reviewed
    by effect and found to shape only the request. Every name in either direction has a
    written reason beside it.
    """
    from blue_data_ops.llm.client import (
        _GENERATION_FIELDS,  # pyright: ignore[reportPrivateUsage]
        _KWARGS_GENERATION_FIELDS,  # pyright: ignore[reportPrivateUsage]
        _SIGNATURE_GENERATION_FIELDS,  # pyright: ignore[reportPrivateUsage]
    )

    assert _SIGNATURE_GENERATION_FIELDS <= COMPLETION_SIGNATURE
    assert COMPLETION_SIGNATURE - _SIGNATURE_GENERATION_FIELDS == set(WITHHELD_FROM_CALLERS)
    assert _KWARGS_GENERATION_FIELDS == set(KWARGS_GENERATION_CONTROLS)
    # The half the old derivation could not have reached: none of the five is a named
    # parameter, which is exactly why a signature census refused all of them.
    assert not (_KWARGS_GENERATION_FIELDS & COMPLETION_SIGNATURE)
    assert _GENERATION_FIELDS == _SIGNATURE_GENERATION_FIELDS | _KWARGS_GENERATION_FIELDS


@pytest.mark.parametrize(
    "field,value",
    [
        ("vertex_project", "caller-project"),
        ("vertex_location", "europe-west1"),
        ("aws_region_name", "eu-central-1"),
        ("tenant_id", "caller-tenant"),
    ],
)
def test_a_routing_selector_outside_the_signature_is_refused(field: str, value: str) -> None:
    """The four the denylist let through.

    None of them is spelled like a credential and none was on any name list, and each one
    sends the deployment's prompt, on the deployment's credential, to a project, tenant or
    region the caller picked.
    """
    client = LLMClient("test", {**OP_PROPS, f"openai.{field}": value})
    with pytest.raises(LLMError, match="outside the generation set") as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "reserved_field"
    assert litellm.calls == []


@pytest.mark.parametrize(
    "field,value",
    [
        # The transport half of the signature itself.
        ("api_key", SENTINEL),
        ("base_url", ELSEWHERE),
        ("api_version", "2024-02-01"),
        ("extra_headers", {"Authorization": SENTINEL}),
        ("model_list", [{"model_name": "gpt-4o"}]),
        ("deployment_id", "elsewhere"),
        # A spread of litellm.utils.all_litellm_params, one per hazard: endpoint,
        # provider selection, proxy, credential, region, observability sink, spend.
        ("api_base", ELSEWHERE),
        ("custom_llm_provider", "elsewhere"),
        ("use_litellm_proxy", True),
        ("proxy_server_request", {"url": ELSEWHERE}),
        ("client_secret", SENTINEL),
        ("azure_ad_token_provider", SENTINEL),
        ("azure_username", "someone-else"),
        ("litellm_credential_name", "someone-elses-credential"),
        ("region_name", "eu-central-1"),
        ("allowed_model_region", "eu"),
        ("s3_bucket_name", "a-bucket-the-caller-owns"),
        ("gcs_bucket_name", "a-bucket-the-caller-owns"),
        ("langfuse_secret_key", SENTINEL),
        ("langsmith_api_key", SENTINEL),
        ("dd_api_key", SENTINEL),
        ("arize_api_key", SENTINEL),
        ("headers", {"Authorization": SENTINEL}),
        ("fallbacks", [{"model": "gpt-4o"}]),
        ("num_retries", 100),
        ("max_retries", 100),
        ("max_budget", 10_000),
        ("cache_key", "a-key-the-caller-chose"),
        ("guardrails", []),
        ("litellm_logging_obj", SENTINEL),
        ("no-log", True),
        # End-user identity: written into the deployment's provider-side safety record.
        ("user", "an-end-user-the-caller-named"),
        ("safety_identifier", "an-end-user-the-caller-named"),
    ],
)
def test_a_litellm_parameter_outside_the_generation_set_is_refused(field: str, value: Any) -> None:
    """A denylist over this surface cannot be finished.

    `litellm.utils.all_litellm_params` holds 246 names in 1.98.0 and the next release adds
    more. The sample below is one per hazard class; the allowlist refuses all 246 without
    naming any of them.
    """
    client = LLMClient("test", {**OP_PROPS, f"openai.{field}": value})
    with pytest.raises(LLMError, match="outside the generation set") as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "reserved_field"
    assert litellm.calls == []


def test_a_refusal_names_the_field_and_where_the_setting_belongs() -> None:
    client = LLMClient("test", {**OP_PROPS, "openai.vertex_project": "caller-project"})
    with pytest.raises(LLMError) as raised:
        client.execute_api_call({}, additional_data={})
    message = str(raised.value)
    assert "vertex_project" in message
    assert "environment this deployment runs in" in message
    assert "temperature" in message  # and what a caller may set instead


def test_forbidden_properties_are_not_retryable_on_sync_or_async_paths() -> None:
    for namespace, code in (("llm", "bad_override"), ("openai", "reserved_field")):
        for field in ("api_key", "api_base", "mock_response", "mock_timeout"):
            client = LLMClient("test", {**OP_PROPS, f"{namespace}.{field}": "private value"})
            for use_async in (False, True):
                litellm.calls.clear()
                with pytest.raises(LLMError) as raised:
                    if use_async:
                        asyncio.run(client.aexecute_api_call({}, additional_data={}))
                    else:
                        client.execute_api_call({}, additional_data={})
                assert raised.value.code == code
                assert raised.value.retryable is False
                assert litellm.calls == []


def test_a_routing_selector_is_refused_on_the_async_path() -> None:
    import asyncio

    client = LLMClient("test", {**OP_PROPS, "openai.vertex_project": "caller-project"})
    with pytest.raises(LLMError, match="outside the generation set"):
        asyncio.run(client.aexecute_api_call({}, additional_data={}))
    assert litellm.calls == []


def test_a_refused_field_never_reaches_the_on_disk_cache_key(tmp_path: Any) -> None:
    """The cache key is the serialized call kwargs, so a forwarded credential used to
    be written to disk with it."""
    cache_dir = tmp_path / "c"
    client = LLMClient(
        "test",
        {
            **OP_PROPS,
            "llm.cache": True,
            "llm.cache_dir": str(cache_dir),
            "openai.api_key": SENTINEL,
        },
    )
    with pytest.raises(LLMError, match="outside the generation set"):
        client.execute_api_call({}, additional_data={})

    written = [path for path in cache_dir.rglob("*") if path.is_file()]
    assert not any(SENTINEL in path.read_bytes().decode("utf-8", "replace") for path in written)


def test_the_supported_configuration_route_still_reaches_the_provider() -> None:
    """A model on a call property, the credential in the environment LiteLLM reads."""
    from blue_data_ops.llm.client import (
        _GENERATION_FIELDS,  # pyright: ignore[reportPrivateUsage]
    )

    client = LLMClient("test", {**OP_PROPS, "openai.model": "gpt-4o-mini"})
    client.execute_api_call({}, additional_data={})
    call = litellm.calls[-1]
    assert call["model"] == "gpt-4o-mini"
    # Everything a caller contributed is inside the allowlist; the one field it did not
    # contribute is the dispatch provider the deployment stamps on.
    assert set(call) - {DISPATCH_FIELD} <= _GENERATION_FIELDS
    assert call[DISPATCH_FIELD] == "openai"


@pytest.mark.parametrize(
    "field,value",
    [
        ("top_p", 0.9),
        ("seed", 7),
        ("stop", ["\n\n"]),
        ("n", 2),
        ("presence_penalty", 0.5),
        ("frequency_penalty", 0.25),
        ("max_completion_tokens", 128),
        ("response_format", {"type": "json_object"}),
        ("tool_choice", "auto"),
        ("tools", [{"type": "function", "function": {"name": "f"}}]),
        ("logprobs", True),
        ("reasoning_effort", "low"),
        ("timeout", 30),
        # The reviewed **kwargs half, one case each.
        ("enable_prompt_caching", True),
        ("assistant_continue_message", {"role": "assistant", "content": "continue"}),
        ("user_continue_message", {"role": "user", "content": "continue"}),
        ("ensure_alternating_roles", True),
        ("merge_reasoning_content_in_choices", True),
    ],
)
def test_a_generation_parameter_still_passes_through(field: str, value: Any) -> None:
    """The half of the namespace the denylist was written to protect.

    What the model is asked and how it answers is the caller's to vary; only where the
    request goes and who it authenticates as is closed.
    """
    client = LLMClient("test", {**OP_PROPS, f"openai.{field}": value})
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1][field] == value


@pytest.mark.parametrize("field", ["mock_response", "mock_timeout"])
def test_a_response_substitution_field_is_refused(field: str) -> None:
    """LiteLLM returns `mock_response` instead of calling anyone, so a property that set
    it made a tool hand back the caller's own text as a model answer."""
    client = LLMClient("test", {**OP_PROPS, f"openai.{field}": "an answer the caller wrote"})
    with pytest.raises(LLMError, match="substitute the provider response") as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "reserved_field"
    assert litellm.calls == []


# --- dispatch identity ----------------------------------------------------------------
# `model` is admitted to the generation set because every shipped document, example and
# test selects a model with it. It is also the field LiteLLM resolves a provider from, so
# admitting it re-opened the hole the set was written to close: offline resolution against
# the pinned 1.98.0 shows `vertex_ai/gemini-2.5-pro` selecting Vertex AI, and a bare
# `gemini-2.5-pro` selecting it too, through LiteLLM's model map. The tests below hold the
# line the client now draws: the model is the caller's, the route is the deployment's.

DISPATCH_FIELD = "custom_llm_provider"
PROVIDER_VAR = "BLUE_DATA_LLM_PROVIDER"
OFFERED_MODELS_VAR = "BLUE_DATA_LLM_ALLOWED_MODELS"
REFUSED_ROUTE = "not a call property's to choose"
"""The sentence both dispatch refusals share, so one assertion covers either of them."""


@pytest.mark.parametrize(
    "model",
    [
        "vertex_ai/gemini-2.5-pro",
        "anthropic/claude-sonnet-4-5",
        "azure/command-r-plus",
        "openrouter/anthropic/claude-3",
        "bedrock/anthropic.claude-v2",
    ],
)
@pytest.mark.parametrize("key", ["openai.model", "llm.model"])
def test_a_provider_qualified_model_is_refused(key: str, model: str) -> None:
    """Both routes to `model` reach the same gate.

    `azure/command-r-plus` is in the list because it is the one name LiteLLM re-routes
    whatever `custom_llm_provider` says: `_is_non_openai_azure_model` sends it to the
    openai handler before the pin is consulted.
    """
    client = LLMClient("test", {**OP_PROPS, key: model})
    with pytest.raises(LLMError, match=REFUSED_ROUTE) as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "model_not_allowed"
    assert litellm.calls == []


def test_a_provider_qualified_model_is_refused_on_the_async_path() -> None:
    import asyncio

    client = LLMClient("test", {**OP_PROPS, "openai.model": "vertex_ai/gemini-2.5-pro"})
    with pytest.raises(LLMError, match=REFUSED_ROUTE):
        asyncio.run(client.aexecute_api_call({}, additional_data={}))
    assert litellm.calls == []


def test_a_refused_model_never_reaches_the_on_disk_cache_key(tmp_path: Any) -> None:
    cache_dir = tmp_path / "c"
    client = LLMClient(
        "test",
        {
            **OP_PROPS,
            "llm.cache": True,
            "llm.cache_dir": str(cache_dir),
            "openai.model": "vertex_ai/gemini-2.5-pro",
        },
    )
    with pytest.raises(LLMError, match=REFUSED_ROUTE):
        client.execute_api_call({}, additional_data={})
    written = [path for path in cache_dir.rglob("*") if path.is_file()]
    assert not any("vertex_ai" in path.read_bytes().decode("utf-8", "replace") for path in written)


def test_a_bare_model_still_selects_the_model_and_not_the_route() -> None:
    """The supported route, unchanged: `openai.model` picks the model, every time."""
    client = LLMClient("test", {**OP_PROPS, "openai.model": "gpt-4o-mini"})
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1]["model"] == "gpt-4o-mini"
    assert litellm.calls[-1][DISPATCH_FIELD] == "openai"


def test_a_bare_name_that_would_route_elsewhere_reaches_the_deployments_provider() -> None:
    """`claude-sonnet-4-5` resolves to Anthropic through LiteLLM's model map on its own.

    Refusing only the qualified spelling would have left this open, which is why the pin
    exists as well as the prefix rule.
    """
    client = LLMClient("test", {**OP_PROPS, "openai.model": "claude-sonnet-4-5"})
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1][DISPATCH_FIELD] == "openai"


def test_the_deployment_names_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROVIDER_VAR, "azure")
    client = LLMClient("test", OP_PROPS)
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1][DISPATCH_FIELD] == "azure"


def test_a_caller_cannot_name_the_provider_even_when_the_deployment_has(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROVIDER_VAR, "azure")
    client = LLMClient("test", {**OP_PROPS, f"openai.{DISPATCH_FIELD}": "anthropic"})
    with pytest.raises(LLMError, match="outside the generation set"):
        client.execute_api_call({}, additional_data={})
    assert litellm.calls == []


@pytest.mark.parametrize(
    "model",
    [
        "accounts/fireworks/models/llama-v3",  # Fireworks
        "meta-llama/Llama-3-70b",  # Together
        "mistralai/Mixtral-8x7B-Instruct-v0.1",  # Together again, another vendor namespace
    ],
)
@pytest.mark.parametrize("offered", ["", "gpt-4o {model}"])
def test_a_slash_that_belongs_to_the_model_identifier_is_not_a_route(
    monkeypatch: pytest.MonkeyPatch, model: str, offered: str
) -> None:
    """A slash is not evidence of a route, so the rule cannot be `no slashes`.

    Fireworks and Together name models with a slash in them and the segment before it is a
    vendor namespace, not a provider. The gate asks LiteLLM which names are providers
    instead of reading the punctuation, so these pass whether or not the deployment has
    narrowed what may be asked for.
    """
    monkeypatch.setenv(PROVIDER_VAR, "together_ai")
    if offered:
        monkeypatch.setenv(OFFERED_MODELS_VAR, offered.format(model=model))
    client = LLMClient("test", {**OP_PROPS, "openai.model": model})
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1]["model"] == model
    assert litellm.calls[-1][DISPATCH_FIELD] == "together_ai"


@pytest.mark.parametrize(
    "provider, model",
    [
        (
            "anthropic",
            "azure/command-r-plus",
        ),  # the reproduced bypass, exactly as reported
        ("azure", "azure/command-r-plus"),
        ("openai", "vertex_ai/gemini-2.5-pro"),
        ("openai", "anthropic/claude-sonnet-4-5"),
        ("openai", "bedrock/anthropic.claude-v2"),
    ],
)
def test_offering_a_model_does_not_make_its_route_the_callers(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str
) -> None:
    """Membership and dispatch are separate questions and both have to hold.

    Listing a model said the deployment would answer for it; it never said the caller could
    pick who answers. When membership stood in for dispatch,
    `BLUE_DATA_LLM_ALLOWED_MODELS=azure/command-r-plus` under a deployment pinned to
    `anthropic` produced a request LiteLLM 1.98.0 serves from `openai`.
    """
    monkeypatch.setenv(PROVIDER_VAR, provider)
    monkeypatch.setenv(OFFERED_MODELS_VAR, f"gpt-4o {model}")
    client = LLMClient("test", {**OP_PROPS, "openai.model": model})
    with pytest.raises(LLMError, match=REFUSED_ROUTE) as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "model_not_allowed"
    assert litellm.calls == []


@pytest.mark.parametrize("model", ["gpt-4o-mini", "vertex_ai/gemini-2.5-pro"])
def test_a_model_the_deployment_does_not_offer_is_refused(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    monkeypatch.setenv(OFFERED_MODELS_VAR, "gpt-4o")
    client = LLMClient("test", {**OP_PROPS, "openai.model": model})
    with pytest.raises(LLMError, match="not one this deployment offers") as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "model_not_allowed"
    assert litellm.calls == []


def test_an_offered_model_still_reaches_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OFFERED_MODELS_VAR, "gpt-4o")
    client = LLMClient("test", OP_PROPS)
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1]["model"] == "gpt-4o"


# --- the outcome check ----------------------------------------------------------------
# The spelling check above refuses a route written into the model string. It holds only for
# the routes LiteLLM spells that way, so the gate also asks LiteLLM to resolve the request
# and requires the answer to be the deployment's provider. Under 1.98.0 every precedence
# rule that overrides `custom_llm_provider` is keyed on a provider prefix, so nothing real
# reaches the outcome check that the spelling check has not already refused — it is the
# guard against the next such rule. These cases drive it with a resolver of their own,
# because what they are testing is the client's composition, not LiteLLM's answer.


def _resolver(provider: str) -> Any:
    def get_llm_provider(model: str, custom_llm_provider: str | None = None) -> tuple[Any, ...]:
        return (model, provider, None, None)

    return get_llm_provider


def test_a_model_litellm_would_serve_from_elsewhere_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(litellm, "get_llm_provider", _resolver("anthropic"), raising=False)
    client = LLMClient("test", {**OP_PROPS, "openai.model": "a-name-with-no-prefix"})
    with pytest.raises(LLMError, match="is served by 'anthropic'") as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "model_not_allowed"
    assert litellm.calls == []


def test_a_model_litellm_serves_from_the_pinned_provider_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(litellm, "get_llm_provider", _resolver("openai"), raising=False)
    client = LLMClient("test", {**OP_PROPS, "openai.model": "a-name-with-no-prefix"})
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1][DISPATCH_FIELD] == "openai"


def test_the_two_dispatch_checks_do_not_stand_in_for_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resolver that agrees with the pin does not license a route in the model string."""
    monkeypatch.setattr(litellm, "get_llm_provider", _resolver("openai"), raising=False)
    client = LLMClient("test", {**OP_PROPS, "openai.model": "vertex_ai/gemini-2.5-pro"})
    with pytest.raises(LLMError, match="names a provider"):
        client.execute_api_call({}, additional_data={})
    assert litellm.calls == []


def test_a_resolver_that_raises_leaves_the_spelling_check_standing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LiteLLM refusing to answer must not be a way through."""

    def explode(model: str, custom_llm_provider: str | None = None) -> tuple[Any, ...]:
        raise RuntimeError("no answer")

    monkeypatch.setattr(litellm, "get_llm_provider", explode, raising=False)
    client = LLMClient("test", {**OP_PROPS, "openai.model": "vertex_ai/gemini-2.5-pro"})
    with pytest.raises(LLMError, match="names a provider"):
        client.execute_api_call({}, additional_data={})
    assert litellm.calls == []


def test_a_litellm_that_names_nothing_makes_every_slash_a_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With neither question answerable there is nothing left to tell the two apart."""
    monkeypatch.setattr(litellm, "provider_list", [], raising=False)
    monkeypatch.setenv(PROVIDER_VAR, "fireworks_ai")
    client = LLMClient("test", {**OP_PROPS, "openai.model": "accounts/fireworks/models/llama-v3"})
    with pytest.raises(LLMError, match="names a provider"):
        client.execute_api_call({}, additional_data={})
    assert litellm.calls == []


# --- against the installed LiteLLM ----------------------------------------------------
# The offline tests use reviewed provider names selected below. The cases here use the
# installed release when the optional llm extra is present. They need a separate interpreter
# because the stub is on `sys.path` for the whole suite. The probe uses the local model-cost
# map, builds call kwargs and stops; it does not contact a provider.

REAL_LITELLM_PROBE = """
import json, os, sys, socket
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline test"))

sys.path[:] = json.loads(sys.argv[1])
try:
    import litellm
except ModuleNotFoundError as error:
    if error.name != "litellm":
        raise
    print(json.dumps({"litellm": None}))
    raise SystemExit(0)

from blue_data_ops.llm.client import LLMClient, _provider_names
from blue_data_ops.llm.errors import LLMError
from blue_data_ops.llm.templating import build_message

props = {
    "service_prefix": "openai",
    "openai.api": "ChatCompletion",
    "input_template": "Say $input",
    "input_json": '[{"role": "user"}]',
    "input_context": "$[0]",
    "input_context_field": "content",
    "input_field": "messages",
    "output_path": "$.choices[0].message.content",
}
cases = {
    "the reproduced bypass": ("anthropic", "azure/command-r-plus", "azure/command-r-plus"),
    "azure prefix on an azure deployment": (
        "azure", "azure/command-r-plus", "azure/command-r-plus",
    ),
    "vertex prefix, offered": ("openai", "vertex_ai/gemini-2.5-pro", "vertex_ai/gemini-2.5-pro"),
    "fireworks identifier": ("fireworks_ai", "", "accounts/fireworks/models/llama-v3"),
    "together identifier": ("together_ai", "", "meta-llama/Llama-3-70b"),
    "bare model": ("openai", "", "gpt-4o"),
    "bare name that routes elsewhere": ("openai", "", "claude-sonnet-4-5"),
    "a model the deployment does not offer": ("openai", "gpt-4o-mini", "gpt-4o"),
}
out = {}
for label, (provider, offered, model) in cases.items():
    os.environ["BLUE_DATA_LLM_PROVIDER"] = provider
    os.environ["BLUE_DATA_LLM_ALLOWED_MODELS"] = offered
    call_props = {**props, "openai.model": model}
    try:
        kwargs = LLMClient("probe", call_props)._build_call_kwargs(
            build_message({}, call_props, {}, "probe"), call_props
        )
        out[label] = {"refused": None, "dispatch": kwargs.get("custom_llm_provider")}
    except LLMError as error:
        out[label] = {"refused": error.code, "dispatch": None}
print(json.dumps({
    "litellm": litellm.__file__,
    "stubbed": hasattr(litellm, "calls"),
    "provider_names": sorted(_provider_names() or ()),
    "cases": out,
}))
"""


@pytest.fixture(scope="module")
def _installed_litellm_probe(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any] | None:
    import json
    import os
    import subprocess
    import sys

    directory = tmp_path_factory.mktemp("installed-provider")
    paths = real_litellm_paths()
    probe_env = {
        "HOME": str(directory),
        "BLUE_DATA_OPS_HOME": str(directory / "profiles"),
        "XDG_CACHE_HOME": str(directory / "cache"),
        "LITELLM_LOCAL_MODEL_COST_MAP": "True",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    if sys.platform == "win32":
        for name in ("SystemRoot", "WINDIR"):
            if name in os.environ:
                probe_env[name] = os.environ[name]
    completed = subprocess.run(
        [
            sys.executable,
            *(["-S"] if sys.flags.no_site else []),
            "-B",
            "-c",
            REAL_LITELLM_PROBE,
            json.dumps(paths),
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        env=probe_env,
        timeout=300,
        check=True,
    )
    observed: dict[str, Any] = json.loads(completed.stdout)
    if observed["litellm"] is None:
        return None
    assert not observed["stubbed"], "the probe imported the stub, so it measured nothing"
    return observed


_STUB_NAMES_198 = tuple(litellm.provider_list)
_STUB_ADDITIONS_1102 = tuple(litellm.provider_additions_1102)
_STUB_ADDITIONS_11065 = tuple(litellm.provider_additions_11065)
_STUB_ADDITIONS_11080 = tuple(litellm.provider_additions_11080)
_REVIEWED_PROVIDER_NAMES = tuple(
    sorted(
        {
            *_STUB_NAMES_198,
            *_STUB_ADDITIONS_1102,
            *_STUB_ADDITIONS_11065,
            *_STUB_ADDITIONS_11080,
        }
    )
)


def _select_provider_names(provider_names: list[str] | None) -> tuple[str, ...]:
    baseline = set(_STUB_NAMES_198)
    additions = set(_STUB_ADDITIONS_1102)
    latest = set(_STUB_ADDITIONS_11065)
    current = set(_STUB_ADDITIONS_11080)
    assert len(current) == len(_STUB_ADDITIONS_11080), "duplicate 1.108.0 additions"
    assert not (current & (baseline | additions | latest)), (
        "1.108.0 additions overlap older snapshots"
    )
    assert len(latest) == len(_STUB_ADDITIONS_11065), "duplicate 1.106.5 additions"
    assert not (latest & (baseline | additions)), "1.106.5 additions overlap older snapshots"
    assert len(baseline) == len(_STUB_NAMES_198), "duplicate names in 1.98.0 snapshot"
    assert len(additions) == len(_STUB_ADDITIONS_1102), "duplicate 1.102.0 additions"
    assert not (baseline & additions), "1.102.0 additions overlap 1.98.0 snapshot"
    if provider_names is None:
        return tuple(sorted(baseline))
    assert provider_names, "installed LiteLLM reported no provider names"
    observed = set(provider_names)
    assert len(observed) == len(provider_names), "duplicate installed provider names"
    unlisted = sorted(observed - (baseline | additions | latest | current))
    assert not unlisted, f"unreviewed installed provider names {unlisted}"
    return tuple(sorted(observed))


def test_installed_provider_names_are_reviewed(real_litellm: dict[str, Any]) -> None:
    _select_provider_names(real_litellm["provider_names"])


@pytest.fixture(scope="module")
def real_litellm(_installed_litellm_probe: dict[str, Any] | None) -> dict[str, Any]:
    if _installed_litellm_probe is None:
        pytest.skip("litellm is not installed; the llm extra is optional")
    return _installed_litellm_probe


def test_provider_coverage_rejects_a_new_installed_provider() -> None:
    with pytest.raises(
        AssertionError,
        match="unreviewed installed provider names.*provider_not_in_stub",
    ):
        _select_provider_names([*_STUB_NAMES_198, *_STUB_ADDITIONS_1102, "provider_not_in_stub"])


def test_provider_coverage_accepts_a_reviewed_subset() -> None:
    names = [name for name in _STUB_NAMES_198 if name != "a2a"]
    assert _select_provider_names(names) == tuple(sorted(names))


def test_provider_coverage_accepts_partial_new_additions() -> None:
    names = [*_STUB_NAMES_198, _STUB_ADDITIONS_1102[0], _STUB_ADDITIONS_11065[0]]
    assert _select_provider_names(names) == tuple(sorted(names))


def test_provider_coverage_rejects_duplicate_names() -> None:
    with pytest.raises(AssertionError, match="duplicate installed provider names"):
        _select_provider_names([*_STUB_NAMES_198, _STUB_NAMES_198[0]])


def test_provider_coverage_rejects_an_empty_list() -> None:
    with pytest.raises(AssertionError, match="no provider names"):
        _select_provider_names([])


def test_provider_coverage_uses_198_when_litellm_is_absent() -> None:
    assert _select_provider_names(None) == tuple(sorted(_STUB_NAMES_198))


@pytest.mark.parametrize("provider", (*_STUB_ADDITIONS_1102, *_STUB_ADDITIONS_11065))
def test_new_provider_names_follow_the_selected_snapshot(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv(PROVIDER_VAR, provider)
    client = LLMClient("test", OP_PROPS)
    for names in (_STUB_NAMES_198, _REVIEWED_PROVIDER_NAMES):
        monkeypatch.setattr(litellm, "provider_list", list(names))
        litellm.calls.clear()
        if provider in names:
            client.execute_api_call({}, additional_data={})
            assert litellm.calls[-1][DISPATCH_FIELD] == provider
        else:
            with pytest.raises(LLMError, match=PROVIDER_VAR) as raised:
                client.execute_api_call({}, additional_data={})
            assert raised.value.code == "bad_provider"
            assert litellm.calls == []


@pytest.mark.parametrize(
    "label",
    [
        "the reproduced bypass",
        "azure prefix on an azure deployment",
        "vertex prefix, offered",
        "a model the deployment does not offer",
    ],
)
def test_the_installed_litellm_refuses_the_same_models(
    real_litellm: dict[str, Any], label: str
) -> None:
    assert real_litellm["cases"][label]["refused"] == "model_not_allowed"


@pytest.mark.parametrize(
    "label, dispatch",
    [
        ("fireworks identifier", "fireworks_ai"),
        ("together identifier", "together_ai"),
        ("bare model", "openai"),
        ("bare name that routes elsewhere", "openai"),
    ],
)
def test_the_installed_litellm_passes_the_same_models(
    real_litellm: dict[str, Any], label: str, dispatch: str
) -> None:
    observed = real_litellm["cases"][label]
    assert observed["refused"] is None
    assert observed["dispatch"] == dispatch


# --- the name the lock rests on -------------------------------------------------------
def test_a_provider_litellm_does_not_serve_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every call is pinned to this name, so a typo in it is a typo in the lock."""
    monkeypatch.setenv(PROVIDER_VAR, "openai-but-misspelled")
    client = LLMClient("test", OP_PROPS)
    with pytest.raises(LLMError, match=PROVIDER_VAR) as raised:
        client.execute_api_call({}, additional_data={})
    assert raised.value.code == "bad_provider"
    assert litellm.calls == []


@pytest.mark.parametrize(
    "provider", ["openai", "anthropic", "azure", "vertex_ai", "bedrock", "fireworks_ai"]
)
def test_a_provider_litellm_serves_is_accepted(
    monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv(PROVIDER_VAR, provider)
    client = LLMClient("test", OP_PROPS)
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1][DISPATCH_FIELD] == provider


def test_a_litellm_that_names_nothing_leaves_the_provider_unchecked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is nothing to check a name against, and this check is for the message."""
    monkeypatch.setattr(litellm, "provider_list", [], raising=False)
    monkeypatch.setenv(PROVIDER_VAR, "openai-but-misspelled")
    client = LLMClient("test", OP_PROPS)
    client.execute_api_call({}, additional_data={})
    assert litellm.calls[-1][DISPATCH_FIELD] == "openai-but-misspelled"
