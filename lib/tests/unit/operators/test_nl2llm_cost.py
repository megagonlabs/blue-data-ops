"""Offline cost-selection tests for ``nl2llm@3.0.0``.

Fixed responses and prices test control flow. They do not verify live usage, provider billing,
prompt-cache accounting, or LiteLLM's price table.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from threading import Barrier, Event
from typing import Any, cast

import litellm
import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import ErrorCode, ErrorStage
from blue_data_ops.operators import _nl2llm_outcome as outcome_module
from blue_data_ops.operators import _outcomes as outcomes_module
from blue_data_ops.operators.nl2llm_operator import NL2LLMOperator
from blue_data_ops.operators.registry import versioned_registry
from blue_data_ops.operators.types import DataBundle, ExecMeta

INPUT: DataBundle = [[]]
SUCCESS_CASES: list[tuple[str, DataBundle, bool, float]] = [
    ('[{"answer": "ok"}]', [[{"answer": "ok"}]], False, 0.125),
    ("[]", [[]], True, 0.0),
]


class _Response:
    def __init__(self, content: str, price: Any = 0.25, *, cached_tokens: int = 0) -> None:
        self.content = content
        self.price = price
        self.cached_tokens = cached_tokens

    def model_dump(self) -> dict[str, Any]:
        usage: dict[str, Any] = {"prompt_tokens": 3, "completion_tokens": 2}
        if self.cached_tokens:
            usage["prompt_tokens_details"] = {"cached_tokens": self.cached_tokens}
        return {
            "choices": [{"message": {"role": "assistant", "content": self.content}}],
            "usage": usage,
        }


@pytest.fixture(autouse=True)
def _reset_fake() -> None:  # pyright: ignore[reportUnusedFunction]
    litellm.calls.clear()
    litellm.fail_next.clear()


@pytest.fixture
def operator() -> Any:
    return versioned_registry().resolve("nl2llm@3.0.0")


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    price: Any = 0.25,
    *,
    cached_tokens: int = 0,
) -> None:
    def completion(**kwargs: Any) -> _Response:
        litellm.calls.append(kwargs)
        return _Response(content, price, cached_tokens=cached_tokens)

    def completion_cost(*, completion_response: _Response) -> Any:
        return completion_response.price

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(litellm, "completion_cost", completion_cost)


def _assert_no_cost(meta: ExecMeta) -> None:
    assert "cost" not in meta.traces
    assert "cost_basis" not in meta.traces


@pytest.mark.parametrize(
    "content,expected,is_empty,price",
    SUCCESS_CASES,
    ids=["records", "successful-empty-observed-zero"],
)
def test_success_attaches_one_fixed_price(
    operator: Any,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    expected: DataBundle,
    is_empty: bool,
    price: float,
) -> None:
    _install_provider(monkeypatch, content, price)
    data, attributes, meta = operator.run(INPUT, {"query": "list records"})

    assert data == expected and attributes == {}
    assert meta.errors == [] and meta.is_empty is is_empty
    assert meta.traces["cost"] == price
    assert meta.traces["cost_basis"] == "estimated"
    assert len(litellm.calls) == 1


def test_blank_query_never_requests_or_reports_cost(operator: Any) -> None:
    _, _, meta = operator.run(INPUT, {"query": "  "})
    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert litellm.calls == []
    _assert_no_cost(meta)


def test_provider_failure_never_reports_partial_cost(operator: Any) -> None:
    litellm.fail_next.extend([RuntimeError("down")] * 3)
    _, _, meta = operator.run(INPUT, {"query": "list records"})

    assert meta.errors[0].code is ErrorCode.EXECUTION_FAILED
    assert len(litellm.calls) == 3
    _assert_no_cost(meta)


@pytest.mark.parametrize(
    "content,expected_stage",
    [("not json", ErrorStage.EXECUTE), ('{"answer": "ok"}', ErrorStage.NORMALIZE)],
    ids=["output-cast", "normalized-shape"],
)
def test_failed_output_does_not_report_cost(
    operator: Any,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    expected_stage: ErrorStage,
) -> None:
    _install_provider(monkeypatch, content)
    _, _, meta = operator.run(INPUT, {"query": "list records"})

    assert meta.errors[0].stage is expected_stage
    assert len(litellm.calls) == 1
    _assert_no_cost(meta)


def test_retry_success_is_incomplete(operator: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def completion(**kwargs: Any) -> _Response:
        nonlocal attempts
        attempts += 1
        litellm.calls.append(kwargs)
        if attempts == 1:
            raise RuntimeError("first attempt")
        return _Response("[]", 0.25)

    def completion_cost(*, completion_response: _Response) -> float:
        return completion_response.price

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(litellm, "completion_cost", completion_cost)
    data, _, meta = operator.run(INPUT, {"query": "list records"})

    assert data and meta.errors == []
    assert len(litellm.calls) == 2
    _assert_no_cost(meta)


def test_concurrent_runs_keep_request_local_prices(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = Barrier(2)

    def completion(**kwargs: Any) -> _Response:
        litellm.calls.append(kwargs)
        content = kwargs["messages"][0]["content"]
        price = 0.1 if "Query: cheap" in content else 0.9
        barrier.wait(timeout=5)
        return _Response(f'[{{"price": {price}}}]', price)

    def completion_cost(*, completion_response: _Response) -> float:
        return completion_response.price

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(litellm, "completion_cost", completion_cost)

    with ThreadPoolExecutor(max_workers=2) as executor:
        cheap = executor.submit(operator.run, INPUT, {"query": "cheap"})
        expensive = executor.submit(operator.run, INPUT, {"query": "expensive"})
        results = [cheap.result(timeout=10), expensive.result(timeout=10)]

    observed = {(result[0][0][0]["price"], result[2].traces["cost"]) for result in results}
    assert observed == {(0.1, 0.1), (0.9, 0.9)}
    assert len(litellm.calls) == 2


def test_real_local_cache_hit_reports_no_request_zero(
    operator: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    pricing_calls = 0

    def completion(**kwargs: Any) -> _Response:
        litellm.calls.append(kwargs)
        return _Response('[{"cached": true}]', 0.4)

    def price(*, completion_response: _Response) -> float:
        nonlocal pricing_calls
        pricing_calls += 1
        return completion_response.price

    monkeypatch.setattr(litellm, "completion", completion)
    monkeypatch.setattr(litellm, "completion_cost", price)
    properties = {"llm.cache": True, "llm.cache_dir": str(tmp_path / "cache")}

    first = operator.run(INPUT, {"query": "cache me"}, properties)
    second = operator.run(INPUT, {"query": "cache me"}, properties)

    assert first[2].traces["cost"] == 0.4
    assert second[2].traces["cost"] == 0.0
    assert second[2].traces["cost_basis"] == "estimated"
    assert len(litellm.calls) == 1 and pricing_calls == 1


def test_provider_prompt_cache_is_still_a_provider_attempt(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, "[]", 0.3, cached_tokens=3)
    _, _, meta = operator.run(INPUT, {"query": "cached by provider"})

    assert len(litellm.calls) == 1
    assert meta.traces["cost"] == 0.3
    assert meta.traces["cost_basis"] == "estimated"


@pytest.mark.parametrize(
    "amount",
    [Decimal("-1e-9999"), Fraction(-1, 10**1000)],
    ids=["decimal", "fraction"],
)
def test_negative_numeric_underflow_does_not_publish_cost(
    operator: Any,
    monkeypatch: pytest.MonkeyPatch,
    amount: Decimal | Fraction,
) -> None:
    _install_provider(monkeypatch, "[]", amount)
    data, _, meta = operator.run(INPUT, {"query": "list records"})

    assert data == [[]] and meta.errors == []
    assert len(litellm.calls) == 1
    _assert_no_cost(meta)


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_cost_publication_isolated_to_exact_v3(
    monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    _install_provider(monkeypatch, "[]")
    operator = versioned_registry().resolve(f"nl2llm@{version}")
    data, attributes, meta = operator.run(INPUT, {"query": "list records"})

    assert data == [[]] and attributes == {} and meta.errors == []
    assert meta.traces == {}
    assert len(litellm.calls) == 1


def test_detached_publication_ignores_source_mapping_assignment_fault(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, "[]")
    original = outcomes_module._OutcomeOperator.run  # pyright: ignore[reportPrivateUsage]

    class RejectBasis(dict[str, Any]):
        def __setitem__(self, key: str, value: Any) -> None:
            if key == "cost_basis":
                raise RuntimeError("old in-place assignment fault")
            super().__setitem__(key, value)

    def with_trace_subclass(*args: Any, **kwargs: Any) -> tuple[DataBundle, Any, ExecMeta]:
        data, attributes, meta = original(*args, **kwargs)
        traces = RejectBasis(
            {**meta.traces, "input_shape": {"groups": 1}, "output_shape": {"groups": 1}}
        )
        return data, attributes, meta._replace(traces=traces)

    monkeypatch.setattr(
        outcomes_module._OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
        "run",
        with_trace_subclass,
    )
    data, attributes, meta = operator.run(INPUT, {"query": "list records"})

    assert data == [[]] and attributes == {} and meta.errors == []
    assert len(litellm.calls) == 1
    assert meta.traces.__class__ is dict
    assert meta.traces["cost"] == 0.25 and meta.traces["cost_basis"] == "estimated"
    assert meta.traces["input_shape"] == {"groups": 1}
    assert meta.traces["output_shape"] == {"groups": 1}
    assert "elapsed_ms" in meta.traces


def test_detached_mapping_failure_returns_the_canonical_result(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, "[]")
    original = outcomes_module._OutcomeOperator.run  # pyright: ignore[reportPrivateUsage]
    canonical: list[tuple[DataBundle, Any, ExecMeta]] = []

    class RejectCopy(dict[str, Any]):
        def keys(self) -> Any:
            raise RuntimeError("detached mapping unavailable")

        def __iter__(self) -> Iterator[str]:
            raise RuntimeError("detached mapping unavailable")

    def with_copy_fault(*args: Any, **kwargs: Any) -> tuple[DataBundle, Any, ExecMeta]:
        data, attributes, meta = original(*args, **kwargs)
        traces = RejectCopy(
            {**meta.traces, "input_shape": {"groups": 1}, "output_shape": {"groups": 1}}
        )
        result = data, attributes, meta._replace(traces=traces)
        canonical.append(result)
        return result

    monkeypatch.setattr(
        outcomes_module._OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
        "run",
        with_copy_fault,
    )
    result = operator.run(INPUT, {"query": "list records"})

    assert result is canonical[0]
    assert result[0] is canonical[0][0] and result[1] is canonical[0][1]
    assert result[2] is canonical[0][2]
    assert len(litellm.calls) == 1
    assert result[2].traces["input_shape"] == {"groups": 1}
    assert result[2].traces["output_shape"] == {"groups": 1}
    assert "elapsed_ms" in result[2].traces
    _assert_no_cost(result[2])


def test_detached_result_failure_returns_the_canonical_result(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, "[]")
    original_run = outcomes_module._OutcomeOperator.run  # pyright: ignore[reportPrivateUsage]
    original_replace = ExecMeta._replace
    canonical: list[tuple[DataBundle, Any, ExecMeta]] = []

    def with_shapes(*args: Any, **kwargs: Any) -> tuple[DataBundle, Any, ExecMeta]:
        data, attributes, meta = original_run(*args, **kwargs)
        traces = {**meta.traces, "input_shape": {"groups": 1}, "output_shape": {"groups": 1}}
        result = data, attributes, original_replace(meta, traces=traces)
        canonical.append(result)
        return result

    def reject_result(self: ExecMeta, **kwargs: Any) -> ExecMeta:
        del self, kwargs
        raise RuntimeError("detached result unavailable")

    monkeypatch.setattr(
        outcomes_module._OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
        "run",
        with_shapes,
    )
    monkeypatch.setattr(ExecMeta, "_replace", reject_result)
    result = operator.run(INPUT, {"query": "list records"})

    assert result[0] is canonical[0][0] and result[1] is canonical[0][1]
    assert result[2] is canonical[0][2]
    assert len(litellm.calls) == 1
    assert result[2].traces["input_shape"] == {"groups": 1}
    assert result[2].traces["output_shape"] == {"groups": 1}
    assert "elapsed_ms" in result[2].traces
    _assert_no_cost(result[2])


def test_timeout_trace_cannot_gain_late_cost(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release, completed = Event(), Event(), Event()
    original_run_once = operator._run_once
    prices: list[float] = []

    def delayed(**kwargs: Any) -> _Response:
        litellm.calls.append(kwargs)
        entered.set()
        assert release.wait(5), "test did not release the provider"
        return _Response("[]", 0.7)

    def completion_cost(*, completion_response: _Response) -> float:
        prices.append(completion_response.price)
        return completion_response.price

    def completed_run(*args: Any, **kwargs: Any) -> Any:
        try:
            return original_run_once(*args, **kwargs)
        finally:
            completed.set()

    monkeypatch.setattr(litellm, "completion", delayed)
    monkeypatch.setattr(litellm, "completion_cost", completion_cost)
    monkeypatch.setattr(operator, "_run_once", completed_run)

    timed_out = operator.run(
        INPUT,
        {"query": "slow"},
        {"execution.timeout_seconds": 0.01},
    )
    assert entered.wait(1)
    assert timed_out[2].errors[0].code is ErrorCode.OPERATOR_TIMEOUT
    before = dict(timed_out[2].traces)
    _assert_no_cost(timed_out[2])

    release.set()
    assert completed.wait(2)
    assert prices == [0.7]
    assert timed_out[2].traces == before
    _assert_no_cost(timed_out[2])

    _install_provider(monkeypatch, "[]", 0.2)
    later = operator.run(INPUT, {"query": "fast"})
    assert later[2].traces["cost"] == 0.2


def test_injected_subclass_stays_on_the_public_path(operator: Any) -> None:
    class InjectedClient(LLMClient):
        def __init__(self) -> None:
            self.calls = 0

        def execute_api_call(
            self,
            input: Any,  # noqa: A002
            properties: dict[str, Any] | None = None,
            additional_data: dict[str, Any] | None = None,
        ) -> Any:
            del input, properties, additional_data
            self.calls += 1
            return [{"source": "injected"}]

    client = InjectedClient()
    data, _, meta = operator.run(INPUT, {"query": "list records"}, {"llm_client": client})

    assert data == [[{"source": "injected"}]] and client.calls == 1
    assert meta.errors == []
    _assert_no_cost(meta)


def test_invalid_injected_value_keeps_its_template_namespace(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, "[]")
    properties = {"llm_client": "caller marker", "input_template": "$llm_client"}
    before = deepcopy(properties)

    _, _, meta = operator.run(INPUT, {"query": "list records"}, properties)

    assert properties == before
    assert litellm.calls[0]["messages"][0]["content"] == "caller marker"
    _assert_no_cost(meta)


@pytest.mark.parametrize("template", [None, "$llm_client"])
def test_instrumentation_preserves_rendered_provider_message(
    operator: Any, monkeypatch: pytest.MonkeyPatch, template: str | None
) -> None:
    _install_provider(monkeypatch, "[]")
    properties = {} if template is None else {"input_template": template}
    before = deepcopy(properties)

    raw = NL2LLMOperator()
    raw.apply(INPUT, {"query": "same prompt"}, properties)
    operator.run(INPUT, {"query": "same prompt"}, properties)

    assert properties == before
    assert litellm.calls[0] == litellm.calls[1]
    if template is not None:
        assert litellm.calls[1]["messages"][0]["content"] == "$llm_client"


def test_setup_failure_falls_back_without_repeating_provider(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, "[]")

    def fail_setup(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise RuntimeError("instrumentation unavailable")

    monkeypatch.setattr(outcome_module, "_ObservedLLMClient", fail_setup)
    _, _, meta = operator.run(INPUT, {"query": "list records"})

    assert meta.errors == [] and len(litellm.calls) == 1
    _assert_no_cost(meta)


def test_elapsed_includes_lazy_delegate_initialization(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, "[]")
    now = [10.0]
    original_init = LLMClient.__init__

    def timed_init(self: LLMClient, name: str, properties: dict[str, Any] | None = None) -> None:
        now[0] += 0.2
        original_init(self, name, properties)

    monkeypatch.setattr(LLMClient, "__init__", timed_init)
    monkeypatch.setattr(outcomes_module, "monotonic", lambda: now[0])

    _, _, meta = operator.run(INPUT, {"query": "list records"})

    assert meta.errors == [] and len(litellm.calls) == 1
    assert meta.traces["elapsed_ms"] == pytest.approx(200.0)
    assert meta.traces["cost"] == 0.25


def test_falsey_non_mapping_properties_keep_canonical_success(
    operator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_provider(monkeypatch, "[]")
    data, _, meta = operator.run(INPUT, {"query": "list records"}, cast(Any, []))

    assert data == [[]] and meta.errors == []
    assert len(litellm.calls) == 1
    _assert_no_cost(meta)


def test_malformed_properties_keep_canonical_containment(operator: Any) -> None:
    _, _, meta = operator.run(INPUT, {"query": "list records"}, cast(Any, 1))

    assert meta.errors[0].code is ErrorCode.INVALID_INPUT
    assert litellm.calls == []
    _assert_no_cost(meta)
