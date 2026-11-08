# Create a table

`create_table@2.0.0` creates one registry-backed database entity. A successful raw call returns the caller's input object.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `collection` | `attributes` | `yes` | `"public"` | attribute-spec:str; required non-blank string with no `"`, backtick, `;` or NUL; forced to `public` when the registry reports SQLite | `scalar` |
| `columns` | `attributes` | `yes` | `[]` | attribute-spec:list; required non-empty list of mappings with a truthy string `name` with no `"`, backtick, `;` or NUL; optional `type` and `misc` must be strings with no `;`, `--`, `/*` or NUL | `structured` |
| `created_by` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `data_registry` | `properties` | `no` | `none` | helper:resolve_registry; `RegistrySeam` or raw `DataRegistry`; another value falls through to naming keys | `seam` |
| `data_registry.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `platform.name`; converted to string | `seam` |
| `database` | `attributes` | `yes` | `"default"` | attribute-spec:str; required non-blank string with no `"`, backtick, `;` or NUL | `scalar` |
| `description` | `attributes` | `yes` | `""` | `attribute-spec:str` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `misc` | `attributes` | `yes` | `{}` | attribute-spec:dict; primary keys must be a list of declared column names, and null counts as none; `foreign_keys`, when present, must be a list, and each entry requires source columns, target table, and target columns, as string lists and a string with no `"`, backtick, `;` or NUL | `structured` |
| `overwrite` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `platform.name` | `properties` | `no` | `none` | helper:resolve_registry; used only with a truthy `data_registry.name`; converted to string | `seam` |
| `properties` | `attributes` | `yes` | `{}` | attribute-spec:str; a caller-supplied mapping fails validation; the mapping default is not materialized | `structured` |
| `source` | `attributes` | `yes` | `"default_source"` | attribute-spec:str; required non-blank string | `scalar` |
| `table` | `attributes` | `yes` | `""` | attribute-spec:str; required non-blank string with no `"`, backtick, `;` or NUL | `scalar` |

## Behavior

The operator first probes the source protocol. Probe errors are ignored; an SQLite result forces `collection="public"`. Raw `apply()` and `invoke()` alias the supplied `misc` mapping, add `cols_definition` with the `columns` value, and pass that same mapping to the create call. This mutates caller-owned attributes. `run()` first copies call attributes, so it mutates only the normalized copy. Description and creator metadata are written after creation, so a later failure can leave earlier effects in place.

SQL sources build `CREATE TABLE` from these names without escaping them, and insert a column's `type` and `misc` as written. Before any registry call, a database, collection, table, column or foreign-key name that is not a string, or holds `"`, a backtick, `;` or NUL, is refused, and so is a `type` or `misc` that is not a string or holds `;`, `--`, `/*` or NUL. Name lists must be lists of such strings. With `overwrite`, the SQLite, PostgreSQL and MySQL sources drop an existing table before they build the new definition, so everything they read is checked first as well: `table` and a non-empty `columns` list whose entries have a non-empty `name` must be present, and a `foreign_keys` value, or any of its entries' fields, cannot be null. Only a null `primary_key` is read as absent, because every SQL source skips it. `run()` returns `INVALID_INPUT` with a suggestion naming the field, `invoke()` returns `None`, and raw `apply()` returns the original input. `overwrite` is read as attribute validation reads it, so `"true"`, `"yes"` and `"1"` mean true and `"false"`, `"no"` and `"0"` mean false. A value validation refuses, such as `"maybe"`, is refused in the same way; when no name or definition is refused first, `run()`'s suggestion is `overwrite must be true or false`. A null `overwrite` is refused by `run()` and `invoke()` as well, but raw `apply()`, which does not validate, reads it as false. Column `type` and `misc` are still SQL: their check stops a second statement and `--` or `/*` comments, but not MySQL's `#` comment, which literal defaults such as `DEFAULT '#fff'` contain, and not a comma that adds further clauses or columns. SQLite also inserts column names without quotes, and names are checked only for the characters above, so there a column named `unit price` becomes a column `unit` whose declared type begins with `price`, `a, b` adds a second column, and a reserved word such as `order` makes SQLite reject the definition. Pass only definitions and names you would run yourself. A definition the database itself rejects is not caught here: PostgreSQL then rolls the drop back, though the registry no longer lists the table until the source is synced again, while SQLite and MySQL have already committed the drop, so there the table is lost.

`apply()` catches a missing registry and guarded registry-operation failures, returning the original input. Registry resolution happens before the guarded block and can still raise. `invoke()` validates first. `run()` calls the execution body directly and returns `[[]]` with `EXECUTION_FAILED` for a missing registry, resolver failure, or guarded operation failure. Empty input is valid because settings identify the table.

`output_attributes` is `{}`. Successful and caught-failure raw paths alias the input bundle; successful raw execution also mutates a supplied `misc` mapping. `explain()` displays the table name from the first input record's `name`, not from `table`. There is no optional extra or provider disclosure beyond the named registry fields and creation metadata. Loading this guide does not authorize a registry write.
