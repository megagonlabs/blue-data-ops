# blue-data-ops

A standalone Python library of Blue data operators: record transforms, registry-backed database operations, and local pipeline planning. Version 3.0 exposes 33 active exact operator IDs and keeps older non-retired IDs in an explicit history registry.

The package lives in [`lib/`](lib/). See [`lib/README.md`](lib/README.md) for requirements, installation, usage, the operator catalog, and compatibility notes. Its [Discovery section](lib/README.md#discovery) explains the six tag axes and shows how to enumerate and filter them. The generated [operator reference](lib/OPERATORS.md#tag-taxonomy) lists the active values and each card's tags.

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
