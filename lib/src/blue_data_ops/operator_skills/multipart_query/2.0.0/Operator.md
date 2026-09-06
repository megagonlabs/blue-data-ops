# Multipart-query refinement

`multipart_query@2.0.0` turns groups of common-table-expression records into portable `DataPipeline` alternatives. Its useful path is `refine()`; compute through `apply()` or `run()` returns `[[]]`.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected; applies to `run()` and `refine()` | `scalar` |
| `plans` | `attributes` | `no` | `none` | none; structured refinement moves normalized input here when absent, then validates nested CTE records | `scalar` |
| `serialize` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |

## Refinement behavior

Each plan alternative is a list of CTE records. A record needs string `description`, `sql`, and `table` values, a `columns` list, and a string `dependency` list. Every column is a mapping with a string `name` and optional string `type`. Optional `generality` must be numeric and not Boolean.

When `plans` is absent, structured `refine()` moves the input bundle into that setting and replaces compute input with `[[]]`. `serialize=true` chains CTEs; false allows parallel branches. Child operator IDs are rewritten to the selected refinement version, so resolving the `@2.0.0` entry produces `@2.0.0` children. A malformed structured input returns no plan with validation metadata. Dependency order, a missing dependency, or duplicate dependencies can still raise from the raw `refiner()` path; `refine()` contains the failure in `ExecMeta`.

The direct validator keeps the two-argument compatibility signature `validate(attributes, properties)`. The inherited three-argument `invoke(input_data, attributes, properties)` path therefore raises `TypeError`. Callers should use `refine()` for plan output. `apply()` returns raw `[[]]`; `run()` returns successful `[[]]` and `{}` for `output_attributes`.

The resulting plan contains the supplied SQL, table, column, dependency, and description fields, but nothing leaves the process and no child is executed during refinement. Loading this guide does not disclose it automatically to a planner, registry, model provider, or MCP client. No optional extra is required.
