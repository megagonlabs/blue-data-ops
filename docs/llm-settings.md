# Choosing a model for an LLM operator

Set `llm.model` in the properties passed to an LLM-backed operator. Set
`llm.reasoning_effort` only when the selected model supports it. These names work for
`nl2llm`, `nl2sql`, `semantic_filter`, and other LLM-backed operators. The
[offline example](../examples/feature-demos/llm_settings.py) shows the values that reach
`nl2llm` without contacting a provider:

```bash
python examples/feature-demos/llm_settings.py
```

The script uses placeholder model names and an injected recording client. For a live
library or MCP call, install the [`llm` extra](installation.md#optional-extras), use a
model allowed by your deployment, and configure its provider credential. The CLI package
already depends on that extra.

Provider routing is set in the process environment: `BLUE_DATA_LLM_PROVIDER` defaults to
`openai`, and `BLUE_DATA_LLM_ALLOWED_MODELS` can limit the models callers may select.
For MCP, these settings belong to the server process. A call, stored pipeline, or operator
node can select an allowed model and its supported effort, but cannot select the provider,
endpoint, project, tenant, region, or credential.

For example, a deployment using Anthropic through LiteLLM can start its operator
process with:

```bash
export BLUE_DATA_LLM_PROVIDER=anthropic
export BLUE_DATA_LLM_ALLOWED_MODELS=claude-sonnet-4-5
export ANTHROPIC_API_KEY="<your-key>"
blue-ops operator run nl2llm@3.0.0 \
  --attribute 'query=Return one example product.' \
  --model claude-sonnet-4-5
```

The last command makes a paid provider call. `BLUE_DATA_LLM_ALLOWED_MODELS` accepts
model names separated by commas or spaces. Use an unqualified model name: a value such
as `anthropic/claude-sonnet-4-5` is rejected as a provider route. LiteLLM documents
the [Anthropic credential variable](https://docs.litellm.ai/docs/providers/anthropic#api-keys) and the
[provider names](https://docs.litellm.ai/docs/providers). Check the installed
adapter and your account for other providers and model names.

Operator calls and provider-backed planning use different clients:

| Call | Provider and credential | Model control | Effort control |
|---|---|---|---|
| `nl2llm`, `nl2sql`, `semantic_*` and other LLM operators | LiteLLM; `BLUE_DATA_LLM_PROVIDER` plus that provider's credential | `llm.model` or the CLI `--model` flag | `llm.reasoning_effort` or `--reasoning-effort`, when supported |
| `OpenAIPlanGenerator` / `pipeline add --planner openai` | OpenAI SDK; `OPENAI_API_KEY` | Generator constructor or planner `--model` flag | No planner effort setting |

The provider setting for operators does not change the planner. A planner can
produce a pipeline whose LLM operators later use a different provider.

All versions of the eight LLM-backed operators default to `gpt-6-luna`, including
exact `@1.0.0` and `@2.0.0` versions called directly from the library. The CLI's
`BLUE_DATA_LLM_MODEL` profile setting also defaults to Luna and is passed at
invocation. Callers can select another allowed model at the pipeline or operator
level. If the deployment sets `BLUE_DATA_LLM_ALLOWED_MODELS`, it must include
`gpt-6-luna` for default calls.

Operators do not set reasoning effort, so Luna uses its
[current `medium` default](https://developers.openai.com/api/docs/models/gpt-6-luna).
The CLI's provider-backed pipeline planner has a separate setting that also
defaults to `gpt-6-luna`. Library callers pass the planner model explicitly.
The planner does not expose an effort setting, so Luna uses its provider default.
Operators and the planner still accept explicit `gpt-4o` selections.

For OpenAI model choices, start with these rules:

| Model | Operator effort setting | Sampling |
|---|---|---|
| `gpt-4o` | Omit effort or clear an inherited value with `None` / `null` | Temperature is supported |
| `gpt-6-luna` or `gpt-6-sol` | `low`, `medium`, `high`, `xhigh`, or `max`; `none` is also supported by OpenAI | Omit temperature and related sampling controls at active effort |
| `gpt-6-astra` | `low`, `medium`, `high`, `xhigh`, or `max`; no `none` | Omit temperature and related sampling controls |

The [OpenAI model guide](https://developers.openai.com/api/docs/guides/deployment-checklist)
lists current effort and sampling constraints. The installed LiteLLM version may
have additional limits; the [compatibility notes](#reasoning-models-and-generation-settings)
below describe the versions checked for this package. For another provider,
consult its model and adapter documentation before setting effort.

## Library

Pass settings to one operator's `run()` call:

```python
from blue_data_ops.operators import active_registry

operator = active_registry().resolve("nl2llm@3.0.0")
output, _, meta = operator.run(
    [[]],
    {"query": "Return one example product."},
    {"llm.model": "gpt-5-mini", "llm.reasoning_effort": "low"},
)
```

The same properties map works with `semantic_filter@3.0.0`; see the
[library examples](../lib/README.md#operators). In a pipeline, the invocation supplies
defaults, the stored pipeline can override them, and one operator node can override both:

```python
from blue_data_ops.operators import active_registry
from blue_data_ops.plan import DataPipeline, PipelineExecutor

pipeline = DataPipeline(
    properties={"llm.model": "gpt-5-mini", "llm.reasoning_effort": "medium"},
)
source = pipeline.define_input("records")
generate = pipeline.define_operator(
    "nl2llm@3.0.0",
    attributes={"query": "Return one example product."},
    properties={"llm.model": "gpt-4o-mini", "llm.reasoning_effort": None},
)
result = pipeline.define_output("result")
pipeline.set_plan_input(source)
pipeline.set_plan_output(result)
pipeline.connect_nodes(source, generate)
pipeline.connect_nodes(generate, result)

run = PipelineExecutor(active_registry()).execute(
    pipeline,
    [[]],
    properties={"llm.model": "gpt-5-mini", "llm.reasoning_effort": "low"},
)
```

The node selects `gpt-4o-mini` and clears the inherited effort. The
[offline example](../examples/feature-demos/llm_settings.py) runs all three layers
without a provider call.

Precedence applies to each setting separately; the two token-limit names count
as one setting. Changing a model at a higher layer does not clear an effort set
at a lower layer. Set `llm.reasoning_effort` to `None` or `null` at the higher
layer when the new model should use its own default.

## CLI

For one direct call, use `--model` and, if supported, `--reasoning-effort`:

```bash
blue-ops operator run nl2llm@3.0.0 \
  --attribute 'query=Return one example product.' \
  --model gpt-5-mini --reasoning-effort low
```

To clear an inherited temperature for an
[unlisted model](#reasoning-models-and-generation-settings), add
`--property llm.temperature=null` to `operator run`. The value is parsed as JSON
null, so it is omitted from the provider request. For a stored pipeline, put
`"llm.temperature": null` in the operator node's JSON properties.

If a reasoning model runs out of completion tokens, set the limit for that
call with `--property llm.max_tokens=8192`. There is no dedicated CLI flag for
this limit. A pipeline node can set the same property in its JSON.

For a stored pipeline, the same flags on `pipeline run` supply invocation defaults. With
`llm-example` and `examples/cli/llm-input.json` from the [CLI guide](../platform/ops-cli/README.md#pipelines):

```bash
blue-ops pipeline import llm-example --pipeline-file examples/cli/llm-pipeline.json
blue-ops pipeline run llm-example --input-file examples/cli/llm-input.json \
  --model gpt-5-mini --reasoning-effort low
```

Put `llm.model` and `llm.reasoning_effort` in the imported pipeline's top-level
`properties` for stored defaults, or in its operator node's `properties` for one node.
The [CLI guide](../platform/ops-cli/README.md#pipelines) has a complete importable JSON example.
`pipeline add --planner openai --model` selects the *planner's* model; it does not set
the models used later by pipeline operators.

## MCP

Set the same properties in an individual tool call. For example, send these arguments
to `ops_nl2llm`:

```json
{
  "input_data": [[]],
  "attributes": {"query": "Return one example product."},
  "properties": {"llm.model": "gpt-5-mini", "llm.reasoning_effort": "low"}
}
```

`ops_semantic_filter` accepts the same properties. See the
[MCP Tool contract](mcp.md#tool-contract) for its request and response. The MCP
adapter exposes individual operator tools; it has no pipeline-run tool or stored-pipeline
settings layer.

## Precedence and compatibility

For `model`, `reasoning_effort`, `stream`, `temperature`, and token limits
(`max_tokens` or provider-prefixed `max_completion_tokens`), the effective order is:

1. Explicit operator-node setting
2. Stored pipeline setting
3. Current library or CLI invocation setting
4. Operator default

A direct operator call has only the current-call setting and operator default. MCP tool
calls are direct calls. Other execution properties, including `llm.cache` and
`llm.max_parallel`, retain their existing order: node, invocation, stored pipeline,
default. Deployment provider routing and its model allowlist still constrain the
selected model.
Within one merged property set, `llm.model` takes precedence over `openai.model`.
The CLI's `--model` flag takes precedence over either property supplied with `--property`.

If you inject an `LLMClient`, its stored model, effort, temperature, stream, and
token limit replace operator defaults. Explicit properties on the operator
call replace those stored settings, including when one uses `openai.*` and the
other uses `llm.*`.

```python
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import active_registry

client = LLMClient("shared", {"openai.model": "gpt-4o", "openai.temperature": 0})
operator = active_registry().resolve("nl2llm@3.0.0")
output, _, meta = operator.run(
    [[]],
    {"query": "Return one example product."},
    {"llm_client": client, "llm.model": "gpt-6-sol"},
)
```

With `BLUE_DATA_LLM_PROVIDER=openai`, the call selects GPT-6 Sol. The client's
temperature of zero is an explicit client setting and is rejected for GPT-6 Sol
before the provider call. Set `llm.temperature` to `None` on the call to clear it. The
client ledger remains available after the call. A live call needs the
deployment's provider credential.

## Rate admission and response cache

`llm.rate_limit` paces provider attempts per client. Use `None` or `0` for unlimited
admission; finite positive rates must be at least `0.1` requests per second. Calls
wait for a slot. With a positive rate, semaphore, lock, and rate waits share a
cumulative budget of at most 10 seconds per provider attempt, capped by the remaining
`execution.timeout_seconds` deadline. Each retry and temperature fallback gets its
own attempt budget. If admission stays full, the call returns retryable
`local_rate_limit`, which the client does not automatically retry. With unlimited
pacing, a concurrency-slot wait obeys cancellation and the operator deadline,
without an additional 10-second limit. Set `execution.timeout_seconds` for calls
from untrusted callers: without a deadline, a valid low-rate call can hold a worker
for roughly ten seconds per provider attempt. This is not a whole-operation limit.
A deadline cannot interrupt provider I/O that has already started. The 0.1 floor
also applies to host-configured rates; slower tiers need host-enforced pacing
outside this client with its rate set to `0` or `None`.

`llm.max_parallel` must resolve to a positive integer. Integral numeric strings and
values are accepted; booleans, nonfinite values, and nonpositive or fractional
values are refused. Separate clients do not share admission state.

Set `llm.cache=true` to cache responses with `diskcache`; the default directory is
`.blue-data-ops-cache` in the working directory. Set `llm.cache_dir` to choose a
different path. On POSIX, the directory must belong to the current user and have no
group or other access; new directories are created with mode `0700`, and unsafe
existing directories are refused without permission changes. The canonical path
must remain stable when `diskcache` expands it a second time. A literal `$` is valid
when the path remains private and stable. Cache hits return the stored response
without waiting for rate or concurrency admission. Use a separate private cache
directory per deployment; cache keys do not distinguish endpoint, project, or
region. See the [MCP Tool contract](mcp.md#tool-contract) for the property names
and caller mapping.

Omit `llm.reasoning_effort` for a model without that option. At an operator node, use
`None` in Python or `null` in pipeline JSON to clear an inherited effort. This
client does not retry a failed call with effort removed. A provider response with a
recognized unsupported-parameter or unsupported-value code stops that call,
except for the inherited-temperature fallback described below; other provider
errors follow the ordinary retry policy. `None`
and `null` are not sent to the provider.

An operator call contains a failed LLM request as an `EXECUTION_FAILED` record.
Its message and suggestion identify known configuration failures, such as a
missing model, a refused routing override, or rejected credentials, without
returning provider exception text. The CLI reports this as `EXECUTION` (exit 8);
the MCP tool returns the record in its result.

When the client loads or calls LiteLLM, it sets `litellm.suppress_debug_info=True`
to suppress LiteLLM's exception-help banner on standard output. This setting is
process-wide and also affects other LiteLLM calls in the same Python process.

## Reasoning models and generation settings

An explicit `gpt-4o` selection sends the operator's configured temperature of
zero. `gpt-5-mini` does not
accept `temperature`, `top_p`, `logprobs`, or `top_logprobs` at any effort. For
`gpt-6-astra`, `gpt-6-sol`, and `gpt-6-luna`, the operator leaves its inherited
temperature out of the request. If you set `llm.reasoning_effort` to `low`,
`medium`, or another active level, an explicit
`temperature`, `top_p`, `logprobs`, or `top_logprobs` setting is rejected before the
provider call. The same applies when effort is omitted and the model defaults to an
active level.

Live tests covered Luna and Sol at `low` effort with LiteLLM 1.98.0, and Luna
at `low` with 1.102.0. The older adapter lacks GPT-6 parameter metadata, so
the library passes through only `reasoning_effort` for OpenAI-pinned GPT-6
calls. Call properties cannot add other adapter pass-through fields.

These constraints come from OpenAI's
[GPT-5 compatibility guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.2)
and [GPT-6 migration guidance](https://developers.openai.com/api/docs/guides/latest-model).
The automatic compatibility rules in this library apply when
`BLUE_DATA_LLM_PROVIDER=openai`. Other deployments, including Azure OpenAI,
should check their own adapter's accepted arguments. To omit a temperature
inherited from an operator default there, set `llm.temperature` to `None` or
`null` on the call.

`None` or `null` clears a supplied effort; it does not turn reasoning off. Use the
literal string `"none"` only on a model that supports it. OpenAI permits sampling on
GPT-6 Sol and Luna at effort `"none"`, but LiteLLM 1.102.0 rejects that
combination. The package allows a range of LiteLLM versions, so
check the installed adapter when using a different one. GPT-6 Astra does not
support effort `"none"`. The operator omits inherited sampling defaults for all
three GPT-6 models; for Sol and Luna it does so even at `"none"`. Explicit
sampling settings still reach the adapter at `"none"` on Sol or Luna; with
LiteLLM 1.102.0, leave them out.

The library's built-in GPT-5 model list covers `gpt-5`, `gpt-5-mini`,
`gpt-5-nano`, `gpt-5.1`, `gpt-5.2`, `gpt-5.4`, `gpt-5.5`, `gpt-5.6`, and the
`gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna` variants. The GPT-6 list
covers `gpt-6-astra`, `gpt-6-sol`, and `gpt-6-luna`. A dated snapshot of any
listed model uses the same rule.
Other Chat Completions models, including `gpt-6.1-sol`, `gpt-6.1-terra`, and `o3`,
initially receive the operator's temperature default. When LiteLLM specifically
refuses temperature, or OpenAI returns HTTP 400 with `code=unsupported_value`
and `param=temperature`, the client retries once with only that inherited
temperature removed. Other sampling settings remain in the request. This applies
to synchronous and asynchronous operator calls and needs no model-list update.

Explicit temperatures remain strict, including zero supplied as `llm.temperature`,
`openai.temperature`, or a stored client setting. Direct clients have no operator
default provenance. Set `llm.temperature` to `None` in Python or `null` in JSON
to omit temperature explicitly. Errors for other fields, credentials, missing
models or malformed replies do not trigger this fallback.

A cached fallback response is stored under the request without temperature.
Repeated default calls can use it without another provider request; an explicit
zero cannot use that fallback entry. Cache hits report zero usage and cost.
The usage ledger records the successful response. Observed cost remains unknown
when a provider rejection precedes success; a local LiteLLM parameter refusal
adds no provider cost.

[GPT-5 Pro](https://developers.openai.com/api/docs/models/gpt-5-pro) and
[GPT-5-Codex](https://developers.openai.com/api/docs/models/gpt-5-codex) use
OpenAI's Responses API. LiteLLM 1.98.0 and 1.102.0 mark them as Responses
models and route `completion()` through a bridge. This library has not verified
their live operator behavior. They are outside the automatic sampling table;
if you try one, clear the inherited temperature and use only an effort the
model supports. GPT-5 Pro supports `high` only.

For recognized GPT-5 and GPT-6 models, `llm.max_tokens` becomes Chat Completions'
`max_completion_tokens`. Do not set both limit names in the same property layer;
a node limit replaces a stored pipeline limit under either name, and an explicit
operator limit replaces a lower-priority client default. The budget
includes reasoning tokens as well as the visible answer. Existing
operator defaults range from 512 tokens for `nl2sql` to 4,096 for `nl2llm`; a
reasoning model may exhaust a smaller budget before it returns useful content.
Set a larger `llm.max_tokens` when needed. The LLM client raises an actionable
error for a cut-off response. Active `@3.0.0` operators preserve that error
instead of treating it as a non-match. Historical semantic-join v2 threshold
optimization can catch the error and return a result after falling back,
even without another model call;
use the active `@3.0.0` operator when a cut-off must stop the join.

The client records provider-reported usage and an available cost estimate
before raising a cut-off error. If you retain an injected `LLMClient`, its ledger
shows that record. Failed operator results do not expose the cost, and after an
earlier failed attempt the total amount billed across retries may be unknown.
`UsageLedger.total_cost` sums recorded estimates; it is not a complete billing
figure when an earlier attempt could have been charged without returning usage.
If LiteLLM cannot price a response, the ledger records zero estimated cost for it;
zero does not mean the provider made no charge.

## Prompt controls

Operators own their prompts and extraction settings. Caller properties cannot contain
`input_template`, `input_json`, `input_context`, `input_context_field`, `input_field`,
`output_template`, `output_path`, `output_transformations`, `output_strip`,
`output_cast`, `service_prefix`, or `template_syntax`, including null or copied defaults.
Provider transport and routing controls remain reserved. Rejection precedes registry,
schema, client, cache, and provider work, including empty-input paths.

Prompts use one dollar-placeholder pass. Unknown names stay literal and `$$` escapes
a dollar. Rendering uses only the standard library; ops declares no direct Jinja2 dependency.
Jinja syntax and dollar tokens inside records, questions, schemas, context,
and model output remain data. The public `utils.safe_substitute` helper now uses
this same one-pass rule and preserves line endings. LLM message formatting normalizes
only trusted template text to LF and removes one final LF before substitution.

For a custom prompt, define a trusted operator subclass with its own
`DEFAULT_PROPERTIES`. An injected client supplies connection and generation settings;
the operator's prompt and extraction defaults take precedence, including masking an
inherited client `output_template`. Internal alternate prompts still take precedence.
Direct, trusted `LLMClient` construction remains available. SQL execution with a
prompt-customizing subclass is supported through the direct Python host API; the
CLI/MCP bound-executor path requires an exact built-in `NL2SQLOperator` or
`NL2SQLOutcomeOperator` instance.

## SQL execution

`nl2sql` generates `[[{"sql": "..."}]]` by default, using registry metadata for the
schema. `nl2sql@4.0.0` is active; earlier IDs resolve through `versioned_registry()`
or CLI `--catalog history` with current host-only restrictions. @3 and @4 share
one implementation. Retained IDs and result schemas do not restore caller-driven
execution. `execute_query` must be an actual boolean.
`validate_query_prefixes`, if supplied, must be an actual one-item list containing
ASCII `SELECT`, ignoring case without trimming. It cannot enable WITH, DDL, or writes.
The generated query must be a nonempty string starting with the SELECT token.

Schema generation uses registered entity and attribute names and declared types,
plus relation names and source/target endpoints (`source`, `target`, `source_entity`,
`target_entity`). The optional `foreign_keys_source_columns` and
`foreign_keys_target_columns` fields are copied only as validated string lists;
other shapes fail closed. Missing types are omitted. Row samples,
connection properties and arbitrary metadata are excluded. Registered schema may
be stale; run `sync_source` before generation because an unsynced source can return
an empty schema. Lookup failures are errors rather than an empty-schema fallback.

The public executor admits an exact `str` containing one SELECT statement and
rejects every unquoted INTO token before driver execution, including OUTFILE,
DUMPFILE, variables, subqueries and UNION branches. It conservatively rejects
executable or nested comments, MySQL `--` without following whitespace, `#`,
unquoted dollar/bracket syntax, backslash quoting, malformed quotes and NUL/VT/FF.
Ordinary quoted literals, doubled quotes/backticks and plain comments are supported.
Bare-CR line comments are refused for every protocol. This can refuse otherwise
valid dialect syntax. The underlying source may also refuse semicolons inside
literals. Numeric-looking identifiers may need quoting because dialects tokenize
them differently. Generation alone does not grant execution.

Execution requires a capability configured in trusted Python host code:

```python
from blue_data_ops.llm.sql_execution import ReadOnlySQLExecutor
from blue_data_ops.operators import NL2SQLOperator, OperatorRegistry

# data_registry already contains a supported SQL source for a pre-existing target.
executor = ReadOnlySQLExecutor(
    data_registry, frozenset({("approved", "analytics", "public")})
)
operator = NL2SQLOperator(read_only_executor=executor)
operators = OperatorRegistry()
operators.register(operator, version="2.0.0")
output, _, meta = operator.run(
    [[]],
    {"question": "Count orders", "source": "approved", "protocol": "sqlite",
     "database": "analytics", "collection": "public"},
    {"execute_query": True},
)
```

Use `PipelineExecutor(operators)` for direct pipeline execution with that registry. Rule planning
admits custom operators at retained `@2.0.0`. `OpenAIPlanGenerator` currently
requires a registry returned by the package's registry factories and that registry's
original built-in cards. It cannot plan this custom instance.
Direct pipeline execution can resolve a host-configured instance at any retained
version, including @4. The OpenAI planner demo therefore generates SQL only. Ordinary
`active_registry()` instances have no executor. Stock CLI/MCP requests cannot install
one. The CLI/MCP bound-executor path supports exact built-in `NL2SQLOperator`
and `NL2SQLOutcomeOperator` instances, including registered version/name aliases,
without deployment-registry injection. Other subclasses must use the direct Python host API. Caller presence of `read_only_executor` is always
denied; `data_registry`, `platform.name`, and `data_registry.name` are denied when
execution is requested, even if null or equal to the host configuration.

The adapter binds exact source/database/collection tuples and existing concrete
SQLiteDBSource, PostgresDBSource or MySQLDBSource objects; source subclasses and wrappers
are refused. DataRegistry subclasses are accepted through `isinstance`, while proxy or
wrapped registries are refused. Source replacement or an unsupported
guard is denied before schema or generation. It requires read-only support in the current blue-data SQL sources. Older dependencies without it can still generate SQL, but execution is refused.
Execution calls the captured source with `commit=False` and has no ordinary-registry
fallback. The shared query guard runs before the driver; the database guard adds read-only
access. Error messages exclude SQL and driver text.

Connections and cursors open before the guard is installed. SQLite path resolution
may create a directory; non-create connections refuse a missing database file.
Use constrained principals and pre-existing approved targets. Read-only SELECT is
not a sandbox for stored functions, privileged file/network access, or resource use.
Use a least-privilege principal without FILE or equivalent file/network privileges.
SELECT functions such as LOAD_FILE, SLEEP, lo_export and pg_read_file remain subject
to database grants and resource controls; this executor is not a general SQL sandbox.
Target collections constrain routing, not which tables generated SQL can read.

`nl2bn` continues to run Bayesian inference. Its legacy `execute_query` property is
ignored and does not provide an SQL execution control.

Consumers migrating to `nl2sql@4.0.0` must bind a `ReadOnlySQLExecutor`
in trusted host code and pass it to the public `NL2SQLOutcomeOperator` constructor.
Use the concrete registry and approved targets shown above. Caller registry
selectors and request or model scan addresses do not authorize execution.
Downstream adapters must adopt this construction in their own integration;
selecting a new card does not migrate an existing caller automatically.
For the @4 card, using the executor and registry above:

```python
from blue_data_ops.operators import NL2SQLOutcomeOperator

operator = NL2SQLOutcomeOperator(read_only_executor=executor)
operators.register(operator, version="4.0.0")
```

Reinstall any earlier 1.0.0 build of this package before selecting @4;
a package version range cannot distinguish builds with the same label.
