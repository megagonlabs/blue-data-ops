from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
    DataRegistry,  # blue-data ships no py.typed
)

from blue_data_ops.data.registry_seam import RegistrySeam

# Local alias rather than operators.types.Properties: the data package must not
# import the operators package (operators import the seam — one-way dependency).
Properties = dict[str, Any]


class DataRegistryProvider(ABC):
    """Resolves and constructs the data registry an operator should use."""

    @abstractmethod
    def get_registry(
        self, platform_name: str, registry_name: str, properties: Properties
    ) -> RegistrySeam: ...


class BlueDataRegistryProvider(DataRegistryProvider):
    """Default provider: a per-name cached blue-data DataRegistry factory."""

    # The default provider uses an in-memory registry with eager index rebuilds.
    # Callers register sources through the seam or inject a custom provider.

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], RegistrySeam] = {}

    def get_registry(
        self, platform_name: str, registry_name: str, properties: Properties
    ) -> RegistrySeam:
        key = (platform_name, registry_name)
        seam = self._cache.get(key)
        if seam is None:
            seam = RegistrySeam(DataRegistry(name=registry_name, rebuild=True))
            self._cache[key] = seam
        return seam


_default_provider = BlueDataRegistryProvider()


def resolve_registry(
    properties: Properties | None, provider: DataRegistryProvider | None = None
) -> RegistrySeam | None:
    """Resolve an injected registry or construct one from the two naming keys."""
    # An invalid injected value falls through to the construction-key branch. A raw
    # blue-data registry is wrapped because its create methods do not accept the
    # compatibility arguments exposed by RegistrySeam.
    if properties is None:
        properties = {}
    injected = properties.get("data_registry")
    if isinstance(injected, RegistrySeam):
        return injected
    if isinstance(injected, DataRegistry):
        return RegistrySeam(injected)

    platform_name = properties.get("platform.name")
    registry_name = properties.get("data_registry.name")
    if platform_name and registry_name:
        active_provider = provider if provider is not None else _default_provider
        return active_provider.get_registry(str(platform_name), str(registry_name), properties)
    return None
