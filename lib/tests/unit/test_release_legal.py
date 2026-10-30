from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ("lib", "platform/ops-cli", "platform/ops-mcp")
LEGAL_FILES = (
    "CODE_OF_CONDUCT.md",
    "LICENSE",
    "NOTICE",
    "docs/disclosures.md",
    "docs/oss-components.md",
    *(f"{package}/{name}" for package in PACKAGES for name in ("LICENSE", "NOTICE")),
)


@pytest.mark.parametrize("relative", LEGAL_FILES)
def test_legal_file_is_present(relative: str) -> None:
    path = ROOT / relative
    assert path.is_file()
    assert path.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("package", PACKAGES)
@pytest.mark.parametrize("name", ("LICENSE", "NOTICE"))
def test_package_legal_files_match_repository(package: str, name: str) -> None:
    assert (ROOT / package / name).read_bytes() == (ROOT / name).read_bytes()
