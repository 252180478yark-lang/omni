from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPERS = (
    ROOT / "services" / "knowledge-engine" / "scripts" / "save_cookies.py",
    ROOT / "scripts" / "set_yuntu_cookies.py",
)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_cookie_helpers_have_no_embedded_secret_blob() -> None:
    for path in HELPERS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assigned = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert "COOKIE_STR" not in assigned
        long_literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and len(node.value) > 512
        ]
        assert long_literals == []


def test_direct_helper_requires_repository_external_secret_reference(tmp_path: Path) -> None:
    helper = load_module(HELPERS[0], "test_save_cookie_reference")
    inside = ROOT / "tests" / "fixture-cookie-secret.txt"
    with pytest.raises(helper.SecretReferenceError, match="outside the repository"):
        helper.external_file(inside, purpose="secret-file")
    relative = Path("fixture-cookie-secret.txt")
    with pytest.raises(helper.SecretReferenceError, match="must be absolute"):
        helper.external_file(relative, purpose="secret-file")

    outside = tmp_path / "cookie-reference.txt"
    outside.write_text("alpha=" + "x" * 32, encoding="utf-8")
    assert helper.external_file(outside, purpose="secret-file") == outside.resolve()


def test_direct_helper_parses_without_echoing_values_and_writes_private_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    helper = load_module(HELPERS[0], "test_save_cookie_storage")
    canary = "sensitive-" + "x" * 24
    cookies = helper.parse_cookie_secret(f"alpha={canary}; beta=value")
    assert [item["name"] for item in cookies] == ["alpha", "beta"]
    output = tmp_path / "auth-state.json"
    helper.write_auth_state(output, cookies)
    assert output.is_file()
    if os.name != "nt":
        assert output.stat().st_mode & 0o077 == 0
    assert canary not in capsys.readouterr().out


def test_api_helper_accepts_only_local_secret_destination(tmp_path: Path) -> None:
    helper = load_module(HELPERS[1], "test_set_cookie_reference")
    assert helper.local_base_url("http://127.0.0.1:8002/api/v1/knowledge").startswith("http://127.0.0.1")
    with pytest.raises(helper.CookieImportError, match="local host"):
        helper.local_base_url("https://example.invalid/api")
    with pytest.raises(helper.CookieImportError, match="credentials or query"):
        helper.local_base_url("http://localhost:8002/api?token=hidden")

    outside = tmp_path / "cookie-reference.json"
    outside.write_text(
        '{"cookies":[{"name":"alpha","value":"' + "x" * 32 + '"}]}',
        encoding="utf-8",
    )
    assert helper.external_secret_file(outside) == outside.resolve()
    parsed = helper.parse_cookie_secret(outside.read_text(encoding="utf-8"))
    assert len(parsed) == 1
    assert parsed[0]["name"] == "alpha"
