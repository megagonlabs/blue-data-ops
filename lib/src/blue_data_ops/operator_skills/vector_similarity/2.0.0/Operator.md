# Vector similarity

`vector_similarity@2.0.0` compares records from exactly two input groups. `cartesian` mode returns every left-right pair. `pairwise` mode requires equal group lengths and compares matching positions. Each result contains `id`, `left_id`, `right_id`, and `similarity.score`.

## Embeddings and results

Records may supply one-dimensional numeric values under `embedding`. When both groups already have embeddings, the operator does not construct a model and `fields` may be omitted. With `on_missing_embedding="embed_missing"`, `fields` must name one text field for each side; missing embeddings are generated through the configured sentence-transformer model. This path needs the `vector` extra and can download model data according to the model library's configuration.

The `cosine`, `dot`, and `l2` metrics are supported. The `l2` score is the negative distance, so larger values remain more similar. A zero vector produces a cosine score of zero. `normalize=True` normalizes each embedding before scoring.

`add_meta_data=True` adds metric and comparison-mode keys. It adds `similarity.model` only when the call generated at least one embedding. A configured `threshold` adds `similarity.threshold` and `similarity.passed`. Input record IDs are copied into the result; missing IDs use positional `left_<n>` and `right_<n>` values.

## Failure behavior

`run()` validates group count, mode, fields, metric, missing-value policies, pairwise length, threshold, and Boolean switches. It returns `[[]]` with structured metadata for rejected input or execution errors such as inconsistent embedding dimensions. `invoke()` returns `None` when validation fails. Direct `apply()` raises `ValueError` for these execution checks and can surface optional-dependency or model errors.

Two empty input groups pass validation but fail during embedding preparation. `run([[], []], {})` returns `[[]]` with an execution error; `apply()` and `invoke()` raise `ValueError` about inconsistent dimensions.

Successful output uses a new result group and an empty `output_attributes` mapping. The operator has no registry, LLM-provider, or data-store side effect. The model path can still download model data. The shared `run()` timeout can bound execution, but cancellation does not guarantee that model work has stopped.
