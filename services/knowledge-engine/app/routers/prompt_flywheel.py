"""Prompt 反馈飞轮 REST API。

所有端点均由 frontend BFF (`/api/omni/prompt/*`) 透传调用。

节点总览:
  GET  /api/v1/prompt/nodes                           — 仪表盘列表
  GET  /api/v1/prompt/nodes/{node_id}                 — 节点详情(规则+近期反馈)

反馈:
  POST /api/v1/prompt/feedback                        — 提交反馈(rating/complaint)
  PATCH /api/v1/prompt/feedback/{fb_id}               — 更新反馈
  POST /api/v1/prompt/feedback/{fb_id}/distill        — LLM 提炼规则草稿
  GET  /api/v1/prompt/feedback/{fb_id}                — 读取完整 prompt + output

规则:
  GET    /api/v1/prompt/rules                         — 列表(可按 node_id 过滤)
  POST   /api/v1/prompt/rules                         — 新建(手动或从 feedback 转化)
  PATCH  /api/v1/prompt/rules/{rule_id}               — 更新
  DELETE /api/v1/prompt/rules/{rule_id}               — 删除
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.services import prompt_rules as pr

router = APIRouter(prefix="/api/v1/prompt", tags=["prompt-flywheel"])


# ─── 节点 ───────────────────────────────────────────────

@router.get("/nodes")
async def list_nodes() -> dict:
    nodes = await pr.list_nodes()
    return {"code": 200, "message": "success", "data": {"nodes": nodes}}


@router.get("/nodes/{node_id}")
async def get_node(node_id: str) -> dict:
    detail = await pr.get_node_detail(node_id)
    if not detail:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="node not found")
    return {"code": 200, "message": "success", "data": detail}


# ─── 跨服务渲染规则（ad-review / news / video 等外部服务用）──

@router.post("/render-rules")
async def render_rules(payload: dict) -> dict:
    """返回指定节点当前启用规则的 prompt suffix，并自动更新 hit_count。

    供不在 knowledge-engine 进程内的外部服务（ad-review-service / news-aggregator /
    video-analysis / livestream-analysis）挂飞轮用。同时也被前端 BFF 使用（比如
    roundtable 主持人在前端拼 prompt）。

    Payload: {"node_id": "review.stage_a", "scope": {...} | null}
    Response: {"data": {"suffix": "..."}}   # 空字符串表示无规则
    """
    node_id = payload.get("node_id")
    if not node_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="node_id required")
    scope = payload.get("scope")
    suffix = await pr.render_rules_suffix(node_id, scope)
    return {"code": 200, "message": "success", "data": {"suffix": suffix}}


# ─── 反馈 ───────────────────────────────────────────────

@router.post("/feedback")
async def create_feedback(payload: dict) -> dict:
    node_id = payload.get("node_id")
    if not node_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="node_id required")

    fb_id = await pr.log_feedback(
        node_id=node_id,
        input_ref=payload.get("input_ref"),
        full_prompt=payload.get("full_prompt"),
        output=payload.get("output"),
        rating=payload.get("rating"),
        severity=payload.get("severity"),
        complaint=payload.get("complaint"),
    )
    if not fb_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="log failed")
    return {"code": 200, "message": "success", "data": {"id": fb_id}}


@router.patch("/feedback/{fb_id}")
async def patch_feedback(fb_id: str, payload: dict) -> dict:
    updated = await pr.update_feedback(
        fb_id,
        rating=payload.get("rating"),
        severity=payload.get("severity"),
        complaint=payload.get("complaint"),
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="feedback not found")
    # UUID/datetime 用 str 返回（下游 JSON 编码器会处理）
    return {"code": 200, "message": "success", "data": {"id": str(updated["id"])}}


@router.post("/feedback/{fb_id}/distill")
async def distill(fb_id: str) -> dict:
    try:
        draft = await pr.distill_feedback(fb_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    return {
        "code": 200,
        "message": "success",
        "data": {
            "draft": draft,  # None 表示 LLM 判定无可复用结论
        },
    }


@router.get("/feedback/{fb_id}")
async def get_feedback(fb_id: str) -> dict:
    fb = await pr.get_feedback(fb_id)
    if not fb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="feedback not found")
    return {
        "code": 200,
        "message": "success",
        "data": {
            "id": str(fb["id"]),
            "node_id": fb["node_id"],
            "input_ref": fb.get("input_ref"),
            "full_prompt": fb.get("full_prompt"),
            "output": fb.get("output"),
            "rating": fb.get("rating"),
            "severity": fb.get("severity"),
            "complaint": fb.get("complaint"),
            "distilled": fb.get("distilled"),
            "applied_as": str(fb["applied_as"]) if fb.get("applied_as") else None,
            "created_at": fb["created_at"].isoformat() if fb.get("created_at") else None,
        },
    }


# ─── 规则 ───────────────────────────────────────────────

@router.get("/rules")
async def list_rules(node_id: str | None = None, enabled_only: bool = False) -> dict:
    rules = await pr.list_rules(node_id, enabled_only=enabled_only)
    return {"code": 200, "message": "success", "data": {"rules": rules}}


@router.post("/rules")
async def create_rule(payload: dict) -> dict:
    node_id = payload.get("node_id")
    rule_text = (payload.get("rule_text") or "").strip()
    if not node_id or not rule_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="node_id and rule_text required",
        )
    rule = await pr.create_rule(
        node_id, rule_text,
        scope=payload.get("scope"),
        created_from=payload.get("created_from"),
        enabled=bool(payload.get("enabled", True)),
    )
    return {"code": 200, "message": "success", "data": {"id": str(rule["id"])}}


@router.patch("/rules/{rule_id}")
async def patch_rule(rule_id: str, payload: dict) -> dict:
    updated = await pr.update_rule(rule_id, payload)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    return {"code": 200, "message": "success", "data": {"id": str(updated["id"])}}


@router.delete("/rules/{rule_id}")
async def remove_rule(rule_id: str) -> dict:
    ok = await pr.delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    return {"code": 200, "message": "success", "data": {"ok": True}}
