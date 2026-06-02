# 视频反推故事板 (video → storyboard prompt) 设计

> spec 日期：2026-05-28
> 状态：design (待写 implementation plan)
> 触发方式：MCP tool `reverse_storyboard_video` + skill `video-reverse`

## 摘要

给 omni 加一个 MCP tool + skill：输入一个视频文件，调 Gemini 多模态模型反推出**可直接喂回 AI 图像/视频模型**的结构化故事板提示词。

核心 ask：反推产出的 prompt 必须按"喂回路径"做功能划分 —— 老板的最终目的是用反推 prompt 重新生成图（故事板分镜）和视频。

## 目标 / 非目标

### 目标
1. 输入任意 mp4 视频（host 文件系统路径），输出结构化 JSON + 给老板眼看的 markdown 报告
2. 自动拆分镜（LLM 自判，不依赖 ffmpeg 等间隔切）；scene 数 N 由 LLM 决定，无上下限
3. 每 scene 输出 3 类即用 prompt 包（image / video i2v / video t2v）+ 16 个结构化字段
4. 输出 3 类整段拼装产物（image_set / video_segments / video_long），分别对接：
   - 故事板分镜图组（喂 generate_image / Imagen / MJ / Flux / Nano Banana / Seedream / gpt-image-1.5）
   - i2v 视频段组（喂 generate_video / Veo3.1 / Seedance i2v / Kling / Hailuo）
   - t2v 长视频（喂 Sora2 / Veo3.1 t2v / Runway / Pika）
5. 模型可换：默认 `gemini-3.1-flash-lite-preview`，通过 `tool_models.yaml` 或 tool 参数覆盖
6. 占位符协议：视频里出现的产品 / 人脸用 `{product_ref_N}` / `{face_ref_N}` 占位，placeholders 字典给每编号 description + appearance_scenes

### 非目标
- v1 **不落库**（不写 `pipeline.*` table，不存 markdown 到磁盘 — 直接返回 result）
- v1 **不做前端 UI**（chat 里 tool 调用 + markdown 渲染即可）
- v1 **不做占位符替换工具**（`apply_storyboard_placeholders` 留 v2，老板手动复制替换够用）
- v1 **不进 pytest CI**（个人自用 + 每次 LLM 调用花 token，手动验收脚本即可）
- v1 **不支持流式 / 不支持批量**（单文件单次调用）
- v1 **不动 `services/video-analysis/app/reverse.py`** 那个独立 web 服务的 stub（跟 MCP tool 路径正交，互不影响）
- v1 **不改 ai-provider-hub**（hub Gemini provider 当前只支持 inline_data ≤20MB；直接在 KE 内用 `google-generativeai` SDK 走 Files API，绕开 hub）

## 架构 + 数据流

```
老板话术 ("反推这个视频 D:/xx.mp4")
   ↓
.claude/skills/video-reverse SKILL 触发
   ↓
MCP tool: reverse_storyboard_video(video_path, model?, extra_context?, product_ref_count=1, face_ref_count=1, target_kind?)
   ↓
[1] 文件存在性 + 大小校验 (file_path 必须 KE 容器内可访问)
   ↓
[2] GeminiVideoClient.analyze_video(video_path, system_prompt, user_prompt)
   ├─ genai.configure(api_key=GEMINI_API_KEY)
   ├─ file = genai.upload_file(video_path)              ← Files API, 大文件友好
   ├─ poll until file.state == ACTIVE  (1s interval, timeout 120s)
   ├─ model.generate_content([system, user, file], response_mime_type="application/json")
   ├─ json.loads(resp.text)
   └─ genai.delete_file(file.name)                       ← 显式删, TTL 是 48h 反正不留
   ↓
[3] 后端校验 JSON schema (Pydantic):
   - scenes[].time_range 不重叠且 |Σ duration - meta.video_duration_sec| < 0.5s
   - 占位符语法 `\{(product|face)_ref_\d+\}` 合法且不超 ref_count
   - methodology_guess.primary ∈ 8 方法论白名单
   - hook_analysis.completion_estimate ∈ {"<5%", "5-15%", ">15%"}
   - 双语 prompt (zh + en) 都非空
   ↓
[4] markdown 拼装 (给老板眼看,带 3 个全局产物的可复制代码块)
   ↓
返回 {ok, result, trace, next_step_hint}
```

### 为什么直调 `google-generativeai` 绕过 ai-provider-hub
- hub Gemini provider 当前只支持 `inline_data`（≤20MB），测试视频 25.2MB 超限
- hub 改代码需要 `docker compose build`（memory `reference_hub_build_mode`），KE 是 mount 模式 restart 就生效，改起来灵活
- `services/video-analysis/app/services/analysis.py` 已经有同款 Files API 调用经验 + httplib2 proxy patch，可直接复用
- 后续如果 hub 加 Files API 支持，再切回去成本低

## Tool 签名 + 返回 schema

### 签名

```python
@tool_with_audit(mcp, require_approval=False)
async def reverse_storyboard_video(
    video_path: str,                    # 容器内绝对路径或 host bind-mount 路径
    model: str | None = None,           # 缺省走 tool_models.yaml; 显式传覆盖 yaml
    extra_context: str | None = None,   # 老板临时方向 ("这视频是抖音收割款"/"重点反推钩子")
    product_ref_count: int = 1,         # 期望产品占位符数 (0/1/N)
    face_ref_count: int = 1,            # 期望人脸占位符数 (0/1/N)
    target_kind: str | None = None,     # 可选: video_planting/video_harvest/video_soft_ad,引导方法论
) -> dict
```

### 返回 schema (完整)

```python
{
  "ok": True,
  "result": {
    # ── Scene 级 (N 个 scene, N 由 LLM 决定) ──
    "scenes": [
      {
        # 基础
        "idx": 1,
        "time_range": [0.0, 2.4],
        "duration_sec": 2.4,
        
        # 结构化字段 (按 Veo3.1+Seedance 共同顺序, 16 个)
        "subject": "中年男性 ({face_ref_1}) 拿着 {product_ref_1}",
        "action": "缓慢倒入酱油到锅中, 蒸汽上升",
        "environment": "家庭厨房, 暖色调灯, 灶台上深棕色铁锅",
        "shot_type": "中近景",
        "camera_motion": "缓推",
        "lighting": "暖色侧光,自然光为主",
        "style_keywords": ["抖音真人感", "iPhone handheld", "非影棚"],
        "mood_keywords": ["温暖", "生活感", "可信"],
        "color_palette": ["#8B4513 棕黄", "#F5E6D3 米色", "#3D2817 深棕"],
        "dialogue": "",
        "voiceover_guess": "老板独白: 我家这瓶酱油是爷爷传下来的方子...",
        "sfx_ambient": "锅滋滋声 + 远处水龙头滴水声",
        "on_screen_text": "古法酿造 180 天",
        "first_frame_hint": "{face_ref_1} 右手拿着 {product_ref_1},立于灶台前,锅冒蒸汽,镜头中景",
        "last_frame_hint": "{product_ref_1} 瓶身标签清晰,锅里酱汁颜色加深",
        "negative_hints": ["不要影棚白底", "不要 AI 风滤镜", "不要过曝高光"],
        
        # 3 类即用 prompt (按喂回模型类型划分) ──
        "prompt_for_image": {
          "zh": "[完整中文图像生成 prompt,含 {product_ref_1}/{face_ref_1} 占位]",
          "en": "[full English image gen prompt with placeholders]",
          "usage": "出这一帧分镜图 (喂 generate_image / Imagen / MJ / Flux / Nano Banana / Seedream / gpt-image-1.5)"
        },
        "prompt_for_video_i2v": {
          "zh": "[镜头动作中文描述: 缓慢推近 + 蒸汽自然上升]",
          "en": "[motion description: slow push-in with steam rising naturally]",
          "needs": ["first_frame_hint", "last_frame_hint"],
          "usage": "出这一段视频, 需先用 prompt_for_image 出起始帧 (喂 generate_video / Veo3.1 i2v / Seedance i2v / Kling / Hailuo)"
        },
        "prompt_for_video_t2v": {
          "zh": "[整段中文自然语言: 含 subject + action + environment + shot_type + camera_motion + lighting + style]",
          "en": "[full English t2v description]",
          "usage": "纯文本出这一段视频, 不依赖首帧 (喂 Sora2 / Runway / Pika / Veo3.1 t2v)"
        }
      }
      # ... 更多 scene
    ],
    
    # ── 全局产物 1: 一组分镜图 ──
    "storyboard_for_image_set": {
      "title": "故事板分镜图组 (N 张)",
      "prompt_zh": "1. [scene 1 image prompt]\n2. [scene 2 image prompt]\n...",
      "prompt_en": "1. [...]\n2. [...]",
      "usage": "逐行喂图像模型 → 出一整套故事板分镜图"
    },
    
    # ── 全局产物 2: 一组 i2v 视频段 (Veo3.1 / Seedance i2v 路径) ──
    "storyboard_for_video_segments": {
      "title": "i2v 视频段组 (N 段 × ≤8s, 首尾帧驱动)",
      "segments": [
        {
          "idx": 1,
          "duration_sec": 8.0,
          "first_frame_prompt_zh": "...",
          "first_frame_prompt_en": "...",
          "last_frame_prompt_zh": "...",
          "last_frame_prompt_en": "...",
          "motion_prompt_zh": "...",
          "motion_prompt_en": "..."
        }
      ],
      "usage": "每段先用 first_frame_prompt 出图 (generate_image) → 喂 generate_video i2v → 拼接出完整视频"
    },
    
    # ── 全局产物 3: 单次长视频 (Sora2 / Veo3.1 t2v / Runway 路径) ──
    "storyboard_for_video_long": {
      "title": "t2v 长视频 (单次, timestamp 多镜头)",
      "prompt_zh": "[00:00-00:03] 中年男性站灶台前,缓推中景...\n[00:03-00:08] 倒酱油入锅,蒸汽升腾,特写酱汁...\n[00:08-00:15] ...",
      "prompt_en": "[00:00-00:03] ...",
      "total_duration_sec": 27.0,
      "usage": "一次性喂 Sora2 (≤20s) / Veo3.1 t2v / Runway Gen-4"
    },
    
    # ── 元数据 ──
    "placeholders": {
      "product_ref_1": {
        "description": "深棕色玻璃瓶酱油, 黄色标签, 500ml 规格",
        "appearance_scenes": [1, 2, 4]
      },
      "face_ref_1": {
        "description": "40 岁男性, 白色短袖, 中等身材, 在家厨房环境",
        "appearance_scenes": [1, 2, 3]
      }
    },
    "methodology_guess": {
      "primary": "Slice of Life",   # ∈ {Pixar, Slice of Life, CER, Hero, Empathy, Cultural Tension, Aspirational, Mini-Doc}
      "evidence": [
        "真实家庭厨房环境,无棚拍感",
        "老板第一人称独白,无第三方旁白",
        "未刻意推销, 卖点融在场景里"
      ],
      "alternative": "CER"
    },
    "hook_analysis": {
      "first_3s": "镜头切到泛黄家庭照片 + 老板说'这瓶酱油是我爷爷传下来的'",
      "completion_estimate": "5-15%",   # ∈ {"<5%", "5-15%", ">15%"}
      "why_it_might_work": [
        "情感共鸣 (家庭传承故事)",
        "悬念 (爷爷的酱油配方是啥)",
        "对比 (现代厨房 vs 老照片)"
      ]
    },
    "meta": {
      "video_path": "/host/Desktop/千川视频/3月25日.mp4",
      "video_duration_sec": 27.8,
      "model_used": "gemini-3.1-flash-lite-preview",
      "scene_count": 4,
      "generated_at": "2026-05-28T...",
      "warnings": []   # e.g. "期望 face_ref_count=2, LLM 只识别到 1 个人脸"
    },
    "markdown": "# 反推故事板报告\n\n## 视频概况...\n## 分镜表...\n## 完整故事板提示词\n\n### 故事板分镜图组\n```\n...\n```\n\n### i2v 视频段组\n```json\n...\n```\n\n### t2v 长视频\n```\n...\n```\n"
  },
  "trace": {
    "system_prompt": "...",
    "user_prompt": "...",
    "model": "gemini-3.1-flash-lite-preview",
    "duration_ms": 12345,
    "input_tokens": 100,
    "output_tokens": 5000
  },
  "next_step_hint": {
    "suggested_tool": "generate_creative_pack",
    "suggested_args": {
      "kind": "video_planting",
      "extra_context": "参考反推故事板: [storyboard_prompt_with_placeholders 内容]"
    },
    "note": "或直接把 storyboard_for_image_set.prompt_zh 喂 generate_image (替换 {product_ref_1}/{face_ref_1} 为真实图)"
  }
}
```

### 占位符协议

- 语法：`{product_ref_N}` / `{face_ref_N}`（N 从 1 开始, 方括号内不带空格, regex `\{(product|face)_ref_\d+\}`）
- 跨 scene 唯一性：同一产品/人物在多个 scene 复用同一编号
- placeholders 字典：每编号给 `description`（眼看是啥）+ `appearance_scenes`（在哪几 scene 出现）
- 替换工具留 v2：v1 老板手动 string.replace 即可

## Prompt 设计

### 文件位置

`services/knowledge-engine/config/prompts/reverse_storyboard.{system,user}.md`

跟 `generate_brief` / `creative_pack` 同 layout, KE mtime 自检, 改完不需要 restart。

### system prompt 五块结构

1. **角色**：你是一个视频反推专家。看完视频, 输出能让其他视频/图像模型 1:1 重做这段视频的结构化故事板提示词。
2. **任务**：拆分镜（识别 cut/transition, 不依赖时间均匀）→ 每 scene 填 16 个结构化字段 + 3 类即用 prompt → 拼 3 类全局产物 → 猜方法论 + 钩子分析。
3. **JSON schema 强制**（用 responseMimeType=application/json + system prompt 内 schema 描述双重保险, 照搬上面 schema 表）。
4. **占位符规则**：同一产品/人脸跨 scene 复用同一编号；placeholders 字典给每编号 description + appearance_scenes。
5. **强约束**（per memory `feedback_writing_style`）：
   - 说人话, 禁 AI 化套话（赋能/打通/闭环/匠心/极致/一站式 等）
   - 反幻觉：编不出来的字段写空字符串/空数组, 不要硬填
   - methodology_guess 必须从 8 个白名单选：Pixar / Slice of Life / CER / Hero / Empathy / Cultural Tension / Aspirational / Mini-Doc
   - hook_analysis.completion_estimate 输出区间字符串："<5%" / "5-15%" / ">15%"
   - 双语 prompt（zh + en）都非空, 各自顺自己语言的 image-gen 模型偏好（en 偏标签式, zh 偏自然语言）

### user prompt 模板

```
请反推附件视频。

老板补充: {extra_context_block}
期望产品占位符数: {product_ref_count}
期望人脸占位符数: {face_ref_count}
反推方法论偏向(可选): {target_kind_or_none}

按 system 描述的 JSON schema 输出,严格 JSON,不带 markdown 围栏。
```

## Gemini Files API 路径

### 新建模块 `services/knowledge-engine/app/services/gemini_video_client.py`

```python
import os, json, asyncio, logging
import google.generativeai as genai
from app.services.gemini_proxy_patch import patch_httplib2_for_proxy

logger = logging.getLogger(__name__)
patch_httplib2_for_proxy()


class GeminiVideoClient:
    def __init__(self, model: str, api_key: str | None = None):
        key = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
        if not key:
            raise RuntimeError("GEMINI_API_KEY 未配置")
        genai.configure(api_key=key)
        self.model = genai.GenerativeModel(model)
        self.model_id = model
    
    async def analyze_video(
        self,
        video_path: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 16000,
        poll_timeout_sec: int = 120,
    ) -> tuple[dict, dict]:
        """返回 (json_result, usage_meta)"""
        # 1. upload (blocking, 在 to_thread 里跑)
        file = await asyncio.to_thread(genai.upload_file, video_path)
        try:
            # 2. wait for ACTIVE
            start = asyncio.get_event_loop().time()
            while file.state.name == "PROCESSING":
                if asyncio.get_event_loop().time() - start > poll_timeout_sec:
                    raise TimeoutError(f"file upload poll timeout ({poll_timeout_sec}s)")
                await asyncio.sleep(1)
                file = await asyncio.to_thread(genai.get_file, file.name)
            if file.state.name != "ACTIVE":
                raise RuntimeError(f"file state not ACTIVE: {file.state.name}")
            
            # 3. generate with JSON output forced
            resp = await asyncio.to_thread(
                self.model.generate_content,
                [system_prompt, user_prompt, file],
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            text = resp.text or ""
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                import re
                m = re.search(r"\{[\s\S]*\}", text)
                if not m:
                    raise RuntimeError(f"LLM 未返回合法 JSON: {text[:300]}")
                result = json.loads(m.group(0))
            
            usage = {
                "input_tokens": getattr(resp.usage_metadata, "prompt_token_count", 0) if resp.usage_metadata else 0,
                "output_tokens": getattr(resp.usage_metadata, "candidates_token_count", 0) if resp.usage_metadata else 0,
            }
            return result, usage
        finally:
            try:
                await asyncio.to_thread(genai.delete_file, file.name)
            except Exception as exc:
                logger.warning(f"删除 Gemini file 失败 (TTL 48h 反正会自动删): {exc}")
```

### 复用 proxy patch `services/knowledge-engine/app/services/gemini_proxy_patch.py`

把 `services/video-analysis/app/services/analysis.py:17-65` 的 `_patch_httplib2_for_proxy()` 函数原样抽出来作为独立模块。逻辑不变：

- 读 `HTTPS_PROXY` / `https_proxy` / `HTTP_PROXY` / `http_proxy` 环境变量
- 跳过 loopback（127.0.0.1）
- 用 PySocks 给 httplib2.Http 注入 proxy_info
- once-only 标记 `_omni_proxy_patched` 防止双 patch

## `tool_models.yaml` 配置

`services/knowledge-engine/config/tool_models.yaml` 加 entry：

```yaml
reverse_storyboard_video:
  provider: gemini
  model: gemini-3.1-flash-lite-preview   # 老板原话首选, 可换 2.5-flash/3-pro
  temperature: 0.2                        # 反推要稳不要发挥
  max_tokens: 16000                       # 多 scene 输出可能膨胀
  prompts:
    system: reverse_storyboard.system
    user: reverse_storyboard.user
```

换模型路径：
- **永久换**：改 yaml + `docker restart omni-knowledge-engine`（memory `feedback_yaml_lru_cache_restart`）
- **一次性换**：tool 调用时显式传 `model="gemini-3-pro-preview"`，不需要 restart，下次调用还是 yaml 里的

## Skill 文件

### 路径

`.claude/skills/video-reverse/SKILL.md`（受 memory `reference_omni_global_link` 的 junction 影响, 会自动全局生效；本项目内编辑, junction 同步到 `~/.claude/skills/`）

### 触发话术

- "反推这视频 X.mp4" / "反推这视频" / "反推故事板 X"
- "拆解这个视频" / "拆解 X.mp4"
- "看这视频咋拍的" / "这视频咋拍出来的"

### SOP（一步一暂停）

1. 老板提供路径 → 调 `reverse_storyboard_video(video_path=X, model=可选, product_ref_count=猜或问老板, face_ref_count=猜或问老板, target_kind=可选)`
2. 拿到 result → 在 chat 里贴 `result.markdown` 完整内容 + 把 `result.placeholders` 表格化展示 + 引用 `meta.warnings`
3. 老板审 → 满意：
   - "扔进 generate_creative_pack" → 用 `storyboard_for_image_set.prompt_zh` 当 extra_context, 调 `generate_creative_pack(kind=target_kind, extra_context=...)`
   - "出图" → 第 N scene 的 `prompt_for_image.zh` 喂 `generate_image`（让老板先填 product_ref/face_ref 真实图）
   - "出视频" → 第 N scene 的 `prompt_for_video_i2v` + first_frame_hint + last_frame_hint 喂 `generate_video`（i2v 模式）
4. 老板不满意 → "重推第 N scene" / "换模型重跑" / "改 target_kind 重推" → 用 `model` 或 `target_kind` 参数显式覆盖再调 tool
5. 老板说 "改 prompt 后重推" → 编辑 `config/prompts/reverse_storyboard.{system,user}.md` 后再调 tool（mtime 自检, 不需要 restart）

### SKILL.md 内容骨架

```markdown
---
name: video-reverse
description: 反推视频生成故事板提示词。老板说"反推这视频 X"/"拆解这个视频"/"看这视频咋拍的"等, 触发标准 5 步 SOP, 调 reverse_storyboard_video tool 出三类即用 prompt 包(image / video i2v / video t2v) + 三类全局产物。
---

# 反推视频→故事板提示词 SOP

## 触发话术
[同上]

## 流程
[同上 5 步]

## tool 参数说明
[reverse_storyboard_video 6 参数详解]

## 老板常见后续
- "出图" → generate_image
- "出视频" → generate_video i2v
- "扔进 creative_pack" → generate_creative_pack(kind=..., extra_context=...)
- "换模型重推" → reverse_storyboard_video(..., model="...")

## 约束
- 不要一气呵成跑完整套, 每步停下等反馈
- result.markdown 必完整贴给老板看
- placeholders 字典必表格化展示 (老板要知道哪张图填哪个 ref)
- meta.warnings 不为空必引用 (避免老板误判 LLM 漏识别)
```

## 测试计划

### 主测视频

`C:\Users\Administrator\Desktop\千川视频\3月25日.mp4`（25.2 MB, 超过 Gemini inline_data 20MB 软上限, 验证 Files API 路径）

### Bind-mount 配置

`docker-compose.yml` 给 KE service 加：

```yaml
services:
  knowledge-engine:
    volumes:
      # ... 现有 mount ...
      - "C:/Users/Administrator/Desktop:/host/Desktop:ro"   # ro 模式只读, 安全
```

测试时容器内路径：`/host/Desktop/千川视频/3月25日.mp4`

### 手动验收脚本

`services/knowledge-engine/scripts/test_reverse_storyboard.py`（独立脚本, 不进 pytest CI）

```python
import asyncio, json
from app.mcp.tools.media import reverse_storyboard_video

async def main():
    result = await reverse_storyboard_video(
        video_path="/host/Desktop/千川视频/3月25日.mp4",
        product_ref_count=1,
        face_ref_count=1,
    )
    
    assert result["ok"], f"tool 失败: {result.get('error')}"
    r = result["result"]
    
    # 1. scenes 时间不重叠且总和 ≈ 视频时长
    for i, s in enumerate(r["scenes"][:-1]):
        nxt = r["scenes"][i+1]
        assert s["time_range"][1] <= nxt["time_range"][0] + 0.5, f"scene {i+1} 跟 scene {i+2} 时间重叠"
    total_dur = sum(s["duration_sec"] for s in r["scenes"])
    video_dur = r["meta"]["video_duration_sec"]
    assert abs(total_dur - video_dur) < 0.5, f"scene 总时长 {total_dur} 跟视频时长 {video_dur} 差太多"
    
    # 2. 占位符语法 + 数量
    import re
    placeholder_re = re.compile(r"\{(product|face)_ref_\d+\}")
    for s in r["scenes"]:
        for field in ["subject", "first_frame_hint", "last_frame_hint"]:
            text = s.get(field, "")
            for m in placeholder_re.finditer(text):
                kind, _, _ = m.group().strip("{}").rpartition("_ref_")
                key = m.group().strip("{}")
                assert f"{kind}_ref_{key.split('_')[-1]}" in r["placeholders"], f"{key} 在 placeholders 字典里缺失"
    
    # 3. methodology_guess 白名单
    METHODOLOGY = {"Pixar", "Slice of Life", "CER", "Hero", "Empathy", "Cultural Tension", "Aspirational", "Mini-Doc"}
    assert r["methodology_guess"]["primary"] in METHODOLOGY
    
    # 4. hook_analysis.completion_estimate
    assert r["hook_analysis"]["completion_estimate"] in {"<5%", "5-15%", ">15%"}
    
    # 5. 3 类全局产物都非空
    assert r["storyboard_for_image_set"]["prompt_zh"]
    assert len(r["storyboard_for_video_segments"]["segments"]) > 0
    assert r["storyboard_for_video_long"]["prompt_zh"]
    
    # 6. scene 级 3 类 prompt 都非空
    for s in r["scenes"]:
        assert s["prompt_for_image"]["zh"] and s["prompt_for_image"]["en"]
        assert s["prompt_for_video_i2v"]["zh"] and s["prompt_for_video_i2v"]["en"]
        assert s["prompt_for_video_t2v"]["zh"] and s["prompt_for_video_t2v"]["en"]
    
    print(f"\n[PASS] reverse_storyboard_video 验收通过")
    print(f"  scene 数: {r['meta']['scene_count']}")
    print(f"  视频时长: {r['meta']['video_duration_sec']}s")
    print(f"  模型: {r['meta']['model_used']}")
    print(f"  方法论: {r['methodology_guess']['primary']}")
    print(f"  完播估算: {r['hook_analysis']['completion_estimate']}")
    if r["meta"]["warnings"]:
        print(f"  warnings: {r['meta']['warnings']}")
    
    # 输出 markdown 给老板眼看
    print("\n---- markdown 报告 ----\n")
    print(r["markdown"])

if __name__ == "__main__":
    asyncio.run(main())
```

### 边界 case

| 场景 | 期望返回 |
|---|---|
| video_path 不存在 | `{ok: false, error: "file_not_found", hint: "..."}` |
| video_path 是目录 | `{ok: false, error: "is_directory"}` |
| GEMINI_API_KEY 未配 | `{ok: false, error: "gemini_not_configured"}` |
| 视频损坏 / Gemini upload 失败 | `{ok: false, error: "upload_failed", hint: ...}` |
| LLM 输出非 JSON | regex 抽 `{...}` 块再 parse; 仍失败返 `{ok: false, error: "parse_failed", raw_text: ...}` |
| 模型不支持视频输入（如老板切到 chat-only 模型） | Gemini API 400 → `{ok: false, error: "model_no_vision", hint: "换 gemini-2.5-flash / 3-pro / 3.1-* 系列"}` |
| 视频 < 5s | 期望 1-2 scene; 不报错 |
| 视频 > 60s | LLM 自判 N, 不应 > 20 scene; 若 LLM 拆 > 20 → warning 但不报错 |
| 无人/无产品视频（如风景片） | placeholders 字典为空; 字段里没占位符 |

## 依赖 / docker 改动

### `services/knowledge-engine/requirements.txt`

加：
```
google-generativeai>=0.8.0
PySocks>=1.7.1   # httplib2 proxy patch 需要
```

### `docker-compose.yml`

KE service 加 volume：
```yaml
- "C:/Users/Administrator/Desktop:/host/Desktop:ro"
```

### 部署

```bash
docker compose build knowledge-engine
docker compose up -d knowledge-engine
```

依赖加了不能 mount 模式 hot reload, 必须 rebuild。

## 验收清单

实施完成后:

- [ ] `reverse_storyboard_video` tool 出现在 `python -m app.mcp.doctor` 输出
- [ ] `services/knowledge-engine/scripts/test_reverse_storyboard.py` 对测试视频跑通
- [ ] result.markdown 在 chat 里渲染正常（3 类全局产物各自一个代码块）
- [ ] `.claude/skills/video-reverse/SKILL.md` 在 `~/.claude/skills/` 可见（junction 同步）
- [ ] 老板话术触发：在 chat 里说"反推这视频 X" 自动触发 SOP
- [ ] 模型可换：tool 调用传 `model=...` 覆盖 yaml 工作
- [ ] 模型可换：改 `tool_models.yaml` + restart KE 后下次调用用新模型
- [ ] 边界 case：file_not_found / API key 缺 / parse failed 三个最容易遇到的错误都正确返
- [ ] proxy patch 复用 video-analysis 同款逻辑，KE 在国内代理网络下 Gemini Files API 上传成功

## 后续 (v2+, 不在本 spec 范围)

- 占位符替换 tool：`apply_storyboard_placeholders(storyboard, product_refs=[url1...], face_refs=[url1...])` 自动 string.replace + 返回完整可喂的 prompt
- lineage 落库：`pipeline.reverse_storyboards` table, denorm sku_id, 多版本
- 前端 `/video-reverse` 页面：拖拽上传 + 实时进度条 + 3 类全局产物可点击复制
- ai-provider-hub Gemini provider 加 Files API 支持, tool 切回走 hub
- 批量反推：`reverse_storyboard_video_batch(video_paths=[...])`, 一次反推一组竞品视频
- 反推 vs 真正向 pipeline 对比：把反推 storyboard 喂回 `generate_creative_pack` + `generate_image` + `generate_video` 看能否 1:1 复刻原视频

## 参考

- memory `feedback_video_soft_ad_design`：8 个视频方法论清单
- memory `feedback_douyin_natural_content_rules`：抖音心法 (完播率分级 + 钩子规则)
- memory `feedback_writing_style`：反 AI 化套话清单
- memory `reference_veo_31_capabilities`：Veo 3.1 8s 硬上限 + i2v 首尾帧能力
- memory `reference_volcengine_seedance_capabilities`：Seedance 2.0 多 ref 能力
- memory `reference_hub_build_mode`：hub 是 build 不是 mount, KE 是 mount
- memory `feedback_yaml_lru_cache_restart`：tool_models.yaml 改完必 restart KE
- memory `feedback_personal_use_no_overengineering`：禁过度工程, 个人自用
- memory `reference_omni_global_link`：skill junction 全局生效
- `services/video-analysis/app/services/analysis.py`：Gemini Files API + httplib2 proxy patch 现成代码
- `services/knowledge-engine/app/mcp/tools/media.py`：现有 media tool layout
- `services/knowledge-engine/config/tool_models.yaml`：现有 tool model 配置
- `services/knowledge-engine/config/prompts/creative_pack.video_planting.system.md`：现有视频脚本 prompt 风格参考
- 调研结论（2026-05-28 agent）：13 个市面热门视频/图像模型字段交集，命中率 ≥ 8/13 = 6 个核心通用字段 (subject/action/environment/shot_type/lighting/style+mood)
