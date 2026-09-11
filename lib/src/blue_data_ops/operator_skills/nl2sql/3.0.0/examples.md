# SQL-result boundary check

Environment: llm

The client and registry are deterministic in-process seams. The example neither contacts a provider nor executes SQL on a backend.

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

    def get_data_source_schema(self, source, database, collection, protocol=None, format="dict"):
        return {"incidents": {"service": "text", "open": "integer"}}

    def execute_query(
        self, query, source, database=None, collection=None, optional_properties=None
    ):
        return deepcopy(self.result)


operator = versioned_registry().resolve("nl2sql@3.0.0")
attributes = {
    "question": "Which services have open incidents?",
    "source": "local",
    "database": "operations",
    "collection": "incidents",
    "protocol": "sqlite",
}
sql = {"query": "SELECT service FROM incidents WHERE open = 1"}
empty_output, output_attributes, empty_meta = operator.run(
    [], attributes, {"llm_client": LocalClient(sql), "data_registry": LocalRegistry([])}
)
bad_output, _, bad_meta = operator.run(
    [], attributes, {"llm_client": LocalClient(sql), "data_registry": LocalRegistry([["bad-row"]])}
)

assert empty_output == [[]]
assert output_attributes == {}
assert empty_meta.is_empty and not empty_meta.errors
assert bad_output == [[]]
assert bad_meta.errors[0].code.value == "EXECUTION_RESULT_INVALID"
assert bad_meta.errors[0].stage.value == "NORMALIZE"
```
