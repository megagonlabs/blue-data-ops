"""Offline regression coverage for inherited-temperature refusals."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

import litellm
import pytest

from blue_data_ops.llm import (
    CachingLLMClientProvider,
    LLMClient,
    LLMError,
    prepare_llm_operator_properties,
)
from blue_data_ops.llm.client import (
    _InvocationCostObservation,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators import active_registry
from tests.unit.llm.test_client import OP_PROPS


def price(**kwargs: Any) -> float:
    return 0.125


def reject_sync(**kwargs: Any) -> Any:
    raise rejection()


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    litellm.calls.clear()
    litellm.fail_next.clear()
    monkeypatch.delenv("BLUE_DATA_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("BLUE_DATA_LLM_ALLOWED_MODELS", raising=False)


def prepared(supplied: dict[str, Any] | None = None) -> dict[str, Any]:
    caller = {"llm.model": "gpt-6.1-sol", "llm.reasoning_effort": "low", **(supplied or {})}
    return prepare_llm_operator_properties({**OP_PROPS, **caller}, OP_PROPS, caller)


def rejection(kind: str = "local") -> Exception:
    if kind == "local":
        return litellm.UnsupportedParamsError(
            "gpt-6.1-sol doesn't support temperature=0 while reasoning is active"
        )
    e = litellm.BadRequestError(
        "private provider detail",
        body={"error": {"code": "unsupported_value", "param": "temperature"}},
    )
    setattr(e, "status_code", 400)
    return e


def install(monkeypatch: pytest.MonkeyPatch, errors: list[Exception]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        if errors:
            raise errors.pop(0)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    async def acompletion(**kwargs: Any) -> dict[str, Any]:
        return completion(**kwargs)

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(litellm, "acompletion", acompletion)
    monkeypatch.setattr(litellm, "completion_cost", price)
    return calls


def invoke(
    client: LLMClient, props: dict[str, Any], mode: str
) -> _InvocationCostObservation | None:
    if mode == "async":
        assert asyncio.run(client.aexecute_api_call({}, props)) == "ok"
    elif mode == "observed":
        observation = _InvocationCostObservation()
        assert cast(Any, client)._execute_api_call_observed({}, props, {}, observation) == "ok"
        return observation
    else:
        assert client.execute_api_call({}, props) == "ok"
    return None


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
@pytest.mark.parametrize("kind", ["local", "structured"])
@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6.1-terra", "o3"])
def test_fallback_preserves_other_fields_and_usage(
    monkeypatch: pytest.MonkeyPatch, mode: str, kind: str, model: str
) -> None:
    props = prepared({"llm.model": model, "openai.top_p": 0.8})
    original = dict(props)
    calls = install(monkeypatch, [rejection(kind)])
    client = LLMClient("test", props)
    observation = invoke(client, props, mode)
    assert len(calls) == 2
    assert calls[0].pop("temperature") == 0
    assert calls[0] == calls[1]
    assert calls[1]["top_p"] == 0.8
    assert calls[1]["custom_llm_provider"] == "openai"
    assert dict(props) == original and OP_PROPS["openai.temperature"] == 0
    assert len(client.ledger.records) == 1
    assert client.last_usage is not None
    assert client.last_usage.cost == 0.125 and client.last_usage.prompt_tokens == 2
    if observation:
        assert observation.provider_attempts == 2
        assert observation.local_refusals == (kind == "local")
        assert observation.complete_cost() == (0.125 if kind == "local" else None)


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
@pytest.mark.parametrize("key", ["llm.temperature", "openai.temperature"])
def test_explicit_zero_is_strict(monkeypatch: pytest.MonkeyPatch, mode: str, key: str) -> None:
    calls = install(monkeypatch, [rejection()])
    props = prepared({key: 0})
    with pytest.raises(LLMError, match="llm.temperature=null"):
        invoke(LLMClient("test", props), props, mode)
    assert len(calls) == 1


@pytest.mark.parametrize("key", ["llm.temperature", "openai.temperature"])
@pytest.mark.parametrize("value", [0, None])
def test_client_configuration_is_explicit(
    monkeypatch: pytest.MonkeyPatch, key: str, value: int | None
) -> None:
    calls = install(monkeypatch, [rejection()] if value == 0 else [])
    client = LLMClient("test", {key: value})
    props = prepared({"llm_client": client})
    if value == 0:
        with pytest.raises(LLMError):
            invoke(client, props, "sync")
    else:
        invoke(client, props, "sync")
        assert "temperature" not in calls[0]
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
@pytest.mark.parametrize("key", ["llm.temperature", "openai.temperature"])
def test_null_omits_without_fallback(monkeypatch: pytest.MonkeyPatch, mode: str, key: str) -> None:
    calls = install(monkeypatch, [])
    props = prepared({key: None})
    invoke(LLMClient("test", props), props, mode)
    assert len(calls) == 1 and "temperature" not in calls[0]


def test_ordinary_model_keeps_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, [])
    props = prepared({"llm.model": "gpt-4o", "llm.reasoning_effort": None})
    invoke(LLMClient("test", props), props, "sync")
    assert len(calls) == 1 and calls[0]["temperature"] == 0


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
@pytest.mark.parametrize(
    "error",
    [
        litellm.UnsupportedParamsError("temperature mentioned in unrelated documentation"),
        litellm.UnsupportedParamsError("does not support ['top_p']; temperature is optional"),
        litellm.BadRequestError("doesn't support temperature=0"),
        litellm.BadRequestError(
            "temperature", body={"code": "unsupported_value", "param": "top_p"}
        ),
        ValueError("temperature parse error"),
    ],
)
def test_unrelated_errors_never_remove_temperature(
    monkeypatch: pytest.MonkeyPatch, mode: str, error: Exception
) -> None:
    calls = install(monkeypatch, [error, error, error])
    props = prepared()
    with pytest.raises(LLMError):
        invoke(LLMClient("test", props), props, mode)
    assert calls and all(call["temperature"] == 0 for call in calls)
    assert len(calls) <= 3  # Existing transport policy is separate.


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
def test_fallback_is_bounded_and_failure_not_cached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    calls = install(monkeypatch, [rejection(), rejection()])
    props = prepared({"llm.cache": True, "llm.cache_dir": str(tmp_path)})
    client = LLMClient("test", props)
    with pytest.raises(LLMError):
        invoke(client, props, mode)
    assert len(calls) == 2 and "temperature" not in calls[1]
    assert not client.ledger.records
    assert len(cast(Any, client)._caches[str(tmp_path)]) == 0


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
@pytest.mark.parametrize("kind", ["local", "structured"])
def test_cache_effective_identity_and_explicit_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str, kind: str
) -> None:
    calls = install(monkeypatch, [rejection(kind)])
    props = prepared({"llm.cache": True, "llm.cache_dir": str(tmp_path)})
    client = LLMClient("test", props)
    invoke(client, props, mode)
    second = LLMClient("test", props)
    observation = invoke(second, props, mode)
    assert second.last_usage is not None
    assert len(calls) == 2 and second.last_usage.cache_hit
    assert second.last_usage.cost == 0 and second.last_usage.prompt_tokens == 0
    if observation:
        assert observation.provider_attempts == 0 and observation.complete_cost() == 0
    cache = cast(Any, second)._caches[str(tmp_path)]
    request_keys = [
        json.loads(key.removeprefix("blue-data-ops:llm:v1:response:"))
        for key in cache
        if key.startswith("blue-data-ops:llm:v1:response:")
    ]
    assert len(request_keys) == 1 and "temperature" not in request_keys[0]
    # Explicit null reuses the effective request; explicit zero must face refusal.
    null = prepared({"llm.temperature": None, "llm.cache": True, "llm.cache_dir": str(tmp_path)})
    invoke(second, null, mode)
    assert len(calls) == 2
    monkeypatch.setattr(litellm, "completion", reject_sync)

    async def reject(**kw: Any) -> None:
        raise rejection()

    monkeypatch.setattr(litellm, "acompletion", reject)
    explicit = prepared({"llm.temperature": 0, "llm.cache": True, "llm.cache_dir": str(tmp_path)})
    with pytest.raises(LLMError):
        invoke(second, explicit, mode)


@pytest.mark.parametrize(
    "flag", ["inherited_temperature", "_operator_default_temperature", "temperature_from_default"]
)
def test_json_cannot_spoof_provenance(monkeypatch: pytest.MonkeyPatch, flag: str) -> None:
    calls = install(monkeypatch, [rejection()])
    props = json.loads(json.dumps({**OP_PROPS, "llm.model": "gpt-6.1-sol", flag: True}))
    with pytest.raises(LLMError):
        invoke(LLMClient("direct", props), props, "sync")
    assert len(calls) == 1


def test_cached_client_provider_separates_provenance() -> None:
    provider = CachingLLMClientProvider()
    trusted = prepared()
    assert provider.get_client(trusted) is not provider.get_client(dict(trusted))


def test_direct_client_has_no_operator_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, [rejection()])
    props = dict(prepared())
    with pytest.raises(LLMError):
        invoke(LLMClient("direct", props), props, "sync")
    assert len(calls) == 1


def test_operator_observed_cost_preserves_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = install(monkeypatch, [rejection()])
    monkeypatch.setattr(litellm, "completion_cost", price)
    original: Any = litellm.completion

    def structured(**kw: Any) -> Any:
        result = original(**kw)
        result["choices"][0]["message"]["content"] = '[{"product":"example"}]'
        return result

    monkeypatch.setattr(litellm, "completion", structured)
    output, _, meta = (
        active_registry()
        .resolve("nl2llm@3.0.0")
        .run(
            [[]],
            {"query": "Return one example product."},
            {"llm.model": "gpt-6.1-sol", "llm.reasoning_effort": "low"},
        )
    )
    assert not meta.errors and output
    assert len(calls) == 2 and meta.traces["cost"] == 0.125


@pytest.mark.parametrize("mode", ["sync", "async", "observed"])
@pytest.mark.parametrize("kind", ["local", "structured"])
def test_non_openai_refusal_does_not_drop_temperature(
    monkeypatch: pytest.MonkeyPatch, mode: str, kind: str
) -> None:
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", "anthropic")
    calls = install(monkeypatch, [rejection(kind)])
    props = prepared({"llm.model": "claude-sonnet-4-5"})
    with pytest.raises(LLMError):
        invoke(LLMClient("test", props), props, mode)
    assert len(calls) == 1
    assert calls[0]["custom_llm_provider"] == "anthropic"
    assert calls[0]["temperature"] == 0
