"""平台登录态健康检查 + 失效告警（scout 抓数稳定化 · 2026-06-09）。

痛点：cookie 悄悄失效 → 每日 metric_ingest 静默落空数据 → 分析面陈旧/空，老板蒙在鼓里。
根因：`/fetch/auth-status` 只查 cookie **存在性**(has_cookies)，查不出"cookie 在但服务端已过期"。

本模块对每平台跑 1 个**轻量真取数探针**（executor 自动回放 catalog verified params），看
verdict：`FAIL_AUTH` = 登录态真失效。失效则：
  1. `dispatcher.broadcast` 告警（企微/应用内/浏览器推，未配企微也走应用内）；
  2. 把 `mvp_session.health` 写真（ok / stale / unknown），桌面「平台登录」面板与 get_session 反映现状。

只对 `FAIL_AUTH` 告警——端点漂移/网络抖动(FAIL_OTHER) 标 unknown 但**不打扰老板**（不喊狼）。
"""
from __future__ import annotations

import logging

from app.database import get_pool
from app.services.notification.dispatcher import dispatcher

log = logging.getLogger(__name__)

# 探针端点：每平台挑一个已验证、需登录态的轻量端点（取自 metric_ingest 每日 INGEST 集，必为 verified）
_PROBE = {
    "yuntu": "yuntu.getaudienceassetstructure",
    "compass": "compass.flow_overview_card",
    "doudian": "doudian.homepage",
}
# fetch 平台名 → mvp_session.platform（与 live_fetch._PLATFORM_SESSION 对齐，禁漂移）
_SESSION_NAME = {"yuntu": "yuntu", "compass": "douyin_compass", "doudian": "douyin_shop_admin"}
_PLATFORM_CN = {"yuntu": "巨量云图", "compass": "抖音罗盘", "doudian": "抖店后台"}

_ALIVE = ("PASS", "PASS_NODATA")


async def check_auth_health(executor) -> dict:
    """逐平台探针真取数判活，写 mvp_session.health，对 FAIL_AUTH 告警。返回汇总。"""
    results: dict[str, dict] = {}
    dead: list[str] = []  # 仅 cookie 真失效(FAIL_AUTH)

    for platform, endpoint in _PROBE.items():
        try:
            r = await executor.fetch(platform, endpoint, None, None)
            verdict = (r or {}).get("verdict", "FAIL_OTHER")
        except Exception as exc:
            verdict = "FAIL_OTHER"
            log.warning("auth_health: %s 探针异常: %s", platform, exc)
        alive = verdict in _ALIVE
        auth_dead = verdict == "FAIL_AUTH"
        results[platform] = {"verdict": verdict, "alive": alive}
        if auth_dead:
            dead.append(platform)
        # ok = 活；stale = cookie 死；unknown = 探针非 auth 失败(端点漂移/网络)，不当失效
        health = "ok" if alive else ("stale" if auth_dead else "unknown")
        await _update_session_health(_SESSION_NAME.get(platform, platform), health, verdict)

    if dead:
        names = "、".join(_PLATFORM_CN.get(p, p) for p in dead)
        body = (f"{names} 登录态已失效——去桌面「平台登录」面板扫码重登，"
                f"否则今天的数据不会更新（分析面会显陈旧/空）。")
        try:
            await dispatcher.broadcast(
                "warn", "omni 平台登录态失效", body, meta={"stale": dead},
            )
            log.warning("auth_health: 检出失效 %s，已告警", dead)
        except Exception as exc:
            log.warning("auth_health: broadcast 失败: %s", exc)
    else:
        log.info("auth_health: 三平台登录态正常 %s", {p: v["verdict"] for p, v in results.items()})

    return {"ok": True, "checked": list(_PROBE.keys()), "results": results, "stale_auth": dead}


async def _update_session_health(session_platform: str, health: str, verdict: str) -> None:
    """写 mvp_session.health（复用现有列，无需 migration）。表无该平台行则跳过(不新建)。"""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE mvp_session
                   SET health=$2, notes=$3, updated_at=NOW()
                   WHERE platform=$1""",
                session_platform, health, f"auth_health 探针: {verdict}",
            )
    except Exception as exc:
        log.warning("auth_health: 更新 mvp_session %s 失败: %s", session_platform, exc)
