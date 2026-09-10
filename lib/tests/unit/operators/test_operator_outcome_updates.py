from pathlib import Path
from typing import Any

import pytest

from tests.unit.operators.outcome_measurement_support import (
    bind_case,
    compare_result,
    load_fixture,
    resolve_operator,
)

CASES: list[dict[str, Any]] = load_fixture()["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_operator_outcome(case: dict[str, Any], tmp_path: Path) -> None:
    operator = resolve_operator(case)
    with bind_case(case, tmp_path) as call:
        result = operator.run(call.input_data, call.attributes, call.properties)
        compare_result(case, result)
        call.compare_persistence(case)
