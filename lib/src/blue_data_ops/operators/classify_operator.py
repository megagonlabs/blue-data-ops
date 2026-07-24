from __future__ import annotations

from importlib import import_module
from typing import Any, ClassVar, cast

from blue_data_ops.operators._discovery import DiscoverySpec
from blue_data_ops.operators.operator import Operator
from blue_data_ops.operators.types import (
    Attributes,
    AttributeSpec,
    Data,
    DataBundle,
    FunctionResult,
    Properties,
    ValidationResult,
)


class _ClassifyModelFailure(Exception):
    pass


class ClassifyOperator(Operator):
    """Train a decision tree and predict labels for every input group."""

    name: ClassVar[str] = "classify"
    description: ClassVar[str] = (
        "Given input data with numeric vectors and training labels, train a classifier "
        "and predict class labels for each sample using DecisionTreeClassifier."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "vector_key": AttributeSpec(
            type="str",
            description="The key to the numeric vector values (features)",
            required=True,
        ),
        "label_key": AttributeSpec(
            type="str",
            description="The key to the target class labels",
            required=True,
        ),
        "output_key": AttributeSpec(
            type="str",
            description="The key name for the predicted labels",
            default="predicted_label",
        ),
        "criterion": AttributeSpec(
            type="str",
            description="Function to measure split quality",
            default="gini",
        ),
        "splitter": AttributeSpec(
            type="str",
            description="Strategy to choose the split",
            default="best",
        ),
        "max_depth": AttributeSpec(
            type="int",
            description="The maximum depth of the tree",
        ),
        "min_samples_split": AttributeSpec(
            type="float",
            description="Minimum samples to split an internal node",
            default=2,
        ),
        "min_samples_leaf": AttributeSpec(
            type="float",
            description="Minimum samples to be at a leaf node",
            default=1,
        ),
        "random_state": AttributeSpec(
            type="int",
            description="Controls the randomness",
        ),
    }

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        try:
            return self._execute(input_data, attributes, properties).output_data
        except _ClassifyModelFailure:
            return input_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        algorithm = properties.get("algorithm", "decision_tree") if properties else "decision_tree"
        vector_key = attributes.get("vector_key")
        label_key = attributes.get("label_key")
        output_key = cast(str, attributes.get("output_key", "predicted_label"))
        criterion = cast(str, attributes.get("criterion", "gini"))
        splitter = cast(str, attributes.get("splitter", "best"))

        max_depth_raw = attributes.get("max_depth")
        max_depth = (
            int(max_depth_raw)
            if max_depth_raw is not None and str(max_depth_raw).lower() != "none"
            else None
        )
        split_raw = attributes.get("min_samples_split", 2)
        min_samples_split = (
            float(split_raw) if isinstance(split_raw, str) and "." in split_raw else int(split_raw)
        )
        leaf_raw = attributes.get("min_samples_leaf", 1)
        min_samples_leaf = (
            float(leaf_raw) if isinstance(leaf_raw, str) and "." in leaf_raw else int(leaf_raw)
        )
        random_state_raw = attributes.get("random_state")
        random_state = (
            int(random_state_raw)
            if random_state_raw is not None and str(random_state_raw).lower() != "none"
            else None
        )

        if not input_data or not input_data[0]:
            return FunctionResult(input_data, {})

        vectors: list[list[Any]] = []
        labels: list[Any] = []
        for record in input_data[0]:
            vector = record.get(cast(str, vector_key))
            label = record.get(cast(str, label_key))
            if vector is not None and isinstance(vector, list) and label is not None:
                vectors.append(cast(list[Any], vector))
                labels.append(label)
        if algorithm == "decision_tree" and not vectors:
            return FunctionResult(input_data, {})
        if algorithm != "decision_tree":
            return FunctionResult(input_data, {})

        # The ml extra is optional; import only when a real model path is reached.
        np = cast(Any, import_module("numpy"))
        decision_tree_classifier = getattr(import_module("sklearn.tree"), "DecisionTreeClassifier")

        try:
            model = decision_tree_classifier(
                criterion=criterion,
                splitter=splitter,
                max_depth=max_depth,
                min_samples_split=min_samples_split,
                min_samples_leaf=min_samples_leaf,
                random_state=random_state,
            )
            model.fit(np.array(vectors), np.array(labels))

            result_data: DataBundle = []
            for data_subset in input_data:
                subset_result: Data = []
                prediction_vectors: list[list[Any]] = []
                valid_indices: list[int] = []
                for index, record in enumerate(data_subset):
                    vector = record.get(cast(str, vector_key))
                    if vector is not None and isinstance(vector, list):
                        prediction_vectors.append(cast(list[Any], vector))
                        valid_indices.append(index)

                if not prediction_vectors:
                    for record in data_subset:
                        new_record = record.copy()
                        new_record[output_key] = None
                        subset_result.append(new_record)
                else:
                    predictions = model.predict(np.array(prediction_vectors))
                    label_index = 0
                    for index, record in enumerate(data_subset):
                        new_record = record.copy()
                        if index in valid_indices:
                            new_record[output_key] = predictions[label_index]
                            label_index += 1
                        else:
                            new_record[output_key] = None
                        subset_result.append(new_record)
                result_data.append(subset_result)
            return FunctionResult(result_data, {})
        except Exception as error:
            raise _ClassifyModelFailure from error

    def validate(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> bool:
        result = self._validate_input(input_data, attributes, properties)
        return type(result) is ValidationResult and result.ok is True

    def _validate_input(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> ValidationResult:
        valid = super().validate(input_data, attributes, properties)
        if valid:
            valid = bool(attributes.get("vector_key")) and bool(attributes.get("label_key"))
        return ValidationResult(
            valid,
            None if valid else "supply non-empty vector_key and label_key values",
        )


DISCOVERY = DiscoverySpec(
    when_to_invoke=(
        "Use when labeled numeric vectors are available and class labels are needed for input "
        "samples."
    ),
    tags=(
        "domain-ml",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-classification",
        "requires-ml",
    ),
)
