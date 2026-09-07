# Blue Data Operators MCP

This package exposes Blue Data Operators as MCP tools over the v2 execution contract. The default server hosts 40 tools: the 36 `name@2.0.0` operators from `blue-data-ops==2.7.0`, followed by four `<name>__refine` companions for the operators that build plans.

The two version numbers differ on purpose. `2.7.0` is the core distribution this adapter pins; `@2.0.0` is the operator card version, which core 2.7.0 does not change. Version 0.9.0 changes only the core pin. Tool names, `_meta`, arguments, result envelopes, error behavior, and transport are unchanged from 0.8.0. Operator skill metadata and resources are not added to MCP descriptions, metadata, arguments, or results.

## Install

For a source checkout, place `blue-data` and `blue-data-ops` under the same parent directory. From the `blue-data-ops` repository root, install the sibling dependency, core, and adapter. The full default surface uses the core ML, vector, and LLM extras:

```bash
python -m pip install ../blue-data/lib
python -m pip install "./lib[ml,vector,llm]"
python -m pip install ./platform/mcp
```

If your artifact index is configured separately:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.7.0" \
  "blue-data-ops-mcp==0.9.0"
```

`nl2llm`, `nl2sql`, `nl2bn`, the `semantic_*` operators, and `query_breakdown` resolve a provider client at call time. Supply the provider credential through its environment variable. The `openai.model` property selects the model (default `gpt-4o`); the default OpenAI client reads `OPENAI_API_KEY` for authentication.

After installation, read the adapter version from distribution metadata:

```python
from importlib.metadata import version

assert version("blue-data-ops-mcp") == "0.9.0"
```

## Embed or serve

`create_server()` returns a configured `FastMCP` server. To initialize a client, list tools, and call `select` without opening a listener:

```python
import asyncio

from blue_data_ops_mcp import create_server
from mcp.shared.memory import create_connected_server_and_client_session


async def main() -> None:
    server = create_server(operator_ids=("select@2.0.0",))
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        listing = await client.list_tools()
        print([tool.name for tool in listing.tools])

        result = await client.call_tool(
            "select",
            {
                "input_data": [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]],
                "attributes": {
                    "operand_key": "score",
                    "operand": ">",
                    "operand_val": 5,
                },
            },
        )
        if result.isError:
            raise RuntimeError(result.content[0].text)
        print(result.structuredContent["output_data"])


asyncio.run(main())
```

To expose the server over stateful streamable HTTP, run it directly. The defaults bind to `127.0.0.1:8000/mcp`:

```python
from blue_data_ops_mcp import create_server

server = create_server()
server.run(transport="streamable-http")
```

`serve()` performs the same construction and starts streamable HTTP:

```bash
python -c 'from blue_data_ops_mcp import serve; serve()'
```

Pass `operator_ids` to either function to replace the default selection with an exact pinned subset. The list is a complete replacement, so an empty list serves nothing and a subset serves only what you name (plus a companion for each selected refinement operator):

```python
from blue_data_ops_mcp import serve

serve(operator_ids=("select@2.0.0", "avg@2.0.0"))
```

Every selected id must resolve to a `2.0.0` card. The default catalog is the version-aware registry, which also carries the `1.0.0` operators; the adapter serves the `2.0.0` snapshot only and rejects any `1.0.0` (or other non-`2.0.0`) selection. The committed default list is available before startup:

```python
from blue_data_ops_mcp import V2_OPERATOR_IDS

print("\n".join(V2_OPERATOR_IDS))
```

Both functions accept `host`, `port`, and `path` (defaults `127.0.0.1`, `8000`, `/mcp`). Review network exposure before changing the loopback host.

## List and call tools

Start the server in one process:

```bash
python -c 'from blue_data_ops_mcp import serve; serve()'
```

Then initialize an MCP session, list its tools, and call one:

```python
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    async with streamable_http_client(
        "http://127.0.0.1:8000/mcp"
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            listing = await client.list_tools()
            print([tool.name for tool in listing.tools])

            result = await client.call_tool(
                "select",
                {
                    "input_data": [[{"name": "a", "score": 3}, {"name": "b", "score": 9}]],
                    "attributes": {
                        "operand_key": "score",
                        "operand": ">",
                        "operand_val": 5,
                    },
                },
            )
            if result.isError:
                raise RuntimeError(result.content[0].text)
            print(result.structuredContent["output_data"])


asyncio.run(main())
```

With the default selection, `list_tools()` returns 40 stable definitions. A subset server started with `operator_ids=("select@2.0.0", "avg@2.0.0")` lists only `select` and `avg`. Selecting `multipart_query@2.0.0`, for example, also adds `multipart_query__refine`.

## Tool contract

Each primary tool is named for its operator. The description is the operator's `when_to_invoke` guidance followed by its card description; a companion is named `<operator>__refine` and prefixes a short refinement note. MCP `_meta` carries the pinned `operator_id`, its version, and the operator's ordered discovery tags.

Every tool accepts the same open arguments:

- required `input_data`: a list of record groups, where each group is a list of record objects;
- optional `attributes`: an open object of operator arguments, defaulting to a fresh empty object;
- optional `properties`: an open object or `null` of execution settings (for example `execution.timeout_seconds`).

Attribute values are open at the wire. Known attributes carry descriptions, and optional attributes that materialize a default publish it; the seven attributes the core leaves unmaterialized, and every required attribute, publish no default. Business validation belongs to the canonical `run()` and `refine()` methods, not the MCP boundary. An operator-invalid attribute reaches canonical validation and comes back as a recoverable error record, not a silent empty result.

### Structured results

Tools publish structured output. For the call above, `result.structuredContent` is exactly:

```json
{
  "output_data": [[{"name": "b", "score": 9}]],
  "output_attributes": {},
  "exec_meta": {"is_empty": false, "errors": [], "logs": [], "traces": {}}
}
```

A zero-plan companion result is exactly:

```json
{
  "plans": [],
  "exec_meta": {"is_empty": true, "errors": [], "logs": [], "traces": {}}
}
```

When plans are present, each item is one `DataPipeline.to_dict()` record. `exec_meta.errors` is a list of error records, each carrying `category`, `code`, `operator_id`, `stage`, `message`, `retryable`, and `suggestion`. Read `structuredContent` as authoritative and decode it once; `json.loads(result.content[0].text)` is the same object.

A call that passes the MCP container schema but fails operator validation remains a successful MCP tool result (`isError` is false). For example, calling `select` without its required attributes returns:

```json
{
  "output_data": [[]],
  "output_attributes": {},
  "exec_meta": {
    "is_empty": false,
    "errors": [{
      "category": "RECOVERABLE",
      "code": "INVALID_INPUT",
      "operator_id": "select@2.0.0",
      "stage": "VALIDATE",
      "message": "input validation failed",
      "retryable": false,
      "suggestion": "supply a supported operand and a nonnegative eps value"
    }],
    "logs": [],
    "traces": {}
  }
}
```

Values are serialized with `default=str` for leaves JSON does not represent natively. `NaN` and `Infinity` are rejected.

### How outcomes surface

- A canonical recoverable, failed, timeout, or successful-empty outcome is a successful tool result (`isError` false). The details live in `exec_meta`. A successful-empty result is `output_data` `[[]]` with `is_empty` true; a contained error is a record in `exec_meta.errors`.
- An unknown tool name, an argument-shape error (missing or malformed `input_data`, `attributes`, or `properties`), or a projection or encoding failure is a tool error (`isError` true) with no operator error record added.
- Malformed JSON-RPC and transport failures follow the MCP SDK's own behavior.

The MCP initialization response's `serverInfo.version` is the MCP SDK version, not this package's version. The distribution version is `blue-data-ops-mcp 0.9.0`; each tool's operator version is in its `_meta`.

## Refinement companions and plans

The four refinement operators (`multipart_query`, `nl2query_router`, `plan_discover`, `query_breakdown`) each expose two tools. Every primary runs its function body through `run()`. The `multipart_query`, `nl2query_router`, and `plan_discover` primary bodies return a successful-empty result. The `query_breakdown` primary calls the configured LLM provider. All four `__refine` companions run normalized `refine()` and return serialized candidate plans.

Pass one of these mappings as the `arguments` to `client.call_tool()`:

```python
multipart_arguments = {
    "input_data": [[{
        "description": "find orders",
        "sql": "select * from orders",
        "table": "orders",
        "columns": [{"name": "total", "type": "float"}],
        "dependency": [],
        "generality": 0,
    }]],
    "attributes": {},
}

router_arguments = {
    "input_data": [[{
        "name": "warehouse",
        "type": "source",
        "scope": "/source/warehouse",
        "properties": {
            "connection": {"protocol": "sqlite"},
            "owner": "warehouse",
        },
    }]],
    "attributes": {
        "search_query": "find orders",
        "columns": [{"name": "total"}],
        "execute_query": False,
        "protocol": "sqlite",
    },
}

discover_arguments = {
    "input_data": [[]],
    "attributes": {"task": "select", "data": "rows", "approximate": True},
}

breakdown_arguments = {
    "input_data": [[]],
    "attributes": {"query": "compare monthly order totals"},
}
```

Use these with `multipart_query__refine`, `nl2query_router__refine`, `plan_discover__refine`, and `query_breakdown__refine`, respectively. The router reads source records from the first input group. `query_breakdown__refine` calls the configured LLM provider; the other three shapes above are credential-free.

An MCP refinement result is a serialized plan, not an execution. `DataPipeline` records the operators, their pinned ids, and their edges; it has no execution method. A caller with the core `blue-data-ops` package installed can load a chosen materialized plan with `DataPipeline.from_dict()` and execute it with `PipelineExecutor` and a registry that resolves its pinned ids. The MCP server itself does not run returned plans.

## Migrating from 0.8.0

`0.9.0` moves the exact core pin from `blue-data-ops==2.6.0` to `==2.7.0`. The core release adds explicit operator-skill availability and resource-metadata inspection before a caller loads text. The adapter still exposes the same 40 tools and does not load or transmit skill metadata or resources.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.7.0" \
  "blue-data-ops-mcp==0.9.0"
```

## Migrating from 0.7.0

`0.8.0` moves the exact core pin from `blue-data-ops==2.5.0` to `==2.6.0`. The core release adds caller-supplied embedding discovery and optional local-planner integration. The adapter still exposes the same 40 tools and does not load or transmit embedding-discovery inputs.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.6.0" \
  "blue-data-ops-mcp==0.8.0"
```

## Migrating from 0.6.0

`0.7.0` moves the exact core pin from `blue-data-ops==2.4.0` to `==2.5.0`. The core release adds resource packages for every active execution operator. MCP does not load or disclose those resources, so its 40-tool protocol surface is unchanged.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.5.0" \
  "blue-data-ops-mcp==0.7.0"
```

## Migrating from 0.5.0

`0.6.0` moves the core pin from `blue-data-ops==2.3.0` to `==2.4.0`. Tool names, `_meta`, the top-level `input_data` / `attributes` / `properties` arguments, the structured result envelope, error surfacing, and the transport are unchanged, and every operator id is still `@2.0.0`. The `classify` description now names `DecisionTreeClassifier`, `KNeighborsClassifier`, and `MultinomialNB`. Its `attributes` schema adds `n_neighbors`, `weights`, `alpha`, and `fit_prior`; the descriptions for `criterion`, `splitter`, `max_depth`, `min_samples_split`, `min_samples_leaf`, and `random_state` now identify them as `decision_tree` settings. The `properties["algorithm"]` values `knn` and `multinomial_nb` now produce predictions instead of returning the input unchanged.

Update both distributions together. The exact pin means one environment holds one pair, so a `0.5.0` adapter cannot run against core `2.4.0` and `0.6.0` cannot run against core `2.3.0`:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.4.0" \
  "blue-data-ops-mcp==0.6.0"
```

Core `2.4.0` adds eight exact-version operator resource packages. They do not change this adapter's surface: skill resources are not added to tool descriptions, `_meta`, arguments, or results.

## Migrating from 0.1.0

`blue-data-ops-mcp 0.1.0` (paired with `blue-data-ops 0.2.0`) dispatched to the raw operator function and returned a single JSON text block. `0.2.0` dispatches to the canonical `run()` / `refine()` methods and returns the structured envelope above. A `0.1.0` client updating to `0.2.0` should:

- read `structuredContent` and take `output_data` (a primary's result) or `plans` (a companion's) instead of decoding the bare body;
- treat canonical error records in `exec_meta.errors` as data rather than expecting an empty result;
- expect the four `__refine` companions and the `2.0.0` operator versions in `_meta`.

Tool names, the `input_data` / `attributes` / `properties` arguments, and the streamable-HTTP transport are unchanged. The two distributions pin different core versions, so a single environment serves either the `0.1.0` (`1.0.0` operators) or the `0.2.0` (`2.0.0` operators) contract, not both.
