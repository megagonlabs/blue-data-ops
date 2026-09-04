# Semantic-filter owner check

This check loads the package and injects a recording client. No provider or credential is used. The recorded payload proves what the operator discloses, and the two calls verify both result shapes. It runs with the base installation.

```python
from typing import Any

from blue_data_ops.llm import LLMClient
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry


class RecordingClient(LLMClient):
    def __init__(self) -> None:
        super().__init__("recording")
        self.disclosures: list[dict[str, Any]] = []

    def execute_api_call(
        self,
        input: Any,
        properties: dict[str, Any] | None = None,
        additional_data: dict[str, Any] | None = None,
    ) -> bool:
        del input, properties
        assert additional_data is not None
        self.disclosures.append(additional_data)
        return additional_data["record"].get("material") == "wood"


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("semantic_filter@2.0.0", level=3)
operator = registry.resolve("semantic_filter@2.0.0")
client = RecordingClient()
records = [[
    {"id": 1, "material": "wood"},
    {"id": 2, "material": "steel"},
]]
attributes = {
    "filter_conditions": {"material": "is a natural material"},
    "context": "Keep furniture materials.",
}

filtered, output_attributes, meta = operator.run(
    records,
    attributes,
    {"llm_client": client},
)
indices, _, index_meta = operator.run(
    records,
    {**attributes, "return_idx": True},
    {"llm_client": client},
)

assert skill.card.operator_id == "semantic_filter@2.0.0"
assert skill.loaded_kinds == ("guide", "examples")
assert filtered == [[records[0][0]]]
assert filtered[0][0] is records[0][0]
assert indices == [[{"indices": [0]}]]
assert len(client.disclosures) == 4
assert client.disclosures[0]["record"] == records[0][0]
assert "Field 'material'" in client.disclosures[0]["conditions"]
assert client.disclosures[0]["context"] == "Keep furniture materials."
assert output_attributes == {}
assert meta.errors == []
assert index_meta.errors == []
```
