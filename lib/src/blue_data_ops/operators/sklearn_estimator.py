from __future__ import annotations

import inspect
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


class _SklearnEstimatorFailure(Exception):
    pass


class SklearnEstimator(Operator):
    """Runtime wrapper for scikit-learn estimators."""

    name: ClassVar[str] = "sklearn_estimator"
    description: ClassVar[str] = (
        "Build and run a scikit-learn estimator for classification, regression, "
        "clustering, or transformation on DataBundle records."
    )

    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "vector_key": AttributeSpec(
            type="str",
            description="The key to numeric vector values (features)",
            required=True,
        ),
        "label_key": AttributeSpec(
            type="str",
            description="The target key for supervised models (labels or continuous targets)",
        ),
        "output_key": AttributeSpec(
            type="str",
            description="The key name for the predictions or transformed outputs",
            default="prediction",
        ),
    }

    _ESTIMATOR_REGISTRY: ClassVar[dict[str, type[Any]]] = {}

    @classmethod
    def _get_registry(cls) -> dict[str, type[Any]]:
        if not cls._ESTIMATOR_REGISTRY:
            sklearn_utils = cast(Any, import_module("sklearn.utils"))
            estimators = sklearn_utils.all_estimators()
            for name, estimator_cls in estimators:
                cls._ESTIMATOR_REGISTRY[name] = estimator_cls
                cls._ESTIMATOR_REGISTRY[name.lower()] = estimator_cls
        return cls._ESTIMATOR_REGISTRY

    @staticmethod
    def _estimator_kinds(estimator_cls: type[Any]) -> tuple[bool, bool, bool]:
        sklearn_base = cast(Any, import_module("sklearn.base"))
        is_supervised = issubclass(
            estimator_cls,
            (sklearn_base.ClassifierMixin, sklearn_base.RegressorMixin),
        )
        is_clusterer = issubclass(estimator_cls, sklearn_base.ClusterMixin)
        is_transformer = issubclass(estimator_cls, sklearn_base.TransformerMixin)
        return is_supervised, is_clusterer, is_transformer

    @staticmethod
    def _normalize_prediction(val: Any) -> Any:
        """Convert NumPy arrays and scalars to native Python types."""
        if isinstance(val, (str, int, float, bool)) or val is None:
            return val

        if hasattr(val, "tolist"):
            return val.tolist()
        if hasattr(val, "item"):
            return val.item()
        return val

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        try:
            return self._execute(input_data, attributes, properties).output_data
        except _SklearnEstimatorFailure:
            return input_data

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        if not input_data or not input_data[0]:
            return FunctionResult(input_data, {})

        algorithm_name = properties.get("algorithm") if properties else None
        if not algorithm_name:
            return FunctionResult(input_data, {})

        registry = self._get_registry()
        estimator_cls = registry.get(str(algorithm_name)) or registry.get(
            str(algorithm_name).lower()
        )
        if estimator_cls is None:
            return FunctionResult(input_data, {})

        vector_key = attributes.get("vector_key")
        label_key = attributes.get("label_key")
        output_key = cast(str, attributes.get("output_key", "prediction"))

        is_supervised, is_clusterer, is_transformer = self._estimator_kinds(estimator_cls)

        vectors: list[list[Any]] = []
        labels: list[Any] = []

        for record in input_data[0]:
            vec = record.get(cast(str, vector_key))
            if vec is not None and isinstance(vec, list):
                if is_supervised:
                    lbl = record.get(cast(str, label_key))
                    if lbl is not None:
                        vectors.append(cast(list[Any], vec))
                        labels.append(lbl)
                else:
                    vectors.append(cast(list[Any], vec))

        if not vectors:
            return FunctionResult(input_data, {})

        model_kwargs = self._extract_model_hyperparameters(estimator_cls, attributes)

        np = cast(Any, import_module("numpy"))
        X_train = np.array(vectors)

        try:
            model = estimator_cls(**model_kwargs)
            use_fit_predict = not hasattr(model, "predict") and hasattr(model, "fit_predict")
            training_outputs: Any | None = None
            if use_fit_predict:
                training_outputs = model.fit_predict(X_train)
            elif is_supervised:
                y_train = np.array(labels)
                model.fit(X_train, y_train)
            else:
                model.fit(X_train)

            result_data: DataBundle = []
            for group_index, data_subset in enumerate(input_data):
                subset_result: Data = []
                pred_vectors: list[list[Any]] = []
                valid_indices: list[int] = []

                for index, record in enumerate(data_subset):
                    vec = record.get(cast(str, vector_key))
                    if vec is not None and isinstance(vec, list):
                        pred_vectors.append(cast(list[Any], vec))
                        valid_indices.append(index)

                if not pred_vectors:
                    for record in data_subset:
                        new_record = record.copy()
                        new_record[output_key] = None
                        subset_result.append(new_record)
                else:
                    X_infer = np.array(pred_vectors)
                    if use_fit_predict:
                        if group_index != 0:
                            raise _SklearnEstimatorFailure(
                                f"{type(model).__name__} cannot infer later groups"
                            )
                        if training_outputs is None:
                            raise _SklearnEstimatorFailure(
                                f"{type(model).__name__} returned no training labels"
                            )
                        outputs = training_outputs
                    else:
                        outputs = self._infer(model, X_infer, is_clusterer, is_transformer)

                    label_index = 0
                    for index, record in enumerate(data_subset):
                        new_record = record.copy()
                        if index in valid_indices:
                            new_record[output_key] = self._normalize_prediction(
                                outputs[label_index]
                            )
                            label_index += 1
                        else:
                            new_record[output_key] = None
                        subset_result.append(new_record)

                result_data.append(subset_result)

            return FunctionResult(result_data, {})
        except _SklearnEstimatorFailure:
            raise
        except Exception as error:
            raise _SklearnEstimatorFailure from error

    def _extract_model_hyperparameters(
        self,
        estimator_cls: type[Any],
        attributes: Attributes,
    ) -> dict[str, Any]:
        """Extract only parameters accepted by estimator.__init__."""
        sig = inspect.signature(estimator_cls.__init__)
        model_kwargs: dict[str, Any] = {}
        for param_name in sig.parameters:
            if param_name in attributes and attributes[param_name] is not None:
                model_kwargs[param_name] = attributes[param_name]
        return model_kwargs

    def _infer(
        self,
        model: Any,
        X: Any,
        is_clusterer: bool,
        is_transformer: bool,
    ) -> Any:
        """Choose the estimator's non-fitting inference method."""
        if is_clusterer and hasattr(model, "predict"):
            return model.predict(X)
        if hasattr(model, "predict"):
            return model.predict(X)
        if is_transformer and hasattr(model, "transform"):
            return model.transform(X)
        if hasattr(model, "transform"):
            return model.transform(X)
        raise AttributeError(f"Estimator {model} does not support predict or transform")

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
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, "Failed base operator validation")

        algorithm = properties.get("algorithm") if properties else None
        if not algorithm:
            return ValidationResult(False, "Missing 'algorithm' in properties")

        try:
            registry = self._get_registry()
        except ImportError:
            # Let structured execution report the missing optional dependency at EXECUTE.
            return ValidationResult(True, None)
        estimator_cls = registry.get(str(algorithm)) or registry.get(str(algorithm).lower())
        if estimator_cls is None:
            return ValidationResult(False, f"Unsupported or unknown algorithm: {algorithm}")

        if not attributes.get("vector_key"):
            return ValidationResult(False, "vector_key is required")

        is_supervised, _, _ = self._estimator_kinds(estimator_cls)
        if is_supervised and not attributes.get("label_key"):
            return ValidationResult(False, "label_key is required for supervised models")

        return ValidationResult(True, None)


DISCOVERY = DiscoverySpec(
    when_to_invoke="Use when an arbitrary scikit-learn estimator is required.",
    tags=(
        "domain-ml",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-classification",
        "capability-clustering",
        "capability-transformation",
        "requires-ml",
    ),
)
