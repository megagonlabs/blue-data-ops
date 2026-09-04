# Classification

`classify@2.0.0` trains a classifier from labeled vectors in the first input group, then predicts labels for records in every group. Install the `ml` extra before executing a model path.

## Training and prediction

Only first-group records that have both a list-valued `vector_key` and a non-null `label_key` train the model. Later groups never contribute training labels. During prediction, records with a list-valued vector receive a prediction; other records are copied with the configured `output_key` set to `None`.

Choose the model with `properties["algorithm"]`. The supported values are `decision_tree` (the default), `knn`, and `multinomial_nb`. Any other value returns the input unchanged. With usable settings, empty input, an empty first group, or a first group with no usable training pair also returns the input unchanged without importing NumPy or scikit-learn.

The live `io.attributes` mapping declares the shared settings `vector_key`, `label_key`, and `output_key`; the decision-tree settings `criterion`, `splitter`, `max_depth`, `min_samples_split`, `min_samples_leaf`, and `random_state`; the k-nearest-neighbor settings `n_neighbors` and `weights`; and the multinomial naive-Bayes settings `alpha` and `fit_prior`. `algorithm` is an undeclared property.

Numeric and Boolean model settings are converted before the empty-input and algorithm checks. A malformed setting for a model that was not selected can therefore fail the call.

## Failure behavior

NumPy and the selected scikit-learn class load only after the input reaches a supported model path. Import errors propagate from `apply()` and `invoke()`; `run()` contains them as execution errors. Model construction, fitting, and prediction failures return the original input from `apply()` and `invoke()`, while `run()` returns `[[]]` with an execution error.

Successful output contains copied records rather than the caller's record objects. `output_attributes` is empty in this version.
