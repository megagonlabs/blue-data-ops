"""Offline control-flow tests for request-local cost observations."""

from __future__ import annotations

import math
from decimal import Decimal
from fractions import Fraction
from typing import Any

import litellm
import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.client import (
    _InvocationCostObservation,  # pyright: ignore[reportPrivateUsage]
)

PROPERTIES: dict[str, Any] = {
    "service_prefix": "openai",
    "openai.model": "gpt-4o",
    "input_template": "Say $input",
    "input_json": '[{"role": "user"}]',
    "input_context": "$[0]",
    "input_context_field": "content",
    "input_field": "messages",
    "output_path": "$.choices[0].message.content",
}


class _Response:
    def __init__(self, content: str = "ok") -> None:
        self.content = content

    def model_dump(self) -> dict[str, Any]:
        return {
            "choices": [{"message": {"role": "assistant", "content": self.content}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }


@pytest.fixture(autouse=True)
def _reset_fake() -> None:  # pyright: ignore[reportUnusedFunction]
    litellm.calls.clear()
    litellm.fail_next.clear()


def _observed_call(client: LLMClient) -> tuple[Any, _InvocationCostObservation]:
    observation = _InvocationCostObservation()
    output = client._execute_api_call_observed(  # pyright: ignore[reportPrivateUsage]
        {}, PROPERTIES, {}, observation
    )
    return output, observation


@pytest.mark.parametrize("amount", [0, 0.0, 0.125])
def test_numeric_price_is_kept_as_an_estimate(
    amount: int | float, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def price(**kwargs: Any) -> int | float:
        nonlocal calls
        del kwargs
        calls += 1
        return amount

    monkeypatch.setattr(litellm, "completion_cost", price)
    client = LLMClient("test", PROPERTIES)
    output, observation = _observed_call(client)

    assert output.startswith("echo:")
    assert calls == 1
    assert observation.provider_attempts == 1
    assert observation.complete_cost() == float(amount)
    assert client.last_usage is not None
    assert client.last_usage.cost == float(amount)


@pytest.mark.parametrize(
    "amount",
    [True, False, -0.1, float("nan"), float("inf"), "0.25"],
    ids=["true", "false", "negative", "nan", "infinity", "numeric-string"],
)
def test_non_reportable_price_keeps_legacy_accounting_only(
    amount: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def price(**kwargs: Any) -> Any:
        del kwargs
        return amount

    monkeypatch.setattr(litellm, "completion_cost", price)
    client = LLMClient("test", PROPERTIES)
    _, observation = _observed_call(client)

    assert observation.complete_cost() is None
    assert client.last_usage is not None
    expected_legacy = float(amount)
    if math.isnan(expected_legacy):
        assert math.isnan(client.last_usage.cost)
    else:
        assert client.last_usage.cost == expected_legacy


def test_pricing_exception_is_unknown_but_legacy_cost_stays_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(**kwargs: Any) -> float:
        del kwargs
        raise RuntimeError("no price")

    monkeypatch.setattr(litellm, "completion_cost", unavailable)
    client = LLMClient("test", PROPERTIES)
    output, observation = _observed_call(client)

    assert output.startswith("echo:")
    assert observation.complete_cost() is None
    assert client.last_usage is not None and client.last_usage.cost == 0.0


def test_numeric_conversion_failure_is_unknown_and_does_not_fail_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(**kwargs: Any) -> Decimal:
        del kwargs
        return Decimal("sNaN")

    monkeypatch.setattr(litellm, "completion_cost", unavailable)
    client = LLMClient("test", PROPERTIES)
    output, observation = _observed_call(client)

    assert output.startswith("echo:")
    assert observation.provider_attempts == 1
    assert observation.complete_cost() is None
    assert client.last_usage is not None and client.last_usage.cost == 0.0


@pytest.mark.parametrize(
    "amount",
    [Decimal("-1e-9999"), Fraction(-1, 10**1000)],
    ids=["decimal", "fraction"],
)
def test_negative_numeric_underflow_stays_unknown_before_float_conversion(
    amount: Decimal | Fraction, monkeypatch: pytest.MonkeyPatch
) -> None:
    pricing_calls = 0

    def price(**kwargs: Any) -> Decimal | Fraction:
        nonlocal pricing_calls
        del kwargs
        pricing_calls += 1
        return amount

    monkeypatch.setattr(litellm, "completion_cost", price)
    client = LLMClient("test", PROPERTIES)
    output, observation = _observed_call(client)

    assert output.startswith("echo:") and pricing_calls == 1
    assert observation.provider_attempts == 1
    assert observation.complete_cost() is None
    assert client.last_usage is not None
    assert client.last_usage.cost == 0.0
    assert math.copysign(1.0, client.last_usage.cost) == -1.0


@pytest.mark.parametrize("first_failure", ["transport", "materialization"])
def test_retry_marks_the_observation_incomplete(
    first_failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def completion(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        litellm.calls.append(kwargs)
        if calls == 1:
            if first_failure == "transport":
                raise RuntimeError("retry transport")
            return {}
        return _Response()

    monkeypatch.setattr(litellm, "completion", completion)

    def price(**kwargs: Any) -> float:
        del kwargs
        return 0.4

    monkeypatch.setattr(litellm, "completion_cost", price)
    client = LLMClient("test", PROPERTIES)
    output, observation = _observed_call(client)

    assert output == "ok"
    assert calls == 2 and observation.provider_attempts == 2
    assert observation.complete_cost() is None
    assert client.last_usage is not None and client.last_usage.cost == 0.4


def test_public_sync_path_preserves_old_arity_overrides() -> None:
    class OldArityClient(LLMClient):
        provider_called = False
        materialize_called = False

        def _call_provider(self, kwargs: dict[str, Any]) -> tuple[dict[str, Any], float]:
            self.provider_called = True
            return super()._call_provider(kwargs)

        def _materialize(self, response: Any) -> tuple[dict[str, Any], float]:
            self.materialize_called = True
            return super()._materialize(response)

    client = OldArityClient("test", PROPERTIES)
    output = client.execute_api_call({}, additional_data={})

    assert output.startswith("echo:")
    assert client.provider_called and client.materialize_called
    assert len(client.ledger.records) == 1
    assert client.last_usage is client.ledger.records[0]


def test_async_path_does_not_use_sync_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    client = LLMClient("test", PROPERTIES)

    def fail(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise AssertionError("sync observation path used")

    monkeypatch.setattr(client, "_call_provider_observed", fail)
    output = asyncio.run(client.aexecute_api_call({}, additional_data={}))
    assert output.startswith("echo:")
