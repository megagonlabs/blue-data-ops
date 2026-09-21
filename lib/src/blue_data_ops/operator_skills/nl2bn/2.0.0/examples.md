# Bayesian-network query example

Environment: llm

The local client first returns an invalid query, then a corrected query. The operator sends the same schema on both attempts.

```python
import json
from typing import Any

from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry


class LocalRegistry(RegistrySeam):
    def __init__(self) -> None:
        self.queries = []

    def execute_query(
        self, query, source, database=None, collection=None, optional_properties=None
    ):
        self.queries.append(query)
        return [{"probability": 0.42}]


class LocalClient(LLMClient):
    def __init__(self) -> None:
        super().__init__("local")
        self.requests: list[dict[str, Any]] = []

    def execute_api_call(self, input, properties=None, additional_data=None):
        self.requests.append(dict(additional_data or {}))
        if len(self.requests) == 1:
            return {"target_state": "present", "context": {}}
        return {"target_node": "disease", "target_state": "present", "context": {}}


schema = {
    "nodes": {"disease": {"states": ["present", "absent"]}},
    "edges": {},
}
registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("nl2bn@2.0.0", level=3)
operator = registry.resolve("nl2bn@2.0.0")
data_registry = LocalRegistry()
client = LocalClient()

output, output_attributes, meta = operator.run(
    [[]],
    {
        "question": "What is the probability of disease?",
        "source": "local",
        "database": "default",
        "collection": "health",
        "protocol_variant": "pgmpy",
        "schema": json.dumps(schema),
        "explanation": False,
    },
    {"data_registry": data_registry, "llm_client": client},
)

assert skill.card.operator_id == "nl2bn@2.0.0"
assert output[0][0]["prob"] == 0.42
assert output[0][0]["query"]["target_node"] == "disease"
assert len(client.requests) == 2
assert client.requests[0]["schema_section"] == client.requests[1]["schema_section"]
assert len(data_registry.queries) == 1
assert output_attributes == {}
assert meta.errors == []
```
