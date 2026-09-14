# Clustering

`cluster@2.0.0` clusters list-valued vectors from the first input group. Install the `ml` extra before using a non-empty model path.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `algorithm` | `properties` | `no` | `"kmeans"` | none; `kmeans`, `dbscan`, or `gaussian`; another value returns the original first group | `scalar` |
| `covariance_type` | `attributes` | `yes` | `"full"` | attribute-spec:str; GaussianMixture validates accepted values | `scalar` |
| `eps` | `attributes` | `yes` | `0.5` | attribute-spec:float; converted with `float()` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `init` | `attributes` | `yes` | `source-dependent` | attribute-spec:str; unsupported values fall back inside the selected model path | `scalar` |
| `init_centroids` | `attributes` | `yes` | `none` | attribute-spec:list; required with `init=specified` for KMeans and Gaussian mixture, with length equal to `n_cluster` | `structured` |
| `max_iter` | `attributes` | `yes` | `300` | attribute-spec:int; converted with `int()` | `scalar` |
| `min_samples` | `attributes` | `yes` | `5` | attribute-spec:int; converted with `int()` | `scalar` |
| `n_cluster` | `attributes` | `yes` | `none` | attribute-spec:int; required for KMeans and Gaussian mixture; converted with `int()` | `scalar` |
| `output_key` | `attributes` | `yes` | `"cluster_index"` | `attribute-spec:str` | `scalar` |
| `vector_key` | `attributes` | `yes` | `none` | attribute-spec:str; custom validation requires a truthy value, while Pydantic-lax bytes pass | `scalar` |

## Behavior

KMeans and Gaussian mixture need at least `n_cluster` usable vectors. DBSCAN needs one. Too few vectors, or an unknown algorithm, returns a new outer list containing the original first-group list. A successful model call copies every first-group record and writes an integer label; a record without a list-valued vector receives `None`. Later groups are ignored.

Empty input returns `[[]]`. Missing counts and ragged vectors can raise before the guarded model call. Model failures are caught by raw `apply()` and return the original first group, while `run()` reports `EXECUTION_FAILED`. Missing NumPy or scikit-learn propagates on raw calls and becomes the same generic structured failure; it does not receive the LLM-extra installation suggestion.

`output_attributes` is `{}`. `explain()` uses shared statistics. There is no provider disclosure or persistent side effect.
