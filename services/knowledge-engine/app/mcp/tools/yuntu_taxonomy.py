"""巨量云图标签体系 确定性查询 MCP tool（2026-06-08 修 "agent 答不全" 根因）。

老板痛点：在客户端问「树状输出标签体系 / 圈包用哪些标签 / 提纯怎么收窄」时，agent 去硬读
582 行的 v2 字典大文件撞 Read token 上限、分页翻翻不全 → 答不全不准；KB 的 RAG 又只返碎片。

修法（§1.2 能力即工具）：query_yuntu_taxonomy 让 agent 一把取到**结构化、完整、不截断**的
标签体系（总览/按维度/搜标签/常量段），不啃大文件、不靠 lossy 召回。数据工具：确定性、不调
LLM、不返 trace、不走 Gate。逻辑全在 yuntu_taxonomy_service（与 build 脚本同源 CSV，禁漂移）。
"""
from __future__ import annotations

import logging

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import yuntu_taxonomy_service as svc

logger = logging.getLogger(__name__)


@tool_with_audit(mcp, require_approval=False)
async def query_yuntu_taxonomy(
    dimension: str | None = None,
    search: str | None = None,
    section: str | None = None,
) -> dict:
    """确定性查询巨量云图标签体系（圈包/提纯/答疑的标签 ground truth，完整不截断）。

    **为什么有这个 tool**：标签体系全量字典 582 行 30k+ token，直接 Read 会撞上限、翻不全；
    KB 的 RAG 召回只返碎片。本 tool 从 SoT（画像 CSV + dump v1 常量）确定性算出结构化标签体系，
    agent 一把取到要的那块——回答标签/圈包/提纯问题时**优先调它，别去硬读 v2 大文件、别靠 RAG**。

    参数（四选一，按需）：
    - 都不传 → **总览**：两大入口（自定义人群直接勾 / 数据工厂标签工厂建标签）+ 各维度
      （名/计数/入口/是否树）+ 常量段索引。先调这个看有啥，再下钻。
    - dimension='电商品类成交偏好' → 该维度**全量**：树（一级>二级，140/975）或平铺值
      + 后台菜单路径 + 入口。支持子串容错。
    - search='食用油' → 跨维度搜标签，返命中标签 + **真实层级路径**（如 粮油米面…>食用油调味油）
      + 维度 + 后台勾选路径。圈包/提纯定位"某标签在哪、怎么勾"用这个。
    - section='提纯三刀法' → 常量段：'标签工厂字段全集' / '行业特色人群' / '固定清单' / '提纯三刀法'。

    口径：数据来自 config/audience 的真实人群画像 CSV（反推一级+二级，后台最准颗粒度）+ dump v1
    菜单骨架；**只返真实抓到的标签，不虚构**；三级及季度微调需老板手动从标签工厂导出核对。

    老板话术触发：'树状输出标签体系' / '电商品类有哪些' / '食用油在哪个标签' /
    '圈包/提纯用哪些标签' / '标签工厂怎么填'。

    Returns（随参数不同）:
        总览 {ok, entrances, dimensions:[{dimension,entrance,ui_path,shape,count}], const_sections, usage}
        维度 {ok, dimension, entrance, ui_path, is_tree, tree|values, l1_count, l2_count}
        搜索 {ok, keyword, count, hits:[{dimension, tag, hierarchy, ui_path, entrance}]}
        常量 {ok, section, content}
    """
    result = svc.query(dimension=dimension, search=search, section=section)
    if result.get("ok"):
        mode = ("search" if search else "dimension" if dimension else "section" if section else "overview")
        logger.info("query_yuntu_taxonomy mode=%s dim=%s search=%s", mode, dimension, search)
    return result
