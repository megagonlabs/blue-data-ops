# Semantic-extraction example

Environment: llm

This example records the provider-bound fields and returns deterministic extracted data.

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
        return {"skill": ["Python"]}


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("semantic_extract@2.0.0", level=3)
operator = registry.resolve("semantic_extract@2.0.0")
client = LocalClient()

output, output_attributes, meta = operator.run(
    [[{"id": 1, "bio": "Ada uses Python", "private": "not selected"}]],
    {"entities": [{"name": "skill", "extract_on_fields": ["bio"]}]},
    {"llm_client": client},
)

assert skill.card.operator_id == "semantic_extract@2.0.0"
assert output == [[{"skill": ["Python"]}]]
assert client.requests[0]["data_record"] == {"bio": "Ada uses Python"}
assert output_attributes == {}
assert meta.errors == []
```
