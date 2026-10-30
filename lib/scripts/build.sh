#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf -- build dist
python -m build
python scripts/check_wheel_contents.py
