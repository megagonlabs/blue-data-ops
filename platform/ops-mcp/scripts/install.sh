#!/usr/bin/env bash
set -euo pipefail
MCP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB_ROOT="$(cd "${MCP_ROOT}/../../lib" && pwd)"
PYTHON="${PYTHON:-python}"
BLUE_DATA_PATH="${BLUE_DATA_PATH:-${LIB_ROOT}/../../blue-data/lib}"
export BLUE_DATA_PATH PYTHON

"${PYTHON}" "${LIB_ROOT}/scripts/check_blue_data.py" "${BLUE_DATA_PATH}" --server
"${LIB_ROOT}/scripts/install.sh"
if ! "${PYTHON}" -m pip install -e "${BLUE_DATA_PATH}[server]"; then
    echo 'Could not install selected blue-data source with [server]. See pip diagnostics above.' >&2
    exit 1
fi
"${PYTHON}" -m pip install -e "${LIB_ROOT}[ml,vector,llm]"
"${PYTHON}" -m pip install -e "${MCP_ROOT}[dev]"
echo "Done. Run: blue-data-ops-mcp"
