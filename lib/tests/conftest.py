from __future__ import annotations

import sys
from pathlib import Path

from tests.stubs import sentence_transformers as sentence_transformers_stub

# sentence-transformers is intentionally absent from the development dependencies;
# load the deterministic test stub before an operator reaches its lazy model import.
sys.path.insert(0, str(Path(__file__).parent / "stubs"))
sys.modules["sentence_transformers"] = sentence_transformers_stub

# Shared fixtures for the blue-data-ops test suite belong here; operator-specific
# fixtures stay beside their tests.
