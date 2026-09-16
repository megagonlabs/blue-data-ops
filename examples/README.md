# Examples

Runnable programs for `blue-data-ops`, grouped by what you want from them: a first working result, one capability in depth, or two subsystems wired together.
Each script is a whole program that runs to completion and prints its result.
The repository's test suite executes every offline script on each supported interpreter, so the commands below are checked rather than described.

Run every command from the directory containing the main README, after the installation steps in the [library README](../lib/README.md).

Two of these scripts import the shared SQLite helper [`_sqlite_demo.py`](_sqlite_demo.py), which sits at the root of this directory rather than inside a category.
Python puts only a script's own directory on the import path, so those two commands add the examples root with `PYTHONPATH`.

## quickstart/ — the shortest program that produces a result, one per install profile

### Record transforms on in-memory data — [`core_quickstart.py`](quickstart/core_quickstart.py)

Resolves `select`, `avg`, `normalize_text`, and `union` from the active registry, then filters three order records down to the two above 100, averages their totals, trims whitespace from a `region` field into a new `region_norm` key, and unions the filtered group with one more record.
Every call asserts its own operator ID, so the script fails loudly if a registry view moves underneath it.

```bash
python examples/quickstart/core_quickstart.py
```


### A real SQLite database, registered and queried — [`sqlite_quickstart.py`](quickstart/sqlite_quickstart.py)

Builds a ten-row `orders` table in a temporary directory, registers it through `RegistrySeam`, and reads the rows back with a direct query.
It then creates a second database, inserts a row through `insert_table`, and finds the table by name through `data_discover`.
The temporary directory and everything in it are removed when the script exits.

```bash
PYTHONPATH=examples python examples/quickstart/sqlite_quickstart.py
```


### Local decision-tree classification — [`ml_quickstart.py`](quickstart/ml_quickstart.py)

Trains the `classify` operator on four labelled two-dimensional vectors and predicts two held-out samples.
`random_state` is pinned, so the prediction is the same on every run.

```bash
python examples/quickstart/ml_quickstart.py
```

**Requires:** the `ml` extra, installed as shown in the [library README](../lib/README.md#installation)

### Similarity from embeddings you already have — [`vector_quickstart.py`](quickstart/vector_quickstart.py)

Scores `vector_similarity` over two records whose embeddings are supplied in the script.
Nothing is downloaded and no model is loaded, which makes this the cheapest way to check that the vector install works.
The `Requires:` line below names the whole extra because that is the supported way to install these operators; this particular script brings its own vectors, so it runs on the numpy half alone.

```bash
python examples/quickstart/vector_quickstart.py
```

**Requires:** the `vector` extra, installed as shown in the [library README](../lib/README.md#installation)

## feature-demos/ — one capability per script, taken further than a quickstart needs

### Loading an operator's resources, and declining to — [`operator_skill_discovery.py`](feature-demos/operator_skill_discovery.py)

Searches the history registry for average operators, then splits the matches into the exact IDs that ship a resource package and the ones that do not.
`avg@1.0.0` is the case worth watching: it stays searchable for migration code, it carries no resource package, and the script prints it as skipped without ever calling `load()` on it.

```bash
python examples/feature-demos/operator_skill_discovery.py
```


### Two callers reaching the same card — [`operator_skill_integrations.py`](feature-demos/operator_skill_integrations.py)

Selects `avg@3.0.0` twice over: once through an embedding index built from a small local embedder, and once through the rule planner's discovery snapshot.
Both paths end at `describe()`, which reports what a resource package offers without reading it, so neither selection puts operator documentation in front of a model.

```bash
python examples/feature-demos/operator_skill_integrations.py
```


### What a pipeline run reports, including the failures — [`operator_outcomes.py`](feature-demos/operator_outcomes.py)

Executes the same two-node pipeline (insert, then average) three times against a real SQLite table: once with empty input, once with a record the insert rejects, and once with three readings.
The rejected run is the point of the script — execution stops at the failing node, the error arrives inside `ExecMeta` rather than as an exception, and a query afterwards confirms the table was never written to.
The successful run prints the full per-node metadata as JSON, including input and output shapes.

```bash
python examples/feature-demos/operator_outcomes.py
```


### Provider-backed scripts

The three scripts below send a request to a hosted model through the operator, so they are not independently runnable without a credential.
Each one exits immediately with a message when `OPENAI_API_KEY` is unset, and no offline substitute for the provider response exists.
The repository checks them by compiling each file, which catches a syntax error without spending provider traffic.
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
The embedder is deliberately crude, which keeps the example about the planner's seams rather than about embedding quality.
`allowed_operator_ids` includes a third operator the queries never select, so the printed discovery result shows the planner choosing rather than accepting a list.

```bash
python examples/integration-demos/embedding_planner.py
```


## Shared files

| File | Purpose |
|---|---|
| [`_sqlite_demo.py`](_sqlite_demo.py) | Builds the ten-row `orders` database and returns it as a registered `RegistrySeam`. Imported by the two SQLite scripts; not an example on its own. |
| [`coverage.json`](coverage.json) | Maps every runnable example to the exact operator IDs it exercises, and names the tag axes that belong in the generated reference without needing a script of their own. |

`coverage.json` is machine-checked: a test extracts the operator IDs each script actually names and fails if the map disagrees, so the map cannot drift from the scripts.
The generated [operator reference](../lib/OPERATORS.md) is the source of truth for per-operator metadata and tags.

## Every script at a glance

| Script | Requires |
|---|---|
| [`quickstart/core_quickstart.py`](quickstart/core_quickstart.py) | base install |
| [`quickstart/sqlite_quickstart.py`](quickstart/sqlite_quickstart.py) | base install |
| [`quickstart/ml_quickstart.py`](quickstart/ml_quickstart.py) | `ml` extra |
| [`quickstart/vector_quickstart.py`](quickstart/vector_quickstart.py) | `vector` extra |
| [`feature-demos/operator_skill_discovery.py`](feature-demos/operator_skill_discovery.py) | base install |
| [`feature-demos/operator_skill_integrations.py`](feature-demos/operator_skill_integrations.py) | base install |
| [`feature-demos/operator_outcomes.py`](feature-demos/operator_outcomes.py) | base install |
| [`feature-demos/nl2llm.py`](feature-demos/nl2llm.py) | `llm` extra, `OPENAI_API_KEY` |
| [`feature-demos/nl2sql_sqlite.py`](feature-demos/nl2sql_sqlite.py) | `llm` extra, `OPENAI_API_KEY` |
| [`feature-demos/semantic_filter.py`](feature-demos/semantic_filter.py) | `llm` extra, `OPENAI_API_KEY` |
| [`integration-demos/embedding_planner.py`](integration-demos/embedding_planner.py) | base install |
| [`_sqlite_demo.py`](_sqlite_demo.py) | base install |
