# Minimum value

`min@3.0.0` reduces the first input group to the smallest usable value at `min_key`. Later groups are ignored. Resolve the exact version with `versioned_registry().resolve("min@3.0.0")`.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `min_key` | `attributes` | `yes` | `none` | attribute-spec:str; required non-empty value | `scalar` |
| `output_key` | `attributes` | `yes` | `"min"` | attribute-spec:str | `scalar` |

## Result

Integers and floats contribute directly, including `True` and `False`. Other values try `int()` before `float()`: numeric bytes can convert, a fractional `Decimal` truncates through `int()`, and a string such as `"2.5"` reaches `float()`. Missing fields, `None`, and values that fail both conversions are skipped. Only `ValueError` and `TypeError` conversion failures are suppressed. The first value at an equal minimum supplies the returned numeric type. NaN and infinity are not filtered.

When a value contributes, output is `[[{"min": value}]]`, or the field uses the selected `output_key`; `is_empty` is false. A real zero is data. If the first group is absent or empty, the field is absent, or no value converts, the call is successful empty: `[[]]`, `{}`, no errors, and `is_empty=True`.

## Calls and errors

Check `exec_meta.errors` first. A missing or empty `min_key` produces `INVALID_INPUT` at `VALIDATE`. An exception outside the two suppressed conversion types, or a comparison error among accepted values, produces `EXECUTION_FAILED` at `EXECUTE`. A malformed result produces `EXECUTION_RESULT_INVALID` at `NORMALIZE`, and a timeout produces `OPERATOR_TIMEOUT`. Failed calls return `[[]]`, `{}`, and `is_empty=False`.

`run()` returns `(output_data, output_attributes, exec_meta)`. Raw `apply()` returns only data and exposes the same successful-empty tensor, but it bypasses structured validation and lets body exceptions propagate. Raw `invoke()` validates first and returns `None` on rejection. Neither raw path returns `ExecMeta`.

Optional `exec_meta.traces["elapsed_ms"]` is finite and nonnegative. Missing traces are valid. See [examples](examples.md) for conversion, zero, successful empty, and invalid input.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.
