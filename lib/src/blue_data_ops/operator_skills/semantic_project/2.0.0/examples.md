# Semantic-projection example

Environment: llm

The local client returns a fixed field mapping and records the data sent to the provider boundary.

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
        return {"name": "person", "score": "rating"}


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("semantic_project@2.0.0", level=3)
operator = registry.resolve("semantic_project@2.0.0")
client = LocalClient()
records = [[{"name": "Ada", "score": 8, "tags": ["python"]}]]

output, output_attributes, meta = operator.run(
    records,
    {"projection_instructions": "Keep name and score; rename both"},
    {"llm_client": client},
)

assert skill.card.operator_id == "semantic_project@2.0.0"
assert output == [[{"person": "Ada", "rating": 8}]]
assert "name (string)" in client.requests[0]["schema"]
assert client.requests[0]["projection_instructions"].startswith("Keep name")
assert output_attributes == {}
assert meta.errors == []
```
