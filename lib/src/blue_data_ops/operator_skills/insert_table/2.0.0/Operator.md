# Insert table rows

`insert_table@2.0.0` writes record groups to an existing table through a `RegistrySeam`. It is a side-effecting operator. Loading this guide does not open a database or authorize a write.

Pass a `RegistrySeam` or raw `DataRegistry` as `properties["data_registry"]`. Provider-backed resolution instead needs both `properties["platform.name"]` and `properties["data_registry.name"]`.

## Write behavior

The first input group controls the empty guard. If it is empty, the whole call returns `[[]]` even when later groups contain records. Later empty groups are skipped.

Each nonempty group is divided by `batch_size`. The first record in a batch fixes the SQL column list; later records supply `None` for missing columns and drop keys that are not in that first record. The operator reconnects to the source for every batch. `collection` appears in logging and the SQLite compatibility probe but does not change the generated `INSERT` statement.

On success the operator returns the original input object. It does not return an inserted-row count. The live `io.attributes` mapping gives the declared source, database, table, collection, and batch-size fields.

## Empty and failure results

`apply()` preserves two compatibility outcomes. A missing registry or an outer operation error passes the original input through. A failed connection or batch write returns `[[]]`. These shapes alone do not tell a caller whether a write succeeded.

Use `run()` when the caller needs structured execution metadata. It returns `[[]]` with an execution error when the write path raises, including a missing registry or failed batch. The operator does not implement its own timeout; the shared `run()` timeout property applies at the execution boundary. `output_attributes` is empty.

The operator does not create the table. Create it before calling this operator and grant the underlying source only the write access the call needs.
