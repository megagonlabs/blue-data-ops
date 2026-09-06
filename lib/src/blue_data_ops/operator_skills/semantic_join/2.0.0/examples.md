# Semantic-join check

Environment: llm

The injected client evaluates two pairs locally. The optional embedding filter is not enabled, so this fence needs no model download.

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
        return {"pair_1": True, "pair_2": False}


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("semantic_join@2.0.0", level=3)
operator = registry.resolve("semantic_join@2.0.0")
client = LocalClient()
left = [{"left_id": 1, "name": "Ada"}, {"left_id": 2, "name": "Bob"}]
right = [{"right_id": "a", "name": "ADA"}]

output, output_attributes, meta = operator.run(
    [left, right],
    {
        "left_fields": ["name"],
        "right_fields": ["name"],
        "join_predicate": "names refer to the same person",
        "keep_keys": "both",
        "estimate_cost": False,
    },
    {"llm_client": client},
)

assert skill.card.operator_id == "semantic_join@2.0.0"
assert output == [
    [
        {
            "left_id": 1,
            "name_left": "Ada",
            "right_id": "a",
            "name_right": "ADA",
        }
    ]
]
assert len(client.requests) == 1
assert "names refer to the same person" in client.requests[0]["join_predicate"]
assert output_attributes == {}
assert meta.errors == []
```
