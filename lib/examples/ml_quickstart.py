from __future__ import annotations

from blue_data_ops import ClassifyOperator


def main() -> None:
    training = [
        {"label": "low", "vector": [0.0, 0.0]},
        {"label": "low", "vector": [0.0, 1.0]},
        {"label": "high", "vector": [10.0, 10.0]},
        {"label": "high", "vector": [10.0, 11.0]},
    ]
    samples = [{"vector": [0.0, 0.5]}, {"vector": [10.0, 10.5]}]
    output, _, meta = ClassifyOperator().run(
        [training, samples],
        {"vector_key": "vector", "label_key": "label", "random_state": 42},
    )
    assert meta.errors == []
    print("predictions:", [record["predicted_label"] for record in output[1]])


if __name__ == "__main__":
    main()
