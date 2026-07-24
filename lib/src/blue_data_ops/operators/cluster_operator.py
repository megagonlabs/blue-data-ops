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


class _ClusterModelFailure(Exception):
    pass


class ClusterOperator(Operator):
    """Cluster list-valued vectors from the first input group."""

    name: ClassVar[str] = "cluster"
    description: ClassVar[str] = (
        "Given input data with numeric vectors, compute clusters and predict cluster "
        "index for each sample using KMeans, DBSCAN, or GaussianMixture."
    )
    attributes: ClassVar[dict[str, AttributeSpec]] = {
        "vector_key": AttributeSpec(
            type="str",
            description="The key to the numeric vector values",
            required=True,
        ),
        "n_cluster": AttributeSpec(
            type="int",
            description="The number of clusters to form",
        ),
        "output_key": AttributeSpec(
            type="str",
            description="The key name for the predicted labels",
            default="cluster_index",
        ),
        "eps": AttributeSpec(
            type="float",
            description="Max distance between two samples for DBSCAN",
            default=0.5,
        ),
        "min_samples": AttributeSpec(
            type="int",
            description="Number of samples in a neighborhood for DBSCAN",
            default=5,
        ),
        "covariance_type": AttributeSpec(
            type="str",
            description="Covariance type for Gaussian Mixture",
            default="full",
        ),
        "init": AttributeSpec(
            type="str",
            description="Method for initialization",
        ),
        "init_centroids": AttributeSpec(
            type="list",
            description="Required when init='specified'",
        ),
        "max_iter": AttributeSpec(
            type="int",
            description="Maximum number of iterations",
            default=300,
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
        except _ClusterModelFailure:
            return [input_data[0]]

    def _execute(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> FunctionResult:
        algorithm = properties.get("algorithm", "kmeans") if properties else "kmeans"
        vector_key = attributes.get("vector_key")
        output_key = cast(str, attributes.get("output_key", "cluster_index"))
        cluster_raw = attributes.get("n_cluster")
        cluster_count = int(cluster_raw) if cluster_raw is not None else None
        init = cast(
            str,
            attributes.get("init", "k-means++" if algorithm == "kmeans" else "kmeans"),
        )
        max_iter = int(attributes.get("max_iter", 300))
        init_centroids = attributes.get("init_centroids")
        eps = float(attributes.get("eps", 0.5))
        min_samples = int(attributes.get("min_samples", 5))
        covariance_type = cast(str, attributes.get("covariance_type", "full"))

        if not input_data or not input_data[0]:
            return FunctionResult([[]], {})

        data = input_data[0]
        vectors: list[list[Any]] = []
        valid_indices: list[int] = []
        for index, record in enumerate(data):
            vector = record.get(cast(str, vector_key))
            if vector is not None and isinstance(vector, list):
                vectors.append(cast(list[Any], vector))
                valid_indices.append(index)

        if algorithm in {"kmeans", "gaussian"} and (
            not vectors or len(vectors) < cast(int, cluster_count)
        ):
            return FunctionResult([data], {})
        if algorithm == "dbscan" and not vectors:
            return FunctionResult([data], {})

        # NumPy is first needed to materialize the vector matrix.
        np = cast(Any, import_module("numpy"))

        matrix = np.array(vectors)
        if algorithm == "kmeans":
            model_constructor = getattr(import_module("sklearn.cluster"), "KMeans")
        elif algorithm == "dbscan":
            model_constructor = getattr(import_module("sklearn.cluster"), "DBSCAN")
        elif algorithm == "gaussian":
            model_constructor = getattr(import_module("sklearn.mixture"), "GaussianMixture")
        else:
            return FunctionResult([data], {})

        try:
            if algorithm == "kmeans":
                if init == "specified" and init_centroids:
                    kmeans_init = np.array(init_centroids)
                else:
                    kmeans_init = init if init in {"k-means++", "random"} else "k-means++"
                model: Any = model_constructor(
                    n_clusters=cast(int, cluster_count),
                    init=kmeans_init,
                    max_iter=max_iter,
                    n_init=1 if init == "specified" else "auto",
                    random_state=42,
                )
            elif algorithm == "dbscan":
                model = model_constructor(eps=eps, min_samples=min_samples)
            else:
                gmm_init = (
                    init
                    if init in {"kmeans", "k-means++", "random", "random_from_data"}
                    else "kmeans"
                )
                means_init = (
                    np.array(init_centroids) if init == "specified" and init_centroids else None
                )
                model = model_constructor(
                    n_components=cast(int, cluster_count),
                    covariance_type=covariance_type,
                    max_iter=max_iter,
                    init_params=gmm_init,
                    means_init=means_init,
                    random_state=42,
                )

            labels = model.fit_predict(matrix)
            result_data: Data = []
            label_index = 0
            for index, record in enumerate(data):
                new_record = record.copy()
                if index in valid_indices:
                    new_record[output_key] = int(labels[label_index])
                    label_index += 1
                else:
                    new_record[output_key] = None
                result_data.append(new_record)
            return FunctionResult([result_data], {})
        except Exception as error:
            raise _ClusterModelFailure from error

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
        suggestion = "supply valid clustering attributes for the selected algorithm"
        if not super().validate(input_data, attributes, properties):
            return ValidationResult(False, suggestion)

        algorithm = properties.get("algorithm", "kmeans") if properties else "kmeans"
        vector_key = attributes.get("vector_key")
        cluster_count = attributes.get("n_cluster")
        if not vector_key:
            return ValidationResult(False, suggestion)
        if algorithm in {"kmeans", "gaussian"} and cluster_count is None:
            return ValidationResult(False, suggestion)

        init = attributes.get("init")
        init_centroids = attributes.get("init_centroids")
        if init == "specified" and algorithm in {"kmeans", "gaussian"}:
            if not init_centroids:
                return ValidationResult(False, suggestion)
            if cluster_count is None:
                return ValidationResult(False, suggestion)
            if len(cast(list[Any], init_centroids)) != int(cluster_count):
                return ValidationResult(False, suggestion)
        return ValidationResult(True, None)


DISCOVERY = DiscoverySpec(
    when_to_invoke="Use when unlabeled numeric vectors must be assigned to clusters.",
    tags=(
        "domain-ml",
        "flow-transform",
        "accepts-data",
        "produces-data",
        "capability-clustering",
        "requires-ml",
    ),
)
