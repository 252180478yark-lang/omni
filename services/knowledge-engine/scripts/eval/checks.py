"""黄金集回归 · 确定性检查层（零 token）。

两个来源：
1. 收割 tool 自带 validation_warnings（portrait 标记配额闸 / brief 结构+禁用词 /
   creative_pack metrics_json 后端反算）—— run_eval 从 tool 返回结果里直接取，
   本模块的 harvest_tool_warnings 负责按 tool 摘对位置。
2. 自补检查（本模块实现）：
   - _BANNED_WORDS（复用 app.mcp.tools.portrait_brief 单一来源，防漂移）+ AI 套话扫描
   - 各 tool 结构必备节
   - director_brief 第 5 部分形态检查：无分镜三件套 / 字数 >= 秒×25 / 时间戳贯穿

fatal 判定（直接判 0 跳过 judge 省 token）：
- 输出为空或过短（< 200 字）
- 结构必备节缺 >= 2 个（结构性塌方）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_KE_ROOT = _HERE.parents[1]  # 容器内 /app；host 上 services/knowledge-engine
for _p in (str(_KE_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 复用线上同一份禁用词清单（单一来源，改 portrait_brief 这边自动跟上）
from app.mcp.tools.portrait_brief import _BANNED_WORDS  # noqa: E402

# AI 套话（CLAUDE.md 反 AI 腔铁律 + anti_ai_voice.md 摘的裸子串安全子集）
_AI_CLICHES = [
    "赋能", "打通", "抢占心智", "一站式", "极致体验",
    "综上所述", "值得注意的是", "不难发现", "总而言之",
    "作为AI", "作为人工智能", "我理解您的需求", "希望对您有帮助",
]

# 各 tool 结构必备节（substring 检查；以各 tool 的 system prompt 为准）
REQUIRED_SECTIONS: dict[str, list[str]] = {
    # generate_brief.system.md 要求的 5 个二级标题段
    "generate_brief": ["核心卖点", "目标人群", "主场景", "文案钩子", "拍摄分镜建议"],
    # selling_points_matrix.system.md 的 5 部分
    "generate_selling_points_matrix": ["第 0 部分", "第 1 部分", "第 2 部分", "第 3 部分", "第 4 部分"],
    # audience_portrait.system.md 的 5 部分
    "generate_audience_portrait": ["第 0 部分", "第 1 部分", "第 2 部分", "第 3 部分", "第 4 部分"],
    # director_brief：结构检查由 tool 自带 _validate_brief 收割，这里不重复
    "generate_director_brief": [],
    # creative_pack video_*：分镜 + 钩子 + metrics_json 三个硬存在
    "generate_creative_pack": ["分镜", "钩子", "metrics_json"],
}

_MIN_OUTPUT_CHARS = 200


# ---------- 收割 tool 自带 warnings ----------

def harvest_tool_warnings(tool: str, result: dict) -> list[str]:
    """从 tool 返回结构里摘 validation_warnings（各 tool 位置不同）。"""
    r = (result or {}).get("result") or {}
    if tool in ("generate_audience_portrait", "generate_creative_pack"):
        return list(r.get("validation_warnings") or [])
    if tool == "generate_director_brief":
        variants = r.get("variants") or []
        out: list[str] = []
        for i, v in enumerate(variants):
            for w in (v or {}).get("validation_warnings") or []:
                out.append(f"[variant {i}] {w}" if len(variants) > 1 else w)
        return out
    # generate_brief / matrix 无自带 warnings
    return []


# ---------- 自补：禁用词 + AI 套话 ----------

def scan_banned_words(md: str) -> list[str]:
    """_BANNED_WORDS + AI 套话扫描。'治愈系'白名单豁免（同 portrait_brief._validate_brief）。"""
    warnings: list[str] = []
    hits = [w for w in _BANNED_WORDS if w in md]
    if "治愈" in hits and not re.search(r"治愈(?!系)", md):
        hits.remove("治愈")
    if hits:
        warnings.append(f"⚠ 命中禁用词：{hits}")
    cliche_hits = [w for w in _AI_CLICHES if w in md]
    if cliche_hits:
        warnings.append(f"⚠ 命中 AI 套话：{cliche_hits}")
    return warnings


# ---------- 自补：结构必备节 ----------

def check_required_sections(tool: str, md: str) -> tuple[list[str], int]:
    """返回 (warnings, 缺节数)。"""
    missing = [s for s in REQUIRED_SECTIONS.get(tool, []) if s not in md]
    warnings = [f"⚠ 缺结构必备节「{s}」" for s in missing]
    return warnings, len(missing)


# ---------- 自补：director_brief 第 5 部分形态 ----------

_PART5_RE = re.compile(
    r"^#{1,6}[^\n]*第\s*5\s*部分(.*?)(?=^#{1,6}[^\n]*(?:自检|第\s*6\s*部分)|\Z)",
    re.S | re.M,
)
# 时间戳形态：0-15s / 12s / 30 秒 / 00:05
_TIMESTAMP_RE = re.compile(r"\d{1,3}\s*[-–~至]\s*\d{1,3}\s*[sS秒]|\d{1,3}\s*[sS秒]|\d{1,2}:\d{2}")
_DURATION_RE = re.compile(r"(\d{1,3})\s*[sS秒]")
_SHOT_LIST_RE = re.compile(r"(?:镜头|分镜)\s*\d+\s*[:：]")


def check_director_part5(md: str, *, include_ai_mapping: bool = True) -> list[str]:
    """形态铁律：一大段连续故事描述（非分镜三件套）/ 字数下限 秒×25 / 时间戳贯穿。"""
    if not include_ai_mapping:
        return []
    m = _PART5_RE.search(md)
    if not m:
        # 缺第 5 部分本身由 tool _validate_brief 报，这里不重复
        return []
    part5 = m.group(1)
    warnings: list[str] = []

    # 1) 三件套 / 分镜表结构检测
    table_lines = [l for l in part5.splitlines() if re.match(r"^\s*\|.+\|\s*$", l)]
    if len(table_lines) >= 3:
        warnings.append("⚠ 第 5 部分出现 markdown 表格（疑似分镜三件套）——铁律要求一大段连续故事描述")
    if len(_SHOT_LIST_RE.findall(part5)) >= 3:
        warnings.append("⚠ 第 5 部分出现「镜头 N：/分镜 N：」列表结构（疑似三件套）——应织进连续叙事")
    if "景别" in part5 and "运镜" in part5 and len(table_lines) >= 1:
        warnings.append("⚠ 第 5 部分含「景别/运镜」表格字段——疑似传统分镜表，违反形态铁律")

    # 2) 时间戳贯穿（>= 3 处）
    ts_n = len(_TIMESTAMP_RE.findall(part5))
    if ts_n < 3:
        warnings.append(f"⚠ 第 5 部分时间戳仅 {ts_n} 处（< 3），未做到「时间戳贯穿」")

    # 3) 字数下限 = 秒 × 25（时长取第 5 部分出现的最大秒数，cap 120 防误抓）
    secs = [int(x) for x in _DURATION_RE.findall(part5) if 0 < int(x) <= 120]
    if secs:
        duration = max(secs)
        # 字数 = 去掉提示词块标题行/空白后的字符数
        body = re.sub(r"^#{1,6}[^\n]*$", "", part5, flags=re.M)
        n_chars = len(re.sub(r"\s", "", body))
        required = duration * 25
        if duration >= 5 and n_chars < required:
            warnings.append(
                f"⚠ 第 5 部分字数 {n_chars} < 时长 {duration}s × 25 = {required}（Seedance 档案字数下限）——细节密度不够"
            )
    else:
        warnings.append("⚠ 第 5 部分识别不到任何时长/秒数标记——无法核字数下限，疑似没按档案写")
    return warnings


# ---------- 总入口 ----------

def run_checks(tool: str, output_md: str, tool_result: dict, *, args: dict | None = None) -> dict:
    """确定性层总入口。返回 {fatal, fatal_reasons, warnings, harvested}。"""
    args = args or {}
    fatal_reasons: list[str] = []
    warnings: list[str] = []

    md = (output_md or "").strip()
    if len(md) < _MIN_OUTPUT_CHARS:
        fatal_reasons.append(f"输出过短（{len(md)} 字 < {_MIN_OUTPUT_CHARS}），视为生成失败")

    sec_warnings, missing_n = check_required_sections(tool, md)
    warnings += sec_warnings
    if missing_n >= 2:
        fatal_reasons.append(f"结构必备节缺 {missing_n} 个（>= 2），结构性塌方")

    warnings += scan_banned_words(md)

    if tool == "generate_director_brief":
        warnings += check_director_part5(
            md, include_ai_mapping=bool(args.get("include_ai_mapping", True))
        )

    harvested = harvest_tool_warnings(tool, tool_result)

    return {
        "fatal": bool(fatal_reasons),
        "fatal_reasons": fatal_reasons,
        "warnings": warnings,
        "harvested": harvested,
    }
