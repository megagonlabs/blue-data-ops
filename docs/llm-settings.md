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

## CLI

For one direct call, use `--model` and, if supported, `--reasoning-effort`:

```bash
blue-ops operator run nl2llm@3.0.0 \
  --attribute 'query=Return one example product.' \
  --model gpt-5-mini --reasoning-effort low
```

For a stored pipeline, the same flags on `pipeline run` supply invocation defaults. With
`llm-example` and `llm-input.json` from the [CLI guide](../platform/ops-cli/README.md#pipelines):

```bash
blue-ops pipeline run llm-example --input-file llm-input.json \
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
[MCP guide](../platform/ops-mcp/README.md#list-and-call-tools) for its full request. The MCP
adapter exposes individual operator tools; it has no pipeline-run tool or stored-pipeline
settings layer.

## Precedence and compatibility

For `model`, `reasoning_effort`, `stream`, `max_tokens`, and `temperature`, whether
supplied as `llm.*` or provider-prefixed keys, the effective order is:

1. Explicit operator-node setting
2. Stored pipeline setting
3. Current library or CLI invocation setting
4. Operator default

A direct operator call has only the current-call setting and operator default. MCP tool
calls are direct calls. Other execution properties, including `llm.cache` and
`llm.max_parallel`, retain their existing order: node, invocation, stored pipeline,
default. Deployment provider routing and its model allowlist still constrain the
selected model.

Omit `llm.reasoning_effort` for a model without that option. At an operator node, use
`None` in Python or `null` in pipeline JSON to clear an inherited effort. An explicit
effort that the provider rejects fails once with an actionable operator error; the call
is not silently retried without effort. `None` and `null` are not sent to the provider.
