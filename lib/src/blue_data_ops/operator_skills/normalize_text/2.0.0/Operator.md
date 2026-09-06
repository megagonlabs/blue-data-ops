# Normalize text

`normalize_text@2.0.0` copies each record and writes normalized text under a derived key. The key is `<first text_field>_norm`, or `text_norm` when the first field name is empty. Missing fields and fields whose value is `None` do not contribute text.

## Settings

| Name | Input | Declared | Effective default | Validation | Kind |
|---|---|---|---|---|---|
| `delimiter` | `attributes` | `yes` | `"\n"` | `attribute-spec:str` | `scalar` |
| `execution.timeout_seconds` | `base-properties` | `no` | `none` | `finite-positive-number` | `scalar` |
| `max_chars` | `attributes` | `yes` | `none` | `attribute-spec:int` | `scalar` |
| `normalize_bullets` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |
| `normalize_dates` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `normalize_unicode` | `attributes` | `yes` | `"NFKC"` | `attribute-spec:str` | `scalar` |
| `normalize_whitespace` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |
| `strip_control_chars` | `attributes` | `yes` | `true` | `attribute-spec:bool` | `scalar` |
| `strip_newline` | `attributes` | `yes` | `false` | `attribute-spec:bool` | `scalar` |
| `text_field` | `attributes` | `yes` | `[]` | `attribute-spec:list[str]` | `structured` |

## Normalization order

The operator converts each selected value to text, applies the chosen Unicode form, normalizes line endings, and then applies the enabled control-character, bullet, date, and whitespace rules. Multiple field results are joined with `delimiter`. `max_chars` truncates the combined result after all other normalization.

Numeric date normalization is selective. If the first number is greater than 12, the form is treated as day-month-year. If the second number is greater than 12, it is treated as month-day-year. A date such as `03/04/2025` stays unchanged because both readings are possible. ISO-style and supported month-name dates are normalized when valid. Invalid dates remain unchanged.

The record copy is shallow, so nested values remain shared with the input. The current `output_attributes` mapping is empty.

## Call boundaries

`run()` rejects an empty `text_field`, an unsupported Unicode form, or a negative `max_chars`, and contains execution failures. `invoke()` returns `None` for validation failure. `apply()` executes without the structured boundary and may raise when a laxly accepted value cannot be used at runtime.

The live key is `normalize_whitespace`; a `whitespace` attribute has no effect. The operator has no registry, provider, model, or data-store side effect.
