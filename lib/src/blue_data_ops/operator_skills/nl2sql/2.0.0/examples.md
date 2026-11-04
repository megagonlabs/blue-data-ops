# Natural-language-to-SQL example

Environment: llm

This example uses local registry and LLM implementations. An explicit Python check confirms that the
generated SQL is returned without being executed.

```python
import json
from typing import Any

from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry


class LocalRegistry(RegistrySeam):
    def __init__(self) -> None:
        self.schema_requests = []

    def get_data_source_schema(self, source, database, collection, protocol=None, format="dict"):
        self.schema_requests.append((source, database, collection))
        return {"jobs": {"columns": ["role"]}}


class LocalClient(LLMClient):
    def __init__(self) -> None:
        super().__init__("local")
        self.requests: list[dict[str, Any]] = []

    def execute_api_call(self, input, properties=None, additional_data=None):
        self.requests.append(dict(additional_data or {}))
        return {"question": "top role", "query": "SELECT role FROM jobs LIMIT 1"}


registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("nl2sql@2.0.0", level=3)
operator = registry.resolve("nl2sql@2.0.0")
data_registry = LocalRegistry()
client = LocalClient()

output, output_attributes, meta = operator.run(
    [[]],
    {
        "question": "top role",
        "source": "local",
        "protocol": "sqlite",
        "database": "demo",
        "collection": "jobs",
    },
    {"data_registry": data_registry, "llm_client": client, "execute_query": False},
)

assert skill.card.operator_id == "nl2sql@2.0.0"
assert output == [[{"sql": "SELECT role FROM jobs LIMIT 1"}]]
assert data_registry.schema_requests == [("local", "demo", "jobs")]
assert json.loads(client.requests[0]["schema"]) == {
    "entities": [{"name": "jobs", "attributes": {"role": {}}}],
    "relations": [],
}
assert output_attributes == {}
assert meta.errors == []
```
