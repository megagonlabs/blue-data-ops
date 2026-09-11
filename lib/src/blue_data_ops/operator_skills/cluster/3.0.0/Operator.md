# Clustering

`cluster@3.0.0` clusters list-valued vectors from the first input group. Later groups are ignored. Install the `ml` extra before using a nonempty model path, then resolve the exact version with `versioned_registry().resolve("cluster@3.0.0")`.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `algorithm` | `properties` | `no` | `"kmeans"` | none; structured validation rejects values outside `kmeans`, `dbscan`, and `gaussian` | `scalar` |
| `covariance_type` | `attributes` | `yes` | `"full"` | attribute-spec:str; GaussianMixture validates accepted values | `scalar` |
| `eps` | `attributes` | `yes` | `0.5` | attribute-spec:float; converted with `float()` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `init` | `attributes` | `yes` | `source-dependent` | attribute-spec:str; KMeans falls back to `"k-means++"`; Gaussian falls back to `"kmeans"`; DBSCAN does not use `init`; `specified` uses `init_centroids` | `scalar` |
| `init_centroids` | `attributes` | `yes` | `none` | attribute-spec:list; required with `init=specified` for KMeans and Gaussian mixture, with length equal to `n_cluster` | `structured` |
| `max_iter` | `attributes` | `yes` | `300` | attribute-spec:int; converted with `int()` | `scalar` |
| `min_samples` | `attributes` | `yes` | `5` | attribute-spec:int; converted with `int()` | `scalar` |
| `n_cluster` | `attributes` | `yes` | `none` | attribute-spec:int; required for KMeans and Gaussian mixture; converted with `int()` | `scalar` |
| `output_key` | `attributes` | `yes` | `"cluster_index"` | `attribute-spec:str` | `scalar` |
| `vector_key` | `attributes` | `yes` | `none` | attribute-spec:str; custom validation requires a truthy value, while lax byte strings may pass | `scalar` |

## Algorithm fallback

The `init` specification has no materialized default. When the setting is omitted, structured `run()`, raw `apply()`, and validated `invoke()` all reach the algorithm-specific fallback shown above.

## Result

A usable fit row has a Python-list vector at `vector_key`. KMeans and Gaussian mixture require at least `n_cluster` usable first-group vectors. DBSCAN requires one usable vector and does not use `n_cluster` for this count rule. The accepted lax integer conversion remains in place, so a value such as `"2"` can supply the cluster count.

A successful model call copies each first-group record and writes an integer label at `output_key`. A record without a list-valued vector receives `None`. DBSCAN label `-1` means noise. Cluster numbers from fitted models are identifiers, not an ordering of the groups.

An absent or empty first group is successful empty, even if a later group contains records. Output is `[[]]`, attributes are `{}`, and `is_empty` is true. A nonempty first group with no usable vector is invalid. Too few usable vectors for KMeans or Gaussian mixture is also invalid.

## Calls and errors

Check `exec_meta.errors` before using labels. Unsupported algorithms and insufficient fit data produce `INVALID_INPUT` at `VALIDATE`. Matrix construction, dependency loading, and model failures produce `EXECUTION_FAILED` at `EXECUTE`. A ragged vector matrix is an execution error, not an input-validation result. A malformed result produces `EXECUTION_RESULT_INVALID` at `NORMALIZE`, and a timeout produces `OPERATOR_TIMEOUT`. Failed calls return `[[]]`, `{}`, and `is_empty=False`.

`run()` returns `(output_data, output_attributes, exec_meta)`. Raw `apply()` bypasses structured validation and returns only data. Its caught model failures return the original first group, while ragged matrix construction can raise before that catch. Raw `invoke()` validates first and returns `None` on rejection. Neither raw path returns `ExecMeta`.

Optional `exec_meta.traces["elapsed_ms"]` is finite and nonnegative. Missing traces are valid. See [examples](examples.md) for fixed KMeans centroids and insufficient-fit validation.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.
