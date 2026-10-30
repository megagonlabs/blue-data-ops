from __future__ import annotations

import json

from blue_data_ops.llm.templating import extract_output
from blue_data_ops.operators.nl2bn_operator import NL2BNOperator
from blue_data_ops.operators.nl2llm_operator import NL2LLMOperator
from blue_data_ops.operators.nl2sql_operator import NL2SQLOperator
from blue_data_ops.operators.semantic_extract_operator import SemanticExtractOperator
from blue_data_ops.operators.semantic_filter_operator import SemanticFilterOperator
from blue_data_ops.operators.semantic_join_operator import SemanticJoinOperator
from blue_data_ops.operators.semantic_project_operator import SemanticProjectOperator
from blue_data_ops.operators.semantic_transform_operator import SemanticTransformOperator


def test_default_output_preserves_json_content() -> None:
    operators = (
        NL2BNOperator,
        NL2LLMOperator,
        NL2SQLOperator,
        SemanticExtractOperator,
        SemanticFilterOperator,
        SemanticJoinOperator,
        SemanticProjectOperator,
        SemanticTransformOperator,
    )
    responses = (
        '{"format": "json", "json_key": "keep"}',
        '```json\n{"format": "json", "json_key": "keep"}\n```',
        '```\n{"format": "json", "json_key": "keep"}\n```',
        '```JSON\n{"format": "json", "json_key": "keep"}\n```\n',
        '```json\r\n{"format": "json", "json_key": "keep"}\r\n```\r\n',
    )
    for operator_type in operators:
        for response in responses:
            payload = {"choices": [{"message": {"content": response}}]}
            output = extract_output(payload, operator_type.DEFAULT_PROPERTIES)
            if isinstance(output, str):
                output = json.loads(output)
            assert output == {"format": "json", "json_key": "keep"}, (
                operator_type.__name__,
                response,
            )
