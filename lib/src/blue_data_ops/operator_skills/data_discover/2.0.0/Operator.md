# Discover registry metadata

`data_discover@2.0.0` searches records through a `RegistrySeam`. Although its discovery tag includes `domain-plan`, the operator executes metadata search and does not propose or refine a pipeline.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `approximate` | `attributes` | `yes` | `true` | attribute-spec:bool; required | `scalar` |
| `auto_construct_scope` | `attributes` | `yes` | `true` | attribute-spec:bool; has no effect when scope is omitted | `scalar` |
| `collection` | `attributes` | `yes` | `none` | attribute-spec:str; requires truthy source and database when supplied; default is not materialized | `scalar` |
| `concept_type` | `attributes` | `yes` | `"source"` | attribute-spec:str; source, database, collection, entity, relation, or attribute | `scalar` |
| `data_registry` | `properties` | `no` | `none` | helper:resolve_registry; `RegistrySeam` or raw `DataRegistry`; another value falls through to naming keys | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `platform.name`; converted to string | `seam` |
| `database` | `attributes` | `yes` | `none` | attribute-spec:str; requires a truthy source when supplied; default is not materialized | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `filter_names` | `attributes` | `yes` | `[]` | attribute-spec:list; entries are compared directly with result names | `structured` |
| `hybrid` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `include_metadata` | `attributes` | `yes` | `false` | attribute-spec:bool; `true` is rejected | `scalar` |
| `limit` | `attributes` | `yes` | `-1` | attribute-spec:int; negative means unlimited and zero returns no records | `scalar` |
| `page` | `attributes` | `yes` | `0` | attribute-spec:int; at least zero | `scalar` |
| `page_size` | `attributes` | `yes` | `10` | attribute-spec:int; greater than zero; the described maximum of 100 is not enforced | `scalar` |
| `platform.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `data_registry.name`; converted to string | `seam` |
| `progressive_pagination` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `scope` | `attributes` | `yes` | `none` | attribute-spec:str; default is not materialized | `scalar` |
| `search_query` | `attributes` | `yes` | `""` | attribute-spec:str; required non-blank string | `scalar` |
| `source` | `attributes` | `yes` | `none` | attribute-spec:str; required when database or collection is truthy; default is not materialized | `scalar` |
| `threshold` | `attributes` | `yes` | `0.5` | attribute-spec:float; from 0 through 1; lower scores are better and values at or below the threshold are retained | `scalar` |
| `use_hierarchical_search` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |

## Behavior

With `scope` omitted, `_construct_scope` returns `None`; `source`, `database`, and `collection` do not construct a scope. With an explicit root scope and automatic construction enabled, those components narrow it for the selected concept type. Setting automatic construction false preserves the explicit scope after trimming its trailing slash.

Hierarchical search is the default. Regular search receives the approximate and hybrid flags. Threshold filtering applies only to approximate or hybrid results. Progressive pagination also requires one of those modes; it stops at an empty page or after the last result on a page exceeds the threshold. Each match has `type`, `name`, `id`, `scope`, and optional `score`. A source may have `properties.kind` if the registry contains a recognized family. Stored descriptions, other properties, and metadata are not returned for any concept type. Set `include_metadata` to `false`.

A missing registry or a search or source-kind lookup exception makes raw `apply()` return `[[]]`. `invoke()` validates first and otherwise has the same raw result. `run()` reports these failures as `[[]]` with `EXECUTION_FAILED`; a valid search with no hits is successful `[[]]` with no errors. With `include_metadata=true`, `run()` reports `INVALID_INPUT`, `invoke()` returns `None`, and raw `apply()` raises `ValueError`. Input data is not read. `output_attributes` is `{}`. There is no persistent side effect, but the search settings leave the process through the registry seam. `explain()` renders the omitted scope as the literal text `None`.
