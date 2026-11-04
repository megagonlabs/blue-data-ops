"""The public SQL outcome constructor preserves the exact registry implementation."""

from blue_data_ops import operators
from blue_data_ops.operators import NL2SQLOutcomeOperator, versioned_registry
from blue_data_ops.operators._nl2sql_outcome import NL2SQLOutcomeOperator as Implementation


def test_public_outcome_export_and_exact_registry_identity() -> None:
    assert NL2SQLOutcomeOperator is Implementation
    assert "NL2SQLOutcomeOperator" in operators.__all__
    registry = versioned_registry()
    resolved = registry.resolve("nl2sql@4.0.0")
    assert type(resolved) is NL2SQLOutcomeOperator
    assert registry.resolve("nl2sql@4.0.0") is resolved
