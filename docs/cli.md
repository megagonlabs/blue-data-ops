# blue-ops — the command line

> The complete package guide is [`platform/ops-cli/README.md`](../platform/ops-cli/README.md).
> For the Python surface these commands call, see [api-reference.md](api-reference.md); for the same operators over MCP, see [mcp.md](mcp.md).

`blue-data-ops-cli` installs one command, `blue-ops`, which reaches the operator library in [`lib/`](../lib/README.md) from a shell.
The package parses arguments, keeps configuration, and prints results; every operator call it makes goes through the same `run()` boundary the library and the MCP adapter use.

## Install

From `platform/ops-cli/`:

```bash
scripts/install.sh
```

That installs the sibling `blue-data` checkout, the library from `../../lib` with the `ml`, `vector` and `llm` extras, then this package, both editable, plus the dev extras.
`blue-data` is a core dependency of the library and is not on a public index, so it has to be resolvable first; [installation.md](installation.md) is the source of truth for the paths that put it there.

Add the provider-backed planner's dependency with the `openai` extra:

```bash
python -m pip install -e ".[dev,openai]" "blue-data-ops-cli==1.0.0" "blue-data-ops==1.0.0"
```

Confirm the install:

```bash
blue-ops metadata inspect
```

## Commands

Run the following examples from the repository root; the JSON inputs are in `examples/cli/`.

```bash
blue-ops --help
```

```bash
blue-ops --version
```

Commands are in the shape the Blue CLI family uses, `blue-ops <component> <action> <parameters>`:

```text
blue-ops [--version] [-h|--help] [--profile NAME]
├── profile
│   ├── add NAME
│   ├── remove NAME [--confirm]
│   ├── list [--format]
│   ├── config [PARAM [VALUE]] [--profile NAME]
│   ├── inspect [NAME] [--format]
│   └── select NAME
├── catalog
│   ├── list [--format]
│   ├── inspect [NAME] [--format]
│   └── select NAME
├── operator
│   ├── list [--catalog] [--format]
│   ├── search QUERY [--tag TAG]... [--limit N] [--catalog] [--format]
│   ├── inspect OPERATOR_ID [--catalog] [--format]
│   ├── run OPERATOR_ID [--input-file PATH] [--attribute KEY=VALUE]... [--attributes-file PATH]
│   │     [--property KEY=VALUE]... [--properties-file PATH] [--timeout SECONDS] [--model NAME]
│   │     [--reasoning-effort LEVEL] [--catalog] [--format] [--log] [--log-limit N]
│   └── resource
│       ├── list [--catalog] [--format]
│       ├── inspect OPERATOR_ID [--catalog] [--format]
│       └── export OPERATOR_ID [--level {2,3}] [--output-file PATH] [--confirm] [--catalog]
├── pipeline
│   ├── add NAME --request-file PATH [--goal TEXT] [--planner {rule,openai}] [--model NAME]
│   │     [--send-data-context] [--confirm] [--catalog] [--format] [--log] [--log-limit N]
│   ├── import NAME --pipeline-file PATH [--confirm] [--catalog] [--format]
│   ├── export NAME [--output-file PATH] [--confirm]
│   ├── list [--format]
│   ├── inspect NAME [--catalog] [--format]
│   ├── remove NAME [--confirm]
│   └── run NAME --input-file PATH [--model NAME] [--reasoning-effort LEVEL]
│         [--catalog] [--format] [--log] [--log-limit N]
└── metadata
    └── inspect [--catalog] [--format]
```

24 commands over five components and one subcomponent.

There is no `database`, `data` or `schema` component.
This repository is not a `-source` repository: it has no store of its own, no database behind it, and no stored schema.
An operator's attribute schema is part of the operator's own description rather than a component, and the data registry those words would name belongs to `blue-data`, whose CLI already manages it with `source add/sync/query/inspect`.

`blue-ops metadata inspect` prints what is installed, which optional extras resolve, and which catalog a command would read now.

With all three distributions and the listed extras installed, the output looks like this:

```text
                   metadata
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ key               ┃ value                   ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ blue-data-ops-cli │ 1.0.0                   │
│ blue-data-ops     │ 1.0.0                   │
│ blue-data-ops-mcp │ 1.0.0                   │
│ blue-data         │ 1.0.0                   │
│ python            │ 3.12.14                 │
│ extras            │ llm, ml, openai, vector │
│ catalog           │ active                  │
│ cards             │ 33                      │
└───────────────────┴─────────────────────────┘
```

A CLI-only install reports `null` for `blue-data-ops-mcp`.

Every version there is read from the installed distribution rather than written down, so none of them can drift from what `pip` reports.
An extra is present when every module it brings can be located; nothing is imported to find out, so asking what is installed never pays for loading a model runtime.

## Configuration

Settings live in profiles under `~/.blue-ops`, and every command reads them in the same order:

**command option > environment variable > profile > built-in default.**

```bash
blue-ops profile config BLUE_DATA_LLM_MODEL gpt-4o
```

`profile config` has three forms.
With no argument it walks the parameters a first run is asked for; with a parameter name it prompts for that one; with a name and a value it sets it outright.
A profile named with `--profile` that does not exist yet is created by the write that needs it, so a refused parameter or a value that will not store leaves nothing behind.

`profile inspect` shows every parameter, its value, and which tier supplied it: `environment`, `profile:<name>`, `default`, or `unset`.
It cannot report `flag`, because a command option never reaches the resolver; it is applied on top of whatever the resolver returned.

```bash
blue-ops profile inspect
```

Profiles are independent, and `--profile` picks one for a single command:

```bash
blue-ops profile add staging
```

```bash
blue-ops profile config --profile staging BLUE_DATA_OPS_PLANNER openai
```

```bash
blue-ops profile select staging
```

```bash
blue-ops profile remove staging --confirm
```

`--confirm` skips the question.
Without it, `profile remove` asks, and answering no changes nothing and exits 0.
Removing a profile deletes that section of the profiles file and nothing else; `~/.blue-ops/<name>/` is left where it is and named on standard error so you can delete it yourself.
The last profile cannot be removed, because the selection has to name a profile that is there.

### Parameters

| Parameter | Cast | Default | Allowed values or bounds | Asked on a first run | Reaches |
|---|---|---|---|---|---|
| `OPENAI_API_KEY` | secret | — | — | yes | the provider SDK, through the environment |
| `BLUE_DATA_LLM_MODEL` | str | `gpt-6-luna` | — | yes | the `openai.model` call property |
| `BLUE_DATA_CLI_FORMAT` | str | `table` | `table`, `json`, `nl` | | the default for `--format` |
| `BLUE_DATA_CLI_LOG_LIMIT` | int | `80` | — | | the default for `--log-limit` |
| `BLUE_DATA_OPS_CATALOG` | str | `active` | `active`, `history` | | the default for `--catalog` |
| `BLUE_DATA_OPS_TIMEOUT` | float | — | finite, greater than 0 | | the `execution.timeout_seconds` call property |
| `BLUE_DATA_OPS_PLANNER` | str | `rule` | `rule`, `openai` | | the default plan generator |
| `BLUE_DATA_OPS_PLANNER_MODEL` | str | `gpt-6-luna` | — | | the provider-backed planner's model |
| `BLUE_DATA_OPS_PLANNER_TIMEOUT` | float | `60.0` | finite, greater than 0 and at most 300 | | the provider-backed planner's timeout |
| `BLUE_DATA_OPS_PLANNER_MAX_OUTPUT_TOKENS` | int | `4096` | 256–16384 | | the provider-backed planner's output allowance |
| `BLUE_DATA_REGISTRY_STORE` | str | `memory` | `memory`, `file`, `redis` (case-insensitive) | | the `blue-data` registry backend |
| `BLUE_DATA_REGISTRY_FILE` | str | — | — | | the file backend's path |
| `BLUE_DATA_REGISTRY_REDIS_URL` | str | — | — | | the redis backend's URL |
| `BLUE_DATA_REGISTRY_REDIS_NAMESPACE` | str | — | — | | the redis backend's namespace |
| `BLUE_DATA_SOURCES_CONFIG` | file | — | — | | the JSON file of sources pre-loaded into the registry |

The first four are the family-wide parameters every Blue CLI declares.
The five registry names are `blue-data`'s own, read verbatim, so the same variables produce the same registry here and in `blue-data`'s CLI.
New profile values are checked against the backends `blue-data` currently documents. Existing profiles and environment values retain `blue-data`'s runtime behavior.
The default `memory` store keeps registry metadata for one command; the next command starts with a new registry and reloads configured sources.
It does not make source operations temporary. Database, file and remote-source writes can persist, including effects completed before a failure or timeout.
The CLI prints a warning on standard error when using the memory store.
Set `BLUE_DATA_REGISTRY_STORE=file` with `BLUE_DATA_REGISTRY_FILE` to retain registry metadata between commands.

`BLUE_DATA_SOURCES_CONFIG` names a file in `blue-data`'s own format, read by its `load_sources`, so a source registered there is in the registry before the first command runs:

```json
{"sources": [{"type": "sqlite", "name": "shop", "properties": {"connection": {"database_directory": "/path/to/dir"}}}]}
```

`type` selects the `blue-data` source class and `properties` is handed to it unchanged, so which keys belong there is that source's question and not this CLI's.
`BLUE_DATA_LLM_MODEL` sets the model the language-model operators call and `BLUE_DATA_OPS_PLANNER_MODEL` sets the planner's, because a deployment may want a cheaper model for planning than for the operator it is planning around.

A parameter name is also its environment variable name, so exporting `BLUE_DATA_OPS_CATALOG` overrides the profile for one shell without editing anything.
Exporting one *empty* is refused rather than read as unset: an empty tier taken as absent would hand the setting down to the profile without saying so.
`unset BLUE_DATA_OPS_CATALOG` is how you take a variable out of the chain, and the store refuses a blank value for the same reason.

Nothing blocks on a parameter being unset.
Every command runs against an empty profile; a missing credential surfaces only when an operator reaches a provider.

Two settings come from the environment and not from a profile.
`BLUE_DATA_OPS_HOME` moves the CLI home, because it is the directory the profiles are read from.
`BLUE_DATA_PROFILE` picks the profile, and the root `--profile` overrides it.
Either one naming a profile that does not exist is refused rather than run as an empty one.

## Catalogs

Registry configuration now rejects an unsupported store selector, surrounding selector whitespace, or an explicit missing, unreadable or malformed sources file. The sources document must contain a `sources` list of objects. `{"sources": []}` remains valid. CLI construction still defaults to empty memory and warns that registry metadata is ephemeral. File/Redis helpers can write/connect, and source loading can connect, enrich and sync before execution starts. `--timeout` bounds the later operator wait, not initial registry construction or backend connection setup; a late worker can still change the backend.

SQL and Bayesian operators check caller template and transport controls before the CLI builds a data registry. Stock SQL operators support generation only. A host-configured exact built-in `NL2SQLOperator` or `NL2SQLOutcomeOperator` instance, including registered version/name aliases, can use its bound read-only executor. Other subclasses, including those that customize prompts, require the direct Python host API for SQL execution.

A catalog is a view of the operator registry, and `--catalog` says which one a command reads.

| View | Cards | What it holds |
|---|---|---|
| `active` | 33 | the reviewed built-ins, one version per operator name |
| `history` | 87 | every retained version, including the reviewed ones |

The selection follows the same four tiers: `--catalog` > `BLUE_DATA_OPS_CATALOG` > `~/.blue-ops/<profile>/.selected.catalog` > `active`.

The library's third view, the raw registry, is not offered.
Its cards carry no tags and no `when_to_invoke`, and the core planner rejects every one of them as planning authority, so `--catalog raw` is refused with that reason rather than with an unknown-value message.

```bash
blue-ops catalog list
```

```text
┏━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Catalog ┃ Selected ┃ Cards ┃ Operators ┃ Planning     ┃
┡━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ active  │ *        │ 33    │ 33        │ yes          │
│ history │          │ 87    │ 33        │ by allowlist │
└─────────┴──────────┴───────┴───────────┴──────────────┘
```

Planning admits the active selection on its own.
A retained version from `history` is admitted only when a planning request names it in `allowed_operator_ids`.

`catalog inspect` reports one view's size, its version spread, and every tag its cards carry, grouped by the library's six axes.
Those tags are the values `operator search --tag` accepts, so this is where you look before writing a filter.

```bash
blue-ops catalog inspect history
```

```bash
blue-ops catalog select history
```

The selection is written to `~/.blue-ops/<profile>/.selected.catalog` at mode 0600 and belongs to that profile alone.

## Operators

An operator is addressed by a pinned id, `name@<major>.<minor>.<patch>`.
A bare name works too: it resolves through the library's own lookup and the command says on standard error which id it became, because a run that silently picked a version is a run nobody can reproduce.
In `history`, where a name has several versions, the bare form is refused and the versions are listed instead.

```bash
blue-ops operator list
```

```bash
blue-ops operator search average
```

```bash
blue-ops operator search "" --tag capability-filter
```

`--tag` is repeatable and every tag given must be present.
It cannot be a fixed list of choices: the library accepts any well-formed tag and validates only its shape, so `blue-ops catalog inspect --format json` is what tells you which values are actually there.
A blank query with no tag is refused rather than answered with an empty table.

```bash
blue-ops operator inspect select@2.0.0
```

```text
                                  select@2.0.0
┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Attribute         ┃ Type  ┃ Required ┃ Default ┃ Description                 ┃
┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ operand_key       │ str   │ yes      │         │ The key to check in each    │
│                   │       │          │         │ record                      │
│ operand           │ str   │ yes      │         │ Comparison operator: =, !=, │
│                   │       │          │         │ >, >=, <, <=                │
│ operand_val       │ Any   │ yes      │         │ Value to compare with       │
│ approximate_match │ bool  │          │ False   │ Use epsilon tolerance for   │
│                   │       │          │         │ numeric comparison          │
│ eps               │ float │          │ 1e-09   │ Epsilon tolerance for       │
│                   │       │          │         │ approximate numeric         │
│                   │       │          │         │ comparison                  │
└───────────────────┴───────┴──────────┴─────────┴─────────────────────────────┘
```

The attribute schema is here rather than under a `schema` component, because it describes this operator and nothing else.
Under `--format json` it appears under a `schema` key, so the family word is used where it means the same thing.

`operator run` takes a record bundle and returns what came back.
A bundle is `list[list[dict]]`: groups of records, which is what every operator in this library consumes and produces.
Run the file-based examples below from the repository root.
The JSON inputs live in the source checkout under `examples/cli/`; if you installed only a wheel, save the displayed JSON to your own files and pass those paths instead.

Sample input at [`examples/cli/orders.json`](../examples/cli/orders.json):

```json
[[{"total": 120.0}, {"total": 215.0}, {"total": 50.0}]]
```

```bash
blue-ops operator run select@2.0.0 --input-file examples/cli/orders.json --attribute operand_key=total --attribute 'operand=>' --attribute operand_val=100
```

```text
  select@2.0.0
┏━━━━━━━┳━━━━━━━┓
┃ group ┃ total ┃
┡━━━━━━━╇━━━━━━━┩
│ 0     │ 120.0 │
│ 0     │ 215.0 │
└───────┴───────┘
settings: (none)
```

`--input-file -` reads the bundle from standard input.
An operator tagged `accepts-none` consumes no records, so the CLI hands it an empty bundle and `--input-file` is required only for the rest.

`--attribute KEY=VALUE` sets one operator attribute and `--property KEY=VALUE` sets one call property, such as `openai.temperature=0`.
Both are repeatable, both read their value as JSON and fall back to the literal text, so `limit=5` is the number and `key=total` is the word.
`--attributes-file` and `--properties-file` take a JSON object of the same thing; the file is applied first and a per-key option overrides one key of it.

**`--attribute` and `--property` are the only places in this CLI where you name both a key and its value in the command itself, so a key that reads as a credential is refused there.**
The two file options are not scanned for credential-shaped keys and are not a general secret filter. Validation of LLM call properties rejects provider credential overrides such as `openai.api_key`; store provider credentials in a profile.
`--property openai.api_key=...` would be in argv and in the shell's history before any masking could reach it, and the refusal names `blue-ops profile config OPENAI_API_KEY` instead.
Ordinary attribute names are untouched: `key`, `argmax_key`, `sum_key` and `partition_key` are attribute names throughout this library.

The footer names each setting this invocation applied and the tier it came from.
`--timeout` sets `execution.timeout_seconds` and requires a finite positive value. Without the flag, it falls back through the environment and profile.
For an LLM-backed operator, `--model` sets `openai.model` with the same fallback, and `--reasoning-effort` sets `llm.reasoning_effort` for the current run.
Other operators receive no inherited model default and reject either LLM flag.

Use the dedicated flags with any LLM-backed operator. `nl2llm` consumes no input records:

```bash
blue-ops operator run nl2llm@3.0.0 \
  --attribute 'query=Return three product categories as JSON objects.' \
  --model gpt-5-mini --reasoning-effort low
```

[`examples/cli/workspaces.json`](../examples/cli/workspaces.json):

```json
[[{"name": "alpha", "summary": "quiet workspace"}]]
```

Pass that bundle to `semantic_filter`:

```bash
blue-ops operator run semantic_filter@3.0.0 --input-file examples/cli/workspaces.json \
  --attribute 'filter_conditions={"summary":"suited to focused work"}' \
  --model gpt-5-mini --reasoning-effort low
```

Leave out `--reasoning-effort` for a model that does not offer it. If the flag is present and the
provider rejects that generation setting, the run fails once with a suggestion to remove the setting
or choose a compatible model. The CLI does not silently retry without it. The same controls are
available as `--property llm.model=...` and `--property llm.reasoning_effort=...`.
When `--model` and a generic model property appear together, the dedicated flag wins. A generic
`llm.model` supplied on its own suppresses the profile or built-in model default, so the settings
footer names the model that reaches the operator.

See [Choosing a model for an LLM operator](llm-settings.md) for the same settings through
Python and MCP, plus an offline precedence example.

## Operator resources

Most operators ship a reviewed package: a guide at level 2, and worked examples at level 3.

```bash
blue-ops operator resource list
```

```bash
blue-ops operator resource inspect select@2.0.0
```

```bash
blue-ops operator resource export select@2.0.0 --level 3 --output-file select.md
```

`--level` is a closed set of `2` and `3` because no package in this release declares a level 4; the library refuses one at runtime, and a closed set says so in `--help` instead.

With `--output-file`, export writes `select.md` in the current directory. Without it, export prints the Markdown on standard output.

`export` has no `--format`.
An export emits the artifact as it is written — here, Markdown — and re-encoding it as a table or a sentence would not be an export.
`pipeline export` follows the same rule and emits its serialized record.

## Pipelines

A pipeline is a graph of operators, stored under the profile that made it.
`add` and `import` are not synonyms: `import` reads a graph that already exists, `add` synthesizes one from a goal and a set of discovery queries.

A planning request is a nested object: the goal, the discovery queries with their own tags and limits, the per-operator attributes, an optional data scope, an allowlist and five bounds.
It arrives as a file rather than as a mini-language spread across the command line.

Sample request at [`examples/cli/request.json`](../examples/cli/request.json):

```json
{
  "goal": "average total of orders above 100",
  "discovery_queries": [
    {"text": "filter", "tags": ["capability-filter"]},
    {"text": "average", "tags": ["capability-average"]}
  ],
  "operator_attributes": {
    "select": {"operand_key": "total", "operand": ">", "operand_val": 100},
    "avg": {"avg_key": "total", "output_key": "average_total"}
  },
  "allowed_operator_ids": ["select@2.0.0", "avg@3.0.0"]
}
```

```bash
blue-ops pipeline add nightly --request-file examples/cli/request.json
```

```text
     pipeline: nightly
┏━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Node     ┃ Operator     ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 2e7f5683 │ select@2.0.0 │
│ 78d364a8 │ avg@3.0.0    │
└──────────┴──────────────┘
stored as nightly in profile default
settings: planner=rule (default)
```

`--goal` replaces the goal in the request file. The shipped rule template matches goals containing `average` and either `above` or `greater`; another goal can produce `NO_CANDIDATES`.
`--planner rule` uses that template. `--planner openai` calls a model, needs the `openai` extra, and needs `allowed_operator_ids` in the request file. The sample request includes the two pinned IDs it may plan with.
`--send-data-context` discloses the request's schema snapshot to that model and is off by default.

```bash
blue-ops pipeline list
```

```bash
blue-ops pipeline inspect nightly
```

```bash
blue-ops pipeline run nightly --input-file examples/cli/orders.json
```

```text
    pipeline: nightly
┏━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ group ┃ average_total ┃
┡━━━━━━━╇━━━━━━━━━━━━━━━┩
│ 0     │ 167.5         │
└───────┴───────────────┘
invocation defaults: (none)
```

`pipeline run` also accepts `--model` and `--reasoning-effort` when the pipeline has an LLM-backed node.
They are invocation defaults; a value stored in the pipeline overrides one, and a value on an operator node overrides the pipeline value.
A pipeline without an LLM-backed node receives no model default and rejects either LLM flag.
Deployment provider routing and the model allowlist still apply
after those layers are merged. A node can set `llm.reasoning_effort` to `null` in an imported pipeline
record to clear an inherited effort for a model that does not support it.
The `--model` on `pipeline add --planner openai` selects the planning model instead; it does not set
the models used later by operator nodes.

This stored pipeline sets a pipeline model and effort, then selects another model on its LLM node
and clears the inherited effort there.

[`examples/cli/llm-pipeline.json`](../examples/cli/llm-pipeline.json):

```json
{
  "id": "llm-example",
  "label": "LLM override and effort clearing",
  "type": "DATA_PIPELINE",
  "nodes": {
    "input": {
      "id": "input", "label": "records", "type": "INPUT", "prev": [],
      "next": ["generate"], "properties": {}, "values": {}, "statuses": {},
      "value": null, "provenance": "$.llm-example"
    },
    "generate": {
      "id": "generate", "label": "generate", "type": "OPERATOR", "prev": ["input"],
      "next": ["output"],
      "properties": {"llm.model": "gpt-4o-mini", "llm.reasoning_effort": null},
      "values": {}, "statuses": {}, "OPERATOR": "llm-operator",
      "provenance": "$.llm-example"
    },
    "output": {
      "id": "output", "label": "result", "type": "OUTPUT", "prev": ["generate"],
      "next": [], "properties": {}, "values": {}, "statuses": {},
      "value": null, "provenance": "$.llm-example"
    }
  },
  "map": {"records": "input", "generate": "generate", "result": "output"},
  "entities": {
    "OPERATOR": {
      "llm-operator": {
        "id": "llm-operator", "label": null, "type": "OPERATOR",
        "properties": {"llm.model": "gpt-4o-mini", "llm.reasoning_effort": null},
        "nodes": ["generate"], "operator_id": "nl2llm@3.0.0",
        "attributes": {"query": "Return an empty JSON array."}
      }
    }
  },
  "properties": {"llm.model": "gpt-5-mini", "llm.reasoning_effort": "medium"},
  "provenance": "$", "input": "input", "output": "output", "attributes": {}
}
```

[`examples/cli/llm-input.json`](../examples/cli/llm-input.json):

```json
[[]]
```

```bash
blue-ops pipeline import llm-example --pipeline-file examples/cli/llm-pipeline.json
blue-ops pipeline run llm-example --input-file examples/cli/llm-input.json --model gpt-6-luna --reasoning-effort high
```

The run's `--model` and `--reasoning-effort` are only invocation defaults. The stored pipeline model
overrides the first, the node model overrides the stored model, and the node's `null` effort clears
both the stored and invocation values. In JSON output, `settings.scope` is
`"invocation_defaults"`; `settings.applied` and `settings.source` describe only those CLI defaults.

**A run never writes to the store.**
Executing a pipeline records what happened on the plan it is handed, so the copy that runs is in memory and the one on disk is left alone.
Writing it back would put your records into `~/.blue-ops`, and it would leave a stored pipeline that runs exactly once, because a node that has already started cannot start again.
`add` and `import` are the only commands that write.

A pipeline stops at the first node that fails, exits `EXECUTION` (8), and reports which node stopped it and what every earlier node did — on standard error under a human format, and in the error's `detail` under `--format json`.

```bash
blue-ops pipeline export nightly --output-file nightly.json
```

```bash
blue-ops pipeline import copy --pipeline-file nightly.json
```

`import` runs the executor's preflight before it stores anything, so a graph that cannot resolve its operators is refused at the door rather than at the first run.

```bash
blue-ops pipeline remove copy --confirm
```

## Where this departs from the family guide

| Departure | Why |
|---|---|
| `run` is a verb outside the standard list | The guide's verbs are `add`, `remove`, `list`, `config`, `select`, `query`, `inspect`, `search`, `import` and `export`. None of them means "apply a transformation to a supplied record bundle and return the result". `query` is the nearest and is the wrong one: everywhere else in the family `query` retrieves from a store, and reusing it here would put one word on two meanings, which the guide forbids more firmly than it forbids a new verb. `run` is the library's own name for the same entry point. |
| `catalog` is a component the guide does not name | It is this repository's analogue of `database`: a named view selected once that later commands read. `registry` would have collided with the data registry that `blue-data` owns and that this CLI also reads. |
| `database`, `data` and `schema` are absent | The guide marks them as mostly for the source repositories. This one has no store: records arrive from a file and leave on stdout, so the resource being named is the operator, not the data. Operator attribute schemas are part of `operator inspect`; data schemas belong to the registry and to `blue-data`'s CLI. `profile` and `metadata` are kept, with the family's meanings. |

## What this CLI leaves out

Four capabilities the library has are not on the command line.

| Capability | Why not |
|---|---|
| Embedding discovery | The caller supplies the embedder and its `space_id`, and the library states that it does not choose or install an embedding model. A flag here would make this CLI choose one. Use `operator search` for keyword and tag discovery. |
| The raw registry view | Its cards carry no tags and no `when_to_invoke`, and the core planner rejects every one of them as planning authority. |
| Data-source and registry management | `blue-data`'s own CLI owns `source add/sync/query/inspect`. `blue-ops` consumes a registry through `BLUE_DATA_REGISTRY_*` and does not manage one. |
| `csv` output | A record bundle is `list[list[dict]]` and CSV has no representation for the group boundary, so flattening one would silently merge groups into a single table. |

Registering a custom operator, editing a pipeline graph node by node, and the library's unstructured `apply()` and `invoke()` entry points are absent for the same kind of reason: the first needs a Python class, the second is a DAG editor on a command line, and the third is a second way to do what `run` already does with weaker error handling.

## Storage and secrets

```text
~/.blue-ops/                      directory mode 0700
├── .profiles                     INI, one [section] per profile, file mode 0600
├── .selected.profile             the selected profile name, mode 0600
└── <profile>/                    mode 0700
    ├── .selected.catalog         active | history, mode 0600
    └── pipeline/                 one directory per stored pipeline, mode 0700
        └── <name>/
            ├── pipeline.json     the serialized DataPipeline, mode 0600
            └── provenance.json   where it came from and when, mode 0600
```

Storage operations follow these rules:

- Writes use a temporary file in the destination directory and then rename it into place. Line breaks are rejected in line-oriented values. Successful writes are not flushed to disk, so a power loss may restore the previous value, but it cannot leave a torn file.
- The CLI opens the home directory once and resolves descendants relative to open directory descriptors. It does not follow directory links during ordinary descent. A link within the home may target another location within the home; the target is resolved and checked by the same traversal. A link that resolves outside the home is refused. This prevents a directory swap from redirecting a later operation outside the home.
- Wider directory permissions produce one warning and are otherwise left unchanged. Files return to mode 0600 on their next write. The first command creates the home directory, `.profiles`, and `.selected.profile` to initialize the default profile. Later reads do not create resource directories. Writes create missing directories with mode 0700.
- Pipeline removal first renames the directory to a private claim name within `<profile>/pipeline/` and flushes that rename. If the flush fails, the original name is restored and the command fails before deleting content.
- Deletion works through the opened claimed directory. Before the final `rmdir`, the CLI verifies that the claim name still refers to that directory; if the entry moved, removal stops. The final `rmdir` is flushed so a successful removal remains complete after a power loss. New pipeline names cannot begin with a dot because that namespace is reserved for claims.
- A claim marker is written before any file is unlinked and removed last. After an interruption, the next `pipeline list` or `pipeline remove` resumes only entries carrying that marker. A claim-shaped entry without the marker is treated as a pipeline created by an older version: it is reported on standard error and remains available to list, inspect, export, or remove, but the name cannot be reused for a new pipeline. Failure to write the marker restores the original name.
- An empty claim-shaped directory without a marker is removed as interrupted cleanup. A nonempty directory or non-directory entry without the marker is left unchanged.

Secrets follow a separate set of rules:

- Secret values are not accepted as command-line arguments. `blue-ops profile config OPENAI_API_KEY` prompts without echo. Entering `$MY_KEY` stores an environment-variable reference; `profile inspect` reports `$MY_KEY (set)` or `$MY_KEY (unset)`.
- A directly entered secret is stored as base64 behind an `enc:` prefix. This is obfuscation, not encryption; file permissions provide the protection.
- Commands do not expose configured secret values through profile output, errors, or logs. Secret masking covers error lines, JSON error objects and their `detail`, logs, logged tracebacks, and `openai.model` in the `settings` envelope. It masks credential values found in the environment and strings with credential syntax. Ordinary model names are unchanged.
- Masking also treats long opaque strings as possible credentials. This can replace UUID-like path components with `***` in messages; use the original command arguments or `BLUE_DATA_OPS_HOME` to recover the full path.
- Operator records are not masked because they are computed output; a token-shaped record value may be a requested result.

When embedded in a Python process, `operator run` and `pipeline run` temporarily route root and existing Blue library loggers through the CLI reporter during execution. The original handlers, package propagation flags, and Python fallback handler are restored when execution ends, including failures. Root logs from other threads can use the same temporary route.

## Output formats

`--format table|json|nl` is on every command that returns a result, and the default comes from `BLUE_DATA_CLI_FORMAT` when a profile sets one.

```bash
blue-ops profile list --format nl
```

```text
1 profile(s): default. The selected one is default.
```

`table` is the Rich table above, `nl` is a short paragraph, and `json` is one object on standard output and nothing else.

Every JSON result is one object with a payload key named for the resource:

| Command | Payload key | Beside it |
|---|---|---|
| `profile list` | `profiles` | `selected` |
| `profile inspect` | `parameters` | `profile` |
| `catalog list` | `catalogs` | `selected` |
| `catalog inspect` | `catalog` | `selected` |
| `operator list` | `operators` | `catalog`, `count` |
| `operator search` | `operators` | `catalog`, `query`, `tags`, `limit`, `count` |
| `operator inspect` | `operator` | `catalog` |
| `operator run` | `result` | `operator_id`, `is_empty`, `errors`, `traces`, `elapsed_seconds`, `settings` |
| `operator resource list` | `operators` | `catalog`, `count` |
| `operator resource inspect` | `resource` | `catalog` |
| `pipeline add` | `pipeline` | `name`, `provenance`, `planning`, `settings` |
| `pipeline import` | `pipeline` | `name`, `preflight` |
| `pipeline list` | `pipelines` | `profile`, `count` |
| `pipeline inspect` | `pipeline` | `name`, `provenance`, `preflight` |
| `pipeline run` | `result` | `name`, `succeeded`, `failed_node_id`, `node_runs`, `elapsed_seconds`, `settings` |
| `metadata inspect` | `metadata` | — |

A key that is a list or a count is there even when it is empty, so a reader branches on what it says rather than on whether it arrived.

Every format strips terminal control characters from every cell, because operator output is whatever a model wrote or whatever came out of a data source, and an escape sequence in one walks the terminal cursor.

Progress, logs, warnings and errors go to standard error; the result goes to standard output.
Every format is safe to pipe, and the spinner is suppressed outright under `json`.

## Errors and exit codes

Errors reach the terminal as one line on standard error. `--log` also prints the CLI failure traceback. Registry and source failures use fixed diagnostic text; private backend exception text, SQL and paths are withheld before logging. Values that reach the logging formatter still pass through secret masking:

```text
ERROR: REQUEST no card for 'selct@2.0.0' in the active catalog. Run `blue-ops operator search selct` to see what is there.
```

The library has four structured failure taxonomies and none of them is a CLI code set, so this CLI declares ten codes, one per failure family, and carries the library's own code in the description and in the JSON error's `detail`.
The CLI code is what a script branches on; the library code is what diagnoses the failure.

| Code | Exit | Cause |
|---|---|---|
| — | 0 | Success, including an empty result and a declined confirmation |
| `INTERNAL` | 1 | An exception outside the classified families |
| `USAGE` | 2 | Usage error: unknown option, bad value, missing argument, an option on the wrong command, a confirmation with no terminal and no `--confirm` |
| `REQUEST` | 3 | `ResolveError`, `DiscoveryError` or `PipelineError`: the request names something that cannot be resolved, or input the library will not accept |
| `CONFIG` | 4 | A resolved configuration value the library refused, including a planner dependency that is not installed |
| `PROFILE` | 4 | A profile operation this CLI rejected: unknown profile, unknown parameter, a value that will not cast |
| `TRANSPORT` | 5 | The pipeline planner's provider timed out, rate-limited the call, or was unavailable |
| `RESOURCE` | 6 | `OperatorSkillLoadError`: an operator's resource package is missing, mismatched or invalid |
| `PLANNING` | 7 | Any other planning failure, with the `PlanningErrorCode` and its stage in the message |
| `EXECUTION` | 8 | An operator run returned a failed `ErrorRecord`, including a contained LLM provider failure. A `RECOVERABLE` record is not one: the run keeps exit 0, and the record is written to standard error |
| `TIMEOUT` | 9 | An operator run exceeded its time allowance |

`CONFIG` and `PROFILE` share exit 4 and are told apart by the code token.
Exits 0 through 5 carry the meanings the family's other guide-compliant CLI gave them; 6 through 9 are this library's own families.

Under `--format json` the same failure is also written to standard output as one object, so a machine consumer gets JSON either way:

```text
{
  "error": {
    "code": "REQUEST",
    "message": "no card for 'selct@2.0.0' in the active catalog. Run `blue-ops operator search selct` to see what is there.",
    "detail": {"library_code": "RESOLVE_ERROR", "operator_id": "selct@2.0.0", "catalog": "active"}
  }
}
```

`detail` is an object or `null`, and it is always there.
For a planning failure it carries the record's `library_code`, `category`, `stage`, `retryable` and `suggestion`; for a failed operator run it carries those plus the `operator_id`.

**Exit 2 belongs to Click's parser.**
A misspelled option or a value of the wrong type is refused before any command body runs, which means before the CLI knows what `--format` you asked for.
Those errors are always plain text on standard error, and they are the only ones that are.
Everything the CLI refuses after the parse is, under `--format json`, also an object on standard output — an unknown `--profile`, a profiles file that cannot be read, a profile value that will not cast.
One residue: if `BLUE_DATA_CLI_FORMAT` itself holds something that is not a format, the failure *is* the lookup that would have named the format, so with no `--format` on the command line there is nothing left to publish in and it reports as text.

## Next steps

- [quickstart.md](quickstart.md) — the same operators from Python
- [mcp.md](mcp.md) — the same operators as MCP tools
- [`lib/OPERATORS.md`](../lib/OPERATORS.md) — every operator's card, tags and attribute schema
