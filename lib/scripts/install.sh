#!/usr/bin/env bash
set -euo pipefail
LIB_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python}"
BLUE_DATA_PATH="${BLUE_DATA_PATH:-${LIB_ROOT}/../../blue-data/lib}"
export BLUE_DATA_PATH PYTHON

"${PYTHON}" "${LIB_ROOT}/scripts/check_blue_data.py" "${BLUE_DATA_PATH}"
if ! "${PYTHON}" -m pip install -e "${BLUE_DATA_PATH}"; then
    echo 'Could not install selected blue-data source. See pip diagnostics above.' >&2
    exit 1
fi
"${PYTHON}" -m pip install -e "${LIB_ROOT}[dev]"
echo "Done. Run: python -c 'import blue_data_ops'"
