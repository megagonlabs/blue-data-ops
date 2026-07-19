# Blue Data Operators MCP

This package exposes Blue Data Operators as MCP tools. The default server hosts 36 pinned
`name@1.0.0` operators from `blue-data-ops==0.2.0`.

## Install

Install this package and the core extras needed by the operators you deploy. The full default surface
uses the ML, vector, and LLM extras:

```bash
pip install blue-data-ops-mcp==0.1.0 "blue-data-ops[ml,vector,llm]==0.2.0"
```

## Embed or serve

`create_server()` returns a configured `FastMCP` server. By default it binds stateful streamable HTTP
to `127.0.0.1:8000/mcp` when run:

```python
from blue_data_ops_mcp import create_server

server = create_server()
server.run(transport="streamable-http")
```

`serve()` performs the same construction and starts streamable HTTP. Pass `operator_ids` to either
function to replace the 36-tool default with an exact pinned subset:

```bash
python -c 'from blue_data_ops_mcp import serve; serve()'
```

```python
from blue_data_ops_mcp import serve

serve(operator_ids=("select@1.0.0", "normalize_text@1.0.0"))
```

The full pinned list is available before startup as `DEFAULT_OPERATOR_IDS`:

```python
from blue_data_ops_mcp import DEFAULT_OPERATOR_IDS

print("\n".join(DEFAULT_OPERATOR_IDS))
```

Both functions accept `host`, `port`, and `path`. Their defaults are `127.0.0.1`, `8000`, and
`/mcp`; for example:

```python
from blue_data_ops_mcp import serve

serve(host="127.0.0.1", port=9000, path="/operators")
```

Review network exposure before changing the loopback host.

## Tool contract

Each tool name is the operator's logical name. Its description comes from the operator card, and MCP
`_meta` contains the pinned `operator_id`, version, and ordered tags. Every tool accepts:

- required `input_data`: a list of record groups, where each group is a list of record objects;
- optional `attributes`: an open object, defaulting to a fresh empty object;
- optional `properties`: an open object or `null`.

`attributes` are the operator arguments described in discovery metadata. `properties` are optional,
operator-specific execution settings passed through to `Operator.apply()`; most basic calls can
omit them.

Known attribute descriptions and defaults appear in discovery metadata. They are annotations only:
the adapter does not insert operator defaults, restrict attribute types, or call operator validators.
The raw `Operator.apply()` method owns function acceptance. An invalid or misspelled attribute value
may therefore return a successful `[[]]` rather than an error; that result is indistinguishable from
a legitimate empty result at the MCP boundary.

For example, call `select` with:

```json
{
  "input_data": [[{"a": 1}, {"a": 5}, {"a": 9}]],
  "attributes": {"operand_key": "a", "operand": ">", "operand_val": 2}
}
```

The tool returns one text block containing:

```json
[[{"a": 5}, {"a": 9}]]
```

Decode the block text once with a JSON decoder to obtain the operator's raw result, which is the
nested list shown here. Empty results remain `[]` or `[[]]`. Operator exceptions and argument-shape
errors are MCP tool errors. Serialization uses `default=str` for values that JSON does not support
and `allow_nan=False`, so `NaN` and `Infinity` fail serialization and surface as tool errors.

The MCP initialization response's `serverInfo.version` is supplied by the MCP SDK and reports its
version, not the `blue-data-ops-mcp` package version.

`plan_discover`, `multipart_query`, and `nl2query_router` return `[[]]` in this release. Their useful
work occurs during plan refinement, which this raw-function MCP surface does not expose.
