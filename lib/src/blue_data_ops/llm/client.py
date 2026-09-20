from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from math import isfinite
from numbers import Real
from typing import Any, cast

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from blue_data_ops.llm.errors import LLMError
from blue_data_ops.llm.templating import build_message, extract_output

# The closed adapter-override key set; unknown llm.* keys are rejected (LLMError).
_ACCEPTED_LLM_KEYS = {
    "model",
    "stream",
    "max_tokens",
    "temperature",
    "cache",
    "cache_dir",
    "max_parallel",
    "rate_limit",
}
# Adapter-control keys: consumed by the client, never forwarded to the provider.
_CONTROL_KEYS = {"cache", "cache_dir", "max_parallel", "rate_limit"}
# Strip dispatch-only and transport-resolution fields after all merges so an
# override cannot forward them to the provider. Both are operator defaults, so they
# are dropped in silence rather than refused.
_RESERVED_FIELDS = {"api", "service_url"}
# What a call property may set on the provider request. The prefixed namespace is closed
# positively because the surface behind it cannot be enumerated the other way round: in
# the pinned litellm 1.98.0, `inspect.signature(litellm.completion)` names 42 parameters
# and another 236 arrive only through **kwargs, and both grow every release. Naming the
# dangerous ones leaves `vertex_project`, `aws_region_name`, `tenant_id` and their
# successors open.
#
# Membership is decided by what a field does, not by where LiteLLM happens to declare it.
# A field is in when it changes what the model is asked or how the answer is shaped. It is
# out when it picks an endpoint, an account, a project, a tenant, a region, a credential or
# a proxy; when it redirects, multiplies or caps the call; when it rewrites the cost model
# the deployment is billed against; when it copies the prompt to a third-party sink; or when
# it writes caller-chosen state onto the deployment's provider account.
#
# The signature half is that 42-name list minus nine. Seven pick an endpoint, an account or
# a credential: `api_key`, `api_version`, `base_url`, `deployment_id`, `extra_headers`,
# `model_list`, `shared_session`. The other two, `user` and `safety_identifier`, are the
# identity the deployment asserts about its end users; a caller that sets them stamps the
# deployment's provider-side abuse and safety record with a label of its own choosing, and
# one that varies `safety_identifier` per call defeats the per-end-user enforcement the
# field exists for. Re-derive the census with:
#
#     python -c "import inspect, litellm; print(sorted(
#         p.name for p in inspect.signature(litellm.completion).parameters.values()
#         if p.kind is not p.VAR_KEYWORD))"
_SIGNATURE_GENERATION_FIELDS = frozenset(
    {
        "audio",
        "enable_json_schema_validation",
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
        "n",
        "parallel_tool_calls",
        "prediction",
        "presence_penalty",
        "reasoning_effort",
        "response_format",
        "seed",
        "service_tier",
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
        "verbosity",
        "web_search_options",
    }
)

# The **kwargs half. Deriving the set from the signature alone refused all 236 names that
# reach LiteLLM through **kwargs, whatever they did, and five of them only shape the
# request: `enable_prompt_caching` installs the provider's prompt-cache annotations, the
# three continue-message controls repair message sequences for providers that require
# strictly alternating roles, and `merge_reasoning_content_in_choices` decides where
# reasoning text lands in the returned choice. None names an endpoint, an account, a
# project, a region, a credential or a sink. Re-derive the surface they were picked from:
#
#     python -c "import inspect, litellm; print(sorted(
#         set(litellm.utils.all_litellm_params) - {p.name for p in
#         inspect.signature(litellm.completion).parameters.values()}))"
_KWARGS_GENERATION_FIELDS = frozenset(
    {
        "assistant_continue_message",
        "enable_prompt_caching",
        "ensure_alternating_roles",
        "merge_reasoning_content_in_choices",
        "user_continue_message",
    }
)

_GENERATION_FIELDS = _SIGNATURE_GENERATION_FIELDS | _KWARGS_GENERATION_FIELDS

# Which provider answers is the deployment's, and it is read from the process environment
# because that is the one channel a caller cannot reach: on the MCP adapter `properties` is
# a tool argument, and the map an LLMClient is constructed with is built out of it.
#
# `model` reads like a generation parameter and is not one. LiteLLM resolves the provider
# from the model string, so `vertex_ai/gemini-2.5-pro` selects Vertex AI — and so does a
# bare `gemini-2.5-pro`, through LiteLLM's own model map. Every call therefore carries
# `custom_llm_provider`, taken from BLUE_DATA_LLM_PROVIDER and defaulting to the `openai`
# every shipped default, example and document already uses, so LiteLLM dispatches on the
# deployment's field instead of inferring a route from the caller's string.
#
# That pin is nearly total and not quite: LiteLLM reads a model beginning `azure/` that its
# own `_is_non_openai_azure_model` recognises before it reads the pin, and hands the request
# to a different provider. So the model is checked as well, and it is checked by asking
# LiteLLM what it would actually do rather than by reading the spelling — the spelling is a
# poor proxy in both directions. `accounts/fireworks/models/llama-v3` on Fireworks and
# `meta-llama/Llama-3-70b` on Together are model identifiers that contain a slash and name
# no route, while a bare `claude-sonnet-4-5` names Anthropic through the model map.
#
# Two questions, both asked on every call, neither able to answer the other:
#
#   * membership — is this model one the deployment offers? BLUE_DATA_LLM_ALLOWED_MODELS
#     answers it, and an empty setting means the deployment has not narrowed the set.
#   * dispatch — would this request be served by BLUE_DATA_LLM_PROVIDER? LiteLLM answers it,
#     through `get_llm_provider` and through its own list of provider names. Both are pure
#     data over LiteLLM's model map and reach no network.
#
# Membership used to stand in for dispatch, and an allowlist entry therefore restored
# provider-qualified routing: `BLUE_DATA_LLM_ALLOWED_MODELS=azure/command-r-plus` under a
# deployment pinned to `anthropic` produced a request LiteLLM 1.98.0 served from `openai`.
# A deployment can widen what may be asked for; it cannot widen where the request goes.
_PROVIDER_VAR = "BLUE_DATA_LLM_PROVIDER"
_ALLOWED_MODELS_VAR = "BLUE_DATA_LLM_ALLOWED_MODELS"
_DEFAULT_PROVIDER = "openai"
_DISPATCH_FIELD = "custom_llm_provider"


def _deployment_provider() -> str:
    """The provider this deployment dispatches to, never a caller's to name."""
    return os.environ.get(_PROVIDER_VAR, "").strip() or _DEFAULT_PROVIDER


def _deployment_models() -> frozenset[str]:
    """The models this deployment offers. Empty means it has not said."""
    return frozenset(os.environ.get(_ALLOWED_MODELS_VAR, "").replace(",", " ").split())


def _litellm_or_none() -> Any | None:
    """LiteLLM if this process has it. The llm extra is optional and tests stub it."""
    try:
        import litellm
    except Exception:
        return None
    return litellm


def _dispatch_target(model: str, provider: str) -> str | None:
    """Which provider LiteLLM would serve *model* from, or None if it will not say.

    This is the same call `litellm.completion` makes on its own first lines, with the same
    two arguments: the other two it passes, `api_base` and `api_key`, are refused call
    properties and are None on this path. Asking the dispatcher itself is what keeps the
    check from drifting away from the thing it checks.
    """
    resolve = getattr(_litellm_or_none(), "get_llm_provider", None)
    if resolve is None:
        return None
    try:
        # Element 1 is the provider name. Elements 2 and 3 are a dynamic credential and an
        # endpoint LiteLLM may have read from the environment; neither is bound or logged.
        resolved = resolve(model=model, custom_llm_provider=provider)[1]
    except Exception:
        return None
    return str(resolved) if resolved else None


def _provider_names() -> frozenset[str] | None:
    """Every name LiteLLM treats as a provider, or None if it will not say.

    `litellm.provider_list` is LiteLLM's own enumeration rather than a list kept here, so a
    provider added upstream is recognised without an edit.
    """
    listed = getattr(_litellm_or_none(), "provider_list", None)
    if not listed:
        return None
    try:
        return frozenset(str(getattr(name, "value", name)) for name in listed)
    except Exception:
        return None


def _refuse_a_provider_litellm_does_not_serve(provider: str) -> None:
    """Refuse a deployment's provider name that LiteLLM does not recognise.

    Every call is now pinned to this name, and both dispatch checks are read against it, so
    a typo in it is a typo in the lock. Left unchecked it surfaces as a failure raised deep
    inside LiteLLM on the first call, naming neither the variable nor the value. Checked, it
    says which name is wrong and where it came from.

    This is a deployment's own configuration rather than anything a caller reaches, so the
    check is for the error message, not for the boundary. When LiteLLM will not name its
    providers there is nothing to check against and the call proceeds.
    """
    names = _provider_names()
    if names is not None and provider not in names:
        raise LLMError(
            f"{_PROVIDER_VAR} names '{provider}', which LiteLLM does not serve — every call "
            "dispatches to it, so it has to be one of LiteLLM's own provider names, such as "
            "'openai', 'anthropic', 'azure', 'vertex_ai', 'bedrock' or 'fireworks_ai'",
            code="bad_provider",
        )


def _refuse_a_model_that_dispatches_elsewhere(model: str, provider: str) -> None:
    """Refuse *model* unless the request it makes is served by *provider*.

    Two checks, both applied, neither standing in for the other.

    The outcome check asks LiteLLM to resolve the request and requires the answer to be the
    deployment's provider. It cannot drift away from what it checks, because it is the call
    the dispatcher makes.

    The spelling check refuses a model whose first path segment is one of LiteLLM's own
    provider names. It is not redundant: the outcome check only holds while the pinned
    release honours `custom_llm_provider`, and 1.98.0 already has one rule that does not —
    which is how `azure/command-r-plus` got through. A route spelled into the model string
    is refused whether or not this release happens to follow it. It is also the check that
    can be made offline, so it is the one the test suite runs.

    When LiteLLM answers neither question there is nothing left to distinguish a route from
    a model identifier, and every slash is treated as a route.
    """
    resolved = _dispatch_target(model, provider)
    if resolved is not None and resolved != provider:
        raise LLMError(
            f"model '{model}' is served by '{resolved}' and this deployment dispatches to "
            f"'{provider}' — which provider answers is not a call property's to choose. "
            f"LiteLLM reads the route out of the model string before it reads "
            f"{_PROVIDER_VAR}, so the call would spend a credential with a provider the "
            f"deployment did not configure. Ask for a model '{provider}' serves",
            code="model_not_allowed",
        )
    if "/" not in model:
        return
    names = _provider_names()
    if names is None or model.split("/", 1)[0] in names:
        raise LLMError(
            f"model '{model}' names a provider, and which provider answers is not a call "
            "property's to choose — LiteLLM reads the part before the '/' as a routing "
            "instruction and would spend this deployment's credential for that provider. "
            "Ask for a model, not a route; a slash that belongs to the model identifier, "
            "as Fireworks and Together write one, is not a provider name and passes",
            code="model_not_allowed",
        )


# Fields that replace the provider's answer with one the caller wrote. LiteLLM returns
# mock_response verbatim without calling anyone, so a property that sets it makes a tool
# hand back the caller's own text as a model answer. This is a separate set from the
# transport fields because the harm is different in kind: the request still goes where
# the deployment configured it, and what comes back is not what answered. On the MCP
# adapter the caller is one agent and the reader of the answer is usually another, so a
# substituted answer is an integrity problem even though it reaches no one else's call.
_SUBSTITUTED_RESPONSE_FIELDS = frozenset({"mock_response", "mock_timeout"})


@dataclass
class UsageRecord:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    latency_seconds: float = 0.0
    cache_hit: bool = False


@dataclass
class _InvocationCostObservation:
    local_cache_hit: bool = False
    provider_attempts: int = 0
    estimated_cost: float | None = None

    def complete_cost(self) -> float | None:
        if self.local_cache_hit and self.provider_attempts == 0:
            return 0.0
        if self.provider_attempts == 1:
            return self.estimated_cost
        return None


class UsageLedger:
    """One record per execute_api_call (cache hits included, end-to-end latency)."""

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    def add(self, record: UsageRecord) -> None:
        self.records.append(record)

    @property
    def total_cost(self) -> float:
        return sum(r.cost for r in self.records)

    @property
    def total_tokens(self) -> int:
        return sum(r.prompt_tokens + r.completion_tokens for r in self.records)


def _safe_int(value: Any) -> int:
    # Accounting must never raise — the contract is total. Any inconvertible value
    # (junk strings, inf/NaN => OverflowError/ValueError, Decimal('NaN'), objects)
    # counts as zero.
    try:
        return int(value or 0)
    except Exception:
        return 0


class LLMClient:
    """Build templated requests and execute them through an LLM provider.

    OpenAI-shaped responses feed the configured output-path extraction. The client
    also provides per-call usage records, async execution, bounded concurrency,
    caching, and rate limiting.
    """

    def __init__(self, name: str, properties: dict[str, Any] | None = None) -> None:
        self.name = name
        self.properties: dict[str, Any] = dict(properties or {})
        self.ledger = UsageLedger()
        self.last_usage: UsageRecord | None = None
        self._caches: dict[str, Any] = {}  # cache_dir -> diskcache.Cache
        self._semaphores: dict[int, asyncio.Semaphore] = {}
        self._rate_lock = threading.Lock()
        self._last_call_at = 0.0

    # ------------------------------------------------------------------ sync --
    def execute_api_call(
        self,
        input: Any,  # noqa: A002 — public call-surface parameter
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        return self._execute_api_call(input, properties, additional_data, observation=None)

    def _execute_api_call_observed(
        self,
        input: Any,  # noqa: A002
        properties: dict[str, Any] | None,
        additional_data: dict[str, Any] | None,
        observation: _InvocationCostObservation,
    ) -> Any:
        return self._execute_api_call(input, properties, additional_data, observation)

    def _execute_api_call(
        self,
        input: Any,  # noqa: A002
        properties: dict[str, Any] | None,
        additional_data: dict[str, Any] | None,
        observation: _InvocationCostObservation | None,
    ) -> Any:
        started = time.monotonic()
        merged = {**self.properties, **(properties or {})}
        message = build_message(input, merged, additional_data, self.name.lower())
        kwargs = self._build_call_kwargs(message, merged)

        cache, cache_key = self._cache_lookup(merged, kwargs)
        if cache is not None and cache_key in cache:
            payload = cache[cache_key]
            if observation is not None:
                observation.local_cache_hit = True
            self._record(kwargs, payload, started, cache_hit=True)
            return extract_output(payload, merged)

        self._apply_rate_limit(merged)
        if observation is None:
            payload, cost = self._call_provider(kwargs)
        else:
            payload, cost = self._call_provider_observed(kwargs, observation)
        if cache is not None and cache_key is not None:
            cache[cache_key] = payload
        self._record(kwargs, payload, started, cache_hit=False, cost=cost)
        return extract_output(payload, merged)

    # ----------------------------------------------------------------- async --
    async def aexecute_api_call(
        self,
        input: Any,  # noqa: A002 — matches the synchronous call surface
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> Any:
        started = time.monotonic()
        merged = {**self.properties, **(properties or {})}
        message = build_message(input, merged, additional_data, self.name.lower())
        kwargs = self._build_call_kwargs(message, merged)

        cache, cache_key = self._cache_lookup(merged, kwargs)
        if cache is not None and cache_key in cache:
            payload = cache[cache_key]
            self._record(kwargs, payload, started, cache_hit=True)
            return extract_output(payload, merged)

        semaphore = self._resolve_semaphore(merged)
        async with semaphore:
            self._apply_rate_limit(merged)
            payload, cost = await self._acall_provider(kwargs)
        if cache is not None and cache_key is not None:
            cache[cache_key] = payload
        self._record(kwargs, payload, started, cache_hit=False, cost=cost)
        return extract_output(payload, merged)

    # ------------------------------------------------------------- internals --
    def _build_call_kwargs(
        self, message: dict[str, Any], properties: dict[str, Any]
    ) -> dict[str, Any]:
        kwargs = dict(message)  # the extracted <prefix>.* fields + input_field payload

        # messages: the wrapped input object built by templating (every operator's shape)
        input_field = properties.get("input_field", "messages")
        if input_field != "messages" and input_field in kwargs:
            kwargs["messages"] = kwargs.pop(input_field)

        # Only the documented llm.* override keys are accepted.
        for key, value in properties.items():
            if key.startswith("llm."):
                short = key[4:]
                if short not in _ACCEPTED_LLM_KEYS:
                    raise LLMError(
                        f"unknown adapter override '{key}' — accepted: "
                        f"{sorted('llm.' + k for k in _ACCEPTED_LLM_KEYS)}",
                        code="bad_override",
                    )
                if short not in _CONTROL_KEYS:
                    kwargs[short] = value

        # Remove transport-resolution fields after every override has been merged.
        for reserved in _RESERVED_FIELDS:
            kwargs.pop(reserved, None)

        # Both refusals run before the cache key is built, so nothing a caller sent under
        # one of these names is written to disk either. The substitution check comes first
        # only to give its own fields the reason that fits them; the allowlist below would
        # refuse them anyway.
        substituted = sorted(key for key in kwargs if key in _SUBSTITUTED_RESPONSE_FIELDS)
        if substituted:
            raise LLMError(
                f"properties may not substitute the provider response: {substituted} — "
                "a result carries what the provider answered, not what the caller sent",
                code="reserved_field",
            )

        refused = sorted(key for key in kwargs if key not in _GENERATION_FIELDS)
        if refused:
            raise LLMError(
                f"properties may not set provider fields outside the generation set: "
                f"{refused} — the provider, project, tenant, region, endpoint and "
                "credential come from the environment this deployment runs in; a call "
                f"property may set {sorted(_GENERATION_FIELDS)}",
                code="reserved_field",
            )

        if not kwargs.get("model"):
            raise LLMError("no model configured (set <prefix>.model or llm.model)", code="no_model")

        model = str(kwargs["model"])
        provider = _deployment_provider()
        _refuse_a_provider_litellm_does_not_serve(provider)
        # Membership and dispatch are separate questions and both have to hold. A
        # deployment narrows what may be asked for; nothing widens where it goes.
        offered = _deployment_models()
        if offered and model not in offered:
            raise LLMError(
                f"model '{model}' is not one this deployment offers — "
                f"{_ALLOWED_MODELS_VAR} names {sorted(offered)}",
                code="model_not_allowed",
            )
        _refuse_a_model_that_dispatches_elsewhere(model, provider)
        # After every refusal, so a caller can neither set this field nor reach it.
        kwargs[_DISPATCH_FIELD] = provider
        return kwargs

    def _cache_lookup(
        self, properties: dict[str, Any], kwargs: dict[str, Any]
    ) -> tuple[Any | None, str | None]:
        if not properties.get("llm.cache"):
            return None, None
        # Caches are bound per directory so a per-call llm.cache_dir override selects
        # its own isolated cache instead of silently reusing the first one opened.
        cache_dir = str(properties.get("llm.cache_dir", ".llm_cache"))
        cache = self._caches.get(cache_dir)
        if cache is None:
            try:
                import diskcache  # pyright: ignore[reportMissingTypeStubs]
            except ImportError as e:
                raise LLMError(
                    "llm.cache requested but diskcache is not installed "
                    "(pip install 'blue-data-ops[llm]')",
                    code="cache_unavailable",
                ) from e
            cache = diskcache.Cache(cache_dir)
            self._caches[cache_dir] = cache
        return cache, json.dumps(kwargs, sort_keys=True, default=str)

    def _resolve_semaphore(self, properties: dict[str, Any]) -> asyncio.Semaphore:
        max_parallel = int(properties.get("llm.max_parallel", 8))
        loop_id = id(asyncio.get_running_loop())
        key = hash((loop_id, max_parallel))
        semaphore = self._semaphores.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(max_parallel)
            self._semaphores[key] = semaphore
        return semaphore

    def _apply_rate_limit(self, properties: dict[str, Any]) -> None:
        rate = properties.get("llm.rate_limit")
        if not rate:
            return
        min_interval = 1.0 / float(rate)  # calls per second
        with self._rate_lock:
            wait_for = self._last_call_at + min_interval - time.monotonic()
            if wait_for > 0:
                time.sleep(wait_for)
            self._last_call_at = time.monotonic()

    def _record(
        self,
        kwargs: dict[str, Any],
        payload: dict[str, Any],
        started: float,
        cache_hit: bool,
        cost: float = 0.0,
    ) -> None:
        usage: dict[str, Any] = {}
        raw_usage: Any = payload.get("usage")
        if isinstance(raw_usage, dict):
            usage = raw_usage  # pyright: ignore[reportUnknownVariableType]
        record = UsageRecord(
            model=str(kwargs.get("model")),
            prompt_tokens=0 if cache_hit else _safe_int(usage.get("prompt_tokens")),
            completion_tokens=0 if cache_hit else _safe_int(usage.get("completion_tokens")),
            cost=0.0 if cache_hit else cost,
            latency_seconds=time.monotonic() - started,  # end-to-end, incl. retries
            cache_hit=cache_hit,
        )
        self.last_usage = record
        self.ledger.add(record)

    @retry(
        retry=retry_if_exception_type(LLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, max=2),
        reraise=True,
    )
    def _call_provider(self, kwargs: dict[str, Any]) -> tuple[dict[str, Any], float]:
        import litellm  # lazy: the llm extra is optional; tests stub this module

        try:
            response: Any = litellm.completion(**kwargs)
        except Exception as e:  # transport boundary: wrap provider errors
            raise LLMError(str(e), code="provider_error", provider_error=e) from e
        return self._materialize(response)

    @retry(
        retry=retry_if_exception_type(LLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, max=2),
        reraise=True,
    )
    def _call_provider_observed(
        self, kwargs: dict[str, Any], observation: _InvocationCostObservation
    ) -> tuple[dict[str, Any], float]:
        import litellm

        observation.provider_attempts += 1
        try:
            response: Any = litellm.completion(**kwargs)
        except Exception as e:
            raise LLMError(str(e), code="provider_error", provider_error=e) from e
        return self._materialize_observed(response, observation)

    @retry(
        retry=retry_if_exception_type(LLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, max=2),
        reraise=True,
    )
    async def _acall_provider(self, kwargs: dict[str, Any]) -> tuple[dict[str, Any], float]:
        import litellm  # lazy — same boundary as the sync path

        try:
            response: Any = await litellm.acompletion(**kwargs)
        except Exception as e:
            raise LLMError(str(e), code="provider_error", provider_error=e) from e
        return self._materialize(response)

    def _materialize(self, response: Any) -> tuple[dict[str, Any], float]:
        payload = self._materialize_payload(response)
        return payload, self._completion_cost(response)

    def _materialize_observed(
        self, response: Any, observation: _InvocationCostObservation
    ) -> tuple[dict[str, Any], float]:
        payload = self._materialize_payload(response)
        legacy_cost, estimated_cost = self._observed_completion_cost(response)
        observation.estimated_cost = estimated_cost
        return payload, legacy_cost

    @staticmethod
    def _materialize_payload(response: Any) -> dict[str, Any]:
        # Provider-response failures stay inside the decorated attempt.
        try:
            raw: Any = response.model_dump() if hasattr(response, "model_dump") else response
        except Exception as e:
            raise LLMError(
                "provider response could not be materialized", code="bad_response", provider_error=e
            ) from e
        raw_dict: dict[str, Any] | None = (
            cast("dict[str, Any]", raw) if isinstance(raw, dict) else None
        )
        if raw_dict is None or not isinstance(raw_dict.get("choices"), list):
            raise LLMError(
                "provider returned a non-OpenAI-shaped response (no choices list)",
                code="bad_response",
            )
        payload: dict[str, Any] = dict(raw)  # pyright: ignore[reportUnknownArgumentType]
        return payload

    @staticmethod
    def _completion_cost(response: Any) -> float:
        try:
            import litellm

            return float(litellm.completion_cost(completion_response=response))
        except Exception:
            return 0.0

    @staticmethod
    def _observed_completion_cost(response: Any) -> tuple[float, float | None]:
        try:
            import litellm

            raw_cost: Any = litellm.completion_cost(completion_response=response)
        except Exception:
            return 0.0, None

        reportable_type = not isinstance(raw_cost, bool) and isinstance(raw_cost, (Real, Decimal))
        raw_nonnegative = False
        if reportable_type:
            try:
                raw_nonnegative = bool(cast(Any, raw_cost) >= 0)
            except Exception:
                pass

        try:
            converted_cost = float(raw_cost)
        except Exception:
            return 0.0, None

        if not reportable_type or not raw_nonnegative:
            return converted_cost, None
        if not isfinite(converted_cost):
            return converted_cost, None
        return converted_cost, converted_cost
