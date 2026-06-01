"""scout-agent 测试共享 fixture。"""
import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _stub_yuntu_cookies(tmp_path, monkeypatch):
    """为 test_live_fetch 提供虚拟 cookies 文件。
    FakeExecutor 用 sessions_root=/tmp/nonexistent；
    这里把该路径下的 yuntu/storage_state.json 建好，
    使 has_cookies() 返回 True（测试只验证 _run_in_page 被调用，不验证真实 cookie）。
    """
    cookies_dir = Path("/tmp/nonexistent/yuntu")
    cookies_dir.mkdir(parents=True, exist_ok=True)
    cookies_file = cookies_dir / "storage_state.json"
    if not cookies_file.exists():
        cookies_file.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
