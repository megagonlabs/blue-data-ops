from __future__ import annotations

from typing import Any

import pytest

from blue_data_ops.llm import LLMClient
from blue_data_ops.llm.templating import extract_output
from blue_data_ops.operators import active_registry
from tests.unit.operators._outcome_test_helpers import RecordingSeam
from tests.unit.operators.test_operator_error_diagnostics import MARKER, REPLY_MESSAGE, Reply


@pytest.mark.parametrize("reply", ["not-json", {"pair_1": "true"}, {}, None])
def test_strict_join_reply_diagnostic(reply: Any) -> None:
    result = (
        active_registry()
        .resolve("semantic_join@3.0.0")
        .run(
            [[{"left": MARKER}], [{"right": MARKER}]],
            {
                "left_fields": ["left"],
                "right_fields": ["right"],
                "join_predicate": "match",
                "estimate_cost": False,
            },
            {"llm_client": Reply(reply)},
        )
    )
    assert result[2].errors[0].message == REPLY_MESSAGE
    assert result[2].errors[0].suggestion
    assert MARKER not in str(result[2].errors)


@pytest.mark.parametrize("kind", ["shape", "owned-parser", "callback"])
def test_strict_bn_distinguishes_reply_from_arbitrary_callback(kind: str) -> None:
    class Client(LLMClient):
        def execute_api_call(
            self,
            input: Any,
            properties: dict[str, Any] | None = None,
            additional_data: dict[str, Any] | None = None,
        ) -> Any:
            if kind == "shape":
                return {}
            if kind == "owned-parser":
                return extract_output(
                    {"value": MARKER}, {"output_path": "$.value", "output_cast": "json"}
                )
            raise ValueError(MARKER)

    result = (
        active_registry()
        .resolve("nl2bn@3.0.0")
        .run(
            [[]],
            {
                "source": "local",
                "database": "shop",
                "collection": "public",
                "question": "probability",
                "protocol_variant": "pgmpy",
                "max_corrections": 0,
            },
            {"data_registry": RecordingSeam(), "llm_client": Client("fixture")},
        )
    )
    error = result[2].errors[0]
    assert error.message == ("operator execution failed" if kind == "callback" else REPLY_MESSAGE)
    assert MARKER not in str(error)
