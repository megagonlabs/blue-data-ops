from __future__ import annotations

from blue_data_ops.operators import active_registry


def main() -> None:
    operator = active_registry().resolve("vector_similarity@3.0.0")
    left = [{"id": "left", "embedding": [1.0, 0.0]}]
    right = [{"id": "right", "embedding": [1.0, 0.0]}]
    output, _, meta = operator.run([left, right], {})
    assert operator.operator_id == "vector_similarity@3.0.0"
    assert meta.errors == []
    print("similarity:", output[0][0]["similarity.score"])


if __name__ == "__main__":
    main()
