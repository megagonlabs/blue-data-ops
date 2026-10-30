#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

: "${TWINE_REPOSITORY_URL:?Set TWINE_REPOSITORY_URL to the intended package index URL}"
metadata=$(python - <<'METADATA'
import tomllib
from pathlib import Path

project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
print(project["name"].replace("-", "_"), project["version"])
METADATA
)
read -r distribution version <<< "$metadata"
shopt -s nullglob
wheels=(dist/"${distribution}-${version}"-*.whl)
sdist="dist/${distribution}-${version}.tar.gz"
if [[ ${#wheels[@]} -ne 1 || ! -f "$sdist" ]]; then
  printf 'Expected one wheel and one sdist for %s %s in dist/\n' "$distribution" "$version" >&2
  exit 1
fi
python scripts/check_wheel_contents.py
twine check "$sdist" "${wheels[0]}"
twine upload --repository-url "$TWINE_REPOSITORY_URL" "$sdist" "${wheels[0]}"
