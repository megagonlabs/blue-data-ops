# Blue Data Operators MCP

> **Synced copy.** [`platform/ops-mcp/README.md`](../platform/ops-mcp/README.md) is the source of truth for the MCP adapter; this page tracks it.
> Where the two disagree, the package README wins.
> For the Python surface these tools project, see [api-reference.md](api-reference.md); for how the adapter sits over the core library, see [architecture.md](architecture.md).

This package exposes Blue Data Operators as MCP tools over the structured execution contract.
It serves 33 primary tools and no refinement companions by default.
The exact operator selection is the same 33-ID projection returned by core `active_registry()`.

The adapter pins `blue-data-ops==3.1.0`.
Every tool name is `ops_` followed by the core operator's logical name, so the `select` operator is served as `ops_select` and `avg` as `ops_avg`.
Each tool's `_meta` carries its exact mixed-version operator ID, which stays unprefixed because it names a core registration rather than a wire surface.

## Install

For a source checkout, place `blue-data` and `blue-data-ops` under the same parent directory.
From the `blue-data-ops` repository root, install the sibling dependency, core, and adapter:

```bash
python -m pip install ../blue-data/lib
python -m pip install "./lib[ml,vector,llm]"
python -m pip install ./platform/ops-mcp
```

`platform/ops-mcp/scripts/install.sh` does the same three steps through the library's own installer, which resolves `blue-data` from its checkout first.

If your artifact index is configured separately:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==3.1.0" \
  "blue-data-ops-mcp==1.0.0"
```

`nl2llm`, `nl2sql`, `nl2bn`, and the `semantic_*` operators resolve a provider client when called.
This package reads no environment variable of its own.
Core reads two: `BLUE_DATA_LLM_PROVIDER`, which names the provider every call is sent to and defaults to `openai`, and `BLUE_DATA_LLM_ALLOWED_MODELS`, which when set is the exact set of models a call property may ask for.
Both come from the environment the server process was started in, which a tool caller cannot reach, and together they are what makes the provider the deployment's choice rather than the caller's.
The rest are the provider SDK's, read the same way — `OPENAI_API_KEY` for an OpenAI-compatible endpoint, and the equivalent for whichever provider `BLUE_DATA_LLM_PROVIDER` names.
The `openai.model` property selects the model within that provider; its default is `gpt-4o`, and a provider-qualified name such as `vertex_ai/gemini-2.5-pro` is refused, because choosing the provider is not a caller's to do.
No tool takes a credential as an argument, and no tool is expected to be given one.

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

A client reaches it at the streamable-HTTP URL rather than by spawning a process.
Point one at it the usual way:

```json
{
  "mcpServers": {
    "blue-data-ops": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

The URL is the server's default bind.
Change it in both places together, and read the transport note below before binding anything but loopback.

### Transport

This server speaks streamable HTTP over a stateful session.
The rest of the Blue Data family speaks stdio, and this server is the exception.

The reason is the shape of the work.
These tools bridge long CPU-bound and provider-bound calls onto worker threads, so a slow call does not hold the event loop and several calls stay in flight at once; the suite proves both, along with protocol cancellation of a running call over a live session.
A client-spawned stdio subprocess is a poor fit for that: it ties the server's lifetime to one client, gives concurrent work nowhere to live across sessions, and makes a long-running deployment restart per client.
Converting would break every existing deployment and buy nothing this package needs.

Both server functions and the console command accept the loopback defaults `127.0.0.1`, `8000`, and `/mcp`.
Review network exposure before changing the loopback host: a tool call carries provider and registry settings in its `properties` argument, and loopback is what keeps that reachable only from the host the server runs on.
A tool argument can no longer choose the provider endpoint — a property that names one is refused — but the settings a call does carry are still worth keeping on one host.

## Embed or serve

`create_server()` returns a configured `FastMCP` server.
This in-memory example lists and calls only `select@2.0.0`:

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

To expose the server over stateful streamable HTTP from your own process, run it directly.
Defaults bind to `127.0.0.1:8000/mcp`:

```python
from blue_data_ops_mcp import create_server

server = create_server()
server.run(transport="streamable-http")
```

`serve()` performs the same construction and starts streamable HTTP; `main()`, which the console command calls, is `serve()` with the defaults:

```python
from blue_data_ops_mcp import serve

serve()
```

Pass `operator_ids` to either function to replace the default selection with an exact pinned subset.
An empty tuple serves no tools.
Without a caller-supplied registry, selections may contain supported retained v2/v3 built-ins.
Every selected card must resolve exactly from the selected registry.
Duplicate logical names fail instead of choosing one:

```python
from blue_data_ops_mcp import serve

serve(operator_ids=("select@2.0.0", "avg@3.0.0"))
```

A caller may pass `registry=` and select caller-created `@2.0.0` cards that resolve exactly from that registry.
A custom card may reuse a removed logical name such as `multipart_query`, but it cannot shadow any of the 33 supported built-in logical names.
Custom v1 and v3 cards are rejected.
For example, after registering `echo@2.0.0` in `caller_registry`:

```python
from blue_data_ops_mcp import create_server

server = create_server(registry=caller_registry, operator_ids=("echo@2.0.0",))
```

A caller-registered operator is served under the same prefix as the built-ins, so `echo@2.0.0` becomes `ops_echo`.

An explicit `registry=` may also serve an exact supported raw package card: a retained `@2.0.0` card such as `default_registry(select="2.0.0")`, or an active `@3.0.0` card such as `default_registry(avg="3.0.0")`.
This is observed adapter behavior, not an ordinary-selection promise.
Raw cards have empty `tags` and `when_to_invoke`, so `_meta.tags` is empty and the tool description contains only the operator description.
MCP accepts the card for explicit execution; acceptance does not grant ordinary or OpenAI planning authority and does not authorize a write.
The caller and deployment host remain responsible for invocation authorization.

`V2_OPERATOR_IDS` remains available for callers that imported the old constant.
It contains the 33 retained v2 exact IDs; it is a compatibility tuple, not the default mixed-version selection.

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

MCP has no server-side tag query.
Call `list_tools()`, read the ordered tags from each tool's `_meta`, and filter them client-side.
Built-in tag values are copied from the selected core operator cards; custom cards expose their caller-supplied tags verbatim.
The six built-in axes describe the primary subject (`domain-*`), pipeline role (`flow-*`), consumed input (`accepts-*`), results or effects (`produces-*`), actions (`capability-*`), and operator-specific runtime requirements (`requires-*`).
The example derives the available values, then performs exact AND matching with `issubset()`.
The client owns any normalization or other matching rules.

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

The command line and this server name the same operations differently.
The command line follows the family's verb-first shape, so listing operators is `blue-ops operator list`.
A tool name here is the operator's own catalog name with a prefix, `ops_select`, because an MCP client selects a tool by matching a task to a name, and the operator's name is the thing it is matching.
Naming a tool `ops_operator_run_select` would hide that under a grammar no client uses.
The two surfaces therefore share a vocabulary of nouns and not of verbs, and neither is a translation of the other.

Each tool is named `ops_` plus its logical operator name.
The prefix is the only part this adapter chooses; the rest is the core operator catalog's own name, verbatim.
The shape of that name is inherited rather than designed here — bare verbs (`ops_select`, `ops_join`), verb_noun (`ops_create_table`), noun_verb (`ops_vector_search`), and codes (`ops_nl2sql`) all appear because the core catalog spells them that way.
A client holds one flat tool namespace across every server it has loaded, and this family ships a server per source, so a bare `select` or `create_database` would collide; `create_database` in fact already does, with `blue-data-user-source`.

A tool's description combines the card's `when_to_invoke` guidance and description.
MCP `_meta` carries the exact `operator_id`, version, and ordered discovery tags.

Every tool accepts the same three open arguments:

- required `input_data`: a list of record groups, where each group is a list of record objects;
- optional `attributes`: an open object of operator arguments, defaulting to a fresh empty object;
- optional `properties`: an open object or `null` carrying execution and backend settings. The recognized keys are `execution.timeout_seconds`; `algorithm`, which selects the estimator for `ops_classify`, `ops_cluster`, and `ops_sklearn_estimator` and without which `ops_sklearn_estimator` does not run at all; `platform.name` together with `data_registry.name`, which the six registry-backed tools need before they return anything but an empty result; `service_prefix`; and the two provider namespaces, `openai.*` and `llm.*`, both closed. `llm.*` takes `model`, `stream`, `max_tokens`, `temperature`, `cache`, `cache_dir`, `max_parallel` and `rate_limit`. `openai.*` takes the generation parameters of the provider call and nothing else. Which provider answers, at which endpoint, in which project, tenant or region, and under which credential are the deployment's to set, from its own environment; a property naming any of them is refused with `reserved_field` rather than quietly dropped, because a dropped routing override would change who answered and say nothing.

Each published attribute carries its description, its JSON Schema `type` where core's declared type has a faithful one, and an `enum` where core's own validator rejects every value outside a fixed set.
Two attributes publish no type because core resolves their declared type to `Any` and would accept anything: `ops_select`'s `operand_val` and `ops_semantic_filter`'s `return_idx`.
An attribute core declares required appears in the `attributes` object's `required` list.
Optional attributes that materialize a default publish it; required attributes and unmaterialized optional values publish no default.

An enum is published only where core enforces it, never on the strength of a description.
Several attributes name their permitted values in prose and still accept others — `ops_nl2sql`'s `protocol`, `ops_nl2bn`'s `protocol_variant`, `ops_semantic_transform`'s `strategy`, and the scikit-learn pass-through settings on `ops_classify` and `ops_cluster` — and those stay open here so the schema does not refuse a call the operator would run.

Business validation belongs to canonical `run()`.
The published schema advertises the operator's contract; it is not a second enforcement point in front of it.
An attribute that violates the schema still reaches operator validation and comes back as a recoverable error record rather than a protocol error.

### Default tool inventory

The 33 tools `create_server()` registers without an `operator_ids` argument, derived from `ACTIVE_OPERATOR_IDS`.
Each row's operator ID is what that tool's `_meta.operator_id` carries, and it is the logical name without the prefix.
Only the `domain-*` and `capability-*` tags are shown; `_meta.tags` carries all six axes in canonical order, and [`lib/OPERATORS.md`](../lib/OPERATORS.md) has each operator's full card.

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
| `ops_nl2sql` | `nl2sql@3.0.0` | `domain-query-compound` | `capability-query-execution`, `capability-query-generation`, `capability-sql` |
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

A logical name appears at most once.
A selection that would serve two versions of one name fails at construction rather than picking one.

### Structured results

Tools publish structured output.
A successful `ops_select` call returns:

```json
{
  "output_data": [[{"name": "b", "score": 9}]],
  "output_attributes": {},
  "exec_meta": {"is_empty": false, "errors": [], "logs": [], "traces": {}}
}
```

`exec_meta.errors` contains records with `category`, `code`, `operator_id`, `stage`, `message`, `retryable`, and `suggestion`.
Read `structuredContent` as authoritative; `json.loads(result.content[0].text)` is the same object.

A call that passes the MCP container schema but fails operator validation is still a successful MCP result.
Calling `ops_select` without its required attributes returns an `INVALID_INPUT` record at the `VALIDATE` stage.
Values are encoded with `default=str` for non-JSON leaves, while `NaN` and `Infinity` are rejected.

### How outcomes surface

- A recoverable, failed, timed-out, or successful-empty operator outcome has `isError` false. Details live in `exec_meta`.
- An unknown tool, malformed top-level arguments, or a projection or encoding failure has `isError` true and adds no operator error record.
- Malformed JSON-RPC and transport failures follow the MCP SDK.

The MCP initialization response reports this package's own version: `serverInfo.version` is `1.0.0`, matching `blue-data-ops-mcp` on the index.
Each tool's operator version is in `_meta` and moves independently of it.

### What this server does not expose

| Not exposed | Why |
|---|---|
| MCP resources | This server is tools-only. The one candidate is core's per-operator skill packages, which are versioned documents on disk with a loader of their own; a client that wants them should read them from the installed library rather than have this server prefetch them into its context, and no tool needs them to run. |
| A `--format` equivalent | An MCP tool's wire format is fixed JSON by protocol. The `--format table/json/nl` of [cli.md](cli.md) is a command-line concern and is deliberately not mirrored here. |
| The pipeline executor | Declarative plan expansion and pipeline execution are a library surface, not a tool. The adapter serves one tool per operator and composes nothing; a caller sequences the calls. |
| Core's operator registry itself | Selection happens at construction, through `operator_ids`, and is frozen for the server's lifetime. There is no tool that registers, resolves, or lists cards, because a client changing the served catalog mid-session is not a thing this contract offers. |

## Migrating from 0.13.0

`1.0.0` renames every tool.
The 33 names gain an `ops_` prefix, so `select` becomes `ops_select` and `create_database` becomes `ops_create_database`.
**Every existing client call site changes.**
A client holds one flat tool namespace across the servers it has loaded, and `create_database` was already served with a different meaning by `blue-data-user-source`; nothing in this catalog was prefixed, and half of it is a bare verb.
Nothing else about a tool moves: `_meta.operator_id` still carries the unprefixed logical name, the arguments are the same three containers, and the result envelope is unchanged.

The published input schema now says what core already enforced.
Each attribute carries its JSON Schema `type`, an attribute core declares required appears in the `attributes` object's `required` list — 46 of them, across 27 tools — and 17 attributes whose values core's validator closes carry an `enum`.
`input_data`, `attributes`, and `properties` each carry a description, which none of them had.
This is a tightening of the advertised contract: a call that omits a required attribute, or passes a value outside a closed set, was schema-valid before and is not now.
The server's own behavior is unchanged — such a call still reaches operator validation and returns a recoverable `INVALID_INPUT` record with `isError` false — but a client that validates against the published schema will refuse it before sending.

Two smaller changes land in the handshake.
`serverInfo.version` now reports this package's version instead of the MCP SDK's, so `1.0.0` and `0.12.0` are finally distinguishable by a client that cannot read distribution metadata.
The server also sends an `instructions` string, which was `None`.

The package ships a console command.
`blue-data-ops-mcp` replaces `python -c 'from blue_data_ops_mcp import serve; serve()'`, and `blue_data_ops_mcp.main` is the function behind it.

The service directory moved from `platform/mcp/` to `platform/ops-mcp/`, matching the family's `<family>-<service>` naming.
The distribution name `blue-data-ops-mcp` and the import name `blue_data_ops_mcp` are unchanged.

The core pin moves with it, from `blue-data-ops==3.0.0` to `==3.1.0`, so a deployment updates both:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==3.1.0" \
  "blue-data-ops-mcp==1.0.0"
```

## Migrating from 0.12.0

Version 0.13.0 moves the exact core pin from `blue-data-ops==2.10.0` to `==3.0.0`.
The default selection changes from 36 v2 primaries plus four refinement companions to the 33 mixed-version primaries in `ACTIVE_OPERATOR_IDS`.

The removed package tools are `multipart_query`, `nl2query_router`, `plan_discover`, and `query_breakdown`.
The four `__refine` companions are also removed.
They no longer resolve from a package registry, and there is no companion result envelope in 0.13.0.
A caller-created v2 card that reuses one of these names runs the caller's implementation; it does not restore the removed package binding.

If a deployment still needs those package bindings, automatic refinement, or declarative plan expansion, keep a compatible core 2.x/MCP 0.x pair, such as core 2.10.0 with MCP 0.12.0.
MCP 0.13.0 has no replacement companion path.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==3.0.0" \
  "blue-data-ops-mcp==0.13.0"
```

## Migrating from 0.11.0

`0.12.0` moves the exact core pin from `blue-data-ops==2.9.0` to `==2.10.0`.
Core expands the outcome set available through explicit `@3.0.0` selection from three cards to 21.
The MCP adapter continues to serve 36 `@2.0.0` primary tools and four refinement companions by default.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.10.0" \
  "blue-data-ops-mcp==0.12.0"
```

## Migrating from 0.9.0

`0.10.0` moves the exact core pin from `blue-data-ops==2.7.0` to `==2.8.0`.
The core release deprecates the four plan-producing operators and the refinement seam, so this adapter annotates eight of its bindings.
No tool is added, renamed, reordered, or removed, and no argument, result envelope, or error behavior changes.

Nothing has to change in a client to keep working.
If you want to move off the deprecated tools before 3.0.0, read `_meta.deprecated` from `list_tools()` to find them:

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

`0.9.0` moves the exact core pin from `blue-data-ops==2.6.0` to `==2.7.0`.
The core release adds explicit operator-skill availability and resource-metadata inspection before a caller loads text.
The adapter still exposes the same 40 tools and does not load or transmit skill metadata or resources.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.7.0" \
  "blue-data-ops-mcp==0.9.0"
```

## Migrating from 0.7.0

`0.8.0` moves the exact core pin from `blue-data-ops==2.5.0` to `==2.6.0`.
The core release adds caller-supplied embedding discovery and optional local-planner integration.
The adapter still exposes the same 40 tools and does not load or transmit embedding-discovery inputs.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.6.0" \
  "blue-data-ops-mcp==0.8.0"
```

## Migrating from 0.6.0

`0.7.0` moves the exact core pin from `blue-data-ops==2.4.0` to `==2.5.0`.
The core release adds resource packages for every active execution operator.
MCP does not load or disclose those resources, so its 40-tool protocol surface is unchanged.

Update both distributions together:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.5.0" \
  "blue-data-ops-mcp==0.7.0"
```

## Migrating from 0.5.0

`0.6.0` moves the core pin from `blue-data-ops==2.3.0` to `==2.4.0`.
Tool names, `_meta`, the top-level `input_data` / `attributes` / `properties` arguments, the structured result envelope, error surfacing, and the transport are unchanged, and every operator id is still `@2.0.0`.
The `classify` description now names `DecisionTreeClassifier`, `KNeighborsClassifier`, and `MultinomialNB`.
Its `attributes` schema adds `n_neighbors`, `weights`, `alpha`, and `fit_prior`; the descriptions for `criterion`, `splitter`, `max_depth`, `min_samples_split`, `min_samples_leaf`, and `random_state` now identify them as `decision_tree` settings.
The `properties["algorithm"]` values `knn` and `multinomial_nb` now produce predictions instead of returning the input unchanged.

Update both distributions together.
The exact pin means one environment holds one pair, so a `0.5.0` adapter cannot run against core `2.4.0` and `0.6.0` cannot run against core `2.3.0`:

```bash
python -m pip install --index-url "$PIP_INDEX_URL" \
  "blue-data-ops[ml,vector,llm]==2.4.0" \
  "blue-data-ops-mcp==0.6.0"
```

Core `2.4.0` adds eight exact-version operator resource packages.
They do not change this adapter's surface: skill resources are not added to tool descriptions, `_meta`, arguments, or results.

## Migrating from 0.1.0

`blue-data-ops-mcp 0.1.0` (paired with `blue-data-ops 0.2.0`) dispatched to the raw operator function and returned a single JSON text block.
`0.2.0` dispatches to the canonical `run()` / `refine()` methods and returns the structured envelope above.
A `0.1.0` client updating to `0.2.0` should:

- read `structuredContent` and take `output_data` (a primary's result) or `plans` (a companion's) instead of decoding the bare body;
- treat canonical error records in `exec_meta.errors` as data rather than expecting an empty result;
- expect the four `__refine` companions and the `2.0.0` operator versions in `_meta`.

Tool names, the `input_data` / `attributes` / `properties` arguments, and the streamable-HTTP transport are unchanged.
The two distributions pin different core versions, so a single environment serves either the `0.1.0` (`1.0.0` operators) or the `0.2.0` (`2.0.0` operators) contract, not both.
