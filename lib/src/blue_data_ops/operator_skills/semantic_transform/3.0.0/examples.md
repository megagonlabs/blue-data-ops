# Semantic-transform example

Environment: llm

The scripted plan supplies fixed transformations locally; it does not evaluate provider planning quality.

```python
from blue_data_ops.llm import LLMClient
from blue_data_ops.operators import versioned_registry


class LocalClient(LLMClient):
    def __init__(self, responses):
        super().__init__("local")
        self.responses = list(responses)

    def execute_api_call(self, input, properties=None, additional_data=None):
        return self.responses.pop(0)


operator = versioned_registry().resolve("semantic_transform@3.0.0")
plan = {
    "label": {
        "source_fields": ["title"],
        "transformation_type": "field_mapping_without_value_change",
    }
}
output, output_attributes, meta = operator.run(
    [[], [{"title": "Queued"}, {"title": "Running"}]],
    {"output_desc": {"label": {"description": "Copy the title", "required": True}}},
    {"llm_client": LocalClient([plan])},
)

assert output == [[], [{"label": "Queued"}, {"label": "Running"}]]
assert output_attributes == {}
assert not meta.errors

failed_output, _, failed_meta = operator.run(
    [[{"title": "Stopped"}]],
    {"output_desc": {"label": {"description": "Copy the title", "required": True}}},
    {"llm_client": LocalClient([[]])},
)
assert failed_output == [[]]
assert failed_meta.errors[0].code.value == "EXECUTION_FAILED"
assert failed_meta.errors[0].stage.value == "EXECUTE"
```
