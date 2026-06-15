---
name: video-reverse
description: 反推视频→可喂回 AI 图像/视频生成模型的故事板提示词。老板说"反推这视频 X"/"拆解这个视频"/"看这视频咋拍的"/"反推故事板 X"等,触发标准 5 步 SOP,调 reverse_storyboard_video tool 出三类即用 prompt 包(image / video i2v / video t2v) + 三类全局产物。产出是可**喂回 AI 生成模型**的故事板 prompt 包（非内容方法论）；凡拆视频/反推故事板都走本 skill，**不走** content-creator/social-content（拆竞品图文走 competitor-product-research）。⚠️消歧：反推**人群/打什么人/对比我们的画像** → `reverse_audience_analysis`（竞品人群逆向分析），不是 reverse_storyboard_video——本 skill 只管"怎么拍"，"打什么人"走那边。
---

# video-reverse:视频反推故事板 SOP

> omni-vibe 项目内 skill。老板给一个视频文件,反推出能 1:1 重做这视频的结构化提示词,**最终目的喂回 AI 出图/出视频**。

## 触发场景（话术 → 参数）

| 老板话术 | 参数解析 | 备注 |
|---|---|---|
| "反推这视频 C:/path/x.mp4" | video_path=直接给的 | 走标准流程 |
| "拆解这个视频" | 老板会上传文件或贴路径 | 反问"文件在哪?" |
| "看这视频咋拍出来的" | 同上 | 同上 |
| "反推故事板 X" | X 是路径 | 走标准流程 |
| "这视频按 video_planting 思路反推" | target_kind="video_planting" | 加 target_kind 引导方法论 |
| "反推时重点看钩子" | extra_context="重点反推钩子" | 加 extra_context |

## 标准 5 步 SOP

### Step 1: 确认 video_path + 视频规格

如果老板话术里没给路径或文件不在 KE 容器可访问的路径:

> "需要文件路径(KE 容器内能访问的)。如果是 Win 桌面文件,可以放 `C:/Users/Administrator/Desktop/` 下,容器内路径会是 `/host/Desktop/<filename>`(已 bind-mount)。"

容器路径转换:
- `C:/Users/Administrator/Desktop/千川视频/3月25日.mp4` → `/host/Desktop/千川视频/3月25日.mp4`

**检查文件大小**(老板可帮看,或用 `ls` 看):
- < 100MB: Gemini Files API 上传约 5-30s
- 100MB-2GB: 上传可能 1-3 分钟
- > 2GB: 直接劝老板先压缩

### Step 2: 询问期望参数（**可选,但建议问**）

```
老板,反推之前确认几个参数:
1. 期望产品占位符数 (product_ref_count): 默认 1。视频里有几个不同产品?
2. 期望人脸占位符数 (face_ref_count): 默认 1。视频里有几个不同人物?
3. 方法论偏向 (target_kind): 默认让 LLM 自判。要指定的话:
   - video_planting (种草, A1/A2→A3 双点同发)
   - video_harvest (收割, 强 CTA + 限时利益)
   - video_soft_ad (软广, O→A1 让人知道)
4. 临时方向 (extra_context): 默认无。要指定的话:
   - "重点反推钩子"
   - "这视频是抖音收割款,反推要带强 CTA 视角"
```

如果老板说"按默认走"→ 全用默认值进 Step 3。

### Step 3: 调 reverse_storyboard_video

```python
reverse_storyboard_video(
    video_path="/host/Desktop/千川视频/3月25日.mp4",
    product_ref_count=1,                 # 或老板指定
    face_ref_count=1,                    # 或老板指定
    target_kind="video_planting",        # 可选
    extra_context="重点反推钩子",         # 可选
    model="gemini-3.1-flash-lite-preview" # 可选,默认走 tool_models.yaml
)
```

返回:
- `result.markdown` 给老板眼看的完整报告
- `result.scenes[]` 19 字段 × N 个 scene
- `result.placeholders` 占位符字典(必表格化展示)
- `result.storyboard_for_image_set` 一组分镜图 prompt
- `result.storyboard_for_video_segments` i2v 段组
- `result.storyboard_for_video_long` t2v 长视频 prompt
- `result.methodology_guess` 方法论判断
- `result.hook_analysis` 钩子分析
- `result.meta.warnings` 警告(必引用)

### Step 4: 给老板看完整 markdown 报告 + 占位符表 + 警告

**完整粘贴 `result.markdown`**(不要省略),然后:

```
警告(如有 meta.warnings):
- 期望 product_ref_count=2,但只识别到 1 个产品
- ...

占位符字典:
| key | 描述 | 出现 scene |
|---|---|---|
| {product_ref_1} | 深色玻璃瓶酱油,黄色标签,500ml | 1,2,4 |
| {face_ref_1} | 40 岁男性,白色短袖,家厨房 | 1,2,3 |

方法论判断: Slice of Life (备选 CER)
完播估算: 5-15%
```

### Step 5: 老板审 + 选下一步

| 老板说 | 含义 | Claude 应做 |
|---|---|---|
| OK / 通过 / 看着对 | 满意 | 问"下一步要扔进 generate_creative_pack / 出图 / 出视频?" |
| 重推 / 重跑 / 改 | 不满意 | 用同 tool 重调,extra_context 加老板新方向 |
| 第 N 个 scene 重推 | 局部不满意(LLM 当前一次性出全部 scene,**无法只改一个**) | 跟老板说明限制,只能整体重跑+加 extra_context |
| 换 gemini-3-pro-preview 重跑 | 想用更强模型 | tool 显式传 model 参数覆盖 yaml |
| 出图 | 用 storyboard_for_image_set 出整套分镜图 | 调 generate_image,prompts=逐行拆 image_set 出来 |
| 出视频 | 用 storyboard_for_video_segments 出 i2v 段 | 老板先给 product_refs/face_refs 真实图 → 替换占位符 → generate_image 出首尾帧 → generate_video i2v |
| 扔进 creative_pack | 当 extra_context 喂 generate_creative_pack | 调 generate_creative_pack(kind=target_kind, extra_context=image_set.prompt_zh) |
| 给我 t2v 长版本 | 用 storyboard_for_video_long(适合 Sora2/Runway) | 把 video_long.prompt_zh / prompt_en 复制给老板,他自己去 Sora 网页用 |

## 错误处理

| 错误 | hint | 怎么办 |
|---|---|---|
| `file_not_found` | 路径不对 / 没 bind-mount | 检查容器内路径 (老板桌面 → /host/Desktop/) |
| `is_directory` | 给的是目录不是文件 | 让老板补具体文件名 |
| `gemini_not_configured` | GEMINI_API_KEY 缺 | docker-compose KE service env_file 应读 ai-provider-hub/.env;不行就 rebuild |
| `gemini_sdk_missing` | google-generativeai 没装 | KE rebuild: `docker compose build knowledge-engine && docker compose up -d` |
| `model_no_vision` | 模型不支持视频 | 换 gemini-2.5-flash / 3-flash-preview / 3.1-pro-preview |
| `upload_or_timeout` | Gemini Files API 上传/处理超时 | 网络问题或视频太大;重试或换小一点的视频 |
| `schema_validation_failed` | LLM 输出 JSON 不符 schema | 看 errors 字段;通常重跑就好(LLM 偶尔 hallucinate) |
| `llm_call_failed` | 其他 Gemini API 错误 | 看 hint;通常网络或代理问题 |
| `parse_failed` | LLM 输出不是合法 JSON | 重跑;持续失败→换模型或调 max_tokens 减少截断 |

## 反例（**禁止**）

- 不调 tool 直接看视频文件名 + 编一个反推 — 没素材就是瞎编
- 一气呵成跑完 5 步 — 必须 Step 2 / Step 3 / Step 4 各暂停老板反馈
- markdown 报告省略不全 — 老板要看 scene 表/占位符表/3 类全局产物代码块
- 占位符不表格化 — 老板不知道每个 ref 指代啥就没法填真实图
- meta.warnings 不引用 — 老板可能误判 LLM 漏识别
- 用 AI 化套话写额外评论 — feedback memory 强制说人话

## 已知约束

- LLM **一次性出全部 scene + 全部产物**,无法只局部重推(改 1 个 scene 也要整体重跑)
- 视频大小 / 网络条件决定 upload 阶段耗时(>30s 老板可能不耐烦,告诉他在等)
- 模型必须支持视频输入(text-only 模型如 deepseek/qwen-text 用不了)
- 反推 prompt 是**起点不是终点**:老板拿到 storyboard_for_image_set 还要手动把 `{product_ref_1}` 替换成自己真实产品图 URL 才能喂 generate_image
- t2v 长视频(storyboard_for_video_long)适合 Sora2(≤20s) / Veo3.1 t2v / Runway,老板自己去网页用

## 跟 CLAUDE.md / 其他 skill 的关系

- 跟 **sku-pipeline** 是逆向:sku-pipeline 是 SKU → 故事板;本 skill 是 故事板视频 → 故事板 prompt
- 老板拿反推 prompt 后通常会:
  - **复刻** — 用 generate_image / generate_video 重做这视频
  - **借鉴** — 拿反推 storyboard 当 extra_context 喂 generate_creative_pack 出新创意
  - **学习** — 看 methodology_guess + hook_analysis 学这视频为啥可能爆
- 不调 record_cost / disable_cost_item / 任何写库 tool (本 skill 是只读分析)

## 老板循环微调测试模式

老板要"反推 → 用 prompt 重生成 → 比对原视频 → 调 prompt 重跑"循环时:

1. Iter 0: 跑 reverse_storyboard_video,日志落 `<视频所在目录>/test_logs/iter_0_*.json`
2. 老板看 markdown,指出"还原度差在哪"(如"风格漂浮没说人话/分镜数不对/钩子识别错")
3. Iter N: 改 `config/prompts/reverse_storyboard.system.md`(改 prompt 不改代码) → 重跑
4. 比对 iter_N 跟 iter_0 的 scenes/methodology/hook 改进
5. 直到老板说"够了"或还原度 ≥ 80% 主观判断

**改 prompt 后**: KE mtime 自检,不需要 restart 容器。
**改 tool 代码后**: KE 是 mount 模式,改完直接 `docker restart omni-knowledge-engine`(不需要 rebuild)。
**改 pyproject.toml**: 必须 `docker compose build knowledge-engine && docker compose up -d knowledge-engine`。
