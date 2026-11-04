from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from blue_data_ops.llm import LLMClient, LLMError

KW = {"model": "synthetic-model", "messages": [{"role": "user", "content": "synthetic"}]}


@pytest.mark.parametrize("source_first", [False, True])
@pytest.mark.parametrize("shared", [False, True])
def test_current_source_cache_coexists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_first: bool, shared: bool
) -> None:
    source_type = getattr(
        pytest.importorskip("blue_data_llm_source.llm.client"), "DefaultLlmClient"
    )
    monkeypatch.chdir(tmp_path)
    old_umask = os.umask(0o022)
    ops = LLMClient("ops")
    source = source_type()
    properties: dict[str, Any] = {"llm.cache": True}
    if shared:
        private = tmp_path / "shared"
        private.mkdir(mode=0o700)
        properties["llm.cache_dir"] = str(private)
    try:
        if source_first:
            source_cache, source_key = source._cache_for(properties, KW)
            ops_cache, ops_key = ops._cache_lookup(properties, KW)  # pyright: ignore[reportPrivateUsage]
        else:
            ops_cache, ops_key = ops._cache_lookup(properties, KW)  # pyright: ignore[reportPrivateUsage]
            source_cache, source_key = source._cache_for(properties, KW)
        assert ops_cache is not None and source_cache is not None
        assert ops_key is not None and source_key is not None
        assert ops_key != source_key
        ops_cache[ops_key] = {"synthetic": "ops"}
        assert source_key not in source_cache
        source_cache[source_key] = {"synthetic": "source"}
        assert ops_cache[ops_key] == {"synthetic": "ops"}
        assert Path(ops_cache.directory).stat().st_mode & 0o777 == 0o700
        if not shared:
            assert Path(ops_cache.directory).name == ".blue-data-ops-cache"
            assert Path(source_cache.directory).name == ".llm_cache"
    finally:
        source.close()
        for cache in ops._caches.values():  # pyright: ignore[reportPrivateUsage]
            cache.close()
        os.umask(old_umask)


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and mode")
def test_permission_change_refused_before_reuse(tmp_path: Path) -> None:
    path = tmp_path / "cache"
    client = LLMClient("ops")
    props = {"llm.cache": True, "llm.cache_dir": str(path)}
    cache, _ = client._cache_lookup(props, KW)  # pyright: ignore[reportPrivateUsage]
    assert cache is not None
    path.chmod(0o755)
    try:
        with pytest.raises(LLMError) as error:
            client._cache_lookup(props, KW)  # pyright: ignore[reportPrivateUsage]
        assert error.value.retryable is False
        assert path.stat().st_mode & 0o777 == 0o755
    finally:
        cache.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and mode")
def test_unsafe_existing_directory_is_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "cache"
    path.mkdir(mode=0o755)
    with pytest.raises(LLMError):
        LLMClient("ops")._cache_lookup({"llm.cache": True, "llm.cache_dir": str(path)}, KW)  # pyright: ignore[reportPrivateUsage]
    assert path.stat().st_mode & 0o777 == 0o755
    assert list(path.iterdir()) == []


def test_relative_cache_identity_follows_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = LLMClient("ops")
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        monkeypatch.chdir(tmp_path / folder)
        cache, key = client._cache_lookup({"llm.cache": True, "llm.cache_dir": "cache"}, KW)  # pyright: ignore[reportPrivateUsage]
        assert cache is not None and key is not None
        assert key not in cache
        cache[key] = folder
        if folder == "b":
            assert len(client._caches) == 2  # pyright: ignore[reportPrivateUsage]
    for cache in client._caches.values():  # pyright: ignore[reportPrivateUsage]
        cache.close()


def test_old_default_is_not_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    old = tmp_path / ".llm_cache"
    old.mkdir(mode=0o755)
    (old / "sentinel").write_text("synthetic")
    client = LLMClient("ops")
    cache, _ = client._cache_lookup({"llm.cache": True}, KW)  # pyright: ignore[reportPrivateUsage]
    assert cache is not None
    try:
        assert list(old.iterdir()) == [old / "sentinel"]
        assert Path(cache.directory).name == ".blue-data-ops-cache"
    finally:
        cache.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership")
def test_foreign_owner_refused_without_chown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from blue_data_ops.llm import client as module

    path = tmp_path / "private"
    path.mkdir(mode=0o700)
    original_stat = os.stat

    def foreign_owner(target: Any, *args: Any, **kwargs: Any) -> Any:
        info = original_stat(target, *args, **kwargs)
        if os.fspath(target) == str(path):
            return SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid + 1)
        return info

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "stat", foreign_owner)
        with pytest.raises(LLMError):
            LLMClient("ops")._cache_lookup(  # pyright: ignore[reportPrivateUsage]
                {"llm.cache": True, "llm.cache_dir": str(path)}, KW
            )
    assert list(path.iterdir()) == []
    assert path.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX cache privacy")
@pytest.mark.parametrize("location", ["$CACHE_TEST_LOCATION", "~/cache"])
def test_expanded_cache_path_is_validated_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CACHE_TEST_LOCATION", str(tmp_path / "shared-cache"))
    monkeypatch.setenv("HOME", str(tmp_path / "host-home"))
    expanded = (
        tmp_path / "host-home" / "cache" if location.startswith("~") else tmp_path / "shared-cache"
    )
    expanded.mkdir(parents=True)
    expanded.chmod(0o755)
    with pytest.raises(LLMError) as error:
        LLMClient("ops")._cache_lookup(  # pyright: ignore[reportPrivateUsage]
            {"llm.cache": True, "llm.cache_dir": location}, KW
        )
    assert error.value.retryable is False
    assert list(expanded.iterdir()) == []


@pytest.mark.parametrize("location", ["literal$", "literal$RUNTIME_UNSET", "$CACHE_DOLLAR_ROOT"])
def test_literal_dollars_stable_through_backend_expansion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RUNTIME_UNSET", raising=False)
    monkeypatch.setenv("CACHE_DOLLAR_ROOT", str(tmp_path / "expanded$RUNTIME_UNSET"))
    client = LLMClient("ops")
    props = {"llm.cache": True, "llm.cache_dir": location}
    cache, key = client._cache_lookup(props, KW)  # pyright: ignore[reportPrivateUsage]
    assert cache is not None and key is not None
    try:
        assert "$" in cache.directory
        assert Path(cache.directory).stat().st_mode & 0o777 == 0o700
        cache[key] = "ops"
        reused, _ = client._cache_lookup(props, KW)  # pyright: ignore[reportPrivateUsage]
        assert reused is cache and cache[key] == "ops"
    finally:
        cache.close()


@pytest.mark.parametrize("reuse", [False, True])
def test_changed_second_expansion_refused_before_backend_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reuse: bool
) -> None:
    path = tmp_path / "private$RUNTIME_INNER"
    path.mkdir(mode=0o700)
    unsafe = tmp_path / "private-unsafe"
    unsafe.mkdir(mode=0o755)
    client = LLMClient("ops")
    monkeypatch.delenv("RUNTIME_INNER", raising=False)
    props = {"llm.cache": True, "llm.cache_dir": "$RUNTIME_OUTER"}
    monkeypatch.setenv("RUNTIME_OUTER", str(path))
    cache = None
    if reuse:
        cache, _ = client._cache_lookup(props, KW)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setenv("RUNTIME_INNER", "-unsafe")
    try:
        with pytest.raises(LLMError) as error:
            client._cache_lookup(props, KW)  # pyright: ignore[reportPrivateUsage]
        assert error.value.code == "bad_cache_dir" and not error.value.retryable
        assert "llm.cache_dir" in str(error.value) and "0700" in str(error.value)
        assert "private" + "$RUNTIME_INNER" not in str(error.value)
        assert list(unsafe.iterdir()) == []
    finally:
        if cache is not None:
            cache.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX cache privacy")
def test_unsafe_symlink_target_refused(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o755)
    link = tmp_path / "link"
    link.symlink_to(unsafe, target_is_directory=True)
    with pytest.raises(LLMError, match="llm.cache_dir"):
        LLMClient("ops")._cache_lookup(  # pyright: ignore[reportPrivateUsage]
            {"llm.cache": True, "llm.cache_dir": str(link)}, KW
        )
    assert list(unsafe.iterdir()) == []


def test_private_symlink_and_expanded_paths_share_canonical_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(private, target_is_directory=True)
    monkeypatch.setenv("CACHE_PRIVATE_ROOT", str(private))
    client = LLMClient("ops")
    first = None
    try:
        for path in [str(private), str(link), "$CACHE_PRIVATE_ROOT"]:
            cache, _ = client._cache_lookup(  # pyright: ignore[reportPrivateUsage]
                {"llm.cache": True, "llm.cache_dir": path}, KW
            )
            if first is None:
                first = cache
            assert cache is first
    finally:
        if first is not None:
            first.close()
