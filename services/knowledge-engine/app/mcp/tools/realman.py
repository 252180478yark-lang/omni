"""W4-B 切片 (realman)：真实人物视频生成 MCP tools。

绕过 Seedance content_sensitive 限制：
  realman_create_avatar       — 单张人脸图 → 标准化头像（可选预处理步骤）
  realman_generate_portrait_video — 头像图 + 驱动视频 → 口型对齐真人视频

服务：Volcengine 图像生成大模型（service 86081），认证 AK/SK。
"""
from __future__ import annotations

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.mcp.trace import attach_next_step, build_trace


@tool_with_audit(mcp, require_approval=False)
async def realman_create_avatar(
    image_url: str,
) -> dict:
    """形象创建：把一张真实人物照片标准化成适合驱动的头像。

    可选预处理步骤；直接用原图 URL 调 realman_generate_portrait_video 也行。

    Args:
        image_url: 人物照片 URL（JPG/PNG，建议正脸清晰，分辨率 ≥ 512×512）

    Returns:
        {ok, avatar_image_url（标准化后的图 URL，没有时回退原图）, trace}
    """
    from app.services.realman_client import create_avatar

    result = await create_avatar(image_url)

    trace = build_trace(
        provider="volcengine_visual",
        model="realman_avatar_picture_v2",
        prompt=f"image_url={image_url[:80]}",
        params={"req_key": "realman_avatar_picture_v2"},
        cost_estimate="1 次火山视觉调用（按量计费）",
    )

    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error"),
            "hint": result.get("hint", "检查 VOLCENGINE_ACCESS_KEY/SECRET_KEY 配置"),
            "trace": trace,
        }

    return attach_next_step(
        {"ok": True, "avatar_image_url": result["avatar_image_url"]},
        suggested_tool="realman_generate_portrait_video",
        suggested_args={
            "image_url": result["avatar_image_url"],
            "driving_video_url": "（填入驱动视频 URL）",
        },
        human_text=f"头像已创建：{result['avatar_image_url'][:80]}…\n下一步：用这张头像 + 驱动视频调 realman_generate_portrait_video",
    )


@tool_with_audit(mcp, require_approval=False)
async def realman_generate_portrait_video(
    image_url: str,
    driving_video_url: str,
    timeout_s: int = 300,
) -> dict:
    """真实人物视频生成：人脸图 + 驱动视频 → 口型对齐的真实人物视频。

    绕过 Seedance InputImageSensitiveContentDetected 限制，走火山引擎
    图像生成大模型（服务 86081），允许真实人脸输入。

    Args:
        image_url: 被驱动的目标人物图（真实人物照片或 realman_create_avatar 输出）
        driving_video_url: 驱动视频 URL（口型/动作来源；建议与目标时长匹配）
        timeout_s: 最大等待秒数（默认 300s / 5 分钟）

    Returns:
        {ok, video_url, task_id, trace, next_step_hint}

    典型用法：
        step 6 出了真实人脸分镜图 → Seedance content_sensitive → 改用这个 tool
        image_url = step 6 的分镜图 URL
        driving_video_url = 一段真实人物讲话/演示的驱动素材 URL
    """
    from app.services.realman_client import generate_portrait_video

    result = await generate_portrait_video(
        image_url,
        driving_video_url,
        timeout_s=float(timeout_s),
    )

    trace = build_trace(
        provider="volcengine_visual",
        model="realman_avatar_imitator_v2v_gen_video",
        prompt=f"image={image_url[:60]} driving={driving_video_url[:60]}",
        params={
            "req_key": "realman_avatar_imitator_v2v_gen_video",
            "task_id": result.get("task_id", ""),
        },
        cost_estimate="1 次火山视觉 v2v 视频生成（按量计费）",
    )

    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error"),
            "task_id": result.get("task_id", ""),
            "hint": result.get("hint", "检查配置或驱动视频 URL"),
            "trace": trace,
        }

    return attach_next_step(
        {
            "ok": True,
            "video_url": result["video_url"],
            "task_id": result["task_id"],
        },
        suggested_tool=None,
        suggested_args={},
        human_text=f"真实人物视频已生成：{result['video_url']}\n下载后可交剪辑（不自动拼接）。",
    )
