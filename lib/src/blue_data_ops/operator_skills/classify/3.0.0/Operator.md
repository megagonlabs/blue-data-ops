# Classification

`classify@3.0.0` trains on labeled vectors in the first group, then predicts labels for records in every group. Install the `ml` extra before using a nonempty model path. Resolve the exact version with `versioned_registry().resolve("classify@3.0.0")`.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `algorithm` | `properties` | `no` | `"decision_tree"` | none; structured validation rejects values outside `decision_tree`, `knn`, and `multinomial_nb` | `scalar` |
| `alpha` | `attributes` | `yes` | `1.0` | attribute-spec:float; converted with `float()` | `scalar` |
| `criterion` | `attributes` | `yes` | `"gini"` | attribute-spec:str; the selected model validates accepted values | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `fit_prior` | `attributes` | `yes` | `true` | attribute-spec:bool; strings other than `false` and `0` execute as true | `scalar` |
| `label_key` | `attributes` | `yes` | `none` | attribute-spec:str; custom validation requires a truthy value, while lax byte strings may pass | `scalar` |
| `max_depth` | `attributes` | `yes` | `none` | attribute-spec:int; raw-path conversion differs as described below | `scalar` |
| `min_samples_leaf` | `attributes` | `yes` | `1` | attribute-spec:float; converted to integer or float from the raw value | `scalar` |
| `min_samples_split` | `attributes` | `yes` | `2` | attribute-spec:float; converted to integer or float from the raw value | `scalar` |
| `n_neighbors` | `attributes` | `yes` | `5` | attribute-spec:int; converted with `int()` | `scalar` |
| `output_key` | `attributes` | `yes` | `"predicted_label"` | `attribute-spec:str` | `scalar` |
| `random_state` | `attributes` | `yes` | `none` | attribute-spec:int; raw-path conversion differs as described below | `scalar` |
| `splitter` | `attributes` | `yes` | `"best"` | attribute-spec:str; the selected model validates accepted values | `scalar` |
| `vector_key` | `attributes` | `yes` | `none` | attribute-spec:str; custom validation requires a truthy value, while lax byte strings may pass | `scalar` |
| `weights` | `attributes` | `yes` | `"uniform"` | attribute-spec:str; KNN validates accepted values | `scalar` |

## Result

A usable training row has a Python-list vector at `vector_key` and a non-`None` label at `label_key`. Training uses usable rows from the first group. Successful prediction copies records in every group, writing the predicted label at `output_key`; a record without a list-valued prediction vector receives `None` there. Vector element types and dimensions are checked by NumPy and the selected model during execution, not by input validation.

Every group empty is successful empty: output is `[[]]`, `output_attributes` is `{}`, `errors` is empty, and `is_empty` is true. If any group has records but the first group has no usable training row, the structured call is invalid. This includes an empty first group followed by a nonempty prediction group.

## Calls and errors

Check `exec_meta.errors` before consuming labels. An unsupported algorithm, missing required setting, or unusable training set produces `INVALID_INPUT` at `VALIDATE`. A model import, construction, fit, or prediction failure produces `EXECUTION_FAILED` at `EXECUTE`. A malformed result produces `EXECUTION_RESULT_INVALID` at `NORMALIZE`, and a timeout produces `OPERATOR_TIMEOUT`. Failed calls return `[[]]`, `{}`, and `is_empty=False`.

`run()` returns `(output_data, output_attributes, exec_meta)` and materializes declared defaults. Raw `apply()` returns only data and bypasses the structured validation boundary. On that compatibility path, an unsupported algorithm or unusable training set returns the input, and a caught model failure does the same. Raw `invoke()` validates first and returns `None` on rejection. Neither raw path returns `ExecMeta`.

For `max_depth` and `random_state`, structured `run()` and validated `invoke()` reject the string `"none"` because both attributes are declared as integers. Raw `apply()` bypasses that type check: its body treats any case-insensitive `"none"` string as unset and converts other supplied values with `int()`.

Optional `exec_meta.traces["elapsed_ms"]` is finite and nonnegative. Missing traces are valid. See [examples](examples.md) for a deterministic decision-tree call and an invalid algorithm check.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.
