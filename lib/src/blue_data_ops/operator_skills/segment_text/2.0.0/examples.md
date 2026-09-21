# Segment-text example

Environment: base

This example creates overlapping word segments, copies one metadata field, and shows the error returned for an invalid strategy.

```python
from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import versioned_registry

registry = versioned_registry()
skill = OperatorSkillLoader(registry).load("segment_text@2.0.0", level=3)
operator = registry.resolve("segment_text@2.0.0")
source = [[{"doc_id": "note-1", "text": "one two three four", "source": "memo"}]]

segments, output_attributes, meta = operator.run(
    source,
    {
        "text_field": "text",
        "split_strategy": "word",
        "max_tokens": 2,
        "min_chars": 1,
        "word_overlap": 1,
        "meta_fields": ["source"],
    },
)
empty, _, empty_meta = operator.run([[{"text": "   "}]], {"text_field": "text"})
invalid, _, invalid_meta = operator.run(
    source,
    {"text_field": "text", "split_strategy": "line"},
)

assert skill.card.operator_id == "segment_text@2.0.0"
assert [row["text"] for row in segments[0]] == ["one two", "two three", "three four", "four"]
assert segments[0][0]["segment.source"] == "memo"
assert segments[0][0]["start_char"] == 0
assert empty == [[]] and empty_meta.errors == []
assert invalid == [[]] and invalid_meta.errors
assert output_attributes == {}
assert meta.errors == []
```
