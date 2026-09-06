# Insert table rows

`insert_table@2.0.0` writes record groups to an existing table through a `RegistrySeam`. Loading this guide does not connect to a database or authorize a write.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `batch_size` | `attributes` | `yes` | `100` | attribute-spec:int; greater than zero; Boolean `true` passes because it is an integer | `scalar` |
| `collection` | `attributes` | `yes` | `"public"` | attribute-spec:str; probed and forced to `public` for SQLite, but does not enter the SQL statement | `scalar` |
| `data_registry` | `properties` | `no` | `none` | helper:resolve_registry; `RegistrySeam` or raw `DataRegistry`; another value falls through to naming keys | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `platform.name`; converted to string | `seam` |
| `database` | `attributes` | `yes` | `"default"` | attribute-spec:str; required non-blank string | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `platform.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `data_registry.name`; converted to string | `seam` |
| `source` | `attributes` | `yes` | `"default_source"` | attribute-spec:str; required non-blank string | `scalar` |
| `table` | `attributes` | `yes` | `""` | attribute-spec:str; required non-blank string | `scalar` |

## Behavior

The first input group controls the empty guard. If it is empty, the whole call returns `[[]]` even when later groups contain records. Later empty groups are skipped. Each nonempty group is divided by `batch_size`, and the source connection is reopened for every batch. The first record in a batch fixes its SQL columns; later records supply `None` for missing columns and omit extra keys. Non-mapping and empty entries are ignored.

On success, raw and structured calls return the original input object. A missing registry or an outer operation error makes `apply()` pass the input through. A failed connection or batch write makes it return `[[]]`. `run()` reports either failure class as `[[]]` with `EXECUTION_FAILED`; a guarded empty first group is a successful empty result with no error. These output shapes do not prove that rows were persisted, so callers that need confirmation must inspect `ExecMeta` and the database.

`output_attributes` is `{}`; there is no inserted-row count. `collection` appears in the log and SQLite probe only. The disclosed boundary contains the source, database, table, generated insert statement, and row values. Earlier batches remain committed if a later batch fails. `explain()` reports the input row count, not the actual inserted count. The default raw `refiner()` returns `[]`; no structured `refine()` method exists.
