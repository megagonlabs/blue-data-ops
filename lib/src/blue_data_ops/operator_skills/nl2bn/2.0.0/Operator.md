# Natural language to Bayesian-network query

`nl2bn@2.0.0` translates a question into a Bayesian-network query, validates it against an optional structured schema, executes it through the registry, and returns the probability.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `<service_prefix>.*` | `properties:<service_prefix>.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `collection` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `context` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `data_registry` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `database` | `attributes` | `yes` | `"default"` | `attribute-spec:str` | `scalar` |
| `execute_query` | `properties` | `no` | `true` | `none` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `explanation` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |
| `input_context` | `properties` | `no` | `"$[0]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_context_field` | `properties` | `no` | `"content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_field` | `properties` | `no` | `"messages"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_json` | `properties` | `no` | `"[{\"role\": \"user\"}]"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `input_template` | `properties` | `no` | `source-sha256:87420873e763ac26481f76dacdb9910314e3f55a1c7d96b3a28781472e68b485` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `llm.*` | `properties:llm.*` | `no` | `none` | `helper:resolve_llm_client` | `namespace` |
| `llm_client` | `properties` | `no` | `none` | `helper:resolve_llm_client` | `seam` |
| `max_corrections` | `attributes` | `yes` | `2` | `attribute-spec:int` | `scalar` |
| `max_num_paths` | `attributes` | `yes` | `50` | `attribute-spec:int` | `scalar` |
| `openai.api` | `properties` | `no` | `"ChatCompletion"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.max_tokens` | `properties` | `no` | `4096` | `none` | `scalar` |
| `openai.model` | `properties` | `no` | `"gpt-6-luna"` | `none` | `scalar` |
| `openai.service_url` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `openai.stream` | `properties` | `no` | `false` | `none` | `scalar` |
| `openai.temperature` | `properties` | `no` | `0` | `none` | `scalar` |
| `output_cast` | `properties` | `no` | `"json"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_path` | `properties` | `no` | `"$.choices[0].message.content"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_strip` | `properties` | `no` | `true` | reserved; Reserved in caller properties; configure trusted operator defaults. | `presence` |
| `output_template` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `output_transformations` | `properties` | `no` | `source-sha256:c6aba812d55427f013ea4096192a330a9984bff294ea41b48982ba0894185b21` | reserved; Reserved in caller properties; configure trusted operator defaults. | `structured` |
| `platform.name` | `properties` | `no` | `none` | `helper:resolve_registry` | `seam` |
| `protocol_variant` | `attributes` | `yes` | `"pgmpy"` | `attribute-spec:str` | `scalar` |
| `question` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `schema` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `service_prefix` | `properties` | `no` | `"openai"` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |
| `source` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `structured_explanation` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `template_syntax` | `properties` | `no` | `none` | reserved; Reserved in caller properties; configure trusted operator defaults. | `scalar` |

## Query, correction, and execution

With no supplied schema, the operator fetches one from the registry. If that schema has no `graph_structure`, the operator uses the graph the registry stored when it synced the source: the collection's `metadata.graph_structure`, or a `graph_structure` on the stored record itself when the metadata holds none it can use. A stored graph is used only when its `nodes` and `edges` are mappings and it has at least one node. A registry that overrides `get_data_source_schema`, or a collection with no stored graph, gets no such fallback. A string containing `nodes` and `edges`, or a raw mapping passed to `apply()`, enables node, state, and evidence validation. Unstructured schema content still reaches the generation prompt but does not receive graph validation, so a guessed state name reaches inference unchecked.

The first provider request includes the question, context, and schema section. A malformed or invalid query can trigger up to `max_corrections` additional calls. Every correction request includes the original query, validation errors, and the same schema section again. Owners must account for that repeated disclosure when the schema is sensitive.

A valid query is executed through the registry. The output is one record containing `prob`, the parsed `query`, and an explanation when requested and returned. An empty registry result gives `prob=None`, not a successful-empty bundle. A blank question returns `[[]]` before registry or provider work. Compatibility `apply()` also returns `[[]]` when no registry resolves.

`run()` contains validation, LLM dependency, provider, parsing, graph-validation, and registry failures. Raw correction-call failures and exhausted corrections remain exceptions. The current `output_attributes` mapping is empty.

Caller prompt, extraction, and transport controls are reserved, including null or
copied defaults. Dollar placeholders are substituted once; inserted data and Jinja
syntax stay literal. Define custom prompts in trusted operator defaults. Injected
clients retain generation settings, while operator prompt/extraction defaults win.

Bayesian inference still runs; the legacy `execute_query` property is ignored and is not an SQL safety switch.

## Bayesian-network sources

`BayesianNetworkSource` comes with the `blue-data` `bn` extra (`pgmpy` and `networkx`). It reads each network from `<source_directory>/<database>/<collection>/`, which must hold `model.bif`, `node_mapping.json` and `state_mapping.json`. A directory without `model.bif` is not listed as a collection, and a model without both mapping files does not load, so sync stores no graph for it and inference fails.

The CLI and MCP server load sources from the file named by `BLUE_DATA_SOURCES_CONFIG`. This source has no short type name; use `"type": "class"` with its full class path:

```json
{"sources": [{"type": "class", "name": "bn", "_class": "blue_data.source.network.bn.bayesian_network_source.BayesianNetworkSource", "properties": {"connection": {"source_directory": "/path/to/networks"}}}]}
```

Loading syncs each source and stores its graphs. With `BLUE_DATA_SOURCES_SYNC=false` nothing is stored, and callers must pass `schema` to get graph validation.
