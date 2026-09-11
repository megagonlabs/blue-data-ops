from __future__ import annotations

from blue_data_ops.operators._outcomes import (
    _OutcomeOperator,  # pyright: ignore[reportPrivateUsage]
)
from blue_data_ops.operators.cluster_operator import ClusterOperator
from blue_data_ops.operators.types import (
    Attributes,
    DataBundle,
    Properties,
    ValidationResult,
)


class ClusterOutcomeOperator(_OutcomeOperator, ClusterOperator):
    """Reject calls that cannot fit the selected clustering model."""

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        validation = super()._validate_input(input_data, attributes, properties)
        if not validation.ok:
            return validation

        algorithm = properties.get("algorithm", "kmeans") if properties else "kmeans"
        if algorithm not in {"kmeans", "dbscan", "gaussian"}:
            return ValidationResult(False, "supply a supported clustering algorithm")

        # Clustering intentionally scopes empty input and vector checks to the first group.
        if not input_data or not input_data[0]:
            return ValidationResult(True, None)

        vector_key = attributes["vector_key"]
        vector_count = sum(isinstance(record.get(vector_key), list) for record in input_data[0])
        if vector_count == 0:
            return ValidationResult(False, "supply usable vectors in the first group")
        if algorithm in {"kmeans", "gaussian"}:
            try:
                required_vector_count = int(attributes["n_cluster"])
            except (TypeError, ValueError):
                return ValidationResult(False, "supply an integer cluster count")
            if vector_count < required_vector_count:
                return ValidationResult(
                    False, "supply at least one usable vector per requested cluster"
                )
        return ValidationResult(True, None)
