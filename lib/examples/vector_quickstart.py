from __future__ import annotations

from blue_data_ops import VectorSimilarityOperator


def main() -> None:
    left = [{"id": "left", "embedding": [1.0, 0.0]}]
    right = [{"id": "right", "embedding": [1.0, 0.0]}]
    output, _, meta = VectorSimilarityOperator().run([left, right], {})
    assert meta.errors == []
    print("similarity:", output[0][0]["similarity.score"])


if __name__ == "__main__":
    main()
