"""tool_models.yaml 加载 + 按 tool 名查模型配置（design doc §2.5）。

调用方式：
    from app.mcp.model_config import get_model_for_tool
    cfg = get_model_for_tool("compute_margin")
    # cfg = {"provider": "anthropic", "model": "claude-opus-4-7", "temperature": 0.0}

2026-06-12 加 local overlay（桌面「模型配置」面板的后端）：
- base `config/tool_models.yaml` 全是老板手写注释，**绝不重写**；
  运行时改模型走覆盖文件 `config/tool_models.local.yaml`（gitignore，不入库）
- 合并顺序：base 的 __default__ → base 的 keyed → local 的 keyed（最高优先）。
  逐 key 浅合并：local 只盖它写了的字段（provider/model/temperature/max_tokens），
  base 里的 prompts/size 等其余字段保留。
- base / local 都走 mtime 缓存（照 prompts.py 模式）：改文件即生效，不用重启。
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import yaml  # PyYAML; FastMCP 顺带带进来，未带则需 pip install pyyaml

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
CONFIG_PATH = _CONFIG_DIR / "tool_models.yaml"
LOCAL_CONFIG_PATH = _CONFIG_DIR / "tool_models.local.yaml"

_FALLBACK_DEFAULT: dict[str, Any] = {
    "provider": "anthropic", "model": "claude-sonnet-4-6", "temperature": 0.3,
}

# mtime 缓存：path str → (mtime, parsed dict)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def _load_file(path: Path) -> dict[str, Any]:
    """读一个 yaml 配置文件（mtime 缓存，文件改了自动重读；缺失/坏文件返 {}）。"""
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    key = str(path)
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        logger.warning("tool_models 配置读取失败（跳过）：%s", path, exc_info=True)
        return {}
    if not isinstance(data, dict):
        data = {}
    with _lock:
        _cache[key] = (mtime, data)
    return data


def _load_yaml() -> dict[str, Any]:
    """base 配置（doctor `_check_yaml` 也调它）。mtime 缓存：老板改 base 也即时生效。"""
    raw = _load_file(CONFIG_PATH)
    if not raw:
        return {"__default__": dict(_FALLBACK_DEFAULT)}
    return raw


def load_local_overrides() -> dict[str, dict[str, Any]]:
    """local overlay 全量（tool_name → 覆盖 dict）。只认 dict 形条目。"""
    data = _load_file(LOCAL_CONFIG_PATH)
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _write_local(data: dict[str, Any]) -> None:
    header = (
        "# tool_models.local.yaml —— 运行时覆盖文件（桌面「模型配置」面板写入，不入 git）\n"
        "# 优先级最高：同名 tool key 覆盖 base tool_models.yaml；删掉 key 即恢复 base。\n"
        "# 手改也行（mtime 热生效，不用重启）。base yaml 的老板注释这里不碰。\n"
    )
    text = header + yaml.safe_dump(
        data, allow_unicode=True, sort_keys=True, default_flow_style=False,
    )
    LOCAL_CONFIG_PATH.write_text(text, encoding="utf-8")
    with _lock:
        _cache.pop(str(LOCAL_CONFIG_PATH), None)  # 同秒写入也保证下次重读


def set_local_override(tool_name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """写/改 local overlay 的一个 key（其余 key 不动）。返回写后的全量 overlay。"""
    data = dict(load_local_overrides())
    data[tool_name] = cfg
    _write_local(data)
    logger.info("tool_models local override set: %s -> %s", tool_name, cfg)
    return data


def remove_local_override(tool_name: str) -> bool:
    """从 local overlay 删一个 key（恢复 base 生效值）。返回是否真删了。"""
    data = dict(load_local_overrides())
    if tool_name not in data:
        return False
    data.pop(tool_name)
    _write_local(data)
    logger.info("tool_models local override removed: %s", tool_name)
    return True


def get_model_for_tool(
    tool_name: str,
    *,
    _override_yaml: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按 tool 名取模型配置（合并后生效值）。

    合并顺序（逐 key 浅合并，后者覆盖前者）：
        base __default__ → base keyed → local keyed（最高优先）

    `_override_yaml` 仅供测试注入（注入时不叠 local overlay，保持测试隔离）。
    """
    raw = _override_yaml if _override_yaml is not None else _load_yaml()
    default = raw.get("__default__") or _FALLBACK_DEFAULT
    merged: dict[str, Any] = dict(default)
    keyed = raw.get(tool_name)
    if isinstance(keyed, dict):
        merged.update(keyed)
    if _override_yaml is None:
        local = load_local_overrides().get(tool_name)
        if local:
            merged.update(local)
    return merged
