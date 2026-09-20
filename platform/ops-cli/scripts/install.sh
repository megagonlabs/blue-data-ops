#!/usr/bin/env bash
set -euo pipefail
CLI_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB_ROOT="$(cd "${CLI_ROOT}/../../lib" && pwd)"

# Through the library's own installer, which puts blue-data in place first. blue-data is a
# core dependency of the library and is not on a public index, so installing this package
# against a library that has not resolved it fails, and it fails reading as a broken
# package rather than as a missing sibling. Override BLUE_DATA_PATH if yours lives
# elsewhere -- that installer is where the variable is read.
"${LIB_ROOT}/scripts/install.sh"

# Then the extras the active operators need. The library's installer takes dev, which
# leaves out litellm and sentence-transformers deliberately, and the eight language-model
# operators and the three vector ones cannot run without them. The core pin in this
# package names the same three, so this line is what a bare `pip install` would do anyway.
pip install -e "${LIB_ROOT}[ml,vector,llm]"
pip install -e "${CLI_ROOT}[dev]"
echo "Done. Run: blue-ops metadata inspect"
