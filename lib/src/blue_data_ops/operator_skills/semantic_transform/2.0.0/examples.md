# Semantic-transform check

Environment: llm

The injected client returns a direct field-mapping plan, so one local call produces the result.

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
        return {
            "person": {
                "source_fields": ["name"],
                "transformation_type": "field_mapping_without_value_change",
            }
        }


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("semantic_transform@2.0.0", level=3)
operator = registry.resolve("semantic_transform@2.0.0")
client = LocalClient()
raw_description = {"person": {"description": "Copied person name"}}
raw_output = operator.apply(
    [[{"name": "Ada", "score": 8}]],
    {"output_desc": raw_description},
    {"llm_client": client},
)

output, output_attributes, meta = operator.run(
    [[{"name": "Ada", "score": 8}]],
    {"output_desc": {"person": {"description": "Copied person name"}}},
    {"llm_client": client},
)

assert skill.card.operator_id == "semantic_transform@2.0.0"
assert raw_output == [[{"person": "Ada"}]]
assert output == [[{"person": "Ada"}]]
assert len(client.requests) == 2
assert raw_description["person"]["source_fields"] == ["name"]
assert output_attributes == {}
assert meta.errors == []
```
