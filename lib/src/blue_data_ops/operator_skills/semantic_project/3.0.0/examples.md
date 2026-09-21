# Semantic-projection example

Environment: llm

The local client below supplies fixed mappings without making a provider call.

```python
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import versioned_registry


class LocalClient(LLMClient):
    def __init__(self, responses):
        super().__init__("local")
        self.responses = list(responses)

    def execute_api_call(self, input, properties=None, additional_data=None):
        return self.responses.pop(0)


operator = versioned_registry().resolve("semantic_project@3.0.0")
output, output_attributes, meta = operator.run(
    [[{"host": "api-1", "zone": "west", "internal": "omit"}], [{"service": "billing", "tier": 2}]],
    {
        "projection_instructions": "Keep host as node in the first schema and service as component in the second."
    },
    {"llm_client": LocalClient([{"host": "node"}, {"service": "component"}])},
)

assert output == [[{"node": "api-1"}], [{"component": "billing"}]]
assert output_attributes == {}
assert not meta.errors

empty_output, _, empty_meta = operator.run(
    [[{"host": "api-2"}]],
    {"projection_instructions": "Drop every field."},
    {"llm_client": LocalClient([{}])},
)
assert empty_output == [[]]
assert empty_meta.is_empty
assert not empty_meta.errors
```
