# Operator reference

This reference covers the live `@2.0.0` cards in `versioned_registry()` and their
fixture-backed outcomes. The snippets assume this registry:

```python
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
```

Each snippet sets `properties = None` when no dependency is needed. Profiles `seam` and
`seam_sql` require a registry seam; `llm` and `llm_refine` require a model client;
`llm_seam` requires both. The runnable examples show those injections.

## Tag taxonomy

Tags are exact metadata, not free-text synonyms. A `find()` call with more than one tag
uses AND semantics. Free-text scoring ranks only the cards that pass the tag filter.

| Axis | Meaning | Values |
|---|---|---|
| `capability-*` | operation performed | `capability-average`, `capability-bayesian-query`, `capability-classification`, `capability-clustering`, `capability-create-database`, `capability-create-table`, `capability-delete`, `capability-discovery`, `capability-embedding`, `capability-embedding-filter`, `capability-extraction`, `capability-extrema`, `capability-filter`, `capability-generation`, `capability-insert`, `capability-intersection`, `capability-join`, `capability-metadata-search`, `capability-normalization`, `capability-operator-discovery`, `capability-persist`, `capability-projection`, `capability-query-decomposition`, `capability-query-execution`, `capability-query-generation`, `capability-query-orchestration`, `capability-query-routing`, `capability-record-selection`, `capability-reduction`, `capability-search`, `capability-segmentation`, `capability-similarity`, `capability-sql`, `capability-sum`, `capability-transformation`, `capability-union` |
| `domain-*` | data or reasoning family | `domain-arithmetic`, `domain-ml`, `domain-plan`, `domain-query-compound`, `domain-relational`, `domain-semantic`, `domain-set`, `domain-text`, `domain-vector` |
| `flow-*` | position in a pipeline | `flow-aggregate`, `flow-combine`, `flow-control`, `flow-head`, `flow-plan`, `flow-sink`, `flow-transform` |
| `accepts-*` | input shape | `accepts-data`, `accepts-metadata`, `accepts-none`, `accepts-query` |
| `produces-*` | output or side effect | `produces-data`, `produces-metadata`, `produces-plan`, `produces-query`, `produces-side-effect` |
| `requires-*` | runtime dependency or integration | `requires-data-registry`, `requires-database-backend`, `requires-llm`, `requires-ml`, `requires-operator-registry`, `requires-query-backend`, `requires-vector` |

```python
cards = registry.find(
    "filter",
    tags=["domain-relational", "flow-transform"],
)
```

## `argmax@2.0.0`

Given an input data, find the record(s) that contain the maximum value for a specified key.

When to invoke: Use when the result must retain the input record or tied records with the largest value for one key.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-extrema`, `capability-record-selection`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `argmax_key` | `str` | yes | `—` | The key to find the maximum value for |
| `return_index` | `bool` | no | `false` | If True, returns indices (0-based) instead of records, otherwise returns records |

Fixture-backed call:

```python
input_data = [[{'value': 3}, {'value': '5'}, {'value': 5}]]
attributes = {'argmax_key': 'value'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('argmax@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `argmax_key`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `argmin@2.0.0`

Given an input data, find the record(s) that contain the minimum value for a specified key.

When to invoke: Use when the result must retain the input record or tied records with the smallest value for one key.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-extrema`, `capability-record-selection`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `argmin_key` | `str` | yes | `—` | The key to find the minimum value for |
| `return_index` | `bool` | no | `false` | If True, returns indices (0-based) instead of records, otherwise returns records |

Fixture-backed call:

```python
input_data = [[{'value': 3}, {'value': '5'}, {'value': 5}]]
attributes = {'argmin_key': 'value'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('argmin@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `argmin_key`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `avg@2.0.0`

Given an input data, calculate the average (arithmetic mean) of values for a specified key across all records.

When to invoke: Use when a numeric key must be reduced to its arithmetic mean across records.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-average`, `capability-reduction`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `avg_key` | `str` | yes | `—` | The key to average the values for |
| `output_key` | `str` | no | `"avg"` | The key name for the result average |

Fixture-backed call:

```python
input_data = [[{'value': 3}, {'value': '5'}, {'value': 5}]]
attributes = {'avg_key': 'value'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('avg@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: output `[[{"avg":0}]]`.
- Invalid: validation suggestion contains `avg_key`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `classify@2.0.0`

Given input data with numeric vectors and training labels, train a classifier and predict class labels for each sample using DecisionTreeClassifier, KNeighborsClassifier, or MultinomialNB.

When to invoke: Use when labeled numeric vectors are available and class labels are needed for input samples.

Tags: `domain-ml`, `flow-transform`, `accepts-data`, `produces-data`, `capability-classification`, `requires-ml`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `vector_key` | `str` | yes | `—` | The key to the numeric vector values (features) |
| `label_key` | `str` | yes | `—` | The key to the target class labels |
| `output_key` | `str` | no | `"predicted_label"` | The key name for the predicted labels |
| `criterion` | `str` | no | `"gini"` | Function to measure split quality for decision_tree |
| `splitter` | `str` | no | `"best"` | Strategy to choose the split for decision_tree |
| `max_depth` | `int` | no | `—` | The maximum depth of the tree for decision_tree |
| `min_samples_split` | `float` | no | `2` | Minimum samples to split an internal node for decision_tree |
| `min_samples_leaf` | `float` | no | `1` | Minimum samples to be at a leaf node for decision_tree |
| `random_state` | `int` | no | `—` | Controls the randomness for decision_tree |
| `n_neighbors` | `int` | no | `5` | Number of neighbors to use for kneighbors queries for knn |
| `weights` | `str` | no | `"uniform"` | Weight function used in prediction for knn |
| `alpha` | `float` | no | `1.0` | Additive smoothing parameter for multinomial_nb |
| `fit_prior` | `bool` | no | `true` | Whether to learn class prior probabilities for multinomial_nb |

Fixture-backed call:

```python
input_data = [[{'label': 'a', 'vector': [0.0, 0.0]}, {'label': 'a', 'vector': [0.0, 1.0]}, {'label': 'b', 'vector': [10.0, 10.0]}, {'label': 'b', 'vector': [10.0, 11.0]}], [{'vector': [0.0, 0.0]}, {'vector': [10.0, 10.0]}]]
attributes = {'label_key': 'label', 'random_state': 42, 'vector_key': 'vector'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('classify@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `label_key`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `cluster@2.0.0`

Given input data with numeric vectors, compute clusters and predict cluster index for each sample using KMeans, DBSCAN, or GaussianMixture.

When to invoke: Use when unlabeled numeric vectors must be assigned to clusters.

Tags: `domain-ml`, `flow-transform`, `accepts-data`, `produces-data`, `capability-clustering`, `requires-ml`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `vector_key` | `str` | yes | `—` | The key to the numeric vector values |
| `n_cluster` | `int` | no | `—` | The number of clusters to form |
| `output_key` | `str` | no | `"cluster_index"` | The key name for the predicted labels |
| `eps` | `float` | no | `0.5` | Max distance between two samples for DBSCAN |
| `min_samples` | `int` | no | `5` | Number of samples in a neighborhood for DBSCAN |
| `covariance_type` | `str` | no | `"full"` | Covariance type for Gaussian Mixture |
| `init` | `str` | no | `—` | Method for initialization |
| `init_centroids` | `list` | no | `—` | Required when init='specified' |
| `max_iter` | `int` | no | `300` | Maximum number of iterations |

Fixture-backed call:

```python
input_data = [[{'vector': [0.0, 0.0]}, {'vector': [0.0, 1.0]}, {'vector': [10.0, 10.0]}, {'vector': [10.0, 11.0]}]]
attributes = {'n_cluster': 2, 'vector_key': 'vector'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('cluster@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `clustering`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `create_database@2.0.0`

Creates databases in data sources using the data registry. If the database already exists, it will be overwritten if overwrite is True.

When to invoke: Use when one or more databases must be created or overwritten through the data registry.

Tags: `domain-relational`, `flow-control`, `accepts-data`, `accepts-none`, `produces-data`, `produces-side-effect`, `capability-create-database`, `requires-data-registry`, `requires-database-backend`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `source` | `str` | yes | `""` | Name of the data source where the database will be created |
| `database` | `str` | yes | `""` | Name of the database to be created |
| `description` | `str` | no | `""` | Description of the database to be created |
| `properties` | `str` | no | `{}` | Properties of the database to be created |
| `created_by` | `str` | no | `""` | Creator of the database |
| `overwrite` | `bool` | no | `false` | Whether to overwrite the existing database |

Fixture-backed call:

```python
input_data = [[{'name': 'row', 'value': 1}]]
attributes = {'database': 'db', 'source': 'src'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('create_database@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `seam`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `source`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `create_table@2.0.0`

Creates tables (entities) in database collections using the data registry. If the table already exists, it will be overwritten if overwrite is True.

When to invoke: Use when tables or entities must be created or overwritten in registry-backed database collections.

Tags: `domain-relational`, `flow-control`, `accepts-data`, `accepts-none`, `produces-data`, `produces-side-effect`, `capability-create-table`, `requires-data-registry`, `requires-database-backend`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `source` | `str` | yes | `"default_source"` | Name of the data source where the table will be created |
| `database` | `str` | yes | `"default"` | Name of the database where the table will be created |
| `collection` | `str` | no | `"public"` | Name of the collection where the table will be created. For SQLite sources, defaults to 'public' if not specified |
| `table` | `str` | yes | `""` | Name of the table to be created |
| `description` | `str` | no | `""` | Description of the table to be created |
| `properties` | `str` | no | `{}` | Properties of the table to be created |
| `columns` | `list` | yes | `[]` | Properties of the table to be created |
| `misc` | `dict` | no | `{}` | Miscellaneous keys such as primary and foreign keys  |
| `created_by` | `str` | no | `""` | Creator of the table |
| `overwrite` | `bool` | no | `false` | Whether to overwrite the existing table |

Fixture-backed call:

```python
input_data = [[{'name': 'row', 'value': 1}]]
attributes = {'columns': [{'name': 'a', 'type': 'INTEGER'}], 'database': 'db', 'source': 'src', 'table': 't'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('create_table@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `seam`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `columns`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `data_discover@2.0.0`

Discovers data sources using the data registry

When to invoke: Use when data sources, databases, collections, or entities must be found through registry search.

Tags: `domain-plan`, `flow-head`, `accepts-none`, `produces-metadata`, `capability-discovery`, `capability-metadata-search`, `requires-data-registry`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `search_query` | `str` | yes | `""` | Text to search for in source names and descriptions |
| `approximate` | `bool` | yes | `true` | Whether to use approximate (vector) search |
| `hybrid` | `bool` | no | `false` | Whether to use hybrid search (text + vector) |
| `limit` | `int` | no | `-1` | Max number of results to return (-1, unlimited) |
| `page` | `int` | no | `0` | Page number for pagination |
| `page_size` | `int` | no | `10` | Number of results per page (default: 10, max: 100) |
| `include_metadata` | `bool` | no | `false` | Whether to include metadata in results (description and properties always included) |
| `threshold` | `float` | no | `0.5` | Similarity threshold for filtering results (0.0-1.0, lower = more similar, only applies to approximate/hybrid search) |
| `progressive_pagination` | `bool` | no | `false` | Whether to use progressive pagination for approximate/hybrid search (searches all pages until threshold exceeded) |
| `concept_type` | `str` | no | `"source"` | Record type to search for (e.g., 'source', 'database', 'collection', 'entity', 'attribute', 'relation') |
| `use_hierarchical_search` | `bool` | no | `true` | Whether to use hierarchical search or regular search |
| `scope` | `str` | no | `null` | Base search scope. When omitted, source, database, and collection do not construct one |
| `source` | `str` | no | `null` | Source component. Refines an explicit scope only; it does not construct one when scope is omitted |
| `database` | `str` | no | `null` | Database component; requires source. Refines an explicit scope only; it does not construct one when scope is omitted |
| `collection` | `str` | no | `null` | Collection component; requires source and database. Refines an explicit scope only; it does not construct one when scope is omitted |
| `auto_construct_scope` | `bool` | no | `true` | Rebuild an explicit scope from source, database, and collection when true; use that scope unchanged when false. Has no effect when scope is omitted |
| `filter_names` | `list` | no | `[]` | Filter out results with matching names in the filter list |

Fixture-backed call:

```python
input_data = [[]]
attributes = {'approximate': False, 'search_query': 'orders'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('data_discover@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `seam`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `search query`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `delete@2.0.0`

Given input data, delete records from the first data source at specified positions

When to invoke: Use when records must be removed from the first input group by position.

Tags: `domain-relational`, `flow-transform`, `accepts-data`, `produces-data`, `capability-delete`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `delete_idx` | `Union[int, list[int]]` | no | `[]` | Position(s) to delete records. Supports negative indexing (-1 = last, -2 = second to last, etc.) |

Fixture-backed call:

```python
input_data = [[{'id': 1, 'name': 'A', 'score': 1}, {'id': 2, 'name': 'B', 'score': 2}]]
attributes = {'delete_idx': 0}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('delete@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `integer`.
- Failure: No separate fixture case.

## `insert@2.0.0`

Given input data, insert records by position(s)

When to invoke: Use when records from input groups must be inserted at specified positions.

Tags: `domain-relational`, `flow-combine`, `flow-transform`, `accepts-data`, `produces-data`, `capability-insert`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `insert_records` | `list[dict]` | no | `[]` | List of records to insert into the first data source (optional if second data group provided) |
| `insert_idx` | `Union[int, list[int]]` | no | `-1` | Position(s) to insert records (-1 for append, 0+ for specific position). If list, each element corresponds to position for each record |

Fixture-backed call:

```python
input_data = [[{'id': 1, 'name': 'A', 'score': 1}, {'id': 2, 'name': 'B', 'score': 2}]]
attributes = {'insert_idx': 1, 'insert_records': [{'id': 3, 'name': 'C', 'score': 3}]}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('insert@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `insert_records`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `insert_table@2.0.0`

Inserts data rows into database tables in a data source.

When to invoke: Use when record rows must be persisted into a registry-backed database table.

Tags: `domain-relational`, `flow-sink`, `accepts-data`, `produces-data`, `produces-side-effect`, `capability-persist`, `requires-data-registry`, `requires-database-backend`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `source` | `str` | yes | `"default_source"` | Name of the data source where the table is located |
| `database` | `str` | yes | `"default"` | Name of the database where the table is located |
| `collection` | `str` | no | `"public"` | Name of the collection where the table is located. For SQLite sources, defaults to 'public' if not specified |
| `table` | `str` | yes | `""` | Name of the table to insert data into |
| `batch_size` | `int` | no | `100` | Number of rows to insert in each batch (default: 100) |

Fixture-backed call:

```python
input_data = [[{'a': 1}, {'a': 2}]]
attributes = {'database': 'db', 'source': 'src', 'table': 't'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('insert_table@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `seam_sql`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `batch size`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `intersect@2.0.0`

Given multiple input data sources, return only records that exist in all data sources

When to invoke: Use when only records shared by all input groups should remain under the configured match rule.

Tags: `domain-set`, `flow-combine`, `accepts-data`, `produces-data`, `capability-intersection`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `match_option` | `str` | no | `"key_match"` | Matching strategy for record comparison: 'key_match' (exact field names and values) or 'seq_match' (position-based comparison regardless of field names) |

Fixture-backed call:

```python
input_data = [[{'id': 1}, {'id': 2}], [{'id': 2}, {'id': 3}]]
attributes = {}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('intersect@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `match_option`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `join@2.0.0`

Joins multiple JSON array data sources using N-way join operations

When to invoke: Use when two or more JSON record groups must be joined on configured keys and join types.

Tags: `domain-relational`, `flow-combine`, `accepts-data`, `produces-data`, `capability-join`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `join_on` | `list[list[str]]` | yes | `—` | List of join key lists for each data source |
| `join_type` | `str` | no | `"inner"` | Type of join: 'inner', 'left', 'right', 'outer' |
| `join_suffix` | `list[str]` | no | `[]` | Suffixes for non-key fields |
| `keep_keys` | `str` | no | `"left"` | 'left' to keep left keys only, 'both' to keep both |

Fixture-backed call:

```python
input_data = [[{'id': 1, 'left': 'L1'}, {'id': 2, 'left': 'L2'}], [{'id': 2, 'right': 'R2'}, {'id': 3, 'right': 'R3'}]]
attributes = {'join_on': [['id'], ['id']]}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('join@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `join_on`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `max@2.0.0`

Given an input data, find the maximum value for a specified key across all records.

When to invoke: Use when a numeric key must be reduced to its largest value.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-extrema`, `capability-reduction`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `max_key` | `str` | yes | `—` | The key to find the maximum value for |
| `output_key` | `str` | no | `"max"` | The key name for the result max value |

Fixture-backed call:

```python
input_data = [[{'value': 3}, {'value': '5'}, {'value': 5}]]
attributes = {'max_key': 'value'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('max@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: output `[[{"max":null}]]`.
- Invalid: validation suggestion contains `max_key`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `min@2.0.0`

Given an input data, find the minimum value for a specified key across all records.

When to invoke: Use when a numeric key must be reduced to its smallest value.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-extrema`, `capability-reduction`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `min_key` | `str` | yes | `—` | The key to find the minimum value for |
| `output_key` | `str` | no | `"min"` | The key name for the result min value |

Fixture-backed call:

```python
input_data = [[{'value': 3}, {'value': '5'}, {'value': 5}]]
attributes = {'min_key': 'value'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('min@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: output `[[{"min":null}]]`.
- Invalid: validation suggestion contains `min_key`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `multipart_query@2.0.0`

Orchestrates the execution of multi-part query, starting with data discovery, leading to execution

When to invoke: Use when alternative multi-part query specifications must be refined into ordered data-query plans.

Tags: `domain-plan`, `flow-plan`, `accepts-query`, `produces-plan`, `capability-query-orchestration`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `serialize` | `bool` | no | `true` | Whether to use serialize each part of the query |

Fixture-backed call:

```python
input_data = [[]]
attributes = {}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('multipart_query@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `multipart-query`.
- Failure: `REFINEMENT_FAILED` at `REFINE`.

## `nl2bn@2.0.0`

Translates natural language questions into Bayesian Network queries using LLM models

When to invoke: Use when a natural-language question must be translated into a Bayesian-network query.

Tags: `domain-query-compound`, `flow-head`, `accepts-none`, `produces-data`, `capability-bayesian-query`, `capability-query-execution`, `capability-query-generation`, `requires-data-registry`, `requires-llm`, `requires-query-backend`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `question` | `str` | yes | `—` | Natural language question to translate to BN query |
| `source` | `str` | yes | `""` | BN data source name |
| `database` | `str` | yes | `""` | Database name |
| `collection` | `str` | yes | `""` | Collection/model name |
| `protocol_variant` | `str` | yes | `"pgmpy"` | Protocol variant (e.g., 'pgmpy') |
| `context` | `str` | no | `""` | Optional context for domain knowledge |
| `schema` | `str` | no | `""` | JSON string of BN schema (optional - will be fetched automatically if not provided) |
| `explanation` | `bool` | no | `true` | Return natural language explanation for the answer |
| `structured_explanation` | `bool` | no | `false` | Return structured explanation (only effective when explanation is True) |
| `max_corrections` | `int` | no | `2` | Maximum number of correction attempts for query validation |
| `max_num_paths` | `int` | no | `50` | Maximum number of reasoning paths to include in explanation (default: 50) |

Fixture-backed call:

```python
input_data = [[]]
attributes = {'collection': 'weather', 'database': 'default', 'protocol_variant': 'pgmpy', 'question': 'What is the probability of wet given rain?', 'source': 'bn'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('nl2bn@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `llm_seam`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `Bayesian-network`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `nl2llm@2.0.0`

Processes natural language query using LLM models and returns structured data

When to invoke: Use when a natural-language request should be sent to the configured reasoning provider and returned as structured data.

Tags: `domain-query-compound`, `flow-head`, `accepts-none`, `produces-data`, `capability-generation`, `requires-llm`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `query` | `str` | yes | `—` | Natural language query to process |
| `context` | `str` | no | `""` | Optional context to provide domain knowledge |
| `attrs` | `list[dict]` | no | `[]` | List of attribute specifications (dicts with name and optional type) |

Fixture-backed call:

```python
input_data = [[]]
attributes = {'query': 'list roles'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('nl2llm@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `llm`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `natural-language query`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `nl2query_router@2.0.0`

Routees the execution of query, based on source

When to invoke: Use when discovered source metadata must be refined into a source-specific query plan.

Tags: `domain-plan`, `flow-plan`, `accepts-metadata`, `produces-plan`, `capability-query-routing`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `search_query` | `str` | yes | `—` | Natural language query to process |
| `columns` | `list[dict]` | no | `[]` | List of attribute specifications (dicts with name and optional type) |
| `execute_query` | `bool` | no | `true` | Whether to execute query or just translate nl to query |
| `protocol` | `str` | no | `""` | Protocol of the source |

Fixture-backed call:

```python
input_data = [[]]
attributes = {'columns': [{'name': 'value'}], 'execute_query': False, 'protocol': 'sqlite', 'search_query': 'find rows'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('nl2query_router@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `query-routing`.
- Failure: No separate fixture case.

## `nl2sql@2.0.0`

Translates natural language questions into SQL queries using LLM models

When to invoke: Use when a natural-language question must be translated into SQL, with optional execution.

Tags: `domain-query-compound`, `flow-head`, `accepts-none`, `produces-data`, `produces-query`, `capability-query-execution`, `capability-query-generation`, `capability-sql`, `requires-data-registry`, `requires-llm`, `requires-query-backend`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `source` | `str` | yes | `""` | Data source name |
| `question` | `str` | yes | `—` | Natural language question to translate to SQL |
| `protocol` | `str` | yes | `"postgres"` | Database protocol (postgres, mysql, sqlite) |
| `database` | `str` | yes | `""` | Database name |
| `collection` | `str` | yes | `""` | Collection/schema name |
| `case_insensitive` | `bool` | no | `true` | Case insensitive string matching |
| `additional_requirements` | `str` | no | `""` | Additional requirements for SQL generation |
| `context` | `str` | no | `""` | Optional context for domain knowledge |
| `schema` | `str` | no | `""` | JSON string of database schema (optional - will be fetched automatically if not provided) |
| `attr_names` | `list[str]` | no | `[]` | Optional list of target field names for the output objects |

Fixture-backed call:

```python
input_data = [[]]
attributes = {'collection': 'public', 'database': 'analytics', 'protocol': 'postgres', 'question': 'Which role is most common?', 'source': 'pg'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('nl2sql@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `llm_seam`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `SQL`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `normalize_text@2.0.0`

Normalize raw text into a stable canonical form for downstream extraction and segmentation.

When to invoke: Use when text needs canonical Unicode, whitespace, case, or recognized-date normalization before later text work.

Tags: `domain-text`, `flow-transform`, `accepts-data`, `produces-data`, `capability-normalization`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `text_field` | `list[str]` | yes | `—` | List of input text fields to normalize |
| `delimiter` | `str` | no | `"\n"` | Delimiter used to concatenate multiple text fields |
| `strip_newline` | `bool` | no | `false` | Whether to collapse line breaks into spaces |
| `normalize_unicode` | `str` | no | `"NFKC"` | Unicode normalization mode |
| `normalize_whitespace` | `bool` | no | `true` | Whether to collapse repeated spaces and tabs |
| `normalize_bullets` | `bool` | no | `true` | Whether to normalize common bullet markers to a hyphen |
| `normalize_dates` | `bool` | no | `false` | Whether to normalize unambiguous date strings to YYYY-MM-DD |
| `strip_control_chars` | `bool` | no | `true` | Whether to strip control characters |
| `max_chars` | `int` | no | `—` | Maximum number of characters to keep after normalization |

Fixture-backed call:

```python
input_data = [[{'text': '  Hello\xa0world  '}]]
attributes = {'text_field': ['text']}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('normalize_text@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `valid input attributes`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `plan_discover@2.0.0`

Discovers plans using the operator registry to search for top-level operators as plan starters

When to invoke: Use when a task description must be matched to pinned operators and emitted as starter plans.

Tags: `domain-plan`, `flow-plan`, `accepts-none`, `produces-plan`, `capability-operator-discovery`, `requires-operator-registry`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `task` | `str` | yes | `""` | Task to discover plans/operators |
| `data` | `str` | yes | `""` | Data to operate the task on |
| `approximate` | `bool` | yes | `true` | Whether to use approximate (vector) search |
| `hybrid` | `bool` | no | `false` | Whether to use hybrid search (text + vector) |
| `limit` | `int` | no | `-1` | Max number of results to return (-1, unlimited) |
| `page` | `int` | no | `0` | Page number for pagination |
| `page_size` | `int` | no | `10` | Number of results per page (default: 10, max: 100) |
| `include_metadata` | `bool` | no | `false` | Whether to include metadata in results (description and properties always included) |
| `threshold` | `float` | no | `0.5` | Similarity threshold for filtering results (0.0-1.0, lower = more similar, only applies to approximate/hybrid search) |
| `progressive_pagination` | `bool` | no | `false` | Whether to use progressive pagination for approximate/hybrid search (searches all pages until threshold exceeded) |

Fixture-backed call:

```python
input_data = [[]]
attributes = {'approximate': True, 'data': 'rows', 'task': 'starter'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('plan_discover@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `supply valid input attributes`.
- Failure: No separate fixture case.

## `project@2.0.0`

Given an input data, return only a set of attributes for each data element (key-wise)

When to invoke: Use when each record should retain and optionally rename a specified set of keys without semantic inference.

Tags: `domain-relational`, `flow-transform`, `accepts-data`, `produces-data`, `capability-projection`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `kept_keys` | `list[str]` | yes | `—` | List of keys to keep in each record |
| `key_mapping` | `dict[str, str]` | no | `{}` | Dictionary mapping old key names to new key names |

Fixture-backed call:

```python
input_data = [[{'id': 1, 'name': 'A', 'score': 1}, {'id': 2, 'name': 'B', 'score': 2}]]
attributes = {'kept_keys': ['id']}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('project@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `kept_keys`.
- Failure: No separate fixture case.

## `query_breakdown@2.0.0`

Processes natural language query and break it down to subqueries using common table expressions

When to invoke: Use when a natural-language query must be decomposed into alternative common-table-expression plans.

Tags: `domain-plan`, `flow-plan`, `accepts-none`, `produces-plan`, `produces-query`, `capability-query-decomposition`, `requires-llm`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `query` | `str` | yes | `—` | Natural language query to process |
| `context` | `str` | no | `""` | Optional context to provide domain knowledge |
| `schema` | `str` | no | `[]` | Optional schema to match |
| `num_alternatives` | `int` | no | `1` | Optional number of alternatives to generate |

Fixture-backed call:

```python
input_data = [[]]
attributes = {'query': 'count roles'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('query_breakdown@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `llm_refine`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `query-breakdown`.
- Failure: `REFINEMENT_FAILED` at `REFINE`.

## `segment_text@2.0.0`

Split normalized text into stable segments with offsets and flat metadata.

When to invoke: Use when normalized text must be split into stable segments with offsets and metadata.

Tags: `domain-text`, `flow-transform`, `accepts-data`, `produces-data`, `capability-segmentation`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `text_field` | `str` | yes | `—` | Field containing normalized text to segment |
| `split_strategy` | `str` | no | `"sentence"` | Segmentation strategy: sentence, paragraph, token, word, or heading |
| `word_overlap` | `int` | no | `0` | Approximate number of words to overlap between segments |
| `max_tokens` | `int` | no | `650` | Approximate maximum token budget per segment |
| `min_chars` | `int` | no | `20` | Minimum characters per segment when possible |
| `keep_delimiters` | `bool` | no | `false` | Whether to retain delimiters in segment units |
| `meta_fields` | `list[str]` | no | `[]` | Record fields to copy into flat segment metadata keys |
| `segment_id_format` | `str` | no | `"{doc_id}::S{index:04d}"` | Segment identifier template using doc_id and index placeholders |

Fixture-backed call:

```python
input_data = [[{'doc_id': 'doc', 'text': 'Hello world.'}]]
attributes = {'text_field': 'text'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('segment_text@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `segment`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `select@2.0.0`

Given an input data, filter data elements based on a specified condition by type-aware comparison (record-wise)

When to invoke: Use when records should be filtered by a type-aware comparison against one key.

Tags: `domain-relational`, `flow-transform`, `accepts-data`, `produces-data`, `capability-filter`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `operand_key` | `str` | yes | `—` | The key to check in each record |
| `operand` | `str` | yes | `—` | Comparison operator: =, !=, >, >=, <, <= |
| `operand_val` | `Any` | yes | `—` | Value to compare with |
| `approximate_match` | `bool` | no | `false` | Use epsilon tolerance for numeric comparison |
| `eps` | `float` | no | `1e-09` | Epsilon tolerance for approximate numeric comparison |

Fixture-backed call:

```python
input_data = [[{'id': 1, 'name': 'A', 'score': 1}, {'id': 2, 'name': 'B', 'score': 2}]]
attributes = {'operand': '>', 'operand_key': 'score', 'operand_val': 1}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('select@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `operand`.
- Failure: `VALIDATION_FAILED` at `VALIDATE`.

## `semantic_extract@2.0.0`

Extracts entities from natural language text fields using LLM models

When to invoke: Use when entities must be extracted from text fields using natural-language instructions.

Tags: `domain-semantic`, `flow-transform`, `accepts-data`, `produces-data`, `capability-extraction`, `requires-llm`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `entities` | `list[dict]` | yes | `—` | List of entities to extract. Each dict has 'name', 'description' (optional), 'extract_on_fields' (optional list of field names - if not provided, extracts from all fields), and 'type' (optional) |
| `context` | `str` | no | `""` | Additional context information that provides domain knowledge or additional instructions for the extraction |
| `demonstrations` | `str` | no | `""` | Additional demonstrations to help in-context learning |
| `extract_with_single_prompt` | `bool` | no | `true` | If true, extract all entities in a single prompt, else extract each entity with individual prompt |

Fixture-backed call:

```python
input_data = [[{'bio': 'Ada uses Python', 'id': 1, 'name': 'Ada'}]]
attributes = {'entities': [{'name': 'skill'}]}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('semantic_extract@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `llm`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `extraction`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `semantic_filter@2.0.0`

Filters records based on natural language conditions using LLM models

When to invoke: Use when records must be filtered by a natural-language condition that cannot be expressed as a simple comparison.

Tags: `domain-semantic`, `flow-transform`, `accepts-data`, `produces-data`, `capability-filter`, `requires-llm`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `filter_conditions` | `dict[str, str]` | yes | `—` | Dictionary mapping field names to natural language filter conditions |
| `context` | `str` | no | `""` | Optional context to provide domain knowledge or additional instructions |
| `demonstrations` | `str` | no | `""` | Optional demonstrations to help in-context learning |
| `return_idx` | `boolean` | no | `false` | If true, return indices of records that satisfy all conditions, else return filtered records |

Fixture-backed call:

```python
input_data = [[{'id': 1, 'score': 8}]]
attributes = {'filter_conditions': {'score': 'is high'}}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('semantic_filter@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `llm`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `filter`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `semantic_join@2.0.0`

Joins two datasets based on natural language join predicate using LLM models

When to invoke: Use when two datasets must be joined by a natural-language relationship rather than exact keys.

Tags: `domain-semantic`, `flow-combine`, `accepts-data`, `produces-data`, `capability-embedding-filter`, `capability-join`, `requires-llm`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `left_fields` | `list[str]` | yes | `—` | Fields from left dataset to consider |
| `right_fields` | `list[str]` | yes | `—` | Fields from right dataset to consider |
| `join_predicate` | `str` | no | `""` | Natural language description of when records should be joined |
| `join_type` | `str` | no | `"inner"` | Type of join: 'inner', 'left', 'right', 'outer' |
| `left_suffix` | `str` | no | `"_left"` | Suffix for field name conflicts from left dataset |
| `right_suffix` | `str` | no | `"_right"` | Suffix for field name conflicts from right dataset |
| `keep_keys` | `str` | no | `"left"` | 'left' to keep left keys only, 'both' to keep both |
| `context` | `str` | no | `""` | Optional context to provide domain knowledge or additional instructions |
| `demonstrations` | `str` | no | `""` | Optional demonstrations to help in-context learning |
| `batch_size` | `int` | no | `10` | Number of record pairs to evaluate per LLM call (batch processing) |
| `use_cache` | `bool` | no | `true` | Enable result caching to avoid re-evaluating similar pairs |
| `use_embedding_filter` | `bool` | no | `false` | Use embedding pre-filtering to reduce candidate pairs (requires sentence-transformers package) |
| `embedding_threshold` | `float` | no | `0.7` | Similarity threshold for embedding pre-filtering (0.0-1.0, maps to cosine similarity [-1,1]) |
| `max_llm_calls` | `int` | no | `1000` | Maximum allowed LLM calls (None = no limit). Prevents accidental expensive operations. |
| `estimate_cost` | `bool` | no | `true` | Show cost estimate and warnings before execution |
| `optimize_thresholds` | `bool` | no | `false` | Enable dynamic threshold learning (Cascade Optimization) |
| `recall_target` | `float` | no | `0.8` | Target recall for optimization (0.0-1.0) |
| `precision_target` | `float` | no | `0.8` | Target precision for auto-acceptance (0.0-1.0) |
| `sampling_percentage` | `float` | no | `0.1` | Fraction of data to sample for learning (0.0-1.0) |
| `failure_probability` | `float` | no | `0.2` | Statistical failure probability (delta) for threshold learning |

Fixture-backed call:

```python
input_data = [[{'id': 1, 'name': 'Ada'}], [{'id': 'a', 'name': 'ADA'}]]
attributes = {'estimate_cost': False, 'join_predicate': 'names refer to the same person', 'left_fields': ['name'], 'right_fields': ['name']}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('semantic_join@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `llm`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `join`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `semantic_project@2.0.0`

Projects records to select and rename columns using LLM-based mapping resolution

When to invoke: Use when fields must be selected or renamed using semantic mapping.

Tags: `domain-semantic`, `flow-transform`, `accepts-data`, `produces-data`, `capability-projection`, `requires-llm`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `projection_instructions` | `str` | yes | `—` | Natural language description of which columns to keep and how to rename them |

Fixture-backed call:

```python
input_data = [[{'id': 1, 'name': 'Ada'}]]
attributes = {'projection_instructions': 'keep and rename name'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('semantic_project@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `llm`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `projection`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `semantic_transform@2.0.0`

Transforms data into target fields and values using LLM-based transformations

When to invoke: Use when records must be converted into requested target fields or values using natural-language transformations.

Tags: `domain-semantic`, `flow-transform`, `accepts-data`, `produces-data`, `capability-transformation`, `requires-llm`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `input_meta` | `dict` | no | `{}` | Optional metadata about input fields |
| `output_desc` | `dict` | yes | `—` | Required description of target fields to create |
| `strategy` | `str` | no | `"auto"` | Execution strategy: 'auto' (automatic cost-based selection), 'per_record' (one LLM call per record), 'distinct_required_values' (deduplicate by distinct values), 'distinct_required_values_with_merged_fields' (merged distinct optimization). |

Fixture-backed call:

```python
input_data = [[{'city': 'NY', 'score': 1}]]
attributes = {'output_desc': {'label': {'description': 'Score label'}}, 'strategy': 'per_record'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('semantic_transform@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `llm`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `transform`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `sum@2.0.0`

Given an input data, calculate the sum of values for a specified key across all records.

When to invoke: Use when a numeric key must be reduced to its total across records.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-reduction`, `capability-sum`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `sum_key` | `str` | yes | `—` | The key to sum the values for |
| `output_key` | `str` | no | `"sum"` | The key name for the result sum |

Fixture-backed call:

```python
input_data = [[{'value': 3}, {'value': '5'}, {'value': 5}]]
attributes = {'sum_key': 'value'}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('sum@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: output `[[{"sum":0}]]`.
- Invalid: validation suggestion contains `sum_key`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `union@2.0.0`

Given multiple input data sources, combine all records and remove exact duplicates

When to invoke: Use when input groups must be combined and duplicate records removed under the configured match rule.

Tags: `domain-set`, `flow-combine`, `accepts-data`, `produces-data`, `capability-union`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `match_option` | `str` | no | `"key_match"` | Matching strategy for duplicate detection: 'key_match' (exact field names and values) or 'seq_match' (position-based comparison regardless of field names) |

Fixture-backed call:

```python
input_data = [[{'id': 1}, {'id': 2}], [{'id': 2}, {'id': 3}]]
attributes = {}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('union@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `match_option`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `vector_embed@2.0.0`

Convert text data into vector embeddings using a specified model.

When to invoke: Use when text fields must be encoded as vectors for later similarity work.

Tags: `domain-vector`, `flow-transform`, `accepts-data`, `produces-data`, `capability-embedding`, `requires-vector`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `model_ref` | `str` | no | `"all-MiniLM-L6-v2"` | Reference to the embedding model |
| `text_field` | `list[str]` | no | `[]` | Keys containing the raw text |
| `delimiter` | `str` | no | `"\n"` | Delimiter for concatenating text fields |
| `append` | `bool` | no | `false` | Append embeddings to dataset or return only embeddings |
| `add_meta_data` | `bool` | no | `false` | Add embed.model and embed.dim to output |
| `on_missing_fields` | `str` | no | `"raise"` | How to handle missing text fields: raise \| use_empty |

Fixture-backed call:

```python
input_data = [[{'id': 'a', 'title': 'alpha'}]]
attributes = {'text_field': ['title']}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('vector_embed@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `embedding`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `vector_search@2.0.0`

Perform semantic search within each dataset using text or vector queries.

When to invoke: Use when records in each group must be ranked by similarity to a text or vector query.

Tags: `domain-vector`, `flow-transform`, `accepts-data`, `produces-data`, `capability-search`, `requires-vector`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `query` | `str | dict` | yes | `—` | Query text or query embedding object |
| `search_fields` | `list[str]` | no | `—` | Keys containing searchable text |
| `model_ref` | `str` | no | `"all-MiniLM-L6-v2"` | Reference to the embedding model |
| `metric` | `str` | no | `"cosine"` | Similarity metric: cosine \| dot \| l2 |
| `add_meta_data` | `bool` | no | `false` | Add search.metric and search.model |
| `on_missing_embedding` | `str` | no | `"embed_missing"` | How to handle missing candidate embeddings: embed_missing \| raise |
| `on_missing_fields` | `str` | no | `"raise"` | How to handle missing search fields: raise \| use_empty |
| `top_k` | `int` | no | `10` | Maximum number of results per dataset |
| `min_score` | `float` | no | `—` | Minimum score threshold |
| `normalize` | `bool` | no | `false` | L2-normalize embeddings before scoring |

Fixture-backed call:

```python
input_data = [[{'embed.model': 'model-2d', 'embedding': [1.0, 0.0], 'id': 'a'}]]
attributes = {'query': {'embedding': [1.0, 0.0], 'model': 'model-2d'}}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('vector_search@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: successful empty result; output `[[]]`.
- Invalid: validation suggestion contains `vector search`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.

## `vector_similarity@2.0.0`

Compute similarity between two lists of records using embeddings.

When to invoke: Use when records from two groups must be compared by embedding-based similarity in pairwise or cartesian mode.

Tags: `domain-vector`, `flow-combine`, `accepts-data`, `produces-data`, `capability-similarity`, `requires-vector`

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `model_ref` | `str` | no | `"all-MiniLM-L6-v2"` | Reference to the embedding model |
| `fields` | `list[str]` | no | `—` | Fields to use when text embedding is needed |
| `metric` | `str` | no | `"cosine"` | Similarity metric |
| `comparison_mode` | `str` | no | `"cartesian"` | Comparison mode: cartesian or pairwise |
| `on_missing_embedding` | `str` | no | `"raise"` | How to handle missing embeddings |
| `on_missing_fields` | `str` | no | `"raise"` | How to handle missing fields: raise \| use_empty |
| `add_meta_data` | `bool` | no | `false` | Add similarity metadata |
| `threshold` | `float` | no | `—` | Threshold for passed flag |
| `normalize` | `bool` | no | `false` | Normalize embeddings |

Fixture-backed call:

```python
input_data = [[{'embedding': [1.0, 0.0], 'id': 'left'}], [{'embedding': [1.0, 0.0], 'id': 'right'}]]
attributes = {}
properties = None  # inject the fixture profile's dependency here when required
output_data, output_attributes, meta = registry.resolve('vector_similarity@2.0.0').run(
    input_data, attributes, properties
)
```

The fixture profile is `none`; non-`none` profiles use deterministic test doubles for the dependencies named by the profile.

- Empty: fixture-backed case.
- Invalid: validation suggestion contains `two`.
- Failure: `EXECUTION_FAILED` at `EXECUTE`.
