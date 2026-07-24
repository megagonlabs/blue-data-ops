from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, cast

from blue_data_ops.operators._metadata import extract_signature, merge_metadata


class Tool:
    """Function plus live properties, validation, explanation, and signature metadata."""

    PROPERTIES: ClassVar[dict[str, Any]] = {}

    @property
    def properties(self) -> dict[str, Any]:
        """Return the live property mapping."""
        try:
            return self._properties
        except AttributeError:
            initialize = object.__getattribute__(self, "_initialize_missing_metadata")
            initialize()
            return self._properties

    @properties.setter
    def properties(self, value: dict[str, Any]) -> None:
        self._properties = value

    def __init__(
        self,
        name: str,
        function: Callable[..., Any],
        description: str | None = None,
        properties: dict[str, Any] | None = None,
        validator: Callable[..., Any] | None = None,
        explainer: Callable[..., Any] | None = None,
    ) -> None:
        self.name = name
        self.description = "" if description is None else description
        self.properties = {}
        self.function = function
        self.validator = validator
        self.explainer = explainer
        self._initialize(properties)

    def _initialize(self, properties: dict[str, Any] | None) -> None:
        self._initialize_properties()
        self._update_properties(properties)
        self.properties["signature"] = {}
        self._extract_signature()

    def _initialize_properties(self) -> None:
        self.properties = {"tool_type": "function"}

    def _update_properties(self, properties: dict[str, Any] | None) -> None:
        if properties is None:
            return
        for name, value in properties.items():
            self.properties[name] = value

    def _extract_signature(self) -> None:
        self.properties["signature"] = extract_signature(self.function)

    def get_properties(
        self,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return properties with optional non-mutating overrides."""
        return merge_metadata(self.properties, {} if properties is None else properties)

    def get_signature(self) -> dict[str, Any]:
        """Return the live function signature."""
        return self.properties["signature"]

    def get_parameters(self) -> dict[str, Any] | None:
        """Return the live parameter mapping, if present."""
        signature = self.get_signature()
        value = signature.get("parameters") if signature else None
        return cast(dict[str, Any], value) if isinstance(value, dict) else None

    def get_parameter(self, parameter: str) -> dict[str, Any] | None:
        """Return one live parameter definition, if present."""
        parameters = self.get_parameters()
        if parameters and parameter in parameters:
            value = parameters[parameter]
            return cast(dict[str, Any], value) if isinstance(value, dict) else None
        return None

    def get_parameter_type(self, parameter: str) -> Any:
        """Return one parameter type, if present."""
        definition = self.get_parameter(parameter)
        return definition.get("type") if definition else None

    def set_parameter_description(
        self,
        parameter: str,
        description: str,
    ) -> dict[str, Any] | None:
        """Set one parameter description and return its live definition."""
        definition = self.get_parameter(parameter)
        if definition:
            definition["description"] = description
        return definition

    def set_parameter_required(
        self,
        parameter: str,
        required: bool,
    ) -> dict[str, Any] | None:
        """Set one parameter's required flag and return its live definition."""
        definition = self.get_parameter(parameter)
        if definition:
            definition["required"] = required
        return definition

    def set_parameter_hidden(
        self,
        parameter: str,
        hidden: bool,
    ) -> dict[str, Any] | None:
        """Set one parameter's hidden flag and return its live definition."""
        definition = self.get_parameter(parameter)
        if definition:
            definition["hidden"] = hidden
        return definition

    def is_parameter_required(self, parameter: str) -> Any:
        """Return one parameter's required flag, if present."""
        definition = self.get_parameter(parameter)
        return definition.get("required") if definition else None

    def is_parameter_hidden(self, parameter: str) -> Any:
        """Return one parameter's hidden flag, if present."""
        definition = self.get_parameter(parameter)
        return definition.get("hidden") if definition else None

    def get_returns(self) -> dict[str, Any] | None:
        """Return the live return definition, if present."""
        signature = self.get_signature()
        value = signature.get("returns") if signature else None
        return cast(dict[str, Any], value) if isinstance(value, dict) else None

    def get_returns_type(self) -> Any:
        """Return the function's declared return type, if present."""
        returns = self.get_returns()
        return returns.get("type") if returns else None

    def set_returns_description(self, description: str) -> dict[str, Any] | None:
        """Set the return description and return its live definition."""
        returns = self.get_returns()
        if returns:
            returns["description"] = description
        return returns


__all__ = ["Tool"]
