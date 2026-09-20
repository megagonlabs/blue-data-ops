#!/usr/bin/env bash
set -euo pipefail
MCP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB_ROOT="$(cd "${MCP_ROOT}/../../lib" && pwd)"

# Through the library's own installer, which puts blue-data in place first. blue-data is a
# core dependency of the library and is not on a public index, so installing this package
# directly fails to resolve it and reads as a broken package rather than a missing sibling.
"${LIB_ROOT}/scripts/install.sh"

# Then the extras the served operators need. That installer takes dev, which leaves out
# litellm and sentence-transformers deliberately, and eleven of the thirty-three tools this
# server exposes -- the eight language-model ones and the three vector ones -- cannot run
# without them. This package's core pin does not name the extras, so nothing else adds them.
pip install -e "${LIB_ROOT}[ml,vector,llm]"
pip install -e "${MCP_ROOT}[dev]"
echo "Done. Run: blue-data-ops-mcp"
