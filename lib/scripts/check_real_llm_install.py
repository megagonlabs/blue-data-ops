from __future__ import annotations

import importlib.metadata
import importlib.util
import sys
from pathlib import Path


def main() -> None:
    if sys.version_info < (3, 11):  # noqa: UP036 - fail before importing optional packages
        raise SystemExit("the llm extra requires Python 3.11 or later")

    spec = importlib.util.find_spec("litellm")
    if spec is None or spec.origin is None:
        raise SystemExit("litellm is not installed")
    origin = Path(spec.origin).resolve()
    if "tests/stubs" in origin.as_posix():
        raise SystemExit(f"litellm resolved to the test stub: {origin}")

    __import__("litellm")
    print(f"litellm {importlib.metadata.version('litellm')} from {origin}")


if __name__ == "__main__":
    main()
