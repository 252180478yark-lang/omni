# 人群画像生活状态 + 编导 Brief 链路设计（step 3.5 / 3.6）

- **日期**：2026-06-11
- **状态**：设计已与老板逐节确认，待老板审 spec 后转实施计划
- **方案**：A（两个新 MCP tool 接在现有 step 3 后面，老板四选已确认）

> **修订 2026-06-12（老板实测反馈，实施中变更）**：第 5 部分从「分镜三件套（每段 image_prompt/last_frame_prompt/motion_prompt）」改为「**一大段连续故事描述提示词**」——老板实战测试：拆开的分镜提示词出不了满意素材。新形态：英文长叙事、时间戳贯穿、人物/场景变换/每次镜头变化/表情微变/产品入画时机全写进叙事、真人感锚内嵌；新增 `ai_prompt_count` 参数（默认 1 段；按目标模型单次生成能力实测拆 N 块，拆块时每块开头重述人物+场景+风格锚保证独立可喂）。随之回退：scripts.scenes 分镜自动解析对 director_brief 不再启用；next_step 不再强指 generate_storyboard_images（大段提示词直接复制喂目标模型）。**更大范围**（creative_pack 6 类、step 6/7 出片链全面转一大段提示词）记为后续切片，本期不动。

> **修订 2 · 2026-06-12（老板补充）**：第 5 部分提示词必须**知道喂给哪个出片模型**——不同模型单次生成时长/写法偏好/负向词支持不同，提示词文本要按模型定。落地：`generate_director_brief` 加 `target_model: str = 'generic'` 参数；模型写法档案外置 `config/prompts/video_model_profiles/<model>.md`（热加载，老板实测后随时改），未知模型回退 generic；`ai_prompt_count` 改 `int | None = None`——None 时由模型档案的"单次生成时长"指导 LLM 自行定拆块数并在输出里说明，显式传值则强制。初始档案：generic / veo / seedance / jimeng（内容标注"初始值待实测校准"）。

## 1. 背景与目标

老板要的完整流程：SKU → 独特卖点分析 → RAG 检索 KB 匹配人群圈层 → 输出人群画像 + 真实生活状态描述（不臆想不编造）→ 基于生活状态给**真人编导**下内容 brief（拍什么视频 / 什么人群 / 这群人爱看什么 / 怎么呈现 / 含什么元素画面台词场景剧情文案），brief 同时附 AI 出片映射（两用）。

摸底结论：前两段已有（step 2 `generate_selling_points_matrix` + step 3 `generate_audience_match`），后两段缺失。老板手搓的两份 Gemini 提示词是后两段的原型：

- `E:\agent\产品人群画像匹配-Gemini-System-Prompt-V4.1-完全体+卖点重构.md` → step 3.5 的方法论蓝本（21 维画像裁剪 + 可信度分级标注 + 卖点重构引擎三层拆解）
- `E:\agent\抖音种草视频生成器_V7.2.md` → step 3.6 的方法论蓝本（一件事原则 / 起伏≠反转 / 卖点种在情绪高点 / 台词画面产品死规矩 / 禁用词 8 类）

## 2. 范围

**做**：

1. step 2 提示词打磨（改 `config/prompts/selling_points_matrix.system.md`，4 处，不动代码）
2. 新 MCP tool `generate_audience_portrait`（step 3.5）+ prompt 外置
3. 新 MCP tool `generate_director_brief`（step 3.6）+ prompt 外置
4. migration 047：新表 `pipeline.audience_portraits` + `pipeline.scripts` 加 kind `director_brief` 和 `portrait_id` 列
5. `pipeline_adopt` 支持 `table='audience_portraits'`（改现有 tool，不新增）
6. step 3 的 `next_step_hint` 增加 3.5 分支（圈包投放走 step 4 / 内容 brief 走 step 3.5）
7. doctor `wanted` 集 78 → 80
8. CLAUDE.md 老板话术表补两行（实施完成后）

**不做（v1 范围外）**：

- /sku-pipeline 前端 tab（先走对话调用，前端留下一个切片）
- portrait 的专用 list/get 查询 tool（要查走 SQL；需要时再加切片）
- 批量模式（一次给多个人群出 brief；v1 一次一个人群）
- 竞品人群逆向分析、反向画像（V4.1 里有，但 v1 不进 tool，避免范围膨胀）

## 3. 总体架构与数据流

```
step 2  generate_selling_points_matrix   ← 打磨 prompt
   ↓ matrix_run_id
step 3  generate_audience_match          ← 不动（50-65 query 跨 46 doc 广撒网，≥15 人群跨 ≥10 doc）
   ↓ 老板选中某个 audience_record（前端卡片勾选 / 对话"选第 N 个"）
step 3.5 generate_audience_portrait 【新】 ← 对选中人群"深挖"：定向二次检索 + 生活状态画像 + 卖点重构
   ↓ portrait_id（落 pipeline.audience_portraits）
step 3.6 generate_director_brief 【新】   ← V7.2 产品化：编导备忘录 + 算法信号三向量 + AI 出片映射
   ↓ script_id（落 pipeline.scripts, kind='director_brief'）
   → 真人编导拿去拍；或 AI 映射段喂 step 6 generate_storyboard_images / step 7 generate_video_segments
   → 投后 record_ad_metrics 回传，v_asset_full_lineage 反查"哪个人群 × 哪版画像 × 哪版 brief 真带货"
```

关键决定（老板已逐条确认）：

| # | 决定 | 理由 |
|---|---|---|
| 1 | 接在现有链后面，step 2/3 不动结构 | 复用已打通的多 query 检索 + 血缘落库 |
| 2 | brief 真人拍为主 + AI 出片映射两用 | `include_ai_mapping` 参数控制 |
| 3 | 生活状态 grounding = KB 锚 + 可信度分级标注 | `[KB:文档名]` / `🧠推演` / `⚠️推测` 三选一逐句标 |
| 4 | 卖点打磨方向 = 三层拆解 + USP 更尖 + 买点视角 + 真需求挖场景 | 老板多选确认 |
| 5 | brief 含算法信号三向量（画面/文案/音乐） | eCPM 思维：让抖音算法把内容映射对人群 |
| 6 | brief 自带人群描述（第 0 部分） | 编导一份文档够用，不回头翻画像 |
| 7 | 每步停等老板反馈 | 项目通用约束 |
| 8 | 4 条铁律全遵守 | @tool_with_audit / 返 trace / prompt 外置热加载 / 👍👎 出口 |

## 4. 组件设计

### 4.1 step 2 提示词打磨（只改 `selling_points_matrix.system.md`）

1. **三层拆解**：1.1 显性 / 1.2 隐性 / 1.3 USP 每条卖点增加一行「功能层 → 利益层 → 价值观层」（例：天然米糀发酵 → 口感柔和配料表干净 → 对家人健康负责）
2. **买点视角**：每条卖点增加一行「用户买它的真实理由（买点）」——从"我有什么"翻成"他为什么掏钱"
3. **USP 更尖**：1.3 排他性检验加狠——竞品反证必须列 ≥2 个具体竞品（可引 `competitor_search`/`competitor_decompose` 的调研数据，没有就明说"搜证缺口"）；新增「排他性 / 可感知 / 可演示」三轴 1-5 评分；推荐主打 USP 必须三轴均 ≥4 才能上，否则明说"本 SKU 暂无够格 USP，建议主打组合卖点"
4. **真需求挖场景**：2.1 每个使用场景增加一行「该场景下的真需求」（用户到底要解决什么）；2.2-2.5 各心智判断必须挂回具体真需求，不许悬空

输出 5 大部分结构不变，下游 step 3 的 regex/锚点不受影响。第七节自检清单同步补对应检查项。

### 4.2 step 3.5 `generate_audience_portrait`

**签名**：

```python
async def generate_audience_portrait(
    audience_record_id: str,        # step 3 选中的人群，反查 audience_run/matrix_run/sku 全血缘
    extra_context: str | None = None,
    kb_recall_override: str | None = None,  # 手动塞检索结果，绕过自动检索（同 step 3 逃生口）
) -> dict
```

**定向检索**（四路并发，复用 step 3 的 `_multi_query_recall` / `_format_kb_recall` 基建，目标 KB 同 step 3 的人群分析报告 KB）：

| 路 | query 构造 | 配额 | 目的 |
|---|---|---|---|
| ① 本圈层深挖 | record.kb_doc 文档名 + 人群名，开 `context_window=True` 拉邻块 | ≤30 | 该人群原文档完整章节（量级/属性/偏好/标签云） |
| ② 生活维度扫描 | 人群名/圈层标签 × 固定后缀：日常作息、内容偏好、触媒习惯、消费决策、价格敏感、家庭角色、节点场景、兴趣爱好、标签云、热点内容、BGM 偏好 | ≤24 | 生活状态原料 + 算法信号原料 |
| ③ 情绪交叉 | 人群名 × 八大情绪人群（打《8大情绪人群运用指南》） | ≤12 | 这群人吃哪种情绪，供 brief 起伏设计 |
| ④ 卖点反打 | matrix 的 USP + 推荐主打卖点做 query | ≤12 | 卖点 ↔ 真需求共振证据，供卖点重构 |

合计 ≤78 chunks，按文档分桶轮询去重，`rerank=True`。每 chunk 带 `[来源: 文档名]` 头注入。

**输出模板（portrait_md，5 部分）**：

- **第 0 部分 · 人群速写**：150 字，"这是谁、量级、一句话生活底色"，全 KB 锚
- **第 1 部分 · 生活状态画像**（核心）：
  - 1.1 身份与日常节奏：工作日 + 周末两条时间轴，触达窗口标 ⭐
  - 1.2 生活场景库 ≥6 个：具体到"周三晚 8 点半，出租屋开放式厨房"级别，每个场景标可承载的矩阵卖点节号
  - 1.3 内容消费与触媒：平台 / 内容形态 / 看什么会停下——**同时产出算法信号原料**：高频内容元素、标签云、搜索词、BGM 风格偏好（KB 硬锚优先，此小节 KB 最有料）
  - 1.4 消费决策：知道→犹豫→下单路径、价格敏感度、谁影响他
  - 1.5 情绪底色：在意什么、焦虑什么、"心里一直有但不怎么说的东西"
- **第 2 部分 · 该人群专属卖点重构**：从 matrix 挑 3-5 个最响卖点，每个「功能层→利益层→价值观层」+ 🔥1-5 匹配度 + **"对这群人说的那句话"**（口语、主语是人不是产品）
- **第 3 部分 · 情绪触点矩阵**：正向触点 ≥4（触发场景+内心独白+对应卖点）/ 负向阻断点 ≥3（必须带化解话术）/ 最佳触达时间窗
- **第 4 部分 · 信息缺口**：KB 哪块没料、⚠️ 用了几处、建议补什么

**防臆想三道闸**：

1. 逐句标记强制：事实性陈述句尾 `[KB:文档名]` / `🧠推演` / `⚠️推测` 三选一；推演必须写明从哪个 KB 锚点推（例：`🧠 由 [KB:赛博食客] "深夜美食内容播放峰值" 推演其 22 点后为触达窗口`）；无标记 = 违规
2. 配额闸：第 1 部分每小节 `[KB]` 占比 ≥50%；`⚠️推测` 全文 ≤5 处，超了说明检索没料，提示补 KB 而不是硬编
3. 输出前自检（写进 system prompt 尾部）：没编 KB 不存在的数据；时间轴/场景与圈层 KB 属性（年龄/城市/消费力）不矛盾；无 AI 套话；生活细节具体到"能拍出来"

**模型**：gemini pro 级，temperature 0.4，max_tokens 10000，timeout 300s。

**返回**：`{ok, result:{portrait_md, sku_id, audience_record_id, portrait_id, recall_meta}, trace, next_step_hint:{suggested_tool:'generate_director_brief', suggested_args:{portrait_id}}}`

**prompt 文件**：`config/prompts/audience_portrait.{system,user}.md`（V4.1 裁剪产品化：保留可信度标注/质量锚定/纪录片式描述原则，砍掉 21 维全量/竞品逆向/反向画像/多轮对话指令）。

### 4.3 step 3.6 `generate_director_brief`

**签名**：

```python
async def generate_director_brief(
    portrait_id: str,               # 反查 record/matrix/sku 全血缘
    idea_seed: str | None = None,   # 可选"想拍的事"；不给则 LLM 从画像场景库自选"一件事"
    include_ai_mapping: bool = True,
    extra_context: str | None = None,
    num_variants: int = 1,          # 1-3 并行创意方案，temperature 递增 +0.1（照 creative_pack 机制）
) -> dict
```

**输出模板（brief_md）**：

- **第 0 部分 · 这条视频拍给谁**（人群描述，300-500 字）：他是谁/量级/生活状态要点/爱看什么/情绪底色/为什么这个产品跟他有关。**只许从 portrait 浓缩，不许新增画像里没有的事实**
- **第 1 部分 · 今天拍什么**：拍给谁看（一句大白话）/ 拍的什么事（一件事原则，不出现产品名）/ 看完观众什么感觉 / 两次"偏"在哪（第一次偏让人笑或有感觉、第二次偏安静地品；起伏≠反转）/ 种的卖点 1-2 个 + 各藏在哪个瞬间（引用 portrait 第 2 部分重构表达 + 三种嵌入方式：对话情绪缝隙/笑点画面/结尾安静画面）/ 产品在哪自然出现
- **第 2 部分 · 分段拍摄备忘**（每段）：拍什么（大白话）/ 手机放哪谁拍 / 说了什么（台词死规矩：≤15 字一句、有语气词、该打断就打断、主语是人不是产品、全片产品信息 ≤2 句且单句 ≤1 个信息点、没人在家里"介绍"东西）/ 注意的事 / 💭 刷到这里的人在想什么
- **第 3 部分 · 算法信号三向量**（每条标 `[KB:...]` 或 `🧠`，不许拍脑袋）：
  - 画面向量：必须入画的可识别视觉元素清单（场景/道具/人物类型/动作），每个标"对应该人群哪个内容偏好"
  - 文案向量：标题/字幕/话题标签/评论引导词里埋的人群信号词——用这群人自己会搜会说的词（锚 portrait 1.3）
  - 音乐向量：BGM 风格方向 + 2-3 个曲风候选，按人群年龄段/情绪基调选（锚 portrait 第 3 部分）；表面"随手选的热门歌"，实际选这群人信息流里正在火的那种
- **第 4 部分 · 发的时候**：标题候选 3 个（不提产品，套用文案向量信号词）/ 封面截哪帧 + ≤8 字 / 评论区置顶（不放链接不提价格不罗列卖点）
- **第 5 部分 · AI 出片映射**（include_ai_mapping=True 时）：每段 → `image_prompt`（首帧）+ `last_frame_prompt` + `motion_prompt`（英文），用 creative_pack 已有「短视频真人感锚」（手持微晃/窗光/9:16/iPhone 质感，禁 cinematic 电影锚），画面向量元素同步写进 image_prompt；格式对齐 step 6/7 输入
- **尾部 · 自检结果**（逐项打勾输出）：V7.2 原 9 项（去掉产品还能发吗 / 两次偏从人物真实反应来 / 无关真实细节有没有 / 信息密度 ≤2 句 / 新旧对比检测 / 禁用词 8 类 / 评论区合规等）+ 新增 3 项：三向量每条有来源标记；信号不破坏真实感（要硬塞道具/硬改台词才能加的信号一律砍，真实感优先——完播和互动本身是最强算法信号）；第 0 部分无画像之外新事实

**模型**：gemini pro 级，temperature 0.7，max_tokens 12000（含 AI 映射段较长），timeout 300s。

**返回**：`{ok, result:{brief_md（或 variants 数组）, sku_id, portrait_id, script_id}, trace, next_step_hint:{suggested_tool:'generate_storyboard_images'（include_ai_mapping 时）}}`

**prompt 文件**：`config/prompts/director_brief.{system,user}.md`（V7.2 方法论主体沉入 system：四大特征/六步工作流/起伏对照表/台词画面产品死规矩/像真的vs像背的对照表/禁用词 8 类；user 注入 portrait_md + SKU 信息 + idea_seed + extra_context）。

## 5. 数据库变更（migration 047_audience_portraits.sql）

```sql
CREATE TABLE IF NOT EXISTS pipeline.audience_portraits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audience_record_id UUID NOT NULL REFERENCES pipeline.audience_records(id),
    audience_run_id UUID REFERENCES pipeline.audience_runs(id),
    matrix_run_id UUID REFERENCES pipeline.matrix_runs(id),
    sku_id TEXT NOT NULL,                 -- denorm，复盘不 join
    portrait_md TEXT NOT NULL,
    recall_meta JSONB,                    -- 四路检索 queries + chunk_count
    final_prompt TEXT,
    extra_context TEXT,
    model_provider TEXT, model TEXT, cost_estimate TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','adopted','archived')),
    version INT NOT NULL DEFAULT 1,
    parent_portrait_id UUID REFERENCES pipeline.audience_portraits(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_portraits_sku ON pipeline.audience_portraits (sku_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_portraits_record ON pipeline.audience_portraits (audience_record_id);

-- scripts 表：kind 枚举加 director_brief + 挂 portrait
ALTER TABLE pipeline.scripts DROP CONSTRAINT IF EXISTS scripts_kind_check;
ALTER TABLE pipeline.scripts ADD CONSTRAINT scripts_kind_check
    CHECK (kind IS NULL OR kind IN (
        'video_soft_ad','video_planting','video_harvest',
        'graphic_harvest','product_main_image','product_detail_page',
        'director_brief'
    ));
ALTER TABLE pipeline.scripts ADD COLUMN IF NOT EXISTS portrait_id UUID REFERENCES pipeline.audience_portraits(id);
```

实施时以 021/023 的实际列名约定为准核对（字段命名跟 matrix_runs/audience_runs 对齐）。`pipeline_adopt` 的允许表清单加 `audience_portraits`。多版本约定同现有：重跑 = 新行，version 自增 + parent_portrait_id 串前后，不覆盖。

## 6. 老板话术 → tool（实施完成后补进 CLAUDE.md）

| 老板说 | Claude 应做 |
|---|---|
| "给这个人群出画像 / 选第 N 个出生活状态 / 深挖这个人群" | `generate_audience_portrait(audience_record_id)` |
| "给 X 出编导 brief / 拍摄 brief / 给编导下个 brief" | 链路缺啥跑啥：没画像先 3.5，有了直接 `generate_director_brief(portrait_id)` |
| "想拍闺女给妈寄酱油那种" | `generate_director_brief(..., idea_seed='闺女给妈寄酱油')` |
| "不要 AI 那段" | `include_ai_mapping=False` |
| "再来一版 / 换个创意" | 同 portrait 重跑 3.6（新版本落库）或 `num_variants=2-3` |

## 7. 错误处理

- 链路断（record/portrait 查无、缺 matrix/sku 血缘）→ 明确报错 + 提示先跑哪步
- 检索空/料薄 → 不硬编：照常出但第 4 部分（portrait）/自检（brief）明列缺口，`recall_meta.chunk_count` 供判断；⚠️ 超配额时输出顶部加横幅提示"该人群 KB 料薄，建议补充圈层文档后重跑"
- LLM 失败 → 照现有模式返 trace + 错误；落库失败 fail-open（结果照常返，warning 日志）
- prompt 文件缺失 → prompts.render 现有报错路径

## 8. 测试与验收

1. doctor 自检 `all 80 ok`（78 + 2）
2. migration 047 上库后 `\d pipeline.audience_portraits` 结构核对；scripts 的 kind 约束含 director_brief
3. 端到端：真 SKU（建议 SKU-375753-0001 辣酱油）走 step 2（打磨后 prompt）→ step 3 → 选 1 个人群 → 3.5 → 3.6，验收：
   - portrait 标记配额达标（第 1 部分各小节 [KB] ≥50%、⚠️ ≤5）；生活细节"能拍出来"；卖点重构的话是口语
   - brief 自检 12 项全过；台词读起来像人话（老板亲自读）；三向量每条有来源
   - include_ai_mapping 的第 5 部分能直接喂 `generate_storyboard_images` 不报格式错
   - 血缘：从 scripts 行反查 portrait → record → audience_run → matrix_run → sku 全通
4. trace 完整（final_prompt 可看）；`mcp.tool_calls` 落审计行
5. step 2 打磨回归：重跑一个已有 SKU 对比新旧 matrix 输出，确认 5 部分结构未破坏、下游 step 3 正常消费

## 9. 风险

- **KB 料薄圈层**：部分圈层文档内容偏宏观，生活细节原料不足 → 防臆想闸会把它显性化（⚠️ 超配额 + 缺口清单），老板按提示补 KB，不静默硬编
- **算法黑盒**：三向量按"算法识别画面物体/文本/音乐归类兴趣池"的公认机制设计，无法保证分发效果 → 信号全部 KB 锚 + 投后 record_ad_metrics 回传验证，转化数据永远压过设计假设
- **长输出截断**：brief 含 AI 映射段较长 → max_tokens 12000 + 自检在尾部（截断时一眼可见缺自检段 = 不完整）
