# Normalize text

`normalize_text@2.0.0` copies each record and writes normalized text under a derived key. The key is `<first text_field>_norm`, or `text_norm` when the first field name is empty. Missing fields and fields whose value is `None` do not contribute text.

## Normalization order

The operator converts each selected value to text, applies the chosen Unicode form, normalizes line endings, and then applies the enabled control-character, bullet, date, and whitespace rules. Control-character stripping is enabled by default. Multiple field results are joined with `delimiter`. `max_chars` truncates the combined result after all other normalization.

Numeric date normalization is deliberately selective. If the first number is greater than 12, the form is treated as day-month-year. If the second number is greater than 12, it is treated as month-day-year. A date such as `03/04/2025` stays unchanged because both readings are possible. ISO-style and supported month-name dates are normalized when valid. Invalid dates remain unchanged.

The current record copy is shallow: nested values remain shared with the input. The operator writes `output_attributes` as an empty mapping.

## Call boundaries

`run()` validates that `text_field` is a nonempty list of nonblank strings, the Unicode form is one of `NFC`, `NFD`, `NFKC`, or `NFKD`, and `max_chars` is nonnegative when provided. Invalid input returns `[[]]` with structured validation metadata. `invoke()` returns `None` for a rejected configuration. `apply()` executes without the structured boundary and may raise when a laxly accepted attribute cannot be used at runtime.

The live `io.attributes` mapping is the machine-readable source for declared settings. `normalize_whitespace` is the declared whitespace switch; a `whitespace` key has no effect.
