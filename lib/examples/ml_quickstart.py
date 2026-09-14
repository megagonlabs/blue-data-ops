from __future__ import annotations

from blue_data_ops.operators import active_registry


def main() -> None:
    classifier = active_registry().resolve("classify@3.0.0")
    training = [
        {"label": "low", "vector": [0.0, 0.0]},
        {"label": "low", "vector": [0.0, 1.0]},
        {"label": "high", "vector": [10.0, 10.0]},
        {"label": "high", "vector": [10.0, 11.0]},
    ]
    samples = [{"vector": [0.0, 0.5]}, {"vector": [10.0, 10.5]}]
    output, _, meta = classifier.run(
        [training, samples],
        {"vector_key": "vector", "label_key": "label", "random_state": 42},
    )
    assert classifier.operator_id == "classify@3.0.0"
    assert meta.errors == []
    print("predictions:", [record["predicted_label"] for record in output[1]])


if __name__ == "__main__":
    main()
