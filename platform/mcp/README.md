# Blue Data Operators MCP

This package exposes Blue Data Operators as MCP tools over the structured execution contract. Version 0.13.0 serves 32 primary tools and no refinement companions by default. The exact operator selection is the same 32-ID projection returned by core `active_registry()`.

The adapter pins `blue-data-ops==3.0.0`. Tool names remain logical operator names such as `select` and `avg`. Each tool's `_meta` carries its exact mixed-version operator ID.

## Install

For a source checkout, place `blue-data` and `blue-data-ops` under the same parent directory. From the `blue-data-ops` repository root, install the sibling dependency, core, and adapter:

```bash
python -m pip install ../blue-data/lib
python -m pip install "./lib[ml,vector,llm]"
python -m pip install ./platform/mcp
```

If your artifact index is configured separately:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==3.0.0" \
  "blue-data-ops-mcp==0.13.0"
```

`nl2llm`, `nl2sql`, `nl2bn`, and the `semantic_*` operators resolve a provider client when called. Supply credentials through the provider's environment variables. The `openai.model` property selects the model; its default is `gpt-4o`.

Read the adapter version from distribution metadata:

```python
from importlib.metadata import version

assert version("blue-data-ops-mcp") == "0.13.0"
```

## Embed or serve

`create_server()` returns a configured `FastMCP` server. This in-memory example lists and calls only `select@2.0.0`:

```python
import asyncio

from blue_data_ops_mcp import create_server
from mcp.shared.memory import create_connected_server_and_client_session


async def main() -> None:
    server = create_server(operator_ids=("select@2.0.0",))
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        listing = await client.list_tools()
        assert [tool.name for tool in listing.tools] == ["select"]

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
        assert result.structuredContent["output_data"] == [[{"name": "b", "score": 9}]]


asyncio.run(main())
```

To expose the server over stateful streamable HTTP, run it directly. Defaults bind to `127.0.0.1:8000/mcp`:

```python
from blue_data_ops_mcp import create_server

server = create_server()
server.run(transport="streamable-http")
```

`serve()` performs the same construction and starts streamable HTTP:

```bash
python -c 'from blue_data_ops_mcp import serve; serve()'
```

Pass `operator_ids` to either function to replace the default selection with an exact pinned subset. An empty tuple serves no tools. Without a caller-supplied registry, selections may contain supported retained v2/v3 built-ins. Every selected card must resolve exactly from the selected registry. Duplicate logical names fail instead of choosing one:

```python
from blue_data_ops_mcp import serve

serve(operator_ids=("select@2.0.0", "avg@3.0.0"))
```

A caller may pass `registry=` and select caller-created `@2.0.0` cards that resolve exactly from that registry. A custom card may reuse a removed logical name such as `multipart_query`, but it cannot shadow any of the 32 supported built-in logical names. Custom v1 and v3 cards are rejected. For example, after registering `echo@2.0.0` in `caller_registry`:

```python
from blue_data_ops_mcp import create_server

server = create_server(registry=caller_registry, operator_ids=("echo@2.0.0",))
```

An explicit `registry=` may also serve an exact supported raw package card: a retained `@2.0.0` card such as `default_registry(select="2.0.0")`, or an active `@3.0.0` card such as `default_registry(avg="3.0.0")`. This is observed adapter behavior, not an ordinary-selection promise. Raw cards have empty `tags` and `when_to_invoke`, so `_meta.tags` is empty and the tool description contains only the operator description. MCP accepts the card for explicit execution; acceptance does not grant ordinary or OpenAI planning authority and does not authorize a write. The caller and deployment host remain responsible for invocation authorization.

`V2_OPERATOR_IDS` remains available for callers that imported the old constant. `V2_OPERATOR_IDS` changed from 36 IDs to 32 and contains the retained v2 exact IDs; it is a compatibility tuple, not the default mixed-version selection.

```python
from blue_data_ops_mcp import ACTIVE_OPERATOR_IDS, V2_OPERATOR_IDS

assert len(ACTIVE_OPERATOR_IDS) == 32
assert len(V2_OPERATOR_IDS) == 32
```

Both server functions accept `host`, `port`, and `path`, with defaults `127.0.0.1`, `8000`, and `/mcp`. Review network exposure before changing the loopback host.

## List and call tools

Start the server in one process:

```bash
python -c 'from blue_data_ops_mcp import serve; serve()'
```

Then initialize an MCP session and call a tool:

```python
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    async with streamable_http_client("http://127.0.0.1:8000/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            listing = await client.list_tools()
            assert len(listing.tools) == 32

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

### Discover tools by tags

MCP has no server-side tag query. Call `list_tools()`, read the ordered tags from each tool's `_meta`, and filter them client-side. Built-in tag values are copied from the selected core operator cards; custom cards expose their caller-supplied tags verbatim. The six built-in axes describe the primary subject (`domain-*`), pipeline role (`flow-*`), consumed input (`accepts-*`), results or effects (`produces-*`), actions (`capability-*`), and operator-specific runtime requirements (`requires-*`). The example derives the available values, then performs exact AND matching with `issubset()`. The client owns any normalization or other matching rules.

<!-- blue-data-ops-mcp-test: tag-discovery -->
```python
import asyncio

from blue_data_ops_mcp import create_server


async def main() -> None:
    tools = await create_server().list_tools()
    available_tags = sorted({tag for tool in tools for tag in (tool.meta or {}).get("tags", [])})
    assert "capability-metadata-search" in available_tags

    wanted = {"domain-vector", "flow-transform"}
    matches = [
        tool.name for tool in tools if wanted.issubset(set((tool.meta or {}).get("tags", [])))
    ]
    assert matches == ["vector_embed", "vector_search"]


asyncio.run(main())
```

## Tool contract

Each tool is named for its logical operator. Its description combines the card's `when_to_invoke` guidance and description. MCP `_meta` carries the exact `operator_id`, version, and ordered discovery tags.

Every tool accepts the same open arguments:

- required `input_data`: a list of record groups, where each group is a list of record objects;
- optional `attributes`: an open object of operator arguments, defaulting to a fresh empty object;
- optional `properties`: an open object or `null` of execution settings, such as `execution.timeout_seconds`.

Known attributes carry descriptions. Optional attributes that materialize a default publish it; required attributes and unmaterialized optional values publish no default. Business validation belongs to canonical `run()`. An invalid attribute reaches operator validation and returns a recoverable error record.

### Structured results

Tools publish structured output. A successful `select` call returns:

```json
{
  "output_data": [[{"name": "b", "score": 9}]],
  "output_attributes": {},
  "exec_meta": {"is_empty": false, "errors": [], "logs": [], "traces": {}}
}
```

`exec_meta.errors` contains records with `category`, `code`, `operator_id`, `stage`, `message`, `retryable`, and `suggestion`. Read `structuredContent` as authoritative; `json.loads(result.content[0].text)` is the same object.

A call that passes the MCP container schema but fails operator validation is still a successful MCP result. Calling `select` without its required attributes returns an `INVALID_INPUT` record at the `VALIDATE` stage. Values are encoded with `default=str` for non-JSON leaves, while `NaN` and `Infinity` are rejected.

### How outcomes surface

- A recoverable, failed, timed-out, or successful-empty operator outcome has `isError` false. Details live in `exec_meta`.
- An unknown tool, malformed top-level arguments, or a projection or encoding failure has `isError` true and adds no operator error record.
- Malformed JSON-RPC and transport failures follow the MCP SDK.

The MCP initialization response's `serverInfo.version` is the MCP SDK version, not this package's version. The distribution version is `blue-data-ops-mcp 0.13.0`; each tool's operator version is in `_meta`.

## Migrating from 0.12.0

Version 0.13.0 moves the exact core pin from `blue-data-ops==2.10.0` to `==3.0.0`. The default catalog changes from 36 v2 primaries plus four refinement companions to the 32 mixed-version primaries in `ACTIVE_OPERATOR_IDS`.

The removed package tools are `multipart_query`, `nl2query_router`, `plan_discover`, and `query_breakdown`. The four `__refine` companions are also removed. They no longer resolve from a package registry, and there is no companion result envelope in 0.13.0. A caller-created v2 card that reuses one of these names runs the caller's implementation; it does not restore the removed package binding.

If a deployment still needs those package bindings, automatic refinement, or declarative plan expansion, keep a compatible core 2.x/MCP 0.x pair, such as core 2.10.0 with MCP 0.12.0. MCP 0.13.0 has no replacement companion path.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==3.0.0" \
  "blue-data-ops-mcp==0.13.0"
```

## Migrating from 0.11.0

`0.12.0` moves the exact core pin from `blue-data-ops==2.9.0` to `==2.10.0`. Core expands the outcome set available through explicit `@3.0.0` selection from three cards to 21. The MCP adapter continues to serve 36 `@2.0.0` primary tools and four refinement companions by default.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.10.0" \
  "blue-data-ops-mcp==0.12.0"
```

## Migrating from 0.9.0

`0.10.0` moves the exact core pin from `blue-data-ops==2.7.0` to `==2.8.0`. The core release deprecates the four plan-producing operators and the refinement seam, so this adapter annotates eight of its bindings. No tool is added, renamed, reordered, or removed, and no argument, result envelope, or error behavior changes.

Nothing has to change in a client to keep working. If you want to move off the deprecated tools before 3.0.0, read `_meta.deprecated` from `list_tools()` to find them:

```python
listing = await client.list_tools()
deprecated = [tool.name for tool in listing.tools if (tool.meta or {}).get("deprecated")]
```

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.8.0" \
  "blue-data-ops-mcp==0.10.0"
```

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
