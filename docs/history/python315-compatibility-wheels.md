# Python 3.15 compatibility wheels (historical)

This route no longer works: every package declares `requires-python = ">=3.12,<3.14"`, so pip refuses to install it on Python 3.15. The notes below are kept only as a record of the earlier compatibility builds and their [scripts in `lib/scripts/`](../../lib/scripts/).

Regular CPython 3.15 on macOS ARM64 can use local `fastuuid==0.14.0+blue.1` and `litellm==1.106.5+blue.1` wheels. These builds are selected with `lib/scripts/python315-constraints.txt`; published dependency ranges stay unchanged. These local versions are not on PyPI.

LiteLLM 1.106.5 excludes 3.15 in its metadata and imports the removed `sre_constants` and `sre_parse` modules. `patch-litellm-python315-wheel.py` replaces those two imports with CPython's `re._constants` and `re._parser`, updates the wheel RECORD and restricts this build to Python 3.15. It checks the official wheel's SHA-256 before writing and preserves native code, tags and licenses. The private regex modules need rechecking on future interpreters.

Fastuuid's upstream build uses a PyO3 version whose direct build gate excludes 3.15. `build-python315-wheel.py` enables `abi3-py310` on the genuine native implementation and builds with regular CPython 3.12–3.14. It verifies the pinned upstream source hash and preserves the license. Renaming a CPython-specific binary or changing only Requires-Python cannot provide native compatibility.

To prepare a wheelhouse on macOS ARM64, use new directories and a regular CPython 3.12–3.14 build environment with `maturin==1.15.0`, Cargo >=1.78, Rust and the Xcode command-line tools. The native build needs PyPI/crates.io access unless its inputs are already cached. From the repository root:

```bash
python3.12 lib/scripts/build-python315-wheel.py \
  --sdist /path/to/fastuuid-0.14.0.tar.gz \
  --work-dir .native315 --wheel-dir .wheels315
python3.12 lib/scripts/patch-litellm-python315-wheel.py \
  /path/to/litellm-1.106.5-cp310-abi3-macosx_11_0_arm64.whl \
  --wheel-dir .wheels315
```

The fastuuid source SHA-256 is `178947fc2f995b38497a74172adee64fdeb8b7ec18f2a5934d037641ba265d26`; the official LiteLLM ARM64 wheel SHA-256 is `25d71b305f7d0c67b990f21993f4aa9cd62c5a48ca0400b9b7aba6a355e2ad0b`. Both scripts refuse an unexpected input; the patcher refuses to replace an output wheel. Keep third-party licenses with any distributed wheelhouse.

For a minimal library/LLM installation in a new regular Python 3.15 environment, point `BLUE_DATA_PATH` at a compatible exported blue-data 1.0 library source and `PIP_FIND_LINKS` at the prepared wheelhouse:

```bash
python3.15 -m venv .venv315
source .venv315/bin/activate
export PIP_FIND_LINKS="$PWD/.wheels315"
export PYYAML_FORCE_LIBYAML=0
python -m pip install -e "$BLUE_DATA_PATH"
python -m pip install -c lib/scripts/python315-constraints.txt -e './lib[llm]'
python -m pip check
python -c 'import blue_data_ops, litellm, fastuuid; print("imports OK")'
```

PyYAML 6.0.3 has a supported pure-Python build selected by `PYYAML_FORCE_LIBYAML=0`; its source build needs setuptools and Cython and executes upstream packaging code. The tested route uses that implementation, without the optional LibYAML accelerator. Keep the constraints and wheelhouse when adding packages to this environment. Resolve the complete dependency closure rather than using `--no-deps` or changing only package metadata.

To install the CLI and MCP adapters in that environment, include the SDK's server extra and the CLI's ML/vector dependencies:

```bash
python -m pip install -e "${BLUE_DATA_PATH}[server]"
python -m pip install -c lib/scripts/python315-constraints.txt \
  -e './lib[ml,vector,llm]' -e ./platform/ops-cli -e ./platform/ops-mcp
python -m pip check
blue-ops --version
python -c 'from importlib.metadata import version; print(version("blue-data-ops-mcp"))'
```

The verified dependency profile uses regular CPython 3.15.0 on macOS ARM64, NumPy 2.5.4, SciPy 1.18.1, scikit-learn 1.9.1, sentence-transformers 6.2.0, PyTorch 2.15.0, FastAPI 0.162.0 and MCP 1.30.0, with the compatibility builds above. The current SciPy and PyTorch wheels in this profile target macOS 14 or later. Native imports and small numerical/estimator operations are checked separately from unit tests that replace model downloads and provider responses. No embedding model download is required by those offline tests. A fresh installation can resolve newer dependency versions, so verify its complete closure before substituting them. Linux, Windows, Intel macOS and free-threaded Python remain unverified.
