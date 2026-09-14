from __future__ import annotations

import inspect
from importlib import import_module
from typing import Any, ClassVar, cast

import sklearn.utils
from sklearn.base import (
    ClassifierMixin,
    ClusterMixin,
    RegressorMixin,
    TransformerMixin,
)

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
    """Universal runtime wrapper for any scikit-learn estimator."""

    name: ClassVar[str] = "sklearn_estimator"
    description: ClassVar[str] = (
        "Dynamically wrap and execute any scikit-learn estimator (classification, "
        "regression, clustering, or transformation) conforming to the DataBundle schema."
    )

    # Core required and common attributes.
    # Hyperparameters for specific estimators are passed dynamically via attributes.
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

    # In-memory registry cache to avoid repeated inspection of all estimators
    _ESTIMATOR_REGISTRY: ClassVar[dict[str, type[Any]]] = {}

    @classmethod
    def _get_registry(cls) -> dict[str, type[Any]]:
        if not cls._ESTIMATOR_REGISTRY:
            # Map both exact names and lowercase names (e.g. 'KMeans' and 'kmeans')
            estimators = sklearn.utils.all_estimators()
            for name, estimator_cls in estimators:
                cls._ESTIMATOR_REGISTRY[name] = estimator_cls
                cls._ESTIMATOR_REGISTRY[name.lower()] = estimator_cls
        return cls._ESTIMATOR_REGISTRY

    @staticmethod
    def _normalize_prediction(val: Any) -> Any:
        """Convert NumPy arrays and scalars to native Python types."""
        if isinstance(val, (str, int, float, bool)) or val is None:
            return val

        val_any = cast(Any, val)
        if hasattr(val_any, "tolist"):
            return val_any.tolist()
        if hasattr(val_any, "item"):
            return val_any.item()
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
        # Guard against empty input bundles
        if not input_data or not input_data[0]:
            return FunctionResult(input_data, {})

        algorithm_name = properties.get("algorithm") if properties else None
        if not algorithm_name:
            return FunctionResult(input_data, {})

        registry = self._get_registry()
        estimator_cls = registry.get(str(algorithm_name)) or registry.get(str(algorithm_name).lower())
        if estimator_cls is None:
            return FunctionResult(input_data, {})

        vector_key = attributes.get("vector_key")
        label_key = attributes.get("label_key")
        output_key = cast(str, attributes.get("output_key", "prediction"))

        # Determine task type based on scikit-learn Mixin classes
        is_supervised = issubclass(estimator_cls, (ClassifierMixin, RegressorMixin))
        is_clusterer = issubclass(estimator_cls, ClusterMixin)
        is_transformer = issubclass(estimator_cls, TransformerMixin)

        # 1. Extract training vectors (and optional labels) from the first group (input_data[0])
        vectors: list[list[Any]] = []
        labels: list[Any] = []

        for record in input_data[0]:
            vec = record.get(cast(str, vector_key))
            if vec is not None and isinstance(vec, list):
                if is_supervised:
                    lbl = record.get(cast(str, label_key))
                    if lbl is not None:
                        vectors.append(vec)
                        labels.append(lbl)
                else:
                    vectors.append(vec)

        if not vectors:
            return FunctionResult(input_data, {})

        # 2. Extract only valid parameters declared in the estimator's __init__
        model_kwargs = self._extract_model_hyperparameters(estimator_cls, attributes)

        np = cast(Any, import_module("numpy"))
        X_train = np.array(vectors)

        try:
            model = estimator_cls(**model_kwargs)
            if is_supervised:
                y_train = np.array(labels)
                model.fit(X_train, y_train)
            else:
                model.fit(X_train)

            # 3. Apply inference over all DataBundle subsets
            result_data: DataBundle = []
            for data_subset in input_data:
                subset_result: Data = []
                pred_vectors: list[list[Any]] = []
                valid_indices: list[int] = []

                for index, record in enumerate(data_subset):
                    vec = record.get(cast(str, vector_key))
                    if vec is not None and isinstance(vec, list):
                        pred_vectors.append(vec)
                        valid_indices.append(index)

                if not pred_vectors:
                    for record in data_subset:
                        new_record = record.copy()
                        new_record[output_key] = None
                        subset_result.append(new_record)
                else:
                    X_infer = np.array(pred_vectors)
                    outputs = self._infer(model, X_infer, is_clusterer, is_transformer)

                    label_index = 0
                    for index, record in enumerate(data_subset):
                        new_record = record.copy()
                        if index in valid_indices:
                            new_record[output_key] = self._normalize_prediction(outputs[label_index])
                            label_index += 1
                        else:
                            new_record[output_key] = None
                        subset_result.append(new_record)

                result_data.append(subset_result)

            return FunctionResult(result_data, {})
        except Exception as error:
            raise _SklearnEstimatorFailure from error

    def _extract_model_hyperparameters(
        self, estimator_cls: type[Any], attributes: Attributes
    ) -> dict[str, Any]:
        """Extract only parameters accepted by estimator.__init__."""
        sig = inspect.signature(estimator_cls.__init__)
        model_kwargs: dict[str, Any] = {}
        for param_name in sig.parameters:
            if param_name in attributes and attributes[param_name] is not None:
                model_kwargs[param_name] = attributes[param_name]
        return model_kwargs

    def _infer(
            self, model: Any, X: Any, is_clusterer: bool, is_transformer: bool
        ) -> Any:
            """Route to appropriate inference method based on estimator capabilities."""
            # 1. Clusterers must return cluster indices (via predict or fit_predict), not distance transforms
            if is_clusterer:
                if hasattr(model, "predict"):
                    return model.predict(X)
                if hasattr(model, "fit_predict"):
                    return model.fit_predict(X)

            # 2. Supervised estimators (classifiers, regressors)
            if hasattr(model, "predict"):
                return model.predict(X)

            # 3. Pure transformers (e.g. PCA, StandardScaler)
            if is_transformer and hasattr(model, "transform"):
                return model.transform(X)

            if hasattr(model, "fit_predict"):
                return model.fit_predict(X)

            if hasattr(model, "transform"):
                return model.transform(X)

            raise AttributeError(f"Estimator {model} does not support predict or transform.")

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

        registry = self._get_registry()
        estimator_cls = registry.get(str(algorithm)) or registry.get(str(algorithm).lower())
        if estimator_cls is None:
            return ValidationResult(False, f"Unsupported or unknown algorithm: {algorithm}")

        if not attributes.get("vector_key"):
            return ValidationResult(False, "vector_key is required")

        # Supervised estimators require label_key
        is_supervised = issubclass(estimator_cls, (ClassifierMixin, RegressorMixin))
        if is_supervised and not attributes.get("label_key"):
            return ValidationResult(False, "label_key is required for supervised models")

        return ValidationResult(True, None)


DISCOVERY = DiscoverySpec(
    when_to_invoke="Use when an arbitrary scikit-learn estimator is required.",
    tags=("domain-ml", "flow-transform", "accepts-data", "produces-data", "requires-ml"),
)