# Create a table

`create_table@2.0.0` creates one registry-backed database entity. A successful raw call returns the caller's input object.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `collection` | `attributes` | `yes` | `"public"` | attribute-spec:str; required non-blank string and forced to `public` when the registry reports SQLite | `scalar` |
| `columns` | `attributes` | `yes` | `[]` | attribute-spec:list; required non-empty list of mappings with a truthy `name`; optional `type` and `misc` must be strings | `structured` |
| `created_by` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `data_registry` | `properties` | `no` | `none` | helper:resolve_registry; `RegistrySeam` or raw `DataRegistry`; another value falls through to naming keys | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `platform.name`; converted to string | `seam` |
| `database` | `attributes` | `yes` | `"default"` | attribute-spec:str; required non-blank string | `scalar` |
| `description` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `misc` | `attributes` | `yes` | `{}` | attribute-spec:dict; primary keys must name declared columns; foreign-key entries require source columns, target table, and target columns | `structured` |
| `overwrite` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `platform.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `data_registry.name`; converted to string | `seam` |
| `properties` | `attributes` | `yes` | `{}` | attribute-spec:str; a caller-supplied mapping fails validation; the mapping default is not materialized | `structured` |
| `source` | `attributes` | `yes` | `"default_source"` | attribute-spec:str; required non-blank string | `scalar` |
| `table` | `attributes` | `yes` | `""` | attribute-spec:str; required non-blank string | `scalar` |

## Behavior

The operator first probes the source protocol. Probe errors are ignored; an SQLite result forces `collection="public"`. Raw `apply()` and `invoke()` alias the supplied `misc` mapping, add `cols_definition` with the `columns` value, and pass that same mapping to the create call. This mutates caller-owned attributes. `run()` first copies call attributes, so it mutates only the normalized copy. Description and creator metadata are written after creation, so a later failure can leave earlier effects in place.

`apply()` catches a missing registry and guarded registry-operation failures, returning the original input. Registry resolution happens before the guarded block and can still raise. `invoke()` validates first. `run()` calls the execution body directly and returns `[[]]` with `EXECUTION_FAILED` for a missing registry, resolver failure, or guarded operation failure. Empty input is valid because settings identify the table.

`output_attributes` is `{}`. Successful and caught-failure raw paths alias the input bundle; successful raw execution also mutates a supplied `misc` mapping. `explain()` displays the table name from the first input record's `name`, not from `table`. There is no optional extra or provider disclosure beyond the named registry fields and creation metadata. Loading this guide does not authorize a registry write. The default raw `refiner()` returns `[]`; no structured `refine()` method exists.
