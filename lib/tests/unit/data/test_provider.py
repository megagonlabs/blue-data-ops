"""Resolver + provider contract tests against real blue-data."""

# blue-data ships no py.typed:
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import pytest

blue_data = pytest.importorskip("blue_data")

from blue_data.registry.data_registry import DataRegistry  # noqa: E402

from blue_data_ops.data import (  # noqa: E402
    BlueDataRegistryProvider,
    DataRegistryProvider,
    RegistrySeam,
    resolve_registry,
)

BOTH_KEYS = {"platform.name": "test_platform", "data_registry.name": "test_registry"}


def test_injected_seam_returned_as_is() -> None:
    seam = RegistrySeam(DataRegistry(name="injected", rebuild=True))
    resolved = resolve_registry({"data_registry": seam}, provider=BlueDataRegistryProvider())
    assert resolved is seam


def test_injected_raw_registry_gets_wrapped() -> None:
    registry = DataRegistry(name="raw", rebuild=True)
    resolved = resolve_registry({"data_registry": registry}, provider=BlueDataRegistryProvider())
    assert isinstance(resolved, RegistrySeam)
    assert resolved._registry is registry  # pyright: ignore[reportPrivateUsage]


def test_invalid_injection_with_both_keys_constructs() -> None:
    # An invalid injection falls through; both construction keys create a registry.
    properties = {"data_registry": "not-a-registry", **BOTH_KEYS}
    resolved = resolve_registry(properties, provider=BlueDataRegistryProvider())
    assert isinstance(resolved, RegistrySeam)


def test_invalid_injection_without_keys_resolves_none() -> None:
    resolved = resolve_registry(
        {"data_registry": "not-a-registry"}, provider=BlueDataRegistryProvider()
    )
    assert resolved is None


def test_both_keys_construct() -> None:
    resolved = resolve_registry(dict(BOTH_KEYS), provider=BlueDataRegistryProvider())
    assert isinstance(resolved, RegistrySeam)


@pytest.mark.parametrize("missing", ["platform.name", "data_registry.name"])
def test_either_key_missing_resolves_none(missing: str) -> None:
    properties = {k: v for k, v in BOTH_KEYS.items() if k != missing}
    assert resolve_registry(properties, provider=BlueDataRegistryProvider()) is None


@pytest.mark.parametrize("key", ["platform.name", "data_registry.name"])
@pytest.mark.parametrize("falsy", ["", None, 0, False])
def test_falsy_key_resolves_none(key: str, falsy: object) -> None:
    # A falsy value in either construction-key position resolves to None.
    properties: dict[str, object] = dict(BOTH_KEYS)
    properties[key] = falsy
    assert resolve_registry(properties, provider=BlueDataRegistryProvider()) is None


def test_none_properties_resolve_none() -> None:
    assert resolve_registry(None, provider=BlueDataRegistryProvider()) is None


def test_repeated_resolution_returns_same_instance() -> None:
    # Per-name cached singleton — the shared-namespace observable.
    provider = BlueDataRegistryProvider()
    first = resolve_registry(dict(BOTH_KEYS), provider=provider)
    second = resolve_registry(dict(BOTH_KEYS), provider=provider)
    assert first is second


def test_different_names_get_different_instances() -> None:
    provider = BlueDataRegistryProvider()
    first = resolve_registry(dict(BOTH_KEYS), provider=provider)
    other = dict(BOTH_KEYS)
    other["data_registry.name"] = "other_registry"
    second = resolve_registry(other, provider=provider)
    assert first is not second


def test_provider_constructed_connect_source_identity() -> None:
    # A caller-registered source on a provider-constructed seam comes back from
    # connect_source as the SAME object.
    class _Source:
        def __init__(self) -> None:
            self.name = "s1"
            self.properties: dict[str, object] = {"connection": {"protocol": "memory"}}

    seam = resolve_registry(dict(BOTH_KEYS), provider=BlueDataRegistryProvider())
    assert isinstance(seam, RegistrySeam)
    source = _Source()
    seam.register_source(source)  # pyright: ignore[reportArgumentType] — structural stub
    assert seam.connect_source("s1") is source


def test_custom_provider_contract() -> None:
    # The 3-arg provider contract, executable — a custom provider receives the two
    # VALIDATED names + the properties mapping.
    class _CustomProvider(DataRegistryProvider):
        def __init__(self) -> None:
            self.seen: list[tuple[str, str]] = []

        def get_registry(
            self, platform_name: str, registry_name: str, properties: dict[str, object]
        ) -> RegistrySeam:
            self.seen.append((platform_name, registry_name))
            return RegistrySeam(DataRegistry(name=registry_name, rebuild=True))

    provider = _CustomProvider()
    resolved = resolve_registry(dict(BOTH_KEYS), provider=provider)
    assert isinstance(resolved, RegistrySeam)
    assert provider.seen == [("test_platform", "test_registry")]


def test_provider_constructed_registry_has_rebuild_policy() -> None:
    # Provider-constructed registries carry instance rebuild=True.
    provider = BlueDataRegistryProvider()
    seam = provider.get_registry("p", "r", {})
    registry = seam._registry  # pyright: ignore[reportPrivateUsage]
    assert getattr(registry, "_rebuild", False) is True
