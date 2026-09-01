# blue-data-ops

A standalone Python library of Blue data operators: record-oriented transforms and registry-backed database operations.

The package lives in [`lib/`](lib/). See [`lib/README.md`](lib/README.md) for requirements, installation, usage, the operator catalog, and compatibility notes.

## Quick start

For a source checkout, place `blue-data` and `blue-data-ops` under the same parent directory:

```text
workspace/
├── blue-data/
└── blue-data-ops/
```

From that parent directory, create an environment and install both packages:

```bash
python -m venv blue-data-ops/lib/.venv
source blue-data-ops/lib/.venv/bin/activate
python -m pip install -e ./blue-data/lib
python -m pip install -e "./blue-data-ops/lib[dev]"
cd blue-data-ops/lib
python -m pytest
```

See [`lib/README.md`](lib/README.md#requirements) for the version constraint, optional extras, and usage examples. The MCP adapter has its own setup and usage guide at [`platform/mcp/README.md`](platform/mcp/README.md).
