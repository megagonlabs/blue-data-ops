"""Check the selected source before invoking pip; pip enforces the version floor."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main() -> None:
    source = Path(sys.argv[1])
    server = "--server" in sys.argv[2:]
    try:
        project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
        if project["name"] != "blue-data" or not isinstance(project["version"], str):
            raise ValueError("selected metadata does not identify blue-data")
        if server and (
            "server" not in project.get("optional-dependencies", {})
            or not (source / "src/blue_data/server.py").is_file()
        ):
            raise ValueError("selected source lacks the server extra or blue_data.server helper")
    except (OSError, KeyError, ValueError) as exc:
        print(f"blue-data 1.0+ source required: {exc}", file=sys.stderr)
        print("Set BLUE_DATA_PATH to its compatible lib directory.", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"Selected blue-data {project['version']}; pip must satisfy blue-data>=1.0.0.")


if __name__ == "__main__":
    main()
