# Extending blue-data-ops

The four things this library is built to have replaced, and how to replace each one.

`blue_data_ops` has no plugin discovery and no entry-point scanning.
Everything below is an explicit constructor argument or an explicit registration, which is why nothing in an installed environment can change what an operator resolves to.
The operator lifecycle, the error vocabulary, the result envelope, and a registry's immutability are fixed and are not extension points.

| To change | Supply | Reached through |
|---|---|---|
| The operator catalog | An `Operator` subclass | `OperatorRegistry.register` |
| How discovery ranks cards | An `OperatorEmbedder` | `OperatorEmbeddingIndex.build` |
| How model calls are made | An `LLMClient`, or an `LLMClientProvider` | `resolve_llm_client` |
| Which data registry an operator uses | A `RegistrySeam`, or a `DataRegistryProvider` | `resolve_registry` |

See [architecture.md](architecture.md) for where these sit, and [api-reference.md](api-reference.md) for the exact signatures.

---

## Adding an operator

Subclass `Operator`, declare `name`, `description`, and `attributes`, and implement `apply`.
Override `_execute` when your operator produces output attributes alongside its data, and `_validate_input` when declared-type checking is not enough.

```python
from typing import ClassVar

from blue_data_ops import Operator
from blue_data_ops.operators import (
    Attributes,
    AttributeSpec,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
    active_registry,
)


class ScaleOperator(Operator):
    """Multiply one numeric record field by a constant factor."""

    name: ClassVar[str] = "scale"
    description: ClassVar[str] = "Multiply a numeric record field by a constant factor."
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "value_key": AttributeSpec(type="str", description="Record field to scale", required=True),
        "factor": AttributeSpec(type="float", description="Multiplier", default=1.0),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        return self._execute(input_data, attributes, properties).output_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        key = str(attributes["value_key"])
        factor = float(attributes.get("factor", 1.0))
        scaled: DataBundle = [
            [{**record, key: record[key] * factor} for record in group] for group in input_data
        ]
        return FunctionResult(scaled, {})

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        # The declared-type pass runs first; only the field-name rule is added here.
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, "supply valid input attributes")
        key = attributes.get("value_key")
        if not isinstance(key, str) or not key:
            return ValidationResult(False, "value_key must be a nonempty field name")
        return ValidationResult(True, None)


registry = active_registry()
registry.register(
    ScaleOperator(),
    "1.0.0",
    ["domain-arithmetic", "capability-transformation"],
    when_to_invoke="Use when a numeric field needs a constant multiplier.",
)

operator = registry.resolve("scale@1.0.0")
output_data, output_attributes, meta = operator.run(
    [[{"total": 2.0}, {"total": 4.0}]],
    {"value_key": "total", "factor": 2.5},
)
assert output_data == [[{"total": 5.0}, {"total": 10.0}]]
assert meta.errors == []

_, _, invalid = operator.run([[{"total": 2.0}]], {})
assert invalid.errors[0].code.value == "INVALID_INPUT"
assert invalid.errors[0].operator_id == "scale@1.0.0"
```

Three things are worth knowing before you write the second one.

**`run()` is not yours to override.**
It materializes declared defaults, calls `_validate_input`, calls `_execute`, and normalizes the result, turning every failure into an `ErrorRecord`.
Your `_execute` therefore does not need its own try/except: an exception becomes `EXECUTION_FAILED` at the `EXECUTE` stage with the bundle normalized to `[[]]`.
A `_validate_input` that returns `ValidationResult(False, reason)` becomes a recoverable `INVALID_INPUT` record carrying your reason as the suggestion.

**Registration is immutable and registrations are not shared.**
`register` raises `ValueError` on a repeated `name@version`, and there is no deregister.
`active_registry()` returns a fresh registry each call, so registering into one does not affect any other caller's.
Version your own operators with real semver; `resolve` accepts nothing else.

**Custom tags are permissive; built-in tags are not.**
The closed six-namespace vocabulary and the ordering rule in `DiscoverySpec` are validated for package built-ins only, and `register` stores whatever tags you pass, verbatim.
`find()` normalizes a requested filter by stripping and case-folding it, then matches the whole token, so a custom tag is discoverable only when its stored value equals the normalized filter.
Reusing the built-in namespaces keeps your operator findable by the same queries — a made-up namespace works, but nobody will guess it.

An operator resolved from your own registry runs through `PipelineExecutor` and `PipelinePlanner` normally.
It will not be accepted by `OpenAIPlanGenerator`, which admits only supported package built-ins from an enriched package registry.

---

## Supplying an embedder for discovery

The package ships no embedding model and never downloads one.
`OperatorEmbeddingIndex` takes a caller-supplied embedder satisfying the `OperatorEmbedder` protocol: a `space_id` property and a batch `__call__`.

```python
from collections.abc import Sequence

from blue_data_ops.operators import OperatorEmbeddingIndex, active_registry

TERMS = ("filter", "join", "average", "embedding", "sql")


class TermEmbedder:
    """A deterministic stand-in: one dimension per term, plus a constant bias."""

    space_id = "term-presence-v1"

    def __call__(self, texts: tuple[str, ...]) -> Sequence[Sequence[float]]:
        return [[1.0, *(float(term in text.casefold()) for term in TERMS)] for text in texts]


catalog = active_registry()
index = OperatorEmbeddingIndex.build(catalog, TermEmbedder())
cards = index.find("filter records", tags=["produces-data"])

assert index.registry is catalog
assert all("produces-data" in card.tags for card in cards)
assert cards[0].operator_id == "select@2.0.0"
```

Swap `TermEmbedder` for a real sentence encoder and the rest stays as written.
The contract is narrow on purpose.

| Rule | Why |
|---|---|
| `space_id` identifies the embedding space, and it is read again on every `find()` | A model or model version swap under a live index is caught rather than silently changing rankings |
| `__call__` receives a tuple of documents and returns one vector per document, same order | `build()` embeds the whole card snapshot in one batch, so a single call covers the catalog |
| Every vector must be finite, nonempty, and the same length | The index normalizes each one and ranks by cosine similarity; a zero or ragged vector has no meaningful ranking |
| Mutating the registry after `build()` invalidates the index | `find()` re-checks the snapshot and raises `EmbeddingDiscoveryError("STALE_INDEX")` instead of ranking against cards that moved |

`build()` sends each card's name, invocation guidance, description, and ordered tags.
`find()` applies exact AND tag filtering first, then ranks what is left, with no threshold and no limit — slice the returned list yourself.
Every failure path raises `EmbeddingDiscoveryError` with a stable `reason`, so a caller can tell a bad embedder result (`INVALID_RESULT`) from a stale snapshot (`STALE_INDEX`) from a callback that threw (`QUERY_FAILED`).

---

## Swapping the LLM provider

The eight provider-backed operators — `nl2llm`, `nl2sql`, `nl2bn`, and the five `semantic_*` operators — do not construct a client of their own.
Each calls `resolve_llm_client(merged_properties)`, and that function takes the first path that works: an `LLMClient` injected at `properties["llm_client"]`, then a provider if the caller passed one, then a fresh client built from the same properties.
The built-ins pass no provider, so injecting a client is how you replace one inside an operator call, and `LLMClientProvider` is the seam for code that calls `resolve_llm_client` itself.

```python
from typing import Any

from blue_data_ops.llm import LLMClient, LLMClientProvider, resolve_llm_client


class SingleModelProvider(LLMClientProvider):
    """Hand every `resolve_llm_client` caller the same configured client."""

    def __init__(self, model: str) -> None:
        self._client = LLMClient(name="llm_client", properties={"llm.model": model})

    def get_client(self, properties: dict[str, Any]) -> LLMClient:
        return self._client


provider = SingleModelProvider("gpt-4o-mini")
client = resolve_llm_client({}, provider)
assert client is provider.get_client({})

injected = resolve_llm_client({"llm_client": client})
assert injected is client
```

There are three depths to choose from.

| Depth | What you supply | Reaches a built-in operator | Use it when |
|---|---|---|---|
| Configuration | `properties` such as `{"openai.model": "gpt-4o-mini"}` on the call | yes | A different model or different limits, same transport |
| A client | Your own object at `properties["llm_client"]` | yes | Replacing the transport, recording every call, or serving canned responses in a test |
| A provider | An `LLMClientProvider`, or the shipped `CachingLLMClientProvider` | only through your own `resolve_llm_client` call | Controlling client lifetime, sharing one client and its usage ledger, or picking a client per config |

An injected client is used exactly as given, which makes it the seam a test uses: nothing reaches a provider and nothing needs a credential.
A real client reports `cost` only for exactly one priced attempt, so an injected client omits the cost fields rather than guessing at them.

The default client is LiteLLM-backed and accepts a closed set of `llm.*` overrides: `model`, `stream`, `max_tokens`, `temperature`, `cache`, `cache_dir`, `max_parallel`, and `rate_limit`.
An unrecognized `llm.*` key raises `LLMError` with code `bad_override` rather than being forwarded to the provider.
Credentials come from the provider's own environment variables; never put a key in a property dict you commit.

Plan generation has a separate seam.
`PipelinePlanner` takes any object satisfying the `PlanGenerator` protocol, so replacing `OpenAIPlanGenerator` means writing one `generate` method — see [api-reference.md](api-reference.md).
`OpenAIPlanGenerator` also accepts `client=` if you only want to hand it a configured SDK client.

---

## Providing a data registry

`create_database`, `create_table`, `insert_table`, and `data_discover` need a `blue-data` registry, and so do `nl2sql` and `nl2bn`, which read the source schema they generate against.
All six call `resolve_registry(properties)` on their own call properties, and its resolution order is fixed: an injected `RegistrySeam` at `properties["data_registry"]`, then a raw `DataRegistry` at that key (which it wraps for you), then construction from `properties["platform.name"]` and `properties["data_registry.name"]` through the default provider.
When none of the three resolves, `resolve_registry` returns `None` and the operator reports a contained `EXECUTION_FAILED` record rather than raising.

Because the built-ins pass no provider argument, injecting a seam at `properties["data_registry"]` is how you hand a built-in operator a registry you built yourself.
`DataRegistryProvider` is the seam for code that calls `resolve_registry` itself: your own operator, a setup helper, or a service that builds one registry per tenant.
Both paths are in the example below.

```python
from typing import Any

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.json.memory_json_source import MemoryJSONSource

from blue_data_ops import DataRegistryProvider, RegistrySeam, resolve_registry


class SharedRegistryProvider(DataRegistryProvider):
    """Hand every operator the same pre-populated registry."""

    def __init__(self, seam: RegistrySeam) -> None:
        self._seam = seam

    def get_registry(
        self, platform_name: str, registry_name: str, properties: dict[str, Any]
    ) -> RegistrySeam:
        return self._seam


seam = RegistrySeam(DataRegistry(store=MemoryJSONSource(), rebuild=False))
provider = SharedRegistryProvider(seam)

assert resolve_registry({"platform.name": "local", "data_registry.name": "demo"}, provider) is seam
assert resolve_registry({"data_registry": seam}) is seam
```

The default provider, `BlueDataRegistryProvider`, builds one in-memory `DataRegistry` per `(platform.name, data_registry.name)` pair and caches it for the life of the process.
That is enough for a demo and wrong for anything durable, since nothing survives the process.
Supply your own provider, from code that calls `resolve_registry` itself, when a registry has to persist, be shared with code outside this package, or sit on a store other than the default.

`RegistrySeam` is the only place this package imports `blue_data`, and it exists to absorb signature differences rather than to add behavior.
It consumes the per-call `rebuild` flag the wrapped registry has no parameter for, reorders `execute_query` arguments by keyword so a positional swap is impossible, and normalizes search results to flat records with an inverted score where lower is closer.
If you wrap a different registry implementation, match that facade's signatures rather than the operators' call sites, and read [`lib/COMPATIBILITY.md`](../lib/COMPATIBILITY.md) for the per-surface differences it absorbs.

Runnable versions of these patterns ship in the repository; [`examples/README.md`](../examples/README.md) lists them with their commands.
