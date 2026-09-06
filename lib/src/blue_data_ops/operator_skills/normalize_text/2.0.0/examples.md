# Normalize-text check

Environment: base

This example combines two text fields, verifies the derived output key and copied record, and exercises an invalid configuration.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("normalize_text@2.0.0", level=3)
operator = registry.resolve("normalize_text@2.0.0")
source = [
    [
        {
            "title": "  Ｐroject   note\n• Shipped 13/04/2026; review 03/04/2025 ",
            "body": " Release notes ",
        }
    ]
]

output, output_attributes, meta = operator.run(
    source,
    {
        "text_field": ["title", "body"],
        "delimiter": " | ",
        "strip_newline": True,
        "normalize_whitespace": True,
        "normalize_dates": True,
    },
)
invalid, _, invalid_meta = operator.run(source, {"text_field": []})

assert skill.card.operator_id == "normalize_text@2.0.0"
assert source[0][0]["title"].startswith("  Ｐ")
assert output[0][0] is not source[0][0]
assert output[0][0]["title_norm"] == (
    "Project note - Shipped 2026-04-13; review 03/04/2025 | Release notes"
)
assert output_attributes == {}
assert meta.errors == []
assert invalid == [[]] and invalid_meta.errors
```
