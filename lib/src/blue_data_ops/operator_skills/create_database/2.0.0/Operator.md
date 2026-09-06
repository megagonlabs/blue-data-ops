# Create a database

`create_database@2.0.0` asks a `RegistrySeam` to create or overwrite one database. It is a pass-through operator: a successful raw call returns the caller's input object.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `created_by` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `data_registry` | `properties` | `no` | `none` | helper:resolve_registry; `RegistrySeam` or raw `DataRegistry`; another value falls through to naming keys | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `platform.name`; converted to string | `seam` |
| `database` | `attributes` | `yes` | `""` | attribute-spec:str; required non-blank string | `scalar` |
| `description` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `overwrite` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `platform.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `data_registry.name`; converted to string | `seam` |
| `properties` | `attributes` | `yes` | `{}` | attribute-spec:str; a caller-supplied mapping fails validation; the mapping default is not materialized | `structured` |
| `source` | `attributes` | `yes` | `""` | attribute-spec:str; required non-blank string | `scalar` |

## Behavior

The registry receives `source`, `database`, `properties`, and `overwrite`. If present, `description` is written next and `created_by` is written last. A later failure can therefore leave the database or its earlier metadata in place. The call requests an index rebuild after each operation.

`apply()` catches a missing registry or a registry-operation failure and returns the original input. Registry resolution itself occurs before that catch, so a resolver exception remains visible. `invoke()` validates first and otherwise keeps the same raw behavior. `run()` calls the execution body directly: it returns `[[]]` with one `EXECUTION_FAILED` error for missing registry, resolver failure, or registry-operation failure. Empty input is accepted because the operation is controlled by attributes.

`output_attributes` is `{}`. The successful and caught-failure raw paths alias the input bundle. `explain()` reports the database name from the first input record's `name`, not from the `database` setting; malformed or empty input produces an empty displayed name. There is no optional extra. Loading this guide performs no registry operation and grants no write authority. The default raw `refiner()` returns `[]`; no structured `refine()` method exists.
