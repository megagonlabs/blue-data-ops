# Operator reference

This reference covers the 33 exact cards selected by `active_registry()`. Each outcome
table summarizes the behavior documented for that exact version.

```python
from blue_data_ops.operators import active_registry

registry = active_registry()
assert len(registry.list_cards()) == 33
```

## Tag taxonomy

This table is derived from the 33 active cards. Built-in tags use five required axes and
one optional axis. A tag states something true in at least one productive public mode.
Tags are flat, exact-match labels with no parent-child relationships.

| Axis | Meaning | Built-in cardinality | Active values |
|---|---|---|---|
| `domain-*` | primary subject area, not the output type | exactly one | `domain-arithmetic`, `domain-ml`, `domain-plan`, `domain-query-compound`, `domain-relational`, `domain-semantic`, `domain-set`, `domain-text`, `domain-vector` |
| `flow-*` | valid role in a pipeline | one or more | `flow-aggregate`, `flow-combine`, `flow-control`, `flow-head`, `flow-sink`, `flow-transform` |
| `accepts-*` | kind of upstream input accepted | one or more | `accepts-data`, `accepts-none` |
| `produces-*` | result kind or externally visible effect | one or more | `produces-data`, `produces-metadata`, `produces-query`, `produces-side-effect` |
| `capability-*` | operation family or specific action | one or more | `capability-average`, `capability-bayesian-query`, `capability-classification`, `capability-clustering`, `capability-create-database`, `capability-create-table`, `capability-delete`, `capability-discovery`, `capability-embedding`, `capability-embedding-filter`, `capability-extraction`, `capability-extrema`, `capability-filter`, `capability-generation`, `capability-insert`, `capability-intersection`, `capability-join`, `capability-metadata-search`, `capability-normalization`, `capability-persist`, `capability-projection`, `capability-query-execution`, `capability-query-generation`, `capability-record-selection`, `capability-reduction`, `capability-search`, `capability-segmentation`, `capability-similarity`, `capability-sql`, `capability-sum`, `capability-transformation`, `capability-union` |
| `requires-*` | unconditional operator-specific runtime requirement | zero or more | `requires-data-registry`, `requires-database-backend`, `requires-llm`, `requires-ml`, `requires-query-backend`, `requires-vector` |

`accepts-none` means that records are not consumed; callers still pass `input_data`,
such as an empty `[[]]` bundle. A card can carry broad and specific capabilities
together. The `requires-*` axis covers operator-specific requirements, not
package-wide install requirements. The active `domain-plan` value is a retained
compatibility label on `data_discover@2.0.0`; use `capability-metadata-search` or
`produces-metadata` to find its behavior. Its result holds registry identities
and an optional search score; stored metadata remains in the registry.

`find()` strips surrounding whitespace and lowercases requested filters. A filter
passes shape validation when the result is nonempty, contains no whitespace, and
includes at least one hyphen. It is then matched as a complete tag. Shape validation
does not check taxonomy membership or hyphen position. The filters `domain-`,
`-vector`, and `domain_-vector` are well-formed but match no built-in card.
Malformed filters raise `DiscoveryError`; well-formed absent tags match no cards.
There is no OR or negative-tag syntax. A blank query with tags performs tag-only
discovery; a blank query without tags returns no cards.

```python
vector_steps = registry.find(
    "",
    tags=["domain-vector", "flow-transform"],
)
assert [card.operator_id for card in vector_steps] == [
    "vector_embed@3.0.0",
    "vector_search@3.0.0",
]

cards = registry.find(
    "filter",
    tags=["domain-relational", "flow-transform"],
)
assert [card.operator_id for card in cards] == ["select@2.0.0"]
```

Inspect `card.tags` when composing filters dynamically. Built-in package cards use a
closed vocabulary. `register()` preserves arbitrary custom tags for compatibility.
Filters are normalized as described above, so a custom tag is discoverable only when
its stored value equals the normalized filter.

## `argmax@2.0.0`

When to invoke: Use when the result must retain the input record or tied records with the largest value for one key.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-extrema`, `capability-record-selection`

Guide: [`argmax@2.0.0`](src/blue_data_ops/operator_skills/argmax/2.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `argmax_key` | `str` | yes | `—` | The key to find the maximum value for |
| `return_index` | `bool` | no | `false` | If True, returns indices (0-based) instead of records, otherwise returns records |

Exact resolution:

```python
operator = registry.resolve("argmax@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.argmax_operator"
assert type(operator).__name__ == "ArgmaxOperator"
```

| Outcome | Behavior |
|---|---|
| Success | First-group record mode preserves both tied maximum records as data. |
| Empty | Empty record mode produces successful-empty. |
| Invalid | A missing argmax_key is INVALID_INPUT at VALIDATE. |
| Failure | A non-record member is contained as EXECUTION_FAILED at EXECUTE. |

## `argmin@2.0.0`

When to invoke: Use when the result must retain the input record or tied records with the smallest value for one key.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-extrema`, `capability-record-selection`

Guide: [`argmin@2.0.0`](src/blue_data_ops/operator_skills/argmin/2.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `argmin_key` | `str` | yes | `—` | The key to find the minimum value for |
| `return_index` | `bool` | no | `false` | If True, returns indices (0-based) instead of records, otherwise returns records |

Exact resolution:

```python
operator = registry.resolve("argmin@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.argmin_operator"
assert type(operator).__name__ == "ArgminOperator"
```

| Outcome | Behavior |
|---|---|
| Success | First-group record mode preserves both tied minimum records as data. |
| Empty | Empty record mode produces successful-empty. |
| Invalid | A missing argmin_key is INVALID_INPUT at VALIDATE. |
| Failure | A non-record member is contained as EXECUTION_FAILED at EXECUTE. |

## `avg@3.0.0`

When to invoke: Use when a numeric key must be reduced to its arithmetic mean across records.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-average`, `capability-reduction`

Guide: [`avg@3.0.0`](src/blue_data_ops/operator_skills/avg/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `avg_key` | `str` | yes | `—` | The key to average the values for |
| `output_key` | `str` | no | `"avg"` | The key name for the result average |

Exact resolution:

```python
operator = registry.resolve("avg@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._avg_outcome"
assert type(operator).__name__ == "AvgOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Decimal 3.9 follows int-before-float coercion and yields average 3.0 with count 1. |
| Empty | No usable values yields [[]], count 0, and successful-empty rather than a zero row. |
| Invalid | Missing avg_key is INVALID_INPUT at VALIDATE. |

## `classify@3.0.0`

When to invoke: Use when labeled numeric vectors are available and class labels are needed for input samples.

Tags: `domain-ml`, `flow-transform`, `accepts-data`, `produces-data`, `capability-classification`, `requires-ml`

Guide: [`classify@3.0.0`](src/blue_data_ops/operator_skills/classify/3.0.0/Operator.md)

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

Exact resolution:

```python
operator = registry.resolve("classify@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._classify_outcome"
assert type(operator).__name__ == "ClassifyOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Decision-tree training uses the first group and predicts across supplied groups. |
| Empty | All groups empty is successful-empty without model work. |
| Invalid | Unsupported algorithm is INVALID_INPUT before the empty shortcut. |
| Failure | Ragged vectors are contained as EXECUTION_FAILED. |

## `cluster@3.0.0`

When to invoke: Use when unlabeled numeric vectors must be assigned to clusters.

Tags: `domain-ml`, `flow-transform`, `accepts-data`, `produces-data`, `capability-clustering`, `requires-ml`

Guide: [`cluster@3.0.0`](src/blue_data_ops/operator_skills/cluster/3.0.0/Operator.md)

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

Exact resolution:

```python
operator = registry.resolve("cluster@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._cluster_outcome"
assert type(operator).__name__ == "ClusterOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | K-means produces stable cluster labels as record data. |
| Empty | An empty first group produces successful-empty under the retained first-group boundary. |
| Invalid | Unsupported algorithm is INVALID_INPUT before empty handling. |
| Failure | Ragged vectors are contained as an execution failure. |

## `create_database@2.0.0`

When to invoke: Use when one or more databases must be created or overwritten through the data registry.

Tags: `domain-relational`, `flow-control`, `accepts-data`, `accepts-none`, `produces-data`, `produces-side-effect`, `capability-create-database`, `requires-data-registry`, `requires-database-backend`

Guide: [`create_database@2.0.0`](src/blue_data_ops/operator_skills/create_database/2.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `source` | `str` | yes | `""` | Name of the data source where the database will be created |
| `database` | `str` | yes | `""` | Name of the database to be created |
| `description` | `str` | no | `""` | Description of the database to be created |
| `properties` | `str` | no | `{}` | Properties of the database to be created |
| `created_by` | `str` | no | `""` | Creator of the database |
| `overwrite` | `bool` | no | `false` | Whether to overwrite the existing database |

Exact resolution:

```python
operator = registry.resolve("create_database@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.create_database_operator"
assert type(operator).__name__ == "CreateDatabaseOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Creates a SQLite database while returning the input tensor unchanged. |
| Empty | An empty returned tensor can still represent successful database creation. |
| Failure | A RegistrySeam failure returns EXECUTION_FAILED rather than a successful result. |

## `create_table@2.0.0`

When to invoke: Use when tables or entities must be created or overwritten in registry-backed database collections.

Tags: `domain-relational`, `flow-control`, `accepts-data`, `accepts-none`, `produces-data`, `produces-side-effect`, `capability-create-table`, `requires-data-registry`, `requires-database-backend`

Guide: [`create_table@2.0.0`](src/blue_data_ops/operator_skills/create_table/2.0.0/Operator.md)

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

Exact resolution:

```python
operator = registry.resolve("create_table@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.create_table_operator"
assert type(operator).__name__ == "CreateTableOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Creates a SQLite table while returning the input tensor unchanged. |
| Empty | An empty returned tensor can still represent successful table creation. |
| Failure | A RegistrySeam failure returns EXECUTION_FAILED rather than a successful result. |

## `data_discover@2.0.0`

When to invoke: Use when data sources, databases, collections, or entities must be found through registry search.

Tags: `domain-plan`, `flow-head`, `accepts-none`, `produces-metadata`, `capability-discovery`, `capability-metadata-search`, `requires-data-registry`

Guide: [`data_discover@2.0.0`](src/blue_data_ops/operator_skills/data_discover/2.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `search_query` | `str` | yes | `""` | Text to search for in source names and descriptions |
| `approximate` | `bool` | yes | `true` | Whether to use approximate (vector) search |
| `hybrid` | `bool` | no | `false` | Whether to use hybrid search (text + vector) |
| `limit` | `int` | no | `-1` | Max number of results to return (-1, unlimited) |
| `page` | `int` | no | `0` | Page number for pagination |
| `page_size` | `int` | no | `10` | Number of results per page (default: 10, max: 100) |
| `include_metadata` | `bool` | no | `false` | Must be false; discovery does not return stored metadata |
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

Exact resolution:

```python
operator = registry.resolve("data_discover@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.data_discover_operator"
assert type(operator).__name__ == "DataDiscoverOperator"
```

| Outcome | Behavior |
|---|---|
| Success | A registry search returns catalog identity fields, an allowlisted source kind, and a score. |
| Empty | A no-match registry search returns successful-empty. |
| Invalid | A blank query returns INVALID_INPUT at VALIDATE. |
| Failure | A registry search failure returns EXECUTION_FAILED at EXECUTE. |

## `delete@2.0.0`

When to invoke: Use when records must be removed from the first input group by position.

Tags: `domain-relational`, `flow-transform`, `accepts-data`, `produces-data`, `capability-delete`

Guide: [`delete@2.0.0`](src/blue_data_ops/operator_skills/delete/2.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `delete_idx` | `Union[int, list[int]]` | no | `[]` | Position(s) to delete records. Supports negative indexing (-1 = last, -2 = second to last, etc.) |

Exact resolution:

```python
operator = registry.resolve("delete@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.delete_operator"
assert type(operator).__name__ == "DeleteOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Deleting from the first group returns the remaining records and ignores later groups. |
| Empty | An empty first group is successful-empty. |
| Invalid | A non-integer delete index is INVALID_INPUT at VALIDATE. |

## `insert@3.0.0`

When to invoke: Use when records from input groups must be inserted at specified positions.

Tags: `domain-relational`, `flow-combine`, `flow-transform`, `accepts-data`, `produces-data`, `capability-insert`

Guide: [`insert@3.0.0`](src/blue_data_ops/operator_skills/insert/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `insert_records` | `list[dict]` | no | `[]` | List of records to insert into the first data source (optional if second data group provided) |
| `insert_idx` | `Union[int, list[int]]` | no | `-1` | Position(s) to insert records (-1 for append, 0+ for specific position). If list, each element corresponds to position for each record |

Exact resolution:

```python
operator = registry.resolve("insert@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._insert_outcome"
assert type(operator).__name__ == "InsertOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Declared records populate an existing empty first group. |
| Empty | Empty base with no supplied records is successful-empty. |
| Invalid | Invalid insertion position is rejected before the no-op shortcut. |
| Failure | A lax string position that reaches the body is contained as EXECUTION_FAILED. |

## `insert_table@3.0.0`

When to invoke: Use when record rows must be persisted into a registry-backed database table.

Tags: `domain-relational`, `flow-sink`, `accepts-data`, `produces-data`, `produces-side-effect`, `capability-persist`, `requires-data-registry`, `requires-database-backend`

Guide: [`insert_table@3.0.0`](src/blue_data_ops/operator_skills/insert_table/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `source` | `str` | yes | `"default_source"` | Name of the data source where the table is located |
| `database` | `str` | yes | `"default"` | Name of the database where the table is located |
| `collection` | `str` | no | `"public"` | Name of the collection where the table is located. For SQLite sources, defaults to 'public' if not specified |
| `table` | `str` | yes | `""` | Name of the table to insert data into |
| `batch_size` | `int` | no | `100` | Number of rows to insert in each batch (default: 100) |

Exact resolution:

```python
operator = registry.resolve("insert_table@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._insert_table_outcome"
assert type(operator).__name__ == "InsertTableOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Successful SQLite writes preserve all records and set num_rows_insert to the total inserted by the call. |
| Empty | Empty input still performs registry setup then returns successful-empty with count 0. |
| Invalid | A later non-record rejects the whole call before any write. |
| Failure | If a later batch fails a UNIQUE constraint, num_rows_insert is omitted even though rows committed by an earlier batch remain. |

## `intersect@3.0.0`

When to invoke: Use when only records shared by all input groups should remain under the configured match rule.

Tags: `domain-set`, `flow-combine`, `accepts-data`, `produces-data`, `capability-intersection`

Guide: [`intersect@3.0.0`](src/blue_data_ops/operator_skills/intersect/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `match_option` | `str` | no | `"key_match"` | Matching strategy for record comparison: 'key_match' (exact field names and values) or 'seq_match' (position-based comparison regardless of field names) |

Exact resolution:

```python
operator = registry.resolve("intersect@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._intersect_outcome"
assert type(operator).__name__ == "IntersectOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Sequence matching returns the exact first-group record. |
| Empty | Any empty supplied operand makes the intersection successful-empty. |
| Invalid | Fewer than two operands is INVALID_INPUT at VALIDATE. |

## `join@3.0.0`

When to invoke: Use when two or more JSON record groups must be joined on configured keys and join types.

Tags: `domain-relational`, `flow-combine`, `accepts-data`, `produces-data`, `capability-join`

Guide: [`join@3.0.0`](src/blue_data_ops/operator_skills/join/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `join_on` | `list[list[str]]` | yes | `—` | List of join key lists for each data source |
| `join_type` | `str` | no | `"inner"` | Type of join: 'inner', 'left', 'right', 'outer' |
| `join_suffix` | `list[str]` | no | `[]` | Suffixes for non-key fields |
| `keep_keys` | `str` | no | `"left"` | 'left' to keep left keys only, 'both' to keep both |

Exact resolution:

```python
operator = registry.resolve("join@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._join_outcome"
assert type(operator).__name__ == "JoinOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Inner join keeps the left key once and uses generated suffix defaults. |
| Empty | No matching keys with an explicit empty suffix list is successful-empty. |
| Invalid | Invalid duplicate suffixes are rejected before an empty-group shortcut. |

## `max@3.0.0`

When to invoke: Use when a numeric key must be reduced to its largest value.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-extrema`, `capability-reduction`

Guide: [`max@3.0.0`](src/blue_data_ops/operator_skills/max/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `max_key` | `str` | yes | `—` | The key to find the maximum value for |
| `output_key` | `str` | no | `"max"` | The key name for the result max value |

Exact resolution:

```python
operator = registry.resolve("max@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._max_outcome"
assert type(operator).__name__ == "MaxOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | First-group coercion and custom output naming produce the real maximum. |
| Empty | No usable comparable value is successful-empty rather than a null record. |
| Invalid | Missing max_key is INVALID_INPUT at VALIDATE. |
| Failure | An unrelated coercion exception is contained as EXECUTION_FAILED. |

## `min@3.0.0`

When to invoke: Use when a numeric key must be reduced to its smallest value.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-extrema`, `capability-reduction`

Guide: [`min@3.0.0`](src/blue_data_ops/operator_skills/min/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `min_key` | `str` | yes | `—` | The key to find the minimum value for |
| `output_key` | `str` | no | `"min"` | The key name for the result min value |

Exact resolution:

```python
operator = registry.resolve("min@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._min_outcome"
assert type(operator).__name__ == "MinOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | First-group coercion and custom output naming produce the real minimum. |
| Empty | No usable comparable value is successful-empty rather than a null record. |
| Invalid | Missing min_key is INVALID_INPUT at VALIDATE. |
| Failure | An unrelated coercion exception is contained as EXECUTION_FAILED. |

## `nl2bn@3.0.0`

When to invoke: Use when a natural-language question must be translated into a Bayesian-network query.

Tags: `domain-query-compound`, `flow-head`, `accepts-none`, `produces-data`, `capability-bayesian-query`, `capability-query-execution`, `capability-query-generation`, `requires-data-registry`, `requires-llm`, `requires-query-backend`

Guide: [`nl2bn@3.0.0`](src/blue_data_ops/operator_skills/nl2bn/3.0.0/Operator.md)

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

Exact resolution:

```python
operator = registry.resolve("nl2bn@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._nl2bn_outcome"
assert type(operator).__name__ == "NL2BNOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | A backend probability of zero remains tensor data. |
| Empty | A backend result with zero rows is successful-empty. |
| Invalid | A blank required question is INVALID_INPUT before provider work. |
| Failure | A nonempty result without probability is EXECUTION_FAILED. |

## `nl2llm@3.0.0`

When to invoke: Use when a natural-language request should be sent to the configured reasoning provider and returned as structured data.

Tags: `domain-query-compound`, `flow-head`, `accepts-none`, `produces-data`, `capability-generation`, `requires-llm`

Guide: [`nl2llm@3.0.0`](src/blue_data_ops/operator_skills/nl2llm/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `query` | `str` | yes | `—` | Natural language query to process |
| `context` | `str` | no | `""` | Optional context to provide domain knowledge |
| `attrs` | `list[dict]` | no | `[]` | List of attribute specifications (dicts with name and optional type) |

Exact resolution:

```python
operator = registry.resolve("nl2llm@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._nl2llm_outcome"
assert type(operator).__name__ == "NL2LLMOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | A provider array of requested records remains tensor data. |
| Empty | An explicit provider empty array is successful-empty. |
| Invalid | A blank required query is INVALID_INPUT before provider work. |
| Failure | A provider object where an array is required is EXECUTION_RESULT_INVALID at NORMALIZE. |

## `nl2sql@3.0.0`

When to invoke: Use when a natural-language question must be translated into SQL, with optional execution.

Tags: `domain-query-compound`, `flow-head`, `accepts-none`, `produces-data`, `produces-query`, `capability-query-execution`, `capability-query-generation`, `capability-sql`, `requires-data-registry`, `requires-llm`, `requires-query-backend`

Guide: [`nl2sql@3.0.0`](src/blue_data_ops/operator_skills/nl2sql/3.0.0/Operator.md)

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

Exact resolution:

```python
operator = registry.resolve("nl2sql@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._nl2sql_outcome"
assert type(operator).__name__ == "NL2SQLOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Query-only SQL remains a tensor record. |
| Empty | A successful backend query with zero rows is successful-empty. |
| Invalid | A blank question is INVALID_INPUT before routing. |
| Failure | A malformed provider response is EXECUTION_FAILED. |

## `normalize_text@2.0.0`

When to invoke: Use when text needs canonical Unicode, whitespace, case, or recognized-date normalization before later text work.

Tags: `domain-text`, `flow-transform`, `accepts-data`, `produces-data`, `capability-normalization`

Guide: [`normalize_text@2.0.0`](src/blue_data_ops/operator_skills/normalize_text/2.0.0/Operator.md)

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

Exact resolution:

```python
operator = registry.resolve("normalize_text@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.normalize_text_operator"
assert type(operator).__name__ == "NormalizeTextOperator"
```

| Outcome | Behavior |
|---|---|
| Success | All groups are preserved; blank field data normalizes to an empty string record. |
| Empty | No input records is successful-empty, distinct from blank-field data. |
| Invalid | An empty text_field list is INVALID_INPUT at VALIDATE. |
| Failure | A non-record member is contained as EXECUTION_FAILED. |

## `project@3.0.0`

When to invoke: Use when each record should retain and optionally rename a specified set of keys without semantic inference.

Tags: `domain-relational`, `flow-transform`, `accepts-data`, `produces-data`, `capability-projection`

Guide: [`project@3.0.0`](src/blue_data_ops/operator_skills/project/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `kept_keys` | `list[str]` | yes | `—` | List of keys to keep in each record |
| `key_mapping` | `dict[str, str]` | no | `{}` | Dictionary mapping old key names to new key names |

Exact resolution:

```python
operator = registry.resolve("project@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._project_outcome"
assert type(operator).__name__ == "ProjectOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Projection uses the first group and an empty projected record remains data. |
| Empty | A valid projection with no source rows is successful-empty. |
| Invalid | An empty requested-key list is INVALID_INPUT before empty execution. |

## `segment_text@2.0.0`

When to invoke: Use when normalized text must be split into stable segments with offsets and metadata.

Tags: `domain-text`, `flow-transform`, `accepts-data`, `produces-data`, `capability-segmentation`

Guide: [`segment_text@2.0.0`](src/blue_data_ops/operator_skills/segment_text/2.0.0/Operator.md)

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

Exact resolution:

```python
operator = registry.resolve("segment_text@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.segment_text_operator"
assert type(operator).__name__ == "SegmentTextOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Segments preserve groups while blank or missing text records are skipped. |
| Empty | Producing no segments from blank-only input is successful-empty. |
| Invalid | A blank text_field is INVALID_INPUT at VALIDATE. |
| Failure | An unknown format placeholder on nonblank input is contained as EXECUTION_FAILED. |

## `select@2.0.0`

When to invoke: Use when records should be filtered by a type-aware comparison against one key.

Tags: `domain-relational`, `flow-transform`, `accepts-data`, `produces-data`, `capability-filter`

Guide: [`select@2.0.0`](src/blue_data_ops/operator_skills/select/2.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `operand_key` | `str` | yes | `—` | The key to check in each record |
| `operand` | `str` | yes | `—` | Comparison operator: =, !=, >, >=, <, <= |
| `operand_val` | `Any` | yes | `—` | Value to compare with |
| `approximate_match` | `bool` | no | `false` | Use epsilon tolerance for numeric comparison |
| `eps` | `float` | no | `1e-09` | Epsilon tolerance for approximate numeric comparison |

Exact resolution:

```python
operator = registry.resolve("select@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.select_operator"
assert type(operator).__name__ == "SelectOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Selection uses the first group, returns matching records, and skips missing fields. |
| Empty | A valid no-match selection is successful-empty. |
| Invalid | An unsupported operand is INVALID_INPUT at VALIDATE. |
| Failure | A lax eps string is contained as VALIDATION_FAILED at VALIDATE. |

## `semantic_extract@3.0.0`

When to invoke: Use when entities must be extracted from text fields using natural-language instructions.

Tags: `domain-semantic`, `flow-transform`, `accepts-data`, `produces-data`, `capability-extraction`, `requires-llm`

Guide: [`semantic_extract@3.0.0`](src/blue_data_ops/operator_skills/semantic_extract/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `entities` | `list[dict]` | yes | `—` | List of entities to extract. Each dict has 'name', 'description' (optional), 'extract_on_fields' (optional list of field names - if not provided, extracts from all fields), and 'type' (optional) |
| `context` | `str` | no | `""` | Additional context information that provides domain knowledge or additional instructions for the extraction |
| `demonstrations` | `str` | no | `""` | Additional demonstrations to help in-context learning |
| `extract_with_single_prompt` | `bool` | no | `true` | If true, extract all entities in a single prompt, else extract each entity with individual prompt |

Exact resolution:

```python
operator = registry.resolve("semantic_extract@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._semantic_extract_outcome"
assert type(operator).__name__ == "SemanticExtractOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | A leading empty group is preserved while a later group is extracted. |
| Empty | All supplied groups empty skips the provider and is successful-empty. |
| Invalid | A malformed input bundle is INVALID_INPUT. |
| Failure | A non-object combined provider response is EXECUTION_FAILED. |

## `semantic_filter@3.0.0`

When to invoke: Use when records must be filtered by a natural-language condition that cannot be expressed as a simple comparison.

Tags: `domain-semantic`, `flow-transform`, `accepts-data`, `produces-data`, `capability-filter`, `requires-llm`

Guide: [`semantic_filter@3.0.0`](src/blue_data_ops/operator_skills/semantic_filter/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `filter_conditions` | `dict[str, str]` | yes | `—` | Dictionary mapping field names to natural language filter conditions |
| `context` | `str` | no | `""` | Optional context to provide domain knowledge or additional instructions |
| `demonstrations` | `str` | no | `""` | Optional demonstrations to help in-context learning |
| `return_idx` | `boolean` | no | `false` | If true, return indices of records that satisfy all conditions, else return filtered records |

Exact resolution:

```python
operator = registry.resolve("semantic_filter@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._semantic_filter_outcome"
assert type(operator).__name__ == "SemanticFilterOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Index mode emits one indices record per group, including an empty group. |
| Empty | A valid false predicate result is successful-empty. |
| Invalid | return_idx must be an actual Boolean. |
| Failure | An undocumented Boolean alias fails instead of becoming false. |

## `semantic_join@3.0.0`

When to invoke: Use when two datasets must be joined by a natural-language relationship rather than exact keys.

Tags: `domain-semantic`, `flow-combine`, `accepts-data`, `produces-data`, `capability-embedding-filter`, `capability-join`, `requires-llm`

Guide: [`semantic_join@3.0.0`](src/blue_data_ops/operator_skills/semantic_join/3.0.0/Operator.md)

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
| `estimate_cost` | `bool` | no | `true` | Log a cost estimate at INFO level before execution |
| `optimize_thresholds` | `bool` | no | `false` | Enable dynamic threshold learning (Cascade Optimization) |
| `recall_target` | `float` | no | `0.8` | Target recall for optimization (0.0-1.0) |
| `precision_target` | `float` | no | `0.8` | Target precision for auto-acceptance (0.0-1.0) |
| `sampling_percentage` | `float` | no | `0.1` | Fraction of data to sample for learning (0.0-1.0) |
| `failure_probability` | `float` | no | `0.2` | Statistical failure probability (delta) for threshold learning |

Exact resolution:

```python
operator = registry.resolve("semantic_join@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._semantic_join_outcome"
assert type(operator).__name__ == "SemanticJoinOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | A valid JSON-Boolean batch response produces joined record data. |
| Empty | A valid false batch response is successful-empty. |
| Invalid | Group arity other than two is INVALID_INPUT. |
| Failure | An unparseable batch response is EXECUTION_FAILED, not no-match. |

## `semantic_project@3.0.0`

When to invoke: Use when fields must be selected or renamed using semantic mapping.

Tags: `domain-semantic`, `flow-transform`, `accepts-data`, `produces-data`, `capability-projection`, `requires-llm`

Guide: [`semantic_project@3.0.0`](src/blue_data_ops/operator_skills/semantic_project/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `projection_instructions` | `str` | yes | `—` | Natural language description of which columns to keep and how to rename them |

Exact resolution:

```python
operator = registry.resolve("semantic_project@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._semantic_project_outcome"
assert type(operator).__name__ == "SemanticProjectOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | A leading empty group is preserved while a later group is projected. |
| Empty | A valid explicit empty mapping has the documented successful-empty drop-all meaning. |
| Failure | A non-object provider mapping is EXECUTION_FAILED. |

## `semantic_transform@3.0.0`

When to invoke: Use when records must be converted into requested target fields or values using natural-language transformations.

Tags: `domain-semantic`, `flow-transform`, `accepts-data`, `produces-data`, `capability-transformation`, `requires-llm`

Guide: [`semantic_transform@3.0.0`](src/blue_data_ops/operator_skills/semantic_transform/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `input_meta` | `dict` | no | `{}` | Optional metadata about input fields |
| `output_desc` | `dict` | yes | `—` | Required description of target fields to create |
| `strategy` | `str` | no | `"auto"` | Execution strategy: 'auto' (automatic cost-based selection), 'per_record' (one LLM call per record), 'distinct_required_values' (deduplicate by distinct values), 'distinct_required_values_with_merged_fields' (merged distinct optimization). |

Exact resolution:

```python
operator = registry.resolve("semantic_transform@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._semantic_transform_outcome"
assert type(operator).__name__ == "SemanticTransformOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | A leading empty group is preserved while later data is transformed. |
| Failure | A non-object transformation plan is EXECUTION_FAILED. |

## `sklearn_estimator@2.0.0`

When to invoke: Use when an arbitrary scikit-learn estimator is required.

Tags: `domain-ml`, `flow-transform`, `accepts-data`, `produces-data`, `capability-classification`, `capability-clustering`, `capability-transformation`, `requires-ml`

Guide: [`sklearn_estimator@2.0.0`](src/blue_data_ops/operator_skills/sklearn_estimator/2.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `vector_key` | `str` | yes | `—` | The key to numeric vector values (features) |
| `label_key` | `str` | no | `—` | The target key for supervised models (labels or continuous targets) |
| `output_key` | `str` | no | `"prediction"` | The key name for the predictions or transformed outputs |

Exact resolution:

```python
operator = registry.resolve("sklearn_estimator@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.sklearn_estimator"
assert type(operator).__name__ == "SklearnEstimator"
```

| Outcome | Behavior |
|---|---|
| Success | A lower-case LinearRegression name trains on the first group and predicts the later group. |
| Empty | An empty bundle returns the original empty input from the raw compatibility call. |
| Invalid | An unknown estimator is INVALID_INPUT at VALIDATE through structured run. |
| Failure | A fit_predict-only estimator with later inference data fails at EXECUTE instead of refitting. |

## `sum@2.0.0`

When to invoke: Use when a numeric key must be reduced to its total across records.

Tags: `domain-arithmetic`, `flow-aggregate`, `accepts-data`, `produces-data`, `capability-reduction`, `capability-sum`

Guide: [`sum@2.0.0`](src/blue_data_ops/operator_skills/sum/2.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `sum_key` | `str` | yes | `—` | The key to sum the values for |
| `output_key` | `str` | no | `"sum"` | The key name for the result sum |

Exact resolution:

```python
operator = registry.resolve("sum@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.sum_operator"
assert type(operator).__name__ == "SumOperator"
```

| Outcome | Behavior |
|---|---|
| Success | First-group numeric coercion produces the exact sum record. |
| Empty | No-contribution and empty inputs produce the domain identity record {sum: 0}, not successful-empty. |
| Invalid | A missing sum_key is INVALID_INPUT at VALIDATE. |
| Failure | A non-record member is contained as EXECUTION_FAILED. |

## `union@2.0.0`

When to invoke: Use when input groups must be combined and duplicate records removed under the configured match rule.

Tags: `domain-set`, `flow-combine`, `accepts-data`, `produces-data`, `capability-union`

Guide: [`union@2.0.0`](src/blue_data_ops/operator_skills/union/2.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `match_option` | `str` | no | `"key_match"` | Matching strategy for duplicate detection: 'key_match' (exact field names and values) or 'seq_match' (position-based comparison regardless of field names) |

Exact resolution:

```python
operator = registry.resolve("union@2.0.0")
assert type(operator).__module__ == "blue_data_ops.operators.union_operator"
assert type(operator).__name__ == "UnionOperator"
```

| Outcome | Behavior |
|---|---|
| Success | key_match flattens all groups while retaining records with different field names. |
| Empty | All empty groups produce successful-empty. |
| Invalid | An unsupported match mode is INVALID_INPUT. |
| Failure | A non-record member is contained as EXECUTION_FAILED. |

## `vector_embed@3.0.0`

When to invoke: Use when text fields must be encoded as vectors for later similarity work.

Tags: `domain-vector`, `flow-transform`, `accepts-data`, `produces-data`, `capability-embedding`, `requires-vector`

Guide: [`vector_embed@3.0.0`](src/blue_data_ops/operator_skills/vector_embed/3.0.0/Operator.md)

| Attribute | Type | Required | Default | Description |
|---|---|---:|---|---|
| `model_ref` | `str` | no | `"all-MiniLM-L6-v2"` | Reference to the embedding model |
| `text_field` | `list[str]` | no | `[]` | Keys containing the raw text |
| `delimiter` | `str` | no | `"\n"` | Delimiter for concatenating text fields |
| `append` | `bool` | no | `false` | Append embeddings to dataset or return only embeddings |
| `add_meta_data` | `bool` | no | `false` | Add embed.model and embed.dim to output |
| `on_missing_fields` | `str` | no | `"raise"` | How to handle missing text fields: raise \| use_empty |

Exact resolution:

```python
operator = registry.resolve("vector_embed@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._vector_embed_outcome"
assert type(operator).__name__ == "VectorEmbedOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Deterministic embeddings are appended to each ordinary record. |
| Empty | All groups empty skips model construction and is successful-empty. |
| Invalid | Invalid control policy is rejected before the empty shortcut. |
| Failure | Model construction failure is contained as EXECUTION_FAILED. |

## `vector_search@3.0.0`

When to invoke: Use when records in each group must be ranked by similarity to a text or vector query.

Tags: `domain-vector`, `flow-transform`, `accepts-data`, `produces-data`, `capability-search`, `requires-vector`

Guide: [`vector_search@3.0.0`](src/blue_data_ops/operator_skills/vector_search/3.0.0/Operator.md)

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

Exact resolution:

```python
operator = registry.resolve("vector_search@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._vector_search_outcome"
assert type(operator).__name__ == "VectorSearchOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | A declared top_k truncates the sorted hit records. |
| Empty | A valid threshold with no hits is successful-empty. |
| Invalid | Missing query is INVALID_INPUT at VALIDATE. |
| Failure | Candidate metadata failure is EXECUTION_FAILED, not successful-empty. |

## `vector_similarity@3.0.0`

When to invoke: Use when records from two groups must be compared by embedding-based similarity in pairwise or cartesian mode.

Tags: `domain-vector`, `flow-combine`, `accepts-data`, `produces-data`, `capability-similarity`, `requires-vector`

Guide: [`vector_similarity@3.0.0`](src/blue_data_ops/operator_skills/vector_similarity/3.0.0/Operator.md)

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

Exact resolution:

```python
operator = registry.resolve("vector_similarity@3.0.0")
assert type(operator).__module__ == "blue_data_ops.operators._vector_similarity_outcome"
assert type(operator).__name__ == "VectorSimilarityOutcomeOperator"
```

| Outcome | Behavior |
|---|---|
| Success | Pairwise cosine emits exact pair identities, order, metrics, and scores. |
| Empty | Both pairwise operands empty is successful-empty. |
| Invalid | One empty pairwise operand is INVALID_INPUT. |
| Failure | Generated vector dimension mismatch is EXECUTION_FAILED. |
