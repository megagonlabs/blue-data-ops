# Bayesian-result boundary check

Environment: llm

The scripted client and registry exercise local control flow only. They do not contact a provider or a Bayesian-query backend.

```python
from copy import deepcopy

from blue_data_ops.data import RegistrySeam
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import versioned_registry


class LocalClient(LLMClient):
    def __init__(self, response):
        super().__init__("local")
        self.response = response

    def execute_api_call(self, input, properties=None, additional_data=None):
        return deepcopy(self.response)


class LocalRegistry(RegistrySeam):
    def __init__(self, result):
        self.result = result

    def execute_query(
        self, query, source, database=None, collection=None, optional_properties=None
    ):
        return deepcopy(self.result)


operator = versioned_registry().resolve("nl2bn@3.0.0")
attributes = {
    "question": "What is the chance of an alert?",
    "source": "local",
    "database": "models",
    "collection": "service_health",
    "protocol_variant": "pgmpy",
    "schema": "local unstructured schema",
    "explanation": False,
}
query = {"target_node": "Alert", "target_state": "yes"}
zero_output, output_attributes, zero_meta = operator.run(
    [],
    attributes,
    {"llm_client": LocalClient(query), "data_registry": LocalRegistry([{"probability": 0}])},
)
empty_output, _, empty_meta = operator.run(
    [], attributes, {"llm_client": LocalClient(query), "data_registry": LocalRegistry([])}
)

assert zero_output == [
    [{"prob": 0, "query": {"target_node": "Alert", "target_state": "yes", "context": {}}}]
]
assert output_attributes == {}
assert not zero_meta.is_empty and not zero_meta.errors
assert empty_output == [[]]
assert empty_meta.is_empty and not empty_meta.errors
```
