# Average example

Environment: base

The first group supplies two numeric values and one skipped value. The later group does not contribute. The caller carries the average into a summary record and reads the count separately.

```python
from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("avg@3.0.0")
data = [[{"value": 10}, {"value": 20}, {"value": "bad"}], [{"value": 999}]]
output_data, output_attributes, exec_meta = operator.run(data, {"avg_key": "value"})
if exec_meta.errors:
    raise RuntimeError(exec_meta.errors)

assert output_data == [[{"avg": 15.0}]]
assert not exec_meta.is_empty
summary = {"mean_value": output_data[0][0]["avg"]}
count = output_attributes.get("num_values_used")
if count is not None:
    assert count == 2
    summary["observations"] = count
print(summary)

elapsed_ms = exec_meta.traces.get("elapsed_ms")
if elapsed_ms is not None:
    print(f"Average call: {elapsed_ms:.3f} ms")

empty, empty_attributes, empty_meta = operator.run(
    [[{"value": None}, {"value": "bad"}]], {"avg_key": "value"}
)
assert not empty_meta.errors and empty_meta.is_empty and empty == [[]]
assert empty_attributes["num_values_used"] == 0

zero, zero_attributes, zero_meta = operator.run(
    [[{"value": 0}, {"value": 0}]], {"avg_key": "value"}
)
assert not zero_meta.errors and not zero_meta.is_empty
assert zero == [[{"avg": 0.0}]] and zero_attributes["num_values_used"] == 2

invalid, invalid_attributes, invalid_meta = operator.run([[{"value": 1}]], {})
assert invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert invalid == [[]] and invalid_attributes == {} and not invalid_meta.is_empty
```

Empty and zero results include the documented count when it is available. In the summary, a missing count leaves `observations` absent; it does not insert a zero. See the [guide](Operator.md) for Boolean, integer-first conversion, and NaN behavior.
