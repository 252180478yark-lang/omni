from pathlib import Path
import subprocess
import sys

import pytest


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.services.system_graph import canonical


def _broken_git(*_args: object, **_kwargs: object) -> str:
    raise subprocess.CalledProcessError(128, ["git", "rev-parse"])


def test_resolve_head_uses_runtime_allocation_commit_when_git_admin_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected = "a" * 40
    monkeypatch.setenv("OMNI_SOURCE_COMMIT", expected)
    monkeypatch.setattr(canonical, "git_output", _broken_git)

    assert canonical.resolve_commit(tmp_path) == expected


@pytest.mark.parametrize("ref", ["main", "HEAD~1", "refs/tags/release"])
def test_resolve_explicit_ref_never_uses_runtime_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ref: str
) -> None:
    monkeypatch.setenv("OMNI_SOURCE_COMMIT", "b" * 40)
    monkeypatch.setattr(canonical, "git_output", _broken_git)

    with pytest.raises(subprocess.CalledProcessError):
        canonical.resolve_commit(tmp_path, ref)


@pytest.mark.parametrize("value", ["", "not-a-commit", "c" * 39, "d" * 64])
def test_resolve_head_rejects_invalid_runtime_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
) -> None:
    monkeypatch.setenv("OMNI_SOURCE_COMMIT", value)
    monkeypatch.setattr(canonical, "git_output", _broken_git)

    with pytest.raises(subprocess.CalledProcessError):
        canonical.resolve_commit(tmp_path)


def test_blob_fallback_uses_git_canonical_hash_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.txt"
    source.write_text("hello\n", encoding="utf-8")
    monkeypatch.setattr(canonical, "git_output", _broken_git)

    assert canonical.blob_id(tmp_path, source) == "ce013625030ba8dba906f756967f9e9ca394464a"
