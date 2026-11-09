# Blue Data Operators MCP

This package exposes Blue Data Operators as MCP tools over the structured execution contract. It serves 33 primary tools and no refinement companions by default. The exact operator selection is the same 33-ID projection returned by core `active_registry()`.

The adapter pins `blue-data-ops==1.0.0`. Every tool name is `ops_` followed by the core operator's logical name, so the `select` operator is served as `ops_select` and `avg` as `ops_avg`. Each tool's `_meta` carries its exact mixed-version operator ID, which stays unprefixed because it names a core registration rather than a wire surface.

## Install

For a source checkout, place `blue-data` and `blue-data-ops` under the same parent directory. From the `blue-data-ops` repository root, create and activate either a standard virtual environment:

```bash
python3.12 -m venv platform/ops-mcp/.venv
source platform/ops-mcp/.venv/bin/activate
```

or a Conda environment:

```bash
conda create --name blue-data-ops-mcp python=3.12 pip
conda activate blue-data-ops-mcp
```

If Conda reports that activation is unavailable, run `conda init zsh` once (replace `zsh` with your shell), reopen the shell, and return to the repository root.

With either environment active, install the sibling dependency, core, and adapter:

```bash
python -m pip install "../blue-data/lib[server]" "blue-data[server]>=1.0.0"
python -m pip install "./lib[ml,vector,llm]" "blue-data-ops==1.0.0"
python -m pip install ./platform/ops-mcp "blue-data-ops-mcp==1.0.0"
```

`platform/ops-mcp/scripts/install.sh` resolves `blue-data` from its checkout first, then installs the core, its ML, vector, and LLM extras, and the MCP adapter. It also installs the core and adapter development extras; use the three commands above for a runtime-only install.

Installation, runtime use, and pytest work in either environment. This package's Pyright configuration still looks for `.venv` in `platform/ops-mcp`, so use the standard virtual-environment path when running the documented Pyright gate.

If your artifact index is configured separately:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==1.0.0" \
  "blue-data-ops-mcp==1.0.0"
```

`nl2llm`, `nl2sql`, `nl2bn`, and the `semantic_*` operators resolve a provider
client when called. Core reads `BLUE_DATA_LLM_PROVIDER` and
`BLUE_DATA_LLM_ALLOWED_MODELS` from the MCP server's environment. The first
defaults to `openai`; the second, when set, limits the model names tool callers
can select. Put the provider credential in the server's environment too. The
default OpenAI deployment reads `OPENAI_API_KEY`; other providers use their
own credential variables. A tool call may choose an allowed model with
`llm.model` or `openai.model`, while
the server controls the provider. Provider-qualified model names such as
`vertex_ai/gemini-2.5-pro` are refused, and tools never accept credentials as
arguments. The [model settings guide](../../docs/llm-settings.md) includes a
provider setup example.

Read the adapter version from distribution metadata:

```python
from importlib.metadata import version

assert version("blue-data-ops-mcp") == "1.0.0"
```

The same string is `blue_data_ops_mcp.__version__`, and the server reports it as `serverInfo.version` during the MCP handshake.

## Run the server

The package installs one console command, which serves the default selection over streamable HTTP on the loopback defaults:

```bash
blue-data-ops-mcp
```

A client reaches it at the streamable-HTTP URL rather than by spawning a process. Point one at it the usual way:

```json
{
  "mcpServers": {
    "blue-data-ops": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8010/mcp"
    }
  }
}
```

The URL is the default bind; the client must also send the configured API key. Update the URL when the host, port or MCP path changes.
The console command does not accept `--help`, `--version`, `--host`, or `--port`. Passing them starts the server with its environment settings instead of showing help or changing the bind address. To use another loopback port, set the port variable and use `http://127.0.0.1:8765/mcp` in the client:

```bash
BLUE_DATA_OPS_MCP_PORT=8765 blue-data-ops-mcp
```

The Python alternative is `serve(port=8765)`; explicit arguments take precedence over environment settings.

### Transport

This server speaks streamable HTTP over a stateful session. The rest of the Blue Data family speaks stdio, and this server is the exception.

Long CPU- and provider-bound calls run on worker threads, keeping the event loop responsive while multiple calls remain in flight. Stateful HTTP sessions do not by themselves cancel product work. With the tested Python MCP 1.30.0, cancelling the local awaiter, using `asyncio.wait_for()`, or reaching the SDK read timeout does not send `notifications/cancelled`; the request can still run. An explicit notification received after the handler enters `DeploymentRegistry.run()` can cancel its wait. An immediate notification sent before the handler starts can be lost. A running worker continues. A client-spawned stdio process would tie the server lifetime to one client and would not preserve the current cross-session concurrency model. Changing to stdio would be a breaking transport change.

### HTTP authentication and bind settings

HTTP requires `blue-data[server]>=1.0.0`. A missing helper or FastAPI installation fails
with an installation error; use the compatible source's `[server]` extra or the configured
index. The same shared guards protect streamable HTTP and SSE, including custom routes,
unknown paths, `/health`, and both SSE endpoints. There are no public path exemptions.
Websocket requests are closed with code 1008 before acceptance.

Set `BLUE_DATA_OPS_MCP_KEY` in the server environment and configure the client to send its
value in `X-API-Key` or `Authorization: Bearer`. Keep values in environment/secret storage.
A Python client can use `httpx.AsyncClient(headers={"X-API-Key": os.environ["BLUE_DATA_OPS_MCP_KEY"]})`
and pass it as `http_client` to `streamable_http_client`. Client configuration formats differ;
the URL example above also requires authentication configured through that client's header support.

| Variable | Default | Meaning |
|---|---|---|
| `BLUE_DATA_OPS_MCP_HOST` | `127.0.0.1` | Built-in listener host |
| `BLUE_DATA_OPS_MCP_PORT` | `8010` | Built-in listener port |
| `BLUE_DATA_OPS_MCP_KEY` | unset | Required key; unset denies HTTP by default |
| `BLUE_DATA_OPS_MCP_AUTH_DISABLED` | unset | Explicit no-key opt-out: `1`, `true`, or `yes`, ignoring case |

`create_server(host=..., port=...)` and `serve(...)` override the environment per field.
Omission (`None`) selects the environment/default. Hosts are stripped and must be nonempty;
ports must be integers 1–65535, with booleans refused as Python arguments. Environment port
text uses Python `int()` syntax, including whitespace, underscores, signs and Unicode decimal
digits; the resulting range is still enforced. Invalid effective settings fail before startup.
An explicit port overrides even invalid environment port text. Recreate the server to change
its host: editing `server.settings.host` is refused because SDK rebinding settings are fixed
at construction. An edited port is validated again by each HTTP app builder.

Authentication is checked on every request. A configured key wins even when the disable flag
is set. After authentication, the shared CSRF guard refuses form, multipart and text/plain
content types on POST, PUT, PATCH and DELETE, including case/parameters. JSON and bodyless
requests proceed to SDK protocol validation. This content-type check is not a general browser
isolation policy or a complete JSON validator. In-memory and stdio calls need no HTTP key.

The SDK automatically enables DNS-rebinding Host/Origin checks only for the exact construction
hosts `127.0.0.1`, `localhost`, and `::1`. Other addresses, including other loopback spellings,
have no automatic SDK protection. Deliberate non-loopback binding with the shared no-key
opt-out remains allowed and warns: reachable callers can run tools with the deployment's
provider configuration and incur costs. A configured key suppresses that unauthenticated
warning. Later environment changes can change authentication; the warning is not enforcement.
Restrict network access and configure TLS/reverse-proxy policy for external deployment.

### Embedding guarded HTTP apps

Both `server.streamable_http_app()` and `server.sse_app(mount_path=None)` return guarded
Starlette apps. The inherited `run(transport="streamable-http")`, `run(transport="sse")`,
`run_streamable_http_async()` and `run_sse_async()` use those builders too. The console
command and `serve()` keep stateful streamable HTTP at `/mcp`; SSE uses `/sse` and `/messages/`.
The inherited stdio runner remains available to Python hosts.

Mount only the guarded builder app. Private SDK handles such as
`server.session_manager.handle_request` and `server._mcp_server` are trusted host internals
and bypass this boundary. Parent FastAPI dependencies do not secure an MCP mount.
Starlette does not start mounted child lifespans; a streamable HTTP host must run the child's
session manager exactly once:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from blue_data_ops_mcp import create_server

server = create_server()
child = server.streamable_http_app()


@asynccontextmanager
async def lifespan(app):
    async with server.session_manager.run():
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/ops", child)  # MCP is /ops/mcp; HTTP authentication still applies.
```

Direct SDK app lifespans are preserved. Repeated builder calls do not stack guards, but the tested MCP
1.30.0 session managers cannot be restarted: use a fresh server for each independent lifespan.
The outer ASGI listener controls its own bind and exposure; the child cannot infer that interface.
A default loopback child's SDK Host allow-list rejects non-loopback Host headers even when the
outer listener is external. Choose the construction host and proxy headers for the intended
exposure, and review the actual `server.settings.transport_security` before deploying.

### Deployment data registry

`create_server(data_registry=...)` and `serve(data_registry=...)` accept a host-owned `RegistrySeam` or raw `DataRegistry`, including an empty one. This is separate from `registry=`, which selects operator implementations. With `data_registry=None`, the first registry-backed call resolves environment configuration once for that server. Caller `data_registry`, `platform.name` and `data_registry.name` values cannot choose or replace the deployment registry. Untagged tools do not initialize it. Ordinary Python `resolve_registry()` keeps its existing injected-object, explicit-provider and cached name-pair behavior.

Set `BLUE_DATA_REGISTRY_STORE` to `memory`, `file` or `redis` (case-insensitive, with no surrounding whitespace), or set `BLUE_DATA_SOURCES_CONFIG` to a readable JSON file containing a `sources` list of objects. An empty list is valid. An explicit store selector permits an empty registry. A missing, non-file, unreadable or malformed source file fails before construction; an unsupported store fails too. Blank values are absent. Other model, search, vector, registry-file or Redis settings alone do not configure MCP. With neither selector nor source file, registry calls return an owned `EXECUTION_FAILED` record; they never allocate a fallback registry from caller names. Missing and failed initialization are cached until a new server is created.

The shared builder uses blue-data's store, enricher, hybrid-search, vector-dimension and source-loader helpers. Selecting `file` permits writes at `BLUE_DATA_REGISTRY_FILE` (default `blue_data_store.json`, relative to the process directory). Selecting `redis` uses its configured endpoint (default local Redis). A sources file without a store selector uses memory. Source loading can connect eagerly, enrich and sync metadata; it does not add embedding/vector builders. After a failed load or sync, `blue-data` 1.0 can retain unavailable sources or partially synced metadata. Successful initialization does not establish source health. Only the `blue_data.config` logger's records from the building thread are suppressed in favor of an owned summary; other dependency loggers are outside that filter.

Registry calls enter an async queue before executor work is scheduled. They serialize within one server. When an explicit `notifications/cancelled` reaches a handler after it enters `DeploymentRegistry.run()`, a call still waiting for admission is removed from the queue and does not execute. Local task cancellation and client-side timeouts in the tested Python MCP 1.30.0 do not send that notification. An explicit notification sent immediately can arrive before the handler starts and be lost, so the request may execute later. Cancelling a handler after its worker starts leaves admission held until the worker finishes. Initial construction has no deadline: `execution.timeout_seconds` bounds only the later operator wait. Configure backend/provider connection timeouts separately. A hung build or an operator without a deadline can stall that server's registry lane indefinitely. An `OPERATOR_TIMEOUT` returns to the caller at once, but the timed-out body keeps this server's registry lane until the worker finishes. Calls already queued and new calls wait for it and then run normally, with no restart. Active or timed-out work may finish and change the backend. A code 0 `Request cancelled` response acknowledges cancellation handling; it does not prove that the operator or backend had no effects. There is no atomic rollback or no-effects guarantee, and cancellation does not terminate a worker. There is no automatic retry. Check backend effects before retrying a cancelled or timed-out write. A body that never finishes keeps the lane. Late non-daemon threads can delay process exit. Untagged calls and other servers continue. Injecting one registry into multiple servers provides no cross-server serialization.

`ops_create_database`, `ops_create_table` and `ops_insert_table` now reach deployment sources and can persist writes, including partial writes before a contained error or timeout. Check backend effects before restarting. Stock NL2SQL tools have no executor and deny execution before registry construction. A host-configured exact built-in `NL2SQLOperator` or `NL2SQLOutcomeOperator` instance, including registered version/name aliases, can use its bound read-only capability; that path builds no ordinary deployment registry and injects no registry/naming selectors. Other subclasses, including those that customize prompts, require the direct Python host API for SQL execution.

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
        assert [tool.name for tool in listing.tools] == ["ops_select"]

        result = await client.call_tool(
            "ops_select",
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

To expose the server over stateful streamable HTTP from your own process, run it directly. Defaults bind to `127.0.0.1:8010/mcp`:

```python
from blue_data_ops_mcp import create_server

server = create_server()
server.run(transport="streamable-http")
```

`serve()` performs the same construction and starts streamable HTTP. `main()`, which the console command calls, invokes `serve()` without explicit bind arguments, so environment settings apply before the built-in loopback defaults:

```python
from blue_data_ops_mcp import serve

serve()
```

Pass `operator_ids` to either function to replace the default selection with an exact pinned subset. An empty tuple serves no tools. Without a caller-supplied registry, selections may contain supported retained v2/v3 built-ins. Every selected card must resolve exactly from the selected registry. Duplicate logical names fail instead of choosing one:

```python
from blue_data_ops_mcp import serve

serve(operator_ids=("select@2.0.0", "avg@3.0.0"))
```

A caller may pass `registry=` and select caller-created `@2.0.0` cards that resolve exactly from that registry. A custom card may reuse a removed logical name such as `multipart_query`, but it cannot shadow any of the 33 supported built-in logical names. Custom v1 and v3 cards are rejected. For example, after registering `echo@2.0.0` in `caller_registry`:

```python
from blue_data_ops_mcp import create_server

server = create_server(registry=caller_registry, operator_ids=("echo@2.0.0",))
```

A caller-registered operator is served under the same prefix as the built-ins, so `echo@2.0.0` becomes `ops_echo`.

With an explicit `registry=`, the server can expose supported raw package cards, including retained `@2.0.0` cards and active `@3.0.0` cards. Raw cards have empty `tags` and `when_to_invoke`, so their tool metadata is correspondingly limited. Serving a raw card does not change planner eligibility and does not authorize a write; the deployment host remains responsible for access control on write-capable tools.

`V2_OPERATOR_IDS` remains available for callers that imported the old constant. It contains the 33 retained v2 exact IDs; it is a compatibility tuple, not the default mixed-version selection.

```python
from blue_data_ops_mcp import ACTIVE_OPERATOR_IDS, V2_OPERATOR_IDS

assert len(ACTIVE_OPERATOR_IDS) == 33
assert len(V2_OPERATOR_IDS) == 33
```

## List and call tools

Start the server in one process:

```bash
blue-data-ops-mcp
```

Then initialize an MCP session and call a tool:

```python
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    async with (
        httpx.AsyncClient(
            headers={"X-API-Key": os.environ["BLUE_DATA_OPS_MCP_KEY"]}
        ) as http_client,
        streamable_http_client("http://127.0.0.1:8010/mcp", http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ),
    ):
        async with ClientSession(read_stream, write_stream) as client:
            await client.initialize()
            listing = await client.list_tools()
            assert len(listing.tools) == 33

            result = await client.call_tool(
                "ops_select",
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
    assert matches == ["ops_vector_embed", "ops_vector_search"]


asyncio.run(main())
```

## Tool contract

Each tool is named `ops_` plus the core operator's logical name, verbatim: `ops_select`, `ops_create_table`, `ops_vector_search`, `ops_nl2sql`. A client holds one flat tool namespace across the servers it has loaded, so the prefix keeps these names from colliding with other servers' tools.

A tool's description combines the card's `when_to_invoke` guidance and description. MCP `_meta` carries the exact `operator_id`, version, and ordered discovery tags.

Every tool accepts the same three open arguments:

- required `input_data`: a list of record groups, where each group is a list of record objects;
- optional `attributes`: an open object of operator arguments, defaulting to a fresh empty object;
- optional `properties`: an open object or `null` carrying execution and backend settings. The recognized keys are `execution.timeout_seconds`; `algorithm`, which selects the estimator for `ops_classify`, `ops_cluster`, and `ops_sklearn_estimator` and without which `ops_sklearn_estimator` does not run at all; the deployment registry is configured by the host, while caller registry and naming selectors are discarded for ordinary registry calls and rejected for SQL execution; and the two provider namespaces, `openai.*` and `llm.*`, both closed. `llm.*` takes `model`, `stream`, `max_tokens`, `temperature`, `reasoning_effort`, `cache`, `cache_dir`, `max_parallel` and `rate_limit`. `openai.*` takes the generation parameters of the provider call and nothing else. Which provider answers, at which endpoint, in which project, tenant or region, and under which credential are the deployment's to set, from its own environment; a service-prefixed property naming any of them is refused with `reserved_field` rather than quietly dropped, because silently dropping it could route the request to a different provider without telling the caller.

`reserved_field` is the internal LLM error code for forbidden service-prefixed properties, including routing, credentials, and response-mocking settings. Forbidden `llm.*` settings instead produce `bad_override`. Both refusals happen before any provider request. The tool returns a non-retryable `EXECUTION_FAILED` record with a safe message and guidance to remove the forbidden property or use a documented setting.

Use the neutral property names when selecting a model or effort for one tool call. These are the
arguments objects for `ops_nl2llm` and `ops_semantic_filter`:

<!-- blue-data-ops-mcp-test: llm-nl2llm-call -->
```json
{
  "input_data": [[]],
  "attributes": {"query": "Return three product categories as JSON objects."},
  "properties": {"llm.model": "gpt-5-mini", "llm.reasoning_effort": "low"}
}
```

<!-- blue-data-ops-mcp-test: llm-semantic-filter-call -->
```json
{
  "input_data": [[{"name": "alpha", "summary": "quiet workspace"}]],
  "attributes": {"filter_conditions": {"summary": "suited to focused work"}},
  "properties": {"llm.model": "gpt-5-mini", "llm.reasoning_effort": "low"}
}
```

Omit `llm.reasoning_effort` when the selected model does not offer it. A `null` value is treated as
absent rather than sent to the provider. An explicit unsupported setting produces a non-retryable
operator error instead of being removed and retried. The caller can then choose a compatible model
or send the call again without that setting. Deployment routing and the model allowlist still apply;
tool properties cannot choose a provider or credential.

See [Choosing a model for an LLM operator](../../docs/llm-settings.md) for the same settings
through Python and CLI, plus an offline precedence example.

Supply the registry when constructing the server:

<!-- blue-data-ops-mcp-test: registry-injection -->
```python
from blue_data.registry.data_registry import DataRegistry
from blue_data_ops.data import RegistrySeam, resolve_registry
from blue_data_ops_mcp import create_server

seam = RegistrySeam(DataRegistry(name="my-registry", rebuild=True))
server = create_server(data_registry=seam, operator_ids=("data_discover@2.0.0",))
assert server is not None
assert resolve_registry({"data_registry": seam}) is seam
```

Each published attribute carries its description, its JSON Schema `type` where core's declared type has a faithful one, and an `enum` where core's own validator rejects every value outside a fixed set. Two attributes publish no type because core resolves their declared type to `Any` and would accept anything: `ops_select`'s `operand_val` and `ops_semantic_filter`'s `return_idx`. An attribute core declares required appears in the `attributes` object's `required` list. Optional attributes that materialize a default publish it; required attributes and unmaterialized optional values publish no default.

An enum is published only where core enforces it, never on the strength of a description. Several attributes name their permitted values in prose and still accept others — `ops_nl2sql`'s `protocol`, `ops_nl2bn`'s `protocol_variant`, `ops_semantic_transform`'s `strategy`, and the scikit-learn pass-through settings on `ops_classify` and `ops_cluster` — and those stay open here so the schema does not refuse a call the operator would run.
`ops_select.operand` also stays open: the core accepts an empty string and returns no matches, while its description names the six comparison operators callers normally use.

Business validation belongs to canonical `run()`. The published schema advertises the operator's contract; it is not a second enforcement point in front of it. An attribute that violates the schema still reaches operator validation and comes back as a recoverable error record rather than a protocol error.

### Default tool inventory

The 33 tools `create_server()` registers without an `operator_ids` argument, derived from `ACTIVE_OPERATOR_IDS`. Each row's operator ID is what that tool's `_meta.operator_id` carries, and it is the unprefixed exact operator ID (for example `select@2.0.0`). Only the `domain-*` and `capability-*` tags are shown; `_meta.tags` carries all six axes in canonical order, and [`lib/OPERATORS.md`](../../lib/OPERATORS.md) has each operator's full card.

| Tool | Operator ID | Domain tag | Capability tags |
|---|---|---|---|
| `ops_argmax` | `argmax@2.0.0` | `domain-arithmetic` | `capability-extrema`, `capability-record-selection` |
| `ops_argmin` | `argmin@2.0.0` | `domain-arithmetic` | `capability-extrema`, `capability-record-selection` |
| `ops_avg` | `avg@3.0.0` | `domain-arithmetic` | `capability-average`, `capability-reduction` |
| `ops_classify` | `classify@3.0.0` | `domain-ml` | `capability-classification` |
| `ops_cluster` | `cluster@3.0.0` | `domain-ml` | `capability-clustering` |
| `ops_create_database` | `create_database@2.0.0` | `domain-relational` | `capability-create-database` |
| `ops_create_table` | `create_table@2.0.0` | `domain-relational` | `capability-create-table` |
| `ops_data_discover` | `data_discover@2.0.0` | `domain-plan` | `capability-discovery`, `capability-metadata-search` |
| `ops_delete` | `delete@2.0.0` | `domain-relational` | `capability-delete` |
| `ops_insert` | `insert@3.0.0` | `domain-relational` | `capability-insert` |
| `ops_insert_table` | `insert_table@3.0.0` | `domain-relational` | `capability-persist` |
| `ops_intersect` | `intersect@3.0.0` | `domain-set` | `capability-intersection` |
| `ops_join` | `join@3.0.0` | `domain-relational` | `capability-join` |
| `ops_max` | `max@3.0.0` | `domain-arithmetic` | `capability-extrema`, `capability-reduction` |
| `ops_min` | `min@3.0.0` | `domain-arithmetic` | `capability-extrema`, `capability-reduction` |
| `ops_nl2bn` | `nl2bn@3.0.0` | `domain-query-compound` | `capability-bayesian-query`, `capability-query-execution`, `capability-query-generation` |
| `ops_nl2llm` | `nl2llm@3.0.0` | `domain-query-compound` | `capability-generation` |
| `ops_nl2sql` | `nl2sql@4.0.0` | `domain-query-compound` | `capability-query-execution`, `capability-query-generation`, `capability-sql` |
| `ops_normalize_text` | `normalize_text@2.0.0` | `domain-text` | `capability-normalization` |
| `ops_project` | `project@3.0.0` | `domain-relational` | `capability-projection` |
| `ops_segment_text` | `segment_text@2.0.0` | `domain-text` | `capability-segmentation` |
| `ops_select` | `select@2.0.0` | `domain-relational` | `capability-filter` |
| `ops_semantic_extract` | `semantic_extract@3.0.0` | `domain-semantic` | `capability-extraction` |
| `ops_semantic_filter` | `semantic_filter@3.0.0` | `domain-semantic` | `capability-filter` |
| `ops_semantic_join` | `semantic_join@3.0.0` | `domain-semantic` | `capability-embedding-filter`, `capability-join` |
| `ops_semantic_project` | `semantic_project@3.0.0` | `domain-semantic` | `capability-projection` |
| `ops_semantic_transform` | `semantic_transform@3.0.0` | `domain-semantic` | `capability-transformation` |
| `ops_sklearn_estimator` | `sklearn_estimator@2.0.0` | `domain-ml` | `capability-classification`, `capability-clustering`, `capability-transformation` |
| `ops_sum` | `sum@2.0.0` | `domain-arithmetic` | `capability-reduction`, `capability-sum` |
| `ops_union` | `union@2.0.0` | `domain-set` | `capability-union` |
| `ops_vector_embed` | `vector_embed@3.0.0` | `domain-vector` | `capability-embedding` |
| `ops_vector_search` | `vector_search@3.0.0` | `domain-vector` | `capability-search` |
| `ops_vector_similarity` | `vector_similarity@3.0.0` | `domain-vector` | `capability-similarity` |

A logical name appears at most once. A selection that would serve two versions of one name fails at construction rather than picking one.

### Structured results

Tools publish structured output. A successful `ops_select` call returns:

```json
{
  "output_data": [[{"name": "b", "score": 9}]],
  "output_attributes": {},
  "exec_meta": {"is_empty": false, "errors": [], "logs": [], "traces": {}}
}
```

`exec_meta.errors` contains records with `category`, `code`, `operator_id`, `stage`, `message`, `retryable`, and `suggestion`. Read `structuredContent` as authoritative; `json.loads(result.content[0].text)` is the same object.

A call that passes the MCP container schema but fails operator validation is still a successful MCP result. Calling `ops_select` without its required attributes returns an `INVALID_INPUT` record at the `VALIDATE` stage. Values are encoded with `default=str` for non-JSON leaves, while `NaN` and `Infinity` are rejected.

### How outcomes surface

- A recoverable, failed, timed-out, or successful-empty operator outcome has `isError` false. Details live in `exec_meta`.
- An unknown tool, malformed top-level arguments, or a projection or encoding failure has `isError` true and adds no operator error record.
- Malformed JSON-RPC and transport failures follow the MCP SDK.

The MCP initialization response reports this package's own version: `serverInfo.version` is `1.0.0`, matching `blue-data-ops-mcp` on the index. Each tool's operator version is in `_meta` and moves independently of it.

### Server scope

| Surface | Availability |
|---|---|
| MCP resources | None. Operator resources remain available through `OperatorSkillLoader` in core. |
| Output formatting | Tool results use the MCP JSON envelope. Table and natural-language rendering are CLI features. |
| Pipeline execution | Available through the core library, not as an MCP tool. The server exposes one tool per operator. |
| Registry management | The server freezes `operator_ids` at construction and exposes no registry-mutation or registry-discovery tools. |

## Tests

Install this package with its `dev` extra, then run the adapter tests from `platform/ops-mcp/`:

```bash
python -m pytest tests
```

The suite covers registration, tool schemas, invocation results, and the streamable-HTTP protocol.
It runs against the sibling core source tree.

## Migrating from 0.13.0

`1.0.0` renames every tool. The 33 names gain an `ops_` prefix, so `select` becomes `ops_select` and `create_database` becomes `ops_create_database`. **Every existing client call site changes.** A client holds one flat tool namespace across the servers it has loaded, and `create_database` was already served with a different meaning by `blue-data-user-source`; nothing in this catalog was prefixed, and half of it is a bare verb. Nothing else about a tool moves: `_meta.operator_id` still carries the unprefixed exact operator ID (for example `select@2.0.0`), the arguments are the same three containers, and the result envelope is unchanged.

The published input schema now says what core already enforced. Each attribute carries its JSON Schema `type`, an attribute core declares required appears in the `attributes` object's `required` list — 46 of them, across 27 tools — and 17 attributes whose values core's validator closes carry an `enum`. `input_data`, `attributes`, and `properties` each carry a description, which none of them had. This is a tightening of the advertised contract: a call that omits a required attribute, or passes a value outside a closed set, was schema-valid before and is not now. The server's own behavior is unchanged — such a call still reaches operator validation and returns a recoverable `INVALID_INPUT` record with `isError` false — but a client that validates against the published schema will refuse it before sending.

Two smaller changes land in the handshake. `serverInfo.version` now reports this package's version instead of the MCP SDK's, so `1.0.0` and `0.12.0` are finally distinguishable by a client that cannot read distribution metadata. The server also sends an `instructions` string, which was `None`.

The package ships a console command. `blue-data-ops-mcp` replaces `python -c 'from blue_data_ops_mcp import serve; serve()'`, and `blue_data_ops_mcp.main` is the function behind it.

The service directory moved from `platform/mcp/` to `platform/ops-mcp/`, matching the family's `<family>-<service>` naming. The distribution name `blue-data-ops-mcp` and the import name `blue_data_ops_mcp` are unchanged.

The core pin moves with it, from `blue-data-ops==3.0.0` to `==1.0.0`, so a deployment updates both distributions:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==1.0.0" \
  "blue-data-ops-mcp==1.0.0"
```

## Migrating from 0.12.0

Version 0.13.0 moves the exact core pin from `blue-data-ops==2.10.0` to `==3.0.0`. The default selection changes from 36 v2 primaries plus four refinement companions to the 33 mixed-version primaries in `ACTIVE_OPERATOR_IDS`.

The removed package tools are `multipart_query`, `nl2query_router`, `plan_discover`, and `query_breakdown`. The four `__refine` companions are also removed. They no longer resolve from a package registry, and there is no companion result envelope in 0.13.0. A caller-created v2 card that reuses one of these names runs the caller's implementation; it does not restore the removed package binding.

If a deployment still needs those package bindings, automatic refinement, or declarative plan expansion, keep a compatible core 2.x/MCP 0.x pair, such as core 2.10.0 with MCP 0.12.0. This MCP release has no replacement companion path.

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
