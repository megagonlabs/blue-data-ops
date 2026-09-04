# Union

`union@2.0.0` appends records from all input groups and removes duplicates. The first record for a signature is retained as the original object. Direct `apply()` returns `[]` for empty outer input and `[[]]` when input groups contain no records. `run()` normalizes either empty result to `[[]]` and marks it empty without adding an error.

## Matching rules

`key_match` builds a signature from sorted key/value pairs, so mapping key order does not matter and differently named fields remain different. `seq_match` ignores keys and compares values in each record's insertion order. Two records with the same values can therefore match under `seq_match` even when their keys differ, while changing insertion order can make them different.

Numeric values are converted to `float` while signatures are built. Equal numeric forms such as `1`, `1.0`, and `True` collide and the first record wins. Every NaN becomes the same sentinel, so repeated NaN values also de-duplicate. Lists, mappings, and sets are converted recursively. A value that remains unhashable, or a structure that raises `TypeError` or `RecursionError` during conversion, falls back to its string form; distinct values with the same fallback text can collide.

## Call boundaries

The live `io.attributes` mapping declares only `match_option`. Its accepted values are `key_match` and `seq_match`. `run()` and `invoke()` validate `match_option`. Invalid input gives structured validation output from `run()` and `None` from `invoke()`. A direct `apply()` with an invalid match option can raise when it builds the first signature.

Successful calls write no `output_attributes`. The operator has no provider, registry, optional dependency, side effect, or operator-specific timeout.
