"""黄金集回归 · LLM-judge 层。

调用配方复刻 business_analysis_service._narrate 的 polish 路：
prompts.load/render（外置 config/prompts/eval_judge.{system,user}.md，热加载）
+ AIHubClient().chat（temperature=0.0, max_tokens=2000）。

输出严格 JSON：
{"dims": {"<维度名>": {"score": 1-5, "reason": "..."}},
 "vs_golden": "better|same|worse", "reason": "..."}

模型选择：tool_models.yaml 里有 `eval_judge` 条目就用它；
没有则代码内兜底 provider=gemini / model=gemini-3-flash-preview
（⚠️ 不改 tool_models.yaml——别的施工在并行改它；要换 judge 模型时
往 yaml 加 eval_judge 条目即可，本文件不用动）。
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_KE_ROOT = _HERE.parents[1]
for _p in (str(_KE_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.mcp import prompts  # noqa: E402
from app.mcp.model_config import _load_yaml  # noqa: E402
from app.services.ai_hub_client import AIHubClient  # noqa: E402

logger = logging.getLogger(__name__)

_RUBRICS_DIR = _KE_ROOT / "config" / "eval" / "rubrics"

# 喂 judge 的单段文本上限（golden/candidate 都很长，留足但防爆）
_MAX_DOC_CHARS = 18000


def _judge_model_cfg() -> dict:
    """yaml 有显式 eval_judge 条目才用；否则代码内兜底（不靠 __default__，按方案钉死）。"""
    try:
        raw = _load_yaml()
    except Exception:  # noqa: BLE001
        raw = {}
    if isinstance(raw, dict) and "eval_judge" in raw:
        return dict(raw["eval_judge"])
    return {"provider": "gemini", "model": "gemini-3-flash-preview",
            "temperature": 0.0, "max_tokens": 2000}


def load_rubric(tool: str) -> str:
    p = _RUBRICS_DIR / f"{tool}.md"
    if not p.exists():
        raise FileNotFoundError(f"rubric 不存在: {p}")
    return p.read_text(encoding="utf-8")


def _clip(text: str, limit: int = _MAX_DOC_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n…（超长截断，原文 {len(text)} 字）"


def _parse_judge_json(text: str) -> dict | None:
    """剥代码围栏 → 取首尾花括号区间 → json.loads。失败返 None。"""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(t[start:end + 1])
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("dims"), dict):
        return None
    return obj


async def judge_output(
    tool: str,
    *,
    input_summary: str,
    golden_md: str,
    candidate_md: str,
    det_warnings: list[str] | None = None,
) -> dict:
    """跑一次 judge。返回 {ok, dims, vs_golden, reason, avg_score, model, error?}。"""
    cfg = _judge_model_cfg()
    provider = cfg.get("provider", "gemini")
    model = cfg.get("model", "gemini-3-flash-preview")
    temperature = float(cfg.get("temperature", 0.0))
    max_tokens = int(cfg.get("max_tokens", 2000))

    rubric = load_rubric(tool)
    system = prompts.load("eval_judge.system")
    user = prompts.render(
        "eval_judge.user",
        tool=tool,
        rubric=rubric,
        input_summary=_clip(input_summary, 2000),
        golden=_clip(golden_md),
        candidate=_clip(candidate_md),
        det_warnings="\n".join(det_warnings or []) or "（无）",
    )

    client = AIHubClient(timeout=180.0)
    last_err = ""
    for attempt in (1, 2):  # JSON 解析失败重试一次
        try:
            resp = await client.chat(
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                provider=provider, model=model,
                temperature=temperature, max_tokens=max_tokens,
                # judge 输出严格 JSON，不注入 human voice 约束（会跟 JSON-only 指令打架）
                enforce_human_voice=False,
            )
            text = (
                ((resp.get("choices") or [{}])[0].get("message") or {}).get("content")
                or resp.get("text") or resp.get("content") or ""
            )
            obj = _parse_judge_json(text)
            if obj is None:
                last_err = f"judge 返回非严格 JSON（attempt {attempt}）: {text[:200]!r}"
                logger.warning(last_err)
                continue
            dims = obj.get("dims") or {}
            scores = [
                int(v.get("score")) for v in dims.values()
                if isinstance(v, dict) and isinstance(v.get("score"), (int, float))
            ]
            avg = round(sum(scores) / len(scores), 2) if scores else None
            return {
                "ok": True,
                "dims": dims,
                "vs_golden": obj.get("vs_golden"),
                "reason": obj.get("reason"),
                "avg_score": avg,
                "model": f"{provider}/{model}",
            }
        except Exception as exc:  # noqa: BLE001
            last_err = f"judge 调用失败（attempt {attempt}）: {type(exc).__name__}: {exc}"
            logger.warning(last_err)
    return {"ok": False, "error": last_err, "model": f"{provider}/{model}"}
