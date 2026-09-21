# Natural-language generation example

Environment: llm

This example injects an in-process client, so it needs no credential or network call.

```python
from typing import Any

from blue_data_ops.llm import LLMClient
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry


class LocalClient(LLMClient):
    def __init__(self) -> None:
        super().__init__("local")
        self.requests: list[dict[str, Any]] = []

    def execute_api_call(self, input, properties=None, additional_data=None):
        self.requests.append(dict(additional_data or {}))
        return [{"language": "Python", "rank": 1}]


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("nl2llm@2.0.0", level=3)
operator = registry.resolve("nl2llm@2.0.0")
client = LocalClient()

output, output_attributes, meta = operator.run(
    [[]],
    {
        "query": "Name the top language",
        "context": "survey results",
        "attrs": [{"name": "language", "type": "string"}, {"name": "rank"}],
    },
    {"llm_client": client},
)

assert skill.card.operator_id == "nl2llm@2.0.0"
assert output == [[{"language": "Python", "rank": 1}]]
assert client.requests[0]["query"] == "Name the top language"
assert "language: string" in client.requests[0]["attrs"]
assert output_attributes == {}
assert meta.errors == []
```
