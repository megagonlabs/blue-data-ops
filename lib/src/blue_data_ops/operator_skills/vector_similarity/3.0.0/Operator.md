# Vector similarity

`vector_similarity@3.0.0` compares records from exactly two groups. Cartesian mode produces every left-right pair. Pairwise mode compares matching positions. Resolve this exact version explicitly; ordinary planner and MCP selection remains on version 2.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `add_meta_data` | `attributes` | `yes` | `false` | attribute-spec:bool | `scalar` |
| `comparison_mode` | `attributes` | `yes` | `"cartesian"` | attribute-spec:str | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | finite-positive-number; Boolean rejected | `scalar` |
| `fields` | `attributes` | `yes` | `none` | attribute-spec:list[str] | `structured` |
| `metric` | `attributes` | `yes` | `"cosine"` | attribute-spec:str | `scalar` |
| `model_ref` | `attributes` | `yes` | `"all-MiniLM-L6-v2"` | attribute-spec:str | `scalar` |
| `normalize` | `attributes` | `yes` | `false` | attribute-spec:bool | `scalar` |
| `on_missing_embedding` | `attributes` | `yes` | `"raise"` | attribute-spec:str | `scalar` |
| `on_missing_fields` | `attributes` | `yes` | `"raise"` | attribute-spec:str | `scalar` |
| `threshold` | `attributes` | `yes` | `none` | attribute-spec:float | `scalar` |

## Setting constraints

`run()` and `invoke()` apply the attribute schema to these five values before the operator-specific rules. `comparison_mode`, `metric`, `on_missing_embedding`, and `on_missing_fields` must be strings, while `fields` must be a list of strings when supplied. The operator then accepts `cartesian` or `pairwise` for `comparison_mode`; `cosine`, `dot`, or `l2` for `metric`; `raise` or `embed_missing` for `on_missing_embedding`; and `raise` or `use_empty` for `on_missing_fields`. A supplied `fields` list must contain exactly two field-name strings.

## Empty comparisons

A validated cartesian call has zero pairs when either group is empty. A pairwise call has zero pairs only when both groups are empty. These cases return `[[]]`, `{}`, `errors=[]`, and `is_empty=True` before NumPy or model work. In cartesian mode, the implementation therefore does not inspect embedding contents in an unused nonempty side. Group shape and control validation still run first. Pairwise input with one empty side remains invalid because the group lengths differ.

## Embeddings and records

Existing one-dimensional embeddings avoid model construction, and `fields` may be omitted. With `on_missing_embedding=embed_missing`, `fields` names one text field for each side. That path imports sentence-transformers and may download model files under the library's configuration. `on_missing_fields=use_empty` supplies empty text for a missing field.

The supported metrics are `cosine`, `dot`, and `l2`. `l2` is stored as negative distance. Normalization, threshold comparison, and existing dimension checks retain their current behavior; this version adds no broader numeric-validity policy.

Every pair record contains `id`, `left_id`, `right_id`, and `similarity.score`. A threshold adds `similarity.threshold` and `similarity.passed`. `add_meta_data=true` adds `similarity.metric` and `similarity.comparison_mode`, plus `similarity.model` only when the call generated an embedding. Scores and metadata remain tensor records. `output_attributes` is `{}`.

Check `exec_meta.errors` before `is_empty`. Invalid group counts, settings, or pairwise lengths are validation errors. Dependency, embedding, shape, dimension, and scoring failures are execution errors. Failed calls return `[[]]`, `{}`, and `is_empty=False`.

`run()` returns `(output_data, output_attributes, exec_meta)` and may add finite, nonnegative `exec_meta.traces["elapsed_ms"]`. Raw `apply()` returns data only, skips structured validation and containment, and exposes exceptions. Raw `invoke()` returns `None` on validation rejection and exposes later exceptions. See [examples](examples.md) for precomputed pairwise scores and a zero-pair result.

For a structurally valid bundle, `run()` may also record `input_shape` before validation and
execution. The value has `groups` and `rows_per_group`; its counts do not change if the caller data
is later mutated. Invalid bundle structure omits this key.

After successful normalization, `output_shape` uses the same fields. Failures and timeouts omit it.
An all-empty successful output is normalized to `[[]]`, while a mixed multi-group output retains a
zero count for each empty group. Both shape keys are optional.
