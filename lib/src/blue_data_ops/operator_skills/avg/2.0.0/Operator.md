# Average

`avg@2.0.0` calculates one arithmetic mean from the first input group. Records in later groups are not read.

## Values included in the mean

The operator reads `avg_key` from each record in the first group. Existing integers and floats count directly, including booleans (`True` counts as 1 and `False` as 0). Other values are converted with `int()` first and `float()` second. This means a `Decimal` with a fractional part is truncated by `int()`, while a string such as `"3.5"` reaches the floating-point conversion. Values that cannot be converted are skipped.

The live `io.attributes` mapping gives the declared `avg_key` and `output_key` schema. The default output key is `avg`.

## Results

A successful call returns one record in one group, such as `[[{"avg": 2.5}]]`. Empty input, an empty first group, or a first group with no convertible values returns the same shape with a zero value. The zero is a successful result, not an error record.

`run()` validates that `avg_key` is nonempty and returns structured execution metadata. The current operator returns an empty `output_attributes` mapping. `invoke()` returns `None` when validation fails; `apply()` returns the raw result and does not add execution metadata.
