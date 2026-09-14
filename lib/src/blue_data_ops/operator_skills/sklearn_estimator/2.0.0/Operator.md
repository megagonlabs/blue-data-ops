# Scikit-learn estimator

`sklearn_estimator@2.0.0` builds one estimator from the first input group and applies it to records
in every group. Install the `ml` extra before using this operator.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `algorithm` | `properties` | `no` | `none` | none | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `label_key` | `attributes` | `yes` | `none` | attribute-spec:str; required for classifiers and regressors | `scalar` |
| `output_key` | `attributes` | `yes` | `"prediction"` | `attribute-spec:str` | `scalar` |
| `vector_key` | `attributes` | `yes` | `none` | `attribute-spec:str` | `scalar` |

## Behavior

Any additional attribute whose name matches a parameter in the selected estimator's constructor is
forwarded unchanged. Other additional attributes are ignored.

`algorithm` is required and accepts any case-insensitive class name returned by
`sklearn.utils.all_estimators()`. `vector_key` must be non-empty. Classifiers and regressors also
require a non-empty `label_key`.

The first group supplies training vectors. Classifiers and regressors also read labels from that
group. Each successful result copies the source record and writes a prediction, cluster label, or
transformed vector to `output_key`. Records without a list-valued vector receive `None`.

The fitted model handles every group when it provides `predict()` or `transform()`. An estimator
that only provides `fit_predict()` can label the training group, but it cannot infer a later
non-empty group. That call fails as a whole instead of fitting a separate model to later data.

Empty input, an empty first group, no usable training vector, or an unknown algorithm returns the
original input from raw `apply()`. Structured `run()` reports an unknown algorithm as
`INVALID_INPUT`; model construction, fitting, and inference errors become `EXECUTION_FAILED`.
An empty first group is also a successful no-op through `run()`, even when later groups contain
records. Without the `ml` extra, raw `apply()` raises `ModuleNotFoundError`; structured `run()`
reports `EXECUTION_FAILED` at `EXECUTE`.
NumPy and scikit-learn are imported only while validating or running this operator, so importing
`blue_data_ops` does not require the `ml` extra.

`output_attributes` is `{}`. `explain()` uses shared statistics. The fitted model is not persisted.
