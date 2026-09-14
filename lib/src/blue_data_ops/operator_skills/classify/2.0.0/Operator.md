# Classification

`classify@2.0.0` trains on labeled vectors in the first group, then predicts labels for records in every group. Install the `ml` extra before using a model path.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `algorithm` | `properties` | `no` | `"decision_tree"` | none; `decision_tree`, `knn`, or `multinomial_nb`; another value returns the input unchanged | `scalar` |
| `alpha` | `attributes` | `yes` | `1.0` | attribute-spec:float; converted with `float()` | `scalar` |
| `criterion` | `attributes` | `yes` | `"gini"` | attribute-spec:str; the selected model validates accepted values | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `fit_prior` | `attributes` | `yes` | `true` | attribute-spec:bool; strings other than `false` and `0` execute as true | `scalar` |
| `label_key` | `attributes` | `yes` | `none` | attribute-spec:str; custom validation requires a non-empty value, while Pydantic-lax bytes pass | `scalar` |
| `max_depth` | `attributes` | `yes` | `none` | attribute-spec:int; converted with `int()` when supplied | `scalar` |
| `min_samples_leaf` | `attributes` | `yes` | `1` | attribute-spec:float; converted to integer or float from the raw value | `scalar` |
| `min_samples_split` | `attributes` | `yes` | `2` | attribute-spec:float; converted to integer or float from the raw value | `scalar` |
| `n_neighbors` | `attributes` | `yes` | `5` | attribute-spec:int; converted with `int()` | `scalar` |
| `output_key` | `attributes` | `yes` | `"predicted_label"` | `attribute-spec:str` | `scalar` |
| `random_state` | `attributes` | `yes` | `none` | attribute-spec:int; converted with `int()` when supplied | `scalar` |
| `splitter` | `attributes` | `yes` | `"best"` | attribute-spec:str; the selected model validates accepted values | `scalar` |
| `vector_key` | `attributes` | `yes` | `none` | attribute-spec:str; custom validation requires a non-empty value, while Pydantic-lax bytes pass | `scalar` |
| `weights` | `attributes` | `yes` | `"uniform"` | attribute-spec:str; KNN validates accepted values | `scalar` |

## Behavior

Only first-group records with a list-valued vector and non-null label train the model. Records in all groups are copied for successful prediction; a record without a list-valued vector receives `None` at `output_key`. Empty input, an empty first group, no usable training pair, or an unknown algorithm returns the caller's input object unchanged.

NumPy and the selected scikit-learn class load only after a supported non-empty path is reached. Missing modules therefore propagate from raw `apply()` and `invoke()`; `run()` returns `[[]]` with a generic `EXECUTION_FAILED` error. Model construction, fitting, and prediction failures are caught: raw calls return the original input, while `run()` reports an execution failure because `_execute()` raises before the compatibility catch in `apply()`.

`output_attributes` is `{}`. `explain()` uses shared statistics. There is no provider disclosure or persistent side effect.
