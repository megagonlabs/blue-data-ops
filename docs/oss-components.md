# Direct components and extras

This inventory covers the three pyprojects' direct dependencies and optional extras, the
blue-data server extra's FastAPI helper, optional SDK backend diagnostics interfaces, and separate
dev/build tooling. Versions below are those installed under Python 3.11 and 3.12. The license labels come from
the installed artifact's METADATA and top-level LICENSE/COPYING text, except blue-data, whose
license is from its 1.0.0 source at `ab2f3bc`. The build backend is setuptools 84.2.1;
the declared `setuptools>=68` floor permits other resolutions, which require their own checks.

The inherited Blue implementation in `lib/src/blue_data_ops/` remains under this repository's
[LICENSE](../LICENSE), BSD 3-Clause with Attribution / NOTICE Requirement, and [NOTICE](../NOTICE).
The [family reference](https://github.com/megagon-internal/blue) supplies the conduct/disclosure
structure. Distribution names, operator versions and schema versions are separate identities;
the CLI and MCP adapters both pin core 1.0.0.

| Direct component | Scope / extra | Installed version (3.11 / 3.12) | Artifact license | Upstream |
|---|---|---|---|---|
| `blue-data` | core:runtime, ops-mcp:runtime | 1.0.0 | BSD 3-Clause with Attribution / NOTICE Requirement (source LICENSE) | [upstream](https://github.com/megagon-internal/blue-data) |
| `build` | core:dev, ops-cli:dev, ops-mcp:dev | 1.6.1 | MIT | [upstream](https://github.com/pypa/build) |
| `click` | ops-cli:runtime | 8.5.0 | BSD-3-Clause | [upstream](https://github.com/pallets/click/) |
| `diskcache` | core:llm, core:dev | 5.6.3 | Apache-2.0 | [upstream](https://github.com/grantjenks/python-diskcache) |
| `fastapi` | blue-data[server] (MCP helper extra) | 0.162.0 | MIT | [upstream](https://github.com/fastapi/fastapi) |
| `jinja2` | core:llm, core:dev | 3.1.6 | BSD-3-Clause | [upstream](https://github.com/pallets/jinja/) |
| `jsonmerge` | core:runtime | 1.9.2 | MIT | [upstream](https://github.com/avian2/jsonmerge) |
| `jsonpath-ng` | core:runtime | 1.14.0 | Apache-2.0 | [upstream](https://github.com/jsonpath-ng/jsonpath-ng) |
| `litellm` | core:llm | 1.106.5 | MIT | [upstream](https://github.com/BerriAI/litellm) |
| `mysql-connector-python` | blue-data[mysql] (optional backend diagnostics interface) | 26.10.0 | GNU GPLv2 (with FOSS License Exception) | [upstream](https://dev.mysql.com/doc/connector-python/en/) |
| `psycopg2-binary` | blue-data[postgres] (optional backend diagnostics interface) | 2.9.13 | LGPL with exceptions | [upstream](https://psycopg.org/) |
| `mcp` | ops-mcp:runtime | 1.30.0 | MIT | [upstream](https://github.com/modelcontextprotocol/python-sdk) |
| `numpy` | core:ml, core:vector, core:dev | 2.4.6 / 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | [upstream](https://github.com/numpy/numpy) |
| `openai` | core:openai, core:dev | 2.54.0 | Apache-2.0 | [upstream](https://github.com/openai/openai-python) |
| `pydantic` | core:runtime, ops-mcp:runtime | 2.14.1 | MIT | [upstream](https://github.com/pydantic/pydantic) |
| `pyright` | core:dev, ops-cli:dev, ops-mcp:dev | 1.1.414 | MIT | [upstream](https://github.com/RobertCraigie/pyright-python) |
| `pytest` | core:dev, ops-cli:dev, ops-mcp:dev | 9.2.0 | MIT | [upstream](https://github.com/pytest-dev/pytest) |
| `pytest-asyncio` | core:dev, ops-cli:dev, ops-mcp:dev | 1.4.1 | Apache-2.0 | [upstream](https://github.com/pytest-dev/pytest-asyncio) |
| `pytest-cov` | core:dev, ops-cli:dev, ops-mcp:dev | 7.1.0 | MIT | [upstream](https://github.com/pytest-dev/pytest-cov) |
| `pytest-recording` | core:dev | 0.14.0 | MIT | [upstream](https://github.com/kiwicom/pytest-recording) |
| `rich` | ops-cli:runtime | 15.0.0 | MIT | [upstream](https://github.com/Textualize/rich) |
| `ruff` | core:dev, ops-cli:dev, ops-mcp:dev | 0.17.3 | MIT | [upstream](https://github.com/astral-sh/ruff) |
| `scikit-learn` | core:ml, core:dev | 1.9.1 | BSD-3-Clause | [upstream](https://github.com/scikit-learn/scikit-learn) |
| `sentence-transformers` | core:vector | 6.2.0 | Apache-2.0 | [upstream](https://github.com/huggingface/sentence-transformers/) |
| `setuptools` | core:build, ops-cli:build, ops-mcp:build | 84.2.1 | MIT | [upstream](https://github.com/pypa/setuptools) |
| `tenacity` | core:runtime, core:llm, core:dev | 9.2.1 | Apache-2.0 | [upstream](https://github.com/jd/tenacity) |
| `twine` | core:dev, ops-cli:dev, ops-mcp:dev | 7.0.0 | Apache-2.0 | [upstream](https://github.com/pypa/twine/) |
| `wheel` | core:build, ops-cli:build, ops-mcp:build | 0.48.0 | MIT | [upstream](https://github.com/pypa/wheel) |

Repeated components have one row with all declaration scopes. NumPy's expression includes the
additional licenses declared by its wheel. Optional model weights and user datasets have their
own terms; this table supplies no transitive licensing certification. Consult the installed
artifacts' complete license texts and [disclosures](disclosures.md) before redistribution.
If a dependency resolution changes, check the affected version and license rows again.

The optional backend rows list installed versions and METADATA license labels; they add no dependency requirement. Consult the complete license texts before redistribution.
