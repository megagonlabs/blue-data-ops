# Segment text

`segment_text@2.0.0` splits record text into groups of segment records with stable character offsets. It supports sentence, paragraph, word, token, and heading strategies.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `keep_delimiters` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `max_tokens` | `attributes` | `yes` | `650` | `attribute-spec:int` | `scalar` |
| `meta_fields` | `attributes` | `yes` | `[]` | `attribute-spec:list[str]` | `structured` |
| `min_chars` | `attributes` | `yes` | `20` | `attribute-spec:int` | `scalar` |
| `segment_id_format` | `attributes` | `yes` | `"{doc_id}::S{index:04d}"` | `attribute-spec:str` | `scalar` |
| `split_strategy` | `attributes` | `yes` | `"sentence"` | `attribute-spec:str` | `scalar` |
| `text_field` | `attributes` | `yes` | `none` | `attribute-spec:str` | `scalar` |
| `word_overlap` | `attributes` | `yes` | `0` | `attribute-spec:int` | `scalar` |

## Segment records

Each result has `segment_id`, `doc_id`, `text`, `start_char`, `end_char`, and `segment.split_strategy`. Requested metadata is copied to flat `segment.<field>` keys. The source record is not returned.

`doc_id` comes from a nonblank `doc_id`, then `id`, then `table<n>_row<n>_<text_field>`. `segment_id_format` may use `doc_id`, `index`, `field_name`, `group_index`, and `record_index`. An unknown placeholder raises during raw execution.

Sentence splitting recognizes `.`, `!`, `?`, paragraph breaks, and end of text. `token` currently uses the same whitespace-word units as `word`. Heading mode begins segments at Markdown headings, short title-cased lines, uppercase lines, or lines ending in `:`. `max_tokens` is an approximate word count. `min_chars` may merge adjacent units, and `word_overlap` applies when a large unit is split.

## Empty and failure behavior

Empty groups, missing fields, `None`, and whitespace-only text produce empty result groups without an error. Other values are converted with `str()`. Output groups follow input groups, and `output_attributes` is empty.

`run()` contains invalid settings and formatting failures as `[[]]` with metadata. `invoke()` returns `None` for validation failure, but a byte-valued format accepted by the lax base check can raise `AttributeError`, and an unknown placeholder can raise `KeyError`. Direct `apply()` exposes the same execution errors.
