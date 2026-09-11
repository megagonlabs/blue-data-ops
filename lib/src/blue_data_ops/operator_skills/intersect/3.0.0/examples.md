# Intersection example

Environment: base

The first group supplies two equal nested records. Both remain because their signature occurs in every other group.

```python
from copy import deepcopy

from blue_data_ops.operators import versioned_registry

operator = versioned_registry().resolve("intersect@3.0.0")
first = {"sku": "tea", "tags": ["warm", {"region": "east"}]}
duplicate = deepcopy(first)
other = {"sku": "coffee", "tags": ["dark"]}
match = {"tags": ["warm", {"region": "east"}], "sku": "tea"}

output, output_attributes, meta = operator.run(
    [[first, other, duplicate], [match], [deepcopy(match)]],
    {"match_option": "key_match"},
)
assert output == [[first, duplicate]]
assert output[0][0] is first and output[0][1] is duplicate
assert output_attributes == {} and not meta.errors and not meta.is_empty

empty, empty_attributes, empty_meta = operator.run(
    [[first], [], [match]], {"match_option": "key_match"}
)
assert empty == [[]] and empty_attributes == {}
assert not empty_meta.errors and empty_meta.is_empty
```

The empty middle group is an operand, so it makes the otherwise valid intersection empty.
