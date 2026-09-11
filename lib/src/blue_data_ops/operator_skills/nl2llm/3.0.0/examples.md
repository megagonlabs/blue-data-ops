# Structured-generation check

Environment: llm

This scripted client checks result boundaries without contacting a provider.

```python
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import versioned_registry


class LocalClient(LLMClient):
    def __init__(self, responses):
        super().__init__("local")
        self.responses = list(responses)

    def execute_api_call(self, input, properties=None, additional_data=None):
        return self.responses.pop(0)


operator = versioned_registry().resolve("nl2llm@3.0.0")
client = LocalClient([[{"service": "search", "healthy": True}], []])
output, output_attributes, meta = operator.run(
    [],
    {
        "query": "List the healthy services",
        "attrs": [{"name": "service"}, {"name": "healthy", "type": "boolean"}],
    },
    {"llm_client": client},
)
empty_output, _, empty_meta = operator.run(
    [], {"query": "List unresolved notices"}, {"llm_client": client}
)

assert output == [[{"service": "search", "healthy": True}]]
assert output_attributes == {}
assert not meta.errors
assert empty_output == [[]]
assert empty_meta.is_empty and not empty_meta.errors

unused = LocalClient([[{"unexpected": True}]])
invalid_output, _, invalid_meta = operator.run([], {"query": "   "}, {"llm_client": unused})
assert invalid_output == [[]]
assert invalid_meta.errors[0].code.value == "INVALID_INPUT"
assert unused.responses == [[{"unexpected": True}]]
```
