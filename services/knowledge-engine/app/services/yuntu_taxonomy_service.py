"""巨量云图标签体系 确定性查询 service（2026-06-08 修 "agent 答不全" 根因）。

老板痛点：在客户端问「树状输出巨量云图标签体系 / 圈包标签 / 提纯用哪些标签」时，agent 去
**硬读 `docs/yuntu-taxonomy/yuntu_taxonomy_full_v2.md`（582 行 / 30k+ token）撞 Read 上限**，
只能分页翻、翻不全→答不全不准；光靠 KB 的 RAG 又只返碎片。

根因修法（§1.2 能力即工具）：把标签体系做成**确定性可查工具**——直接从 SoT（两份画像 CSV
+ dump v1 菜单骨架常量）算出结构化树，按 overview / dimension / search / section 返回，agent
一把取到要的那块（完整、不啃大文件、不靠 lossy 召回）。与 build_yuntu_taxonomy_full.py 同源
数据（config/audience 的 CSV），口径一致。
"""
from __future__ import annotations

import collections
import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 画像 CSV 目录（与 audience_pack_service 同源；bind-mount 进容器 /app/config/audience/）
_AUDIENCE_DIR: Path = Path(__file__).resolve().parents[2] / "config" / "audience"
_CSV_FILES = ["baseline_a4.csv", "diyu_xunwei.csv"]

# 标签类型 → (后台菜单路径, 入口)。入口 custom=自定义人群直接勾 / factory=数据工厂标签工厂建标签。
# 与 build_yuntu_taxonomy_full.py 的 DIM_UI_PATH 同步。
_DIM_UI: dict[str, tuple[str, str]] = {
    "预测性别": ("自定义人群 > 用户属性 > 基础属性 > 预测性别", "custom"),
    "预测年龄段": ("自定义人群 > 用户属性 > 基础属性 > 预测年龄", "custom"),
    "预测消费能力": ("自定义人群 > 用户属性 > 基础属性 > 消费属性 > 预测消费能力", "custom"),
    "预测职业": ("自定义人群 > 用户属性 > 基础属性 > 预测职业", "custom"),
    "预测人生阶段": ("自定义人群 > 用户属性 > 基础属性 > 预测人生阶段", "custom"),
    "八大消费群体": ("自定义人群 > 用户属性 > 基础属性 > 八大消费群体", "custom"),
    "手机价格": ("自定义人群 > 用户属性 > 基础属性 > 设备属性（手机价格档位）", "custom"),
    "手机品牌": ("自定义人群 > 用户属性 > 基础属性 > 设备属性（手机品牌）", "custom"),
    "地域分布": ("自定义人群 > 用户属性 > 地域属性 > 地域分布（按省市）", "custom"),
    "城市": ("自定义人群 > 用户属性 > 地域属性 > 地域分布（按省市，城市级）", "custom"),
    "城市等级": ("自定义人群 > 用户属性 > 地域属性 > 地域分布（按城市级别）", "custom"),
    "电商消费金额": ("自定义人群 > 用户属性 > 基础属性 > 电商消费金额", "custom"),
    "电商消费频次": ("自定义人群 > 用户属性 > 基础属性 > 电商消费频次", "custom"),
    "抖音活跃用户": ("自定义人群 > 兴趣偏好 > 行为偏好 > 抖音产品活跃用户（抖音端）", "custom"),
    "头条活跃用户": ("自定义人群 > 兴趣偏好 > 行为偏好 > 抖音产品活跃用户（头条端）", "custom"),
    "西瓜活跃用户": ("自定义人群 > 兴趣偏好 > 行为偏好 > 抖音产品活跃用户（西瓜端）", "custom"),
    "火山活跃用户": ("自定义人群 > 兴趣偏好 > 行为偏好 > 抖音产品活跃用户（火山端）", "custom"),
    "头条用户阅读兴趣分类": ("自定义人群 > 兴趣偏好 > 内容偏好 > 头条用户阅读兴趣", "custom"),
    "抖音视频观看兴趣分类": ("自定义人群 > 兴趣偏好 > 内容偏好 > 抖音视频观看分类", "custom"),
    "抖音视频观看兴趣分类v2": ("自定义人群 > 兴趣偏好 > 内容偏好 > 抖音视频观看分类(v2新版一级)", "custom"),
    "西瓜视频观看兴趣分类": ("自定义人群 > 兴趣偏好 > 内容偏好 > 西瓜视频观看兴趣", "custom"),
    "触点互动偏好": ("自定义人群 > 触点场景圈人 > 触点互动偏好（公域触点）", "custom"),
    "美妆行业特色人群": ("自定义人群 > 行业品类兴趣 > 行业特色人群 > 美妆行业特色人群", "custom"),
    # 数据工厂标签工厂的海量树（自定义人群创建页是占位符，必须走入口 B 建商品人群标签）
    "电商品类成交偏好": ("数据工厂 > 标签工厂 > 新建商品人群标签 > 电商品类成交偏好", "factory"),
    "电商品牌成交偏好": ("数据工厂 > 标签工厂 > 新建商品人群标签 > 电商品牌成交偏好", "factory"),
}
# 哪些维度的标签值自带层级分隔符（一级<sep>二级）
_HIER_SEP: dict[str, str] = {
    "电商品类成交偏好": "-",
    "抖音视频观看兴趣分类": "_",
    "触点互动偏好": "-",
}
# 维度显示名（友好）
_DIM_CN: dict[str, str] = {
    "电商品类成交偏好": "电商品类成交偏好（一级>二级树）",
    "电商品牌成交偏好": "电商品牌成交偏好（品牌）",
    "抖音视频观看兴趣分类": "抖音视频观看分类（一级>二级树）",
    "触点互动偏好": "触点互动偏好（端>广告位树）",
}

# 两大入口
_ENTRANCES = {
    "A_自定义人群": {
        "name": "A. 自定义人群（直接勾）",
        "path": "云图 > 人群 > 人群列表 > 新建人群",
        "what": "6 大维度现成档位标签（年龄/性别/八大群体/兴趣/地域/触点…）直接勾",
    },
    "B_数据工厂标签工厂": {
        "name": "B. 数据工厂·标签工厂（先造再引用）",
        "path": "云图 > 数据工厂 > 标签工厂 > 新建标签",
        "what": "把行为信号（搜/看/买）+ 电商品类(140一级/975二级)/品牌(1109) 海量树包成标签再回 A 引用",
    },
}
# dump v1 + 标签工厂 Playbook 的常量段（CSV 里没有、但圈包必须知道的）
_CONST_SECTIONS = {
    "标签工厂字段全集": {
        "标签类型": "内容标签 / 人群标签(内容人群·商品人群·搜索人群) / 达人标签",
        "数据源端": "抖音 / 今日头条 / 西瓜视频 / 抖音火山版（多选，食品默认抖音）",
        "用户行为": "内容(有效播放·点赞·收藏·评论·转发) / 商品(曝光·点击·浏览·加购·购买) / 搜索",
        "频次时间窗": "≥1/≥3/≥6 次 × 近 7/14/30/60/90 天",
        "匹配方式": "规则匹配(含词即算) / 内容理解(语义近似，默认推荐)",
        "命名规范": "<人群核心词>-<标签类型>-<时间窗>-<频次>，如 有机调味-商品购买-30D-≥1次",
    },
    "行业特色人群": {
        "食饮（调味品最相关）": ["酒桌江湖排面族", "食补护家精算师", "高速职场补给官", "轻享悦己品质家",
                          "百尝零食大玩家", "人间精致赏味王", "清醒务实生活家", "成分美学品鉴官"],
        "健康": ["满电生活合伙人", "内外兼修美学家", "儿童成长补给派", "家庭健康守门人", "东方养生追随派（等11类）"],
        "美妆": ["合群拔草人", "好物狂想家", "格调鉴赏家", "悦己质享派", "惠选生活家", "理性刚需派", "美潮文艺咖"],
        "点哪里": "自定义人群 > 行业品类兴趣 > 行业特色人群 > 选对应行业",
    },
    "固定清单": {
        "八大消费群体(固定8)": "小镇青年/小镇中老年/Z世代/都市蓝领/精致妈妈/新锐白领/资深中产/都市银发",
        "IP偏好(固定5类)": "明星/电影/电视剧/综艺/动漫偏好（具体名在后台 IP偏好 搜索框看，无独立短剧类目）",
        "预测人生阶段": "单身/二人世界/家有儿女",
    },
    "提纯三刀法": {
        "第一刀_付得起": "∩ 八大消费群体(资深中产/新锐白领/精致妈妈) + 预测消费能力(中/高) + 电商消费金额(高档位) + 手机价格(≥3000)",
        "第二刀_需求相邻": "∩ 电商品类成交偏好(粮油米面南北干货调味品>食用油调味油/调味品果酱沙拉、奶粉辅食营养品零食>婴童调味品、保健食品、水果蔬菜、肉蛋低温制品) 或 品牌",
        "第三刀_内容亲和": "∩ 抖音视频观看分类(美食>制作美食/日常美食展示、生活>生活探店、亲子>母婴)",
        "组合": "原始宽包 ∩ 第一刀 ∩ 第二刀 ∩ 第三刀 − 排除已购老客 = 高潜核心包；每砍一刀看一次预计覆盖人数",
    },
}

_cache: dict | None = None


def _load_union() -> dict[str, list[str]]:
    """读 config/audience 的画像 CSV，union 每个标签类型的全量标签值（去重保序）。带缓存。"""
    global _cache
    if _cache is not None:
        return _cache
    union: dict[str, list[str]] = collections.defaultdict(list)
    seen: dict[str, set] = collections.defaultdict(set)
    for fn in _CSV_FILES:
        p = _AUDIENCE_DIR / fn
        if not p.exists():
            continue
        with open(p, encoding="utf-8-sig") as fh:
            r = csv.reader(fh)
            next(r, None)
            for row in r:
                if not row or not row[0].strip():
                    continue
                lt, val = row[0].strip(), row[1].strip()
                if val and val not in seen[lt]:
                    seen[lt].add(val)
                    union[lt].append(val)
    _cache = dict(union)
    return _cache


def _split_tree(values: list[str], sep: str) -> "collections.OrderedDict[str, list[str]]":
    tree: "collections.OrderedDict[str, list[str]]" = collections.OrderedDict()
    for v in values:
        if sep in v:
            a, b = v.split(sep, 1)
            tree.setdefault(a, [])
            if b not in tree[a]:
                tree[a].append(b)
        else:
            tree.setdefault(v, [])
    return tree


def overview() -> dict:
    """标签体系总览：两大入口 + 各维度（名/计数/入口/是否树）+ 常量段索引。小巧，给 agent 先看。"""
    union = _load_union()
    dims = []
    for lt, vals in union.items():
        ui, entrance = _DIM_UI.get(lt, ("（未映射菜单路径，后台搜）", "custom"))
        sep = _HIER_SEP.get(lt)
        if sep:
            tree = _split_tree(vals, sep)
            n_l1, n_l2 = len(tree), sum(len(x) for x in tree.values())
            shape = f"{n_l1} 一级 / {n_l2} 二级（树）"
        else:
            shape = f"{len(vals)} 项（平铺）"
        dims.append({"dimension": lt, "entrance": entrance, "ui_path": ui, "shape": shape, "count": len(vals)})
    return {
        "ok": True,
        "entrances": _ENTRANCES,
        "dimensions": dims,
        "const_sections": list(_CONST_SECTIONS.keys()),
        "usage": "要某维度全量→query_yuntu_taxonomy(dimension='电商品类成交偏好')；"
                 "找某标签在哪→search='食用油'；要字段/行业特色/提纯等→section='提纯三刀法'。",
        "note": "确定性来自画像 CSV(SoT) + dump v1 常量，完整不截断、不啃大文件、不走 lossy RAG。",
    }


def get_dimension(name: str) -> dict:
    """某维度全量：树（一级>二级）或平铺值 + 菜单路径 + 入口。"""
    union = _load_union()
    # 容错：精确名 / 子串
    if name not in union:
        cand = [lt for lt in union if name in lt or lt in name]
        if len(cand) == 1:
            name = cand[0]
        elif not cand:
            return {"ok": False, "error": "dimension_not_found", "available": list(union.keys()),
                    "hint": f"没这个维度 {name!r}，看 available 选一个或用 search。"}
        else:
            return {"ok": False, "error": "ambiguous", "candidates": cand}
    vals = union[name]
    ui, entrance = _DIM_UI.get(name, ("（未映射，后台搜）", "custom"))
    sep = _HIER_SEP.get(name)
    out: dict = {"ok": True, "dimension": name, "cn": _DIM_CN.get(name, name),
                 "entrance": entrance, "ui_path": ui, "total_values": len(vals)}
    if sep:
        tree = _split_tree(vals, sep)
        out["is_tree"] = True
        out["l1_count"] = len(tree)
        out["l2_count"] = sum(len(x) for x in tree.values())
        out["tree"] = {k: v for k, v in tree.items()}
    else:
        out["is_tree"] = False
        out["values"] = vals
    return out


def search_tag(keyword: str, limit: int = 60) -> dict:
    """跨所有维度搜标签，返命中标签 + 完整层级路径 + 维度 + 菜单路径（圈包/提纯定位用）。"""
    kw = (keyword or "").strip()
    if not kw:
        return {"ok": False, "error": "empty_keyword"}
    union = _load_union()
    hits = []
    for lt, vals in union.items():
        ui, entrance = _DIM_UI.get(lt, ("（未映射）", "custom"))
        sep = _HIER_SEP.get(lt)
        for v in vals:
            if kw not in v:
                continue
            if sep and sep in v:
                a, b = v.split(sep, 1)
                full = f"{a} > {b}"
            else:
                full = v
            hits.append({"dimension": lt, "entrance": entrance, "tag": v,
                         "hierarchy": full, "ui_path": ui})
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    return {"ok": True, "keyword": kw, "count": len(hits), "hits": hits,
            "truncated": len(hits) >= limit,
            "note": "命中标签的 hierarchy 是真实上下级，ui_path 是后台勾选路径；factory 入口要先在标签工厂建商品人群标签。"}


def get_section(key: str) -> dict:
    """取常量段（标签工厂字段全集 / 行业特色人群 / 固定清单 / 提纯三刀法）。"""
    if key not in _CONST_SECTIONS:
        return {"ok": False, "error": "section_not_found", "available": list(_CONST_SECTIONS.keys())}
    return {"ok": True, "section": key, "content": _CONST_SECTIONS[key]}


def query(dimension: str | None = None, search: str | None = None, section: str | None = None) -> dict:
    """统一入口：search > dimension > section > overview。"""
    try:
        if search:
            return search_tag(search)
        if dimension:
            return get_dimension(dimension)
        if section:
            return get_section(section)
        return overview()
    except Exception as exc:  # noqa: BLE001
        logger.exception("query_yuntu_taxonomy 失败")
        return {"ok": False, "error": f"failed: {exc}"}
