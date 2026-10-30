#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Start fresh: setuptools reuses build/lib, so a module deleted from src/ would
# otherwise still be packaged.
rm -rf -- build dist
python -m build
python scripts/check_wheel_contents.py
