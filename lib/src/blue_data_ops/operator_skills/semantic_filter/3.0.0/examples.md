# Semantic-filter check

Environment: llm

This scripted client exercises deterministic control flow. It makes no live provider call and says nothing about model judgment.

```python
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import versioned_registry


class LocalClient(LLMClient):
    def __init__(self, responses):
        super().__init__("local")
        self.responses = list(responses)
        self.call_count = 0

    def execute_api_call(self, input, properties=None, additional_data=None):
        self.call_count += 1
        return self.responses.pop(0)


operator = versioned_registry().resolve("semantic_filter@3.0.0")
client = LocalClient(["false", " TRUE "])
output, output_attributes, meta = operator.run(
    [[], [{"ticket": "R-7", "priority": "low"}, {"ticket": "R-8", "priority": "urgent"}]],
    {"filter_conditions": {"priority": "requires immediate attention"}, "return_idx": True},
    {"llm_client": client},
)

assert output == [[{"indices": []}], [{"indices": [1]}]]
assert client.call_count == 2
assert output_attributes == {}
assert not meta.errors

unused = LocalClient([True])
invalid_output, _, invalid_meta = operator.run(
    [[{"ticket": "R-9"}]],
    {"filter_conditions": {"ticket": "is assigned"}, "return_idx": "yes"},
    {"llm_client": unused},
)
assert invalid_output == [[]]
assert unused.call_count == 0
assert invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert invalid_meta.errors[0].stage.value == "VALIDATE"
```
