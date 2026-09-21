# Semantic-join example

Environment: llm

The fixed batch response below supplies merge decisions locally. It makes no provider call and does not enable embeddings.

```python
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import versioned_registry


class LocalClient(LLMClient):
    def __init__(self, response):
        super().__init__("local")
        self.response = response
        self.call_count = 0

    def execute_api_call(self, input, properties=None, additional_data=None):
        self.call_count += 1
        return self.response


operator = versioned_registry().resolve("semantic_join@3.0.0")
client = LocalClient({"pair_1": True})
output, output_attributes, meta = operator.run(
    [[{"ticket": "I-3", "owner": "Kai"}], [{"team": "Infra", "queue": "on-call"}]],
    {
        "join_predicate": "the owner belongs to the team",
        "left_fields": ["owner"],
        "right_fields": ["team"],
        "keep_keys": "both",
        "estimate_cost": False,
    },
    {"llm_client": client},
)

assert output == [[{"ticket": "I-3", "owner": "Kai", "team": "Infra", "queue": "on-call"}]]
assert client.call_count == 1
assert output_attributes == {}
assert not meta.errors

bad_output, _, bad_meta = operator.run(
    [[{"owner": "Mina"}], [{"team": "Storage"}]],
    {"left_fields": ["owner"], "right_fields": ["team"], "estimate_cost": False},
    {"llm_client": LocalClient({"pair_1": "true"})},
)
assert bad_output == [[]]
assert bad_meta.errors[0].code.value == "EXECUTION_FAILED"
assert bad_meta.errors[0].stage.value == "EXECUTE"
```
