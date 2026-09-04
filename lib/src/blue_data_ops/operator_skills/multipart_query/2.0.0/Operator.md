# Multipart-query refinement

`multipart_query@2.0.0` turns groups of common-table-expression records into portable `DataPipeline` alternatives. Its useful path is `refine()`. Compute through `apply()` or `run()` returns `[[]]`.

## Refinement input

Each alternative is a list of CTE records. A record needs `description`, `sql`, `table`, `columns`, and `dependency`. `description`, `sql`, and `table` are strings. Each `columns` entry is a mapping with a string `name` and an optional string `type`; every dependency is a string. A numeric, non-Boolean `generality` value is optional. The structured refinement path rejects a malformed `plans` value and returns no plan with validation metadata. Dependency-order, missing-dependency, and duplicate-dependency errors can still fail a direct `refiner()` call.

When `plans` is absent from the attributes, `refine()` moves the input bundle into that attribute and replaces compute input with `[[]]`. The `serialize` flag chooses one chain or parallel CTE branches. The returned plan rewrites child operator IDs to the selected refinement version. A call through the `@2.0.0` registry entry therefore returns `@2.0.0` child IDs even though the plan builder's compatibility constants are `@1.0.0`.

## Call boundaries

`refine()` returns a list of plans and `ExecMeta`. `run()` reports a successful empty compute result. `apply()` returns the same raw empty result.

The direct validator keeps the two-argument compatibility signature `validate(attributes, properties)`. The canonical three-argument `invoke(input_data, attributes, properties)` path calls it with `input_data` and raises `TypeError`. Callers should use `refine()` for this operator. `output_attributes` is empty on the compute path.
