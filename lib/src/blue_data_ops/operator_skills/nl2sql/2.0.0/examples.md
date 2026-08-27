# NL-to-SQL owner check

Load the reviewed text through an explicit Python check. This reads the package index, manifest, guide, and examples; it does not invoke `nl2sql` or contact a provider.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("nl2sql@2.0.0", level=3)

assert skill.card.operator_id == "nl2sql@2.0.0"
assert skill.loaded_kinds == ("guide", "examples")
assert skill.io.attributes["question"].required
assert skill.io.attributes["protocol"].default == "postgres"
```

When calling the operator, pass a registry seam and LLM client through its properties. Set `execute_query` to `False` when the caller needs generated SQL without registry execution. Use `run()` when the caller needs structured empty and failure metadata.
