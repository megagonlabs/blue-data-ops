from __future__ import annotations

import hashlib
import json
from pathlib import Path

from blue_data_ops.operator_skills import OperatorSkillLoader
from blue_data_ops.operators import Attributes, DataBundle, Operator, OperatorRegistry, Properties

_RESOURCE_FILES = {
    "guide": "Operator.md",
    "examples": "examples.md",
    "optimization": "optimization.md",
    "issues": "issues.md",
    "history": "history.md",
}


class _SyntheticOperator(Operator):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, description=f"Synthetic {name} operator.")

    def apply(
        self,
        input_data: DataBundle,
        attributes: Attributes,
        properties: Properties | None = None,
    ) -> DataBundle:
        del attributes, properties
        return input_data


def _register_builtin(registry: OperatorRegistry, operator_id: str) -> None:
    name, version = operator_id.split("@", 1)
    registry._register_builtin(  # pyright: ignore[reportPrivateUsage]
        _SyntheticOperator(name),
        version,
    )


def _write_package(root: Path, operator_id: str, kinds: tuple[str, ...]) -> None:
    name, version = operator_id.split("@", 1)
    package = root / name / version
    package.mkdir(parents=True)
    resources: dict[str, dict[str, str]] = {}
    for kind in kinds:
        content = f"# {operator_id} {kind}\n".encode()
        filename = _RESOURCE_FILES[kind]
        (package / filename).write_bytes(content)
        resources[kind] = {
            "path": filename,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    manifest = {
        "format": "blue-data-ops/operator-skill@1",
        "operator_id": operator_id,
        "resources": resources,
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _write_index(root: Path, operator_ids: tuple[str, ...]) -> None:
    packages = {
        operator_id: f"{operator_id.replace('@', '/')}/manifest.json"
        for operator_id in operator_ids
    }
    index = {"format": "blue-data-ops/operator-skill-index@1", "packages": packages}
    (root / "_index.json").write_text(json.dumps(index), encoding="utf-8")


def test_synthetic_catalog_proves_order_intersection_and_sparse_levels(tmp_path: Path) -> None:
    root = tmp_path / "operator_skills"
    root.mkdir()
    declarations = {
        "alpha@1.0.0": ("guide",),
        "alpha@2.0.0": ("history", "guide"),
        "alpha@10.0.0": ("examples", "guide"),
        "beta@0.4.1": ("issues", "history", "examples", "optimization", "guide"),
        "beta2@1.0.0": ("guide",),
    }
    for operator_id, kinds in declarations.items():
        _write_package(root, operator_id, kinds)

    shuffled = (
        "beta2@1.0.0",
        "alpha@1.0.0",
        "beta@0.4.1",
        "alpha@2.0.0",
        "alpha@10.0.0",
    )
    _write_index(root, shuffled)
    registry = OperatorRegistry()
    for operator_id in (
        "beta2@1.0.0",
        "alpha@1.0.0",
        "beta@0.4.1",
        "alpha@10.0.0",
        "alpha@2.0.0",
    ):
        _register_builtin(registry, operator_id)

    loader = OperatorSkillLoader(registry, _resource_root=root)
    expected = (
        "alpha@10.0.0",
        "alpha@2.0.0",
        "alpha@1.0.0",
        "beta@0.4.1",
        "beta2@1.0.0",
    )
    assert loader.available_operator_ids() == expected

    expected_metadata = {
        "alpha@1.0.0": (("guide",), (2,)),
        "alpha@2.0.0": (("guide", "history"), (2,)),
        "alpha@10.0.0": (("guide", "examples"), (2, 3)),
        "beta@0.4.1": (
            ("guide", "examples", "optimization", "issues", "history"),
            (2, 3, 4),
        ),
        "beta2@1.0.0": (("guide",), (2,)),
    }
    for operator_id, (kinds, levels) in expected_metadata.items():
        descriptor = loader.describe(operator_id)
        assert descriptor.card is registry.get_card(operator_id)
        assert descriptor.declared_kinds == kinds
        assert descriptor.declared_levels == levels

    assert loader.load("beta@0.4.1", level=4).loaded_kinds == (
        "guide",
        "examples",
        "history",
    )

    index_only = (*shuffled, "gamma@1.0.0")
    _write_index(root, index_only)
    assert loader.available_operator_ids() == expected

    _register_builtin(registry, "gamma@1.0.0")
    assert loader.available_operator_ids() == (*expected, "gamma@1.0.0")
