#!/usr/bin/env bash
set -euo pipefail
MCP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB_ROOT="$(cd "${MCP_ROOT}/../../lib" && pwd)"
PYTHON="${PYTHON:-python}"
BLUE_DATA_PATH="${BLUE_DATA_PATH:-${LIB_ROOT}/../../blue-data/lib}"
export BLUE_DATA_PATH PYTHON

"${PYTHON}" "${LIB_ROOT}/scripts/check_blue_data.py" "${BLUE_DATA_PATH}" --server
"${LIB_ROOT}/scripts/install.sh"
if ! "${PYTHON}" -m pip install -e "${BLUE_DATA_PATH}[server]" "blue-data[server]>=1.0.0"; then
    echo 'MCP requires blue-data>=1.0.0 with [server]. Select a compatible BLUE_DATA_PATH.' >&2
    exit 1
fi
"${PYTHON}" -m pip install -e "${LIB_ROOT}[ml,vector,llm]" "blue-data-ops==1.0.0"
"${PYTHON}" -m pip install -e "${MCP_ROOT}[dev]" "blue-data-ops-mcp==1.0.0"
echo "Done. Run: blue-data-ops-mcp"
