# blue-data-ops

A standalone Python library of Blue data operators: record-oriented transforms and registry-backed
database operations.

The package lives in [`lib/`](lib/). See [`lib/README.md`](lib/README.md) for requirements,
installation, usage, the operator catalog, and compatibility notes.

## Quick start

Requires `blue-data` installed first. Then:

```bash
# from the repository root
python -m venv .venv && source .venv/bin/activate
cd lib
python -m pip install -e ".[dev]"
python -m pytest
```

See [`lib/README.md`](lib/README.md#requirements) for the version constraint, optional extras, and
usage examples.
