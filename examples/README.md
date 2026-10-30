# Examples

Runnable programs for `blue-data-ops`, grouped by what you want from them: a first working result, one capability in depth, or two subsystems wired together.
Each script is a whole program that runs to completion and prints its result.
Offline examples include captured output files. Provider-backed examples require `OPENAI_API_KEY`
and have no captured output.

Run every command from the directory containing the main README (the `blue-data-ops` repository root), after the installation steps in the [library README](../lib/README.md). If you installed from the shared parent directory, run `cd blue-data-ops` first.

The [CLI sample inputs](cli/) contain the order records and planning request used in the [`blue-ops` guide](../docs/cli.md).
The CLI commands read these JSON files as input.
The LLM examples also use [workspaces.json](cli/workspaces.json),
[llm-pipeline.json](cli/llm-pipeline.json), and [llm-input.json](cli/llm-input.json).
They require the LLM extra and deployment provider credentials when run against a provider.

Three of these scripts import the shared SQLite helper [`_sqlite_demo.py`](_sqlite_demo.py), which sits at the root of this directory rather than inside a category.
Python puts only a script's own directory on the import path, so those three commands add the examples root with `PYTHONPATH`.

## quickstart/ — the shortest program that produces a result, one per install profile

### Record transforms on in-memory data — [`core_quickstart.py`](quickstart/core_quickstart.py)

Resolves `select`, `avg`, `normalize_text`, and `union` from the active registry, then filters three order records down to the two above 100, averages their totals, trims whitespace from a `region` field into a new `region_norm` key, and unions the filtered group with one more record.

```bash
python examples/quickstart/core_quickstart.py
```

Captured output: [`core_quickstart.output.txt`](quickstart/core_quickstart.output.txt)


### A real SQLite database, registered and queried — [`sqlite_quickstart.py`](quickstart/sqlite_quickstart.py)

Builds a ten-row `orders` table in a temporary directory, registers it through `RegistrySeam`, and reads the rows back with a direct query.
It then creates a second database, inserts a row through `insert_table`, and finds the table by name through `data_discover`.
The temporary directory and everything in it are removed when the script exits.

```bash
PYTHONPATH=examples python examples/quickstart/sqlite_quickstart.py
```

Captured output: [`sqlite_quickstart.output.txt`](quickstart/sqlite_quickstart.output.txt)


### Local decision-tree classification — [`ml_quickstart.py`](quickstart/ml_quickstart.py)

Trains the `classify` operator on four labelled two-dimensional vectors and predicts two held-out samples.
`random_state` is pinned, so the prediction is the same on every run.

```bash
python examples/quickstart/ml_quickstart.py
```

Captured output: [`ml_quickstart.output.txt`](quickstart/ml_quickstart.output.txt)

**Requires:** the `ml` extra, installed as shown in the [library README](../lib/README.md#installation)

### Similarity from embeddings you already have — [`vector_quickstart.py`](quickstart/vector_quickstart.py)

Scores `vector_similarity` over two records whose embeddings are supplied in the script.
Nothing is downloaded and no model is loaded. The `Requires:` line below names the supported vector
extra; because the script supplies its own vectors, it runs with the NumPy part of that installation.

```bash
python examples/quickstart/vector_quickstart.py
```

Captured output: [`vector_quickstart.output.txt`](quickstart/vector_quickstart.output.txt)

**Requires:** the `vector` extra, installed as shown in the [library README](../lib/README.md#installation)

## feature-demos/ — one capability per script, taken further than a quickstart needs

### Loading an operator's resources, and declining to — [`operator_skill_discovery.py`](feature-demos/operator_skill_discovery.py)

Searches the history registry for average operators, then splits the matches into the exact IDs that ship a resource package and the ones that do not.
The script shows that `avg@1.0.0` remains searchable for migration code but has no resource package.
It prints the card as skipped without calling `load()` on it.

```bash
python examples/feature-demos/operator_skill_discovery.py
```

Captured output: [`operator_skill_discovery.output.txt`](feature-demos/operator_skill_discovery.output.txt)


### Two callers reaching the same card — [`operator_skill_integrations.py`](feature-demos/operator_skill_integrations.py)

Selects `avg@3.0.0` through two paths: an embedding index built from a small local embedder and the rule planner's discovery snapshot.
Both paths end at `describe()`, which reports what a resource package offers without reading it, so neither selection puts operator documentation in front of a model.

```bash
python examples/feature-demos/operator_skill_integrations.py
```

Captured output: [`operator_skill_integrations.output.txt`](feature-demos/operator_skill_integrations.output.txt)


### What a pipeline run reports, including the failures — [`operator_outcomes.py`](feature-demos/operator_outcomes.py)

Executes the same two-node pipeline (insert, then average) three times against a real SQLite table: once with empty input, once with a record the insert rejects, and once with three readings.
The rejected run shows that execution stops at the failing node, reports the error in `ExecMeta` rather than as an exception, and leaves the table unchanged.
The successful run prints the full per-node metadata as JSON, including input and output shapes.

```bash
python examples/feature-demos/operator_outcomes.py
```

Captured output: [`operator_outcomes.output.txt`](feature-demos/operator_outcomes.output.txt), with the timing scrub below applied.

### Model and effort precedence (offline) — [`llm_settings.py`](feature-demos/llm_settings.py)

Runs `nl2llm` with a recording client to show direct-call, invocation, stored-pipeline, and
operator-node settings. It makes no provider request, and the model names are placeholders.

```bash
python examples/feature-demos/llm_settings.py
```

Captured output: [`llm_settings.output.txt`](feature-demos/llm_settings.output.txt)

**Requires:** the `llm` extra. See [LLM settings](../docs/llm-settings.md) for CLI and MCP calls.


### Provider-backed scripts

The three scripts below send a request to a hosted model through the operator, so they are not independently runnable without a credential.
Each one exits immediately with a message when `OPENAI_API_KEY` is unset, and no offline substitute for the provider response exists.
They have no `.output.txt` because provider responses can vary between runs.
Run them with your own key exported.
In each block below, `<your-key>` is a placeholder: substitute your own key and do not commit it.
No key is stored anywhere in this repository.
Each script sets the model through the properties mapping in its `run()` call, which is where to change it.

#### Natural language to typed records — [`nl2llm.py`](feature-demos/nl2llm.py)

Asks for two example products under a declared attribute schema and returns them as records.

```bash
export OPENAI_API_KEY=<your-key>
python examples/feature-demos/nl2llm.py
```

**Requires:** the `llm` extra and `OPENAI_API_KEY`

#### Natural language to SQL against a real schema — [`nl2sql_sqlite.py`](feature-demos/nl2sql_sqlite.py)

Builds the same ten-row `orders` database as the SQLite quickstart, then asks for the region with the highest total order value and prints the generated SQL.
Generation and execution are separate: the query is returned but not run unless you pass `--execute`.
The registry schema projection gives the model the `orders` table name but not its columns. This example supplies the known SQLite column names through the operator's `context` attribute so the model can use `region` and `total`.
The `SELECT` prefix check is a guard against obvious misuse, not a SQL parser, so database permissions remain your responsibility.

```bash
export OPENAI_API_KEY=<your-key>
PYTHONPATH=examples python examples/feature-demos/nl2sql_sqlite.py --execute
```

**Requires:** the `llm` extra and `OPENAI_API_KEY`

#### Filtering records by a written condition — [`semantic_filter.py`](feature-demos/semantic_filter.py)

Filters a two-record product list down to the records whose description reads as "made mostly from wood", which no keyword match would get right.

```bash
export OPENAI_API_KEY=<your-key>
python examples/feature-demos/semantic_filter.py
```

**Requires:** the `llm` extra and `OPENAI_API_KEY`

## integration-demos/ — discovery and planning working together on one dataset

### Embedding discovery feeding the local planner — [`embedding_planner.py`](integration-demos/embedding_planner.py)

Builds an `OperatorEmbeddingIndex` over the active registry from a keyword embedder defined in the script, hands `PipelinePlanner` two discovery queries in plain English, and executes the pipeline the rule generator produces.
The script uses a small keyword embedder to exercise planner integration without requiring an embedding model.
`allowed_operator_ids` includes a third operator the queries never select, so the printed discovery result shows the planner choosing rather than accepting a list.

```bash
python examples/integration-demos/embedding_planner.py
```

Captured output: [`embedding_planner.output.txt`](integration-demos/embedding_planner.output.txt)

### Live discovery, LLM planning, and NL2SQL — [`openai_planner_sqlite.py`](integration-demos/openai_planner_sqlite.py)

Builds an embedding index over all 33 active operator cards and creates a temporary ten-row SQLite database through Blue's real registry and source.
Tag discovery first finds the three query-head operators: `nl2bn`, `nl2llm`, and `nl2sql`.
Embedding discovery then ranks the full active catalog against the question.
`OpenAIPlanGenerator`, not a rule or fixed template, receives the combined discovered catalog and chooses the plan.
The NL2SQL attributes in the request constrain its database address if the model selects it; they do not force that selection.
For the default question, the expected selection is `nl2sql@3.0.0`, which returns a generated `SELECT` without executing it.
This is an NL2SQL demonstration, so the command exits nonzero if the planner selects another operator.

The script prints the active allowlist, tag matches, embedding ranking, combined discovery snapshot, model-visible read-only candidates, selected steps, preflight result, and generated SQL.
It makes four outbound calls: one batch for the operator documents, one for the question embedding, one for the plan, and one inside NL2SQL for SQL generation.
The embedding cache prevents the planner from sending the same question embedding twice.
The planner provider receives the question, operator metadata, caller-constrained NL2SQL address, and a registry-derived schema snapshot, but no database rows.
NL2SQL separately sends the question and its current registry-derived schema to its configured model.
That inner schema currently includes the `orders` entity but not its separately registered columns, so the default count query deliberately needs no column names.
A shared column-aware projection is required before this example can claim broader source-backed coverage.

```bash
export OPENAI_API_KEY=<your-key>
PYTHONPATH=examples python examples/integration-demos/openai_planner_sqlite.py \
  --question "How many orders are there?" \
  --planner-model gpt-6-luna \
  --embedding-model text-embedding-3-small \
  --nl2sql-model gpt-6-luna
```

**Requires:** the `openai` and `llm` extras and `OPENAI_API_KEY`


## Shared files

| File | Purpose |
|---|---|
| [`_sqlite_demo.py`](_sqlite_demo.py) | Builds the ten-row `orders` database and returns it as a registered `RegistrySeam`. Imported by the three SQLite scripts; not an example on its own. |
| [`coverage.json`](coverage.json) | Maps each runnable example to the operator IDs it uses and lists tag axes covered by the generated reference. |
| `<script>.output.txt` | What that script printed to standard output on a real run, captured beside it. One per offline script, nine in all. |

The generated [operator reference](../lib/OPERATORS.md) is the source of truth for per-operator metadata and tags.

### Re-capturing an output file

Run the command shown for the script and redirect standard output to its adjacent `.output.txt` file.
Standard error is not part of the captured result. For `operator_outcomes.py`, replace each varying
`elapsed_ms` value with `0.0` before committing the refreshed output.

## Every script at a glance

| Script | Requires | Captured output |
|---|---|---|
| [`quickstart/core_quickstart.py`](quickstart/core_quickstart.py) | base install | [yes](quickstart/core_quickstart.output.txt) |
| [`quickstart/sqlite_quickstart.py`](quickstart/sqlite_quickstart.py) | base install | [yes](quickstart/sqlite_quickstart.output.txt) |
| [`quickstart/ml_quickstart.py`](quickstart/ml_quickstart.py) | `ml` extra | [yes](quickstart/ml_quickstart.output.txt) |
| [`quickstart/vector_quickstart.py`](quickstart/vector_quickstart.py) | `vector` extra | [yes](quickstart/vector_quickstart.output.txt) |
| [`feature-demos/operator_skill_discovery.py`](feature-demos/operator_skill_discovery.py) | base install | [yes](feature-demos/operator_skill_discovery.output.txt) |
| [`feature-demos/operator_skill_integrations.py`](feature-demos/operator_skill_integrations.py) | base install | [yes](feature-demos/operator_skill_integrations.output.txt) |
| [`feature-demos/operator_outcomes.py`](feature-demos/operator_outcomes.py) | base install | [yes, timings scrubbed](feature-demos/operator_outcomes.output.txt) |
| [`feature-demos/llm_settings.py`](feature-demos/llm_settings.py) | `llm` extra; no credential | [yes](feature-demos/llm_settings.output.txt) |
| [`feature-demos/nl2llm.py`](feature-demos/nl2llm.py) | `llm` extra, `OPENAI_API_KEY` | no — a provider answers |
| [`feature-demos/nl2sql_sqlite.py`](feature-demos/nl2sql_sqlite.py) | `llm` extra, `OPENAI_API_KEY` | no — a provider answers |
| [`feature-demos/semantic_filter.py`](feature-demos/semantic_filter.py) | `llm` extra, `OPENAI_API_KEY` | no — a provider answers |
| [`integration-demos/embedding_planner.py`](integration-demos/embedding_planner.py) | base install | [yes](integration-demos/embedding_planner.output.txt) |
| [`integration-demos/openai_planner_sqlite.py`](integration-demos/openai_planner_sqlite.py) | `openai` and `llm` extras, `OPENAI_API_KEY` | no — providers answer |
| [`_sqlite_demo.py`](_sqlite_demo.py) | base install | not a script of its own |

The NL2SQL demos generate SQL by default. The feature demo's `--execute` path binds
`ReadOnlySQLExecutor` to its pre-existing temporary SQLite database. The OpenAI planner
SQLite demo uses stock operators and generates SQL only. The built-in-only OpenAI
generator currently refuses custom registry cards. Python rule planning and
`PipelineExecutor` can share a custom registry containing the host-configured instance. Request properties cannot install an executor or select
a registry for execution. See [SQL execution](../docs/llm-settings.md#sql-execution).
