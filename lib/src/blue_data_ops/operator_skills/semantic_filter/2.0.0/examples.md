# Semantic-filter example

Environment: llm

This local client accepts records whose `status` field is `active`.

```python
from blue_data_ops.llm import LLMClient
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry


class LocalClient(LLMClient):
    def __init__(self) -> None:
        super().__init__("local")
        self.seen = []

    def execute_api_call(self, input, properties=None, additional_data=None):
        request = dict(additional_data or {})
        self.seen.append(request)
        return request["record"].get("status") == "active"


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("semantic_filter@2.0.0", level=3)
operator = registry.resolve("semantic_filter@2.0.0")
client = LocalClient()
records = [[{"id": 1, "status": "active"}, {"id": 2, "status": "closed"}]]

output, output_attributes, meta = operator.run(
    records,
    {"filter_conditions": {"status": "is active"}},
    {"llm_client": client},
)

assert skill.card.operator_id == "semantic_filter@2.0.0"
assert output == [[records[0][0]]]
assert output[0][0] is records[0][0]
assert len(client.seen) == 2
assert "is active" in client.seen[0]["conditions"]
assert output_attributes == {}
assert meta.errors == []
```
