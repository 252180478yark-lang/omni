"""综合经营分析结果的进程内缓存（桌面 AiAnalysisPanel 打开秒返，不必每次等 10-30s）。

KE 是单进程：cron(daily_pulse) 预热 + REST(/comprehensive) 读写共用同一 dict。
- 仅缓存 focus=None 的常规视图（focus 是临时关注点，不缓存）。
- 进程重启即清（首调重算，可接受）。
- TTL 6h：覆盖一个工作时段的重复打开；数据日更，过期后首调重算反映新数据。
  结果里带 as_of（数据日期）+ cached 标记，老板能判新鲜度。
不碰核心分析函数 generate_business_analysis（禁漂移：分析逻辑不变，缓存只是传输层）。
"""
from __future__ import annotations

import time

_CACHE: dict[str, tuple[float, dict]] = {}
TTL_S = 6 * 3600


def key(face: str, days: int, platform: str, polish: bool, focus: str | None) -> str:
    return f"{face}|{days}|{platform}|{int(bool(polish))}|{focus or ''}"


def get(k: str) -> dict | None:
    """命中且未过期返结果，否则 None。"""
    hit = _CACHE.get(k)
    if hit and (time.time() - hit[0]) < TTL_S:
        return hit[1]
    return None


def put(k: str, value: dict) -> None:
    _CACHE[k] = (time.time(), value)
