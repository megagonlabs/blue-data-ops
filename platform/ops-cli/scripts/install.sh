#!/usr/bin/env bash
set -euo pipefail
CLI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB_ROOT="$(cd "${CLI_ROOT}/../../lib" && pwd)"
PYTHON="${PYTHON:-python}"
export PYTHON

"${LIB_ROOT}/scripts/install.sh"
"${PYTHON}" -m pip install -e "${LIB_ROOT}[ml,vector,llm]"
"${PYTHON}" -m pip install -e "${CLI_ROOT}[dev]"
echo "Done. Run: blue-ops metadata inspect"
