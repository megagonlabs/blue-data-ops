from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, cast

from blue_data_ops.data.errors import RegistryFailure, RegistryReason
from blue_data_ops.data.registry_seam import RegistrySeam


def registry_backend() -> str:
    selector = os.environ.get("BLUE_DATA_REGISTRY_STORE", "")
    if selector and (
        selector != selector.strip() or selector.lower() not in {"memory", "file", "redis"}
    ):
        raise RegistryFailure(RegistryReason.CONFIGURATION_FAILED)
    return selector.lower() or "memory"


def _validate_sources() -> None:
    path = os.environ.get("BLUE_DATA_SOURCES_CONFIG")
    if not path:
        return
    try:
        document: object = json.loads(Path(path).read_text(encoding="utf-8"))
        if type(document) is not dict:
            raise ValueError
        sources: object = cast(dict[str, Any], document).get("sources")
        if type(sources) is not list:
            raise ValueError
        if any(type(source) is not dict for source in cast(list[object], sources)):
            raise ValueError
    except Exception:
        raise RegistryFailure(RegistryReason.CONFIGURATION_FAILED) from None


class _BuildLogFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self.thread_id = threading.get_ident()

    def filter(self, record: logging.LogRecord) -> bool:
        return record.thread != self.thread_id


def build_environment_registry(*, require_configuration: bool = False) -> RegistrySeam | None:
    """Build from the shared blue-data helpers; source loading may connect and sync."""
    registry_backend()
    _validate_sources()
    if require_configuration and not (
        os.environ.get("BLUE_DATA_REGISTRY_STORE") or os.environ.get("BLUE_DATA_SOURCES_CONFIG")
    ):
        return None
    from blue_data.config import (  # pyright: ignore[reportMissingTypeStubs]
        build_enricher,
        build_hybrid_config,  # pyright: ignore[reportUnknownVariableType]
        build_store,
        get_vector_dim,
        load_sources,  # pyright: ignore[reportUnknownVariableType]
    )
    from blue_data.registry.data_registry import (  # pyright: ignore[reportMissingTypeStubs]
        DataRegistry,
    )

    config_logger = logging.getLogger("blue_data.config")
    build_filter = _BuildLogFilter()
    config_logger.addFilter(build_filter)
    try:
        registry: Any = DataRegistry(
            store=build_store(),
            metadata_enricher=build_enricher(),
            hybrid_config=build_hybrid_config(),
            vector_dim=get_vector_dim(),
        )
        load_sources(registry)
        logging.getLogger(__name__).info("data registry initialized")
        return RegistrySeam(registry)
    except Exception:
        raise RegistryFailure(RegistryReason.CONFIGURATION_FAILED) from None
    finally:
        config_logger.removeFilter(build_filter)
