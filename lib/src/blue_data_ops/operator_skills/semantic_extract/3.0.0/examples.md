# Semantic-extraction check

Environment: llm

This deterministic in-process client checks control flow only. It does not call a provider or measure extraction quality.

```python
from typing import Any

from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import versioned_registry


class LocalClient(LLMClient):
    def __init__(self, responses: list[Any]) -> None:
        super().__init__("local")
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def execute_api_call(self, input, properties=None, additional_data=None):
        self.requests.append(dict(additional_data or {}))
        return self.responses.pop(0)


operator = versioned_registry().resolve("semantic_extract@3.0.0")
client = LocalClient([{"topic": []}, {"topic": ["observability"]}])
output, output_attributes, meta = operator.run(
    [[{"note": "No topic named"}], [{"note": "Review observability alerts"}]],
    {"entities": [{"name": "topic", "extract_on_fields": ["note"]}]},
    {"llm_client": client},
)

assert output == [[{"topic": []}], [{"topic": ["observability"]}]]
assert len(client.requests) == 2
assert output_attributes == {}
assert not meta.errors

bad_output, _, bad_meta = operator.run(
    [[{"note": "Review tracing"}]],
    {"entities": [{"name": "topic"}]},
    {"llm_client": LocalClient([["tracing"]])},
)
assert bad_output == [[]]
assert bad_meta.errors[0].code.value == "EXECUTION_FAILED"
assert bad_meta.errors[0].stage.value == "EXECUTE"
```
