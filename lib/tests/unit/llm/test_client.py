"""Offline transport, retry, usage-ledger, and cache tests for LLMClient."""

from __future__ import annotations

import os
from typing import Any

import litellm  # the tests/stubs deterministic fake (conftest inserts the stub path)
import pytest

from blue_data_ops.llm import LLMClient, LLMError

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


@pytest.fixture(autouse=True)
def _reset_fake(  # pyright: ignore[reportUnusedFunction] — autouse
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert call["model"] == "gpt-4o"  # the op default survives
    assert call["temperature"] == 0
    assert call["messages"] == [{"role": "user", "content": "Say {}"}]


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
) -> None:
    import builtins

    real_import = builtins.__import__

    def no_diskcache(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "diskcache":
            raise ImportError("gone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_diskcache)
    client = LLMClient("test", {**OP_PROPS, "llm.cache": True})
    with pytest.raises(LLMError, match="diskcache is not installed"):
        client.execute_api_call({}, additional_data={})


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
        ("anthropic", "azure/command-r-plus"),  # the reproduced bypass, exactly as reported
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


def test_an_offered_model_still_reaches_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
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
# Everything above runs against the offline stub, which answers the spelling question with
# LiteLLM's real provider names and deliberately will not answer the resolution one. The
# cases below put the gate in front of the installed release instead. They need a separate
# interpreter, because the stub is on `sys.path` for the whole suite, and they skip when
# the optional llm extra is not installed. `get_llm_provider` is a pure function over
# LiteLLM's model map: the probe builds call kwargs and stops, so no provider is contacted.

REAL_LITELLM_PROBE = """
import json, os, sys

sys.path.insert(0, sys.argv[1])
try:
    import litellm
except Exception:
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
def real_litellm() -> dict[str, Any]:
    import json
    import subprocess
    import sys
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[3] / "src")
    environment = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-c", REAL_LITELLM_PROBE, src],
        capture_output=True,
        text=True,
        env=environment,
        timeout=300,
        check=True,
    )
    observed: dict[str, Any] = json.loads(completed.stdout)
    if observed["litellm"] is None:
        pytest.skip("litellm is not installed; the llm extra is optional")
    assert not observed["stubbed"], "the probe imported the stub, so it measured nothing"
    return observed


def test_the_stubs_provider_names_are_litellms_own(real_litellm: dict[str, Any]) -> None:
    """The offline gate is only as good as the names the stub carries."""
    assert real_litellm["provider_names"] == sorted(litellm.provider_list)


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
def test_a_provider_litellm_does_not_serve_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
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
