---
name: short-video-director-brief
description: Use when老板要把和田宽/SKU/已圈人群包或人群画像转成给真人短视频编导、内容策划、拍摄团队执行的种草 Brief；尤其出现“给编导下 brief”“编导看不懂怎么拍”“人群理解＋拍摄脚本”“按这个100万人群包拍什么”“一次至少十条”“扩充内容类型”“给真人团队准备拍摄素材”等话术。输出人群理解、痛点场景、至少10种不同观看机制和至少10条五段式可拍脚本。不要用于人群包诊断提纯、纯AI/Seedance出片、普通单条文案、摄影机位施工单或竞品视频反推。
compatibility: omni MCP tools; Python 3 for deterministic validation
---

# short-video-director-brief：真人短视频编导 Brief

## 目标

把已经确认的商品、卖点、人群和知识库信息，翻译成短视频编导真正能执行的两部分交付：

1. **人群理解**：这群人在过什么生活、痛点在哪、什么场景会产生共鸣、产品能和不能解决什么。
2. **拍摄脚本**：按不同“观看机制”展开内容类型，每批至少 10 种类型、至少 10 条完整脚本，每条都能直接试拍。

这个 Skill 解决的是“给真人内容团队下什么 Brief”。它不负责圈包、提纯、AI 出片、摄影技术施工或单条文案。

## 使用前必读

创建新 Brief 时读取：

- `references/content-types.md`：内容类型目录、去同质化规则和选型方法。
- `references/fact-boundaries.md`：事实等级、人群/商品/证据边界。
- `assets/director-brief-template.md`：最终 Markdown 结构。
- `assets/brief-manifest.template.json`：未来血缘和自动验收所需的结构化伴生文件。

修改已有 Brief 时也先读前两份参考，再保留用户已经确认的内容，只改用户指出的问题。

## 路由边界

| 用户真正要什么 | 路由 |
|---|---|
| 真人短视频团队 Brief：人群理解＋批量内容类型＋拍摄脚本 | 本 Skill |
| 单独一条视频脚本、直播话术、图文文案 | `script-writer` |
| 纯 AI、Seedance/Veo/即梦脚本或直接出片 | `soft-ad-ai-video` / `generate_creative_pack` |
| 从 SKU 跑卖点、人群、圈包前链路 | `sku-pipeline` |
| 已有包诊断、提纯、缩量级 | `audience-pack-diagnosis` |
| 从零圈一个新包 | `crowd-sop` |
| 拆竞品视频“怎么拍” | `video-reverse` |

如果用户从真人 Brief 改成纯 AI 出片，停止本流程并重新路由；不要把 `director_brief` 强塞进 AI step 7。

## 必要输入

尽量复用现有血缘，不要求用户重复提供系统已经有的数据：

| 输入 | 优先来源 |
|---|---|
| SKU 事实 | `get_sku` |
| 卖点矩阵 | adopted `matrix_run_id` / `pipeline_get_matrix_run` |
| 已圈人群 | `audience_record_id` / `pipeline_get_audience_record` |
| 圈包结果 | `audience_pack_id` / `pipeline_get_audience_pack` |
| 生活状态画像 | 已有 `portrait_id`；没有才 `generate_audience_portrait` |
| 人群包实际画像 | 用户导出的云图画像或已整理摘要 |
| 内容方法与案例 | `search_kb` / `query_template_chunks` / 用户指定材料 |
| 临时约束 | 演员、场地、时长、菜品、禁词、已审核证据 |

先校验 SKU、matrix、record、pack、portrait 是否属于同一条血缘。不一致时停止生成，列出冲突 ID，不能拼接不同 SKU 或不同人群的数据。

## 标准流程

### 1. 判断工作模式

- **新建模式**：从 SKU/人群血缘生成完整 Brief。
- **修改模式**：用户正在点评已有 Brief。直接按反馈改现有文件，不重新跑整条前链路，不丢掉已确认内容。
- **预览模式**：用户明确说“先看 2-3 条试方向”。可以少于 10 条，但必须标为“方向预览，不是正式交付”。
- **正式交付模式**：默认至少 10 种内容类型、至少 10 条完整脚本。用户已把它定义为项目交付下限，不能用 3 条同类脚本或换开头凑数。

若用户说“直接完整给我 / 一次给完”，跳过中间确认点；否则先交付“人群理解＋内容类型矩阵”，确认后再生成全批脚本，避免一次烧 10 次真人 brief 调用后方向仍不对。

### 2. 锁定事实和血缘

1. 用 `get_sku` 读取品名、规格、状态、owner facts。
2. 优先找 adopted/latest 的 matrix、audience record、pack、portrait，不重跑已有产物。
3. 没有画像时先调用 `generate_audience_portrait(audience_record_id)`；画像失败就返回 `blocked_missing_portrait`，不要用通用男性画像补写脚本。
4. 若人群包约 100 万且老板已确认“适合种草、不需要提纯”，记为 `[项目确认]`：
   - 不调用 `diagnose_audience_pack`；
   - 不调用 `audience-pack-sizing`；
   - 不写收窄、切包、缩量级建议。
5. 用商品名、品类、人群状态检索 authoritative、methodology、private_doc 和模板 KB。案例只提炼结构，不照抄完整脚本，也不虚构播放量、转化率或品牌表现。

### 3. 写第一部分：人群理解

按模板输出：

1. 30 秒人群摘要。
2. 已知信号表：`已知信号 / 对编导意味着什么 / 不能推导成什么`。
3. 本轮要测试的生活状态和生活心理。
4. `痛点 / 场景 / 开头发生的具体事件 / 产品怎么进入 / 观众最后看懂什么` 映射表。
5. 选角、表演和语言原则，只写内容状态，不写机位、焦段、灯光。

必须明确：

> 生活场景负责共鸣；产品只解决使用理解、换购理由和证据理解，不解决疲惫、孤独、家庭分工、亲子关系或厨艺。

人群描述可以丰富，但避免重复。生活状态、心理拉扯和痛点场景不要用三张表重复说同一件事。

### 4. 建立内容类型矩阵

内容类型按“观众为什么继续看”划分，不按场景或卖点划分：

- 家庭、单人、晚归、周末、厨房、餐桌是**场景**。
- 套组、配料表、有机、180 天是**选题主题**。
- `STORY / VLOG / COMEDY / HOWTO / ASMR / QNA / PROOF` 等才是**内容类型**。

正式批次规则：

- 至少 10 个唯一内容类型。
- 至少 10 条完整脚本。
- 每种类型至少一条脚本；同一类型写三条仍只算一种。
- 先覆盖 10 种观看机制，再给高匹配类型增加变体。
- 只换开头、演员、菜品或家庭/单人场景，不算新类型。
- 某类型所需事实不成立时换类型，不能为了凑数编商品证据。

从 `references/content-types.md` 选择 10-14 种最适合当前人群的类型，并为每种写清：`type_code / 类型名 / 核心观看价值 / 解决的购买疑问 / 适配的人群状态`。

### 5. 生成每条真人编导脚本

如需现有数据库血缘，对每种内容类型分别调用一次：

```python
generate_director_brief(
    portrait_id="<portrait_id>",
    include_ai_mapping=False,
    intent="planting",
    num_variants=1,
    idea_seed="<该类型的一件具体生活事件>",
    extra_context="<类型代码、观看价值、痛点、场景、五段短视频编导格式、事实边界>",
)
```

一次生成 10 条时按 3 条一波并发。不要传 `num_variants=10`（上限为 3）；`portrait_ids` 是多人群批量，不是一个人群生成十种类型。

不调用 AI 提示词、故事板、定妆照或视频段工具。`include_ai_mapping=False`。

每条最终脚本必须包含：

- 编号、类型代码、类型名、标题、建议时长。
- 对应人群状态、共鸣痛点、使用场景。
- 产品要回答的唯一购买问题。
- 核心观看动力和前 3 秒事件钩子。
- 五段表：`段落 / 时段 / 画面中实际发生什么 / 台词或字幕 / 产品怎么进入`。
- 表达边界；证据型内容还要写开拍审核前置。

五段必须是现场能拍到的动作、对白或结果。禁止“情绪升华、建立心智、氛围拉满”等抽象导演语言。

### 6. 事实与证据审核

统一使用以下标记，并逐句标注：

- `[人群包数据]`
- `[项目确认]`
- `[商品事实]`
- `[KB:文档名]`
- `[创意假设]`
- `[实测]`
- `[待审核]`

一句话同时包含事实和推演时，拆成两句分别标记。禁止 `[人群包数据＋创意假设]`、`[商品事实＋创意假设]` 这类混合标签。

证据规则：

- 人群比例不是每个人都符合。
- “愿意买更好的”“担心四瓶太多”没有直接数据时，只能是 `[创意假设]`。
- 食物颜色、味道、第二筷等是 `[实测]`，不能变成普遍口味结论。
- 有机、180 天、33 年、配料表不含白砂糖等，仅在当前瓶身或审核材料支持时使用。
- 一条证据片只核验一个事实；资料不足就取消，不让演员用口播补证据。
- 禁止把“不含白砂糖”写成“无糖/零糖”，把有机推导成健康、无农残或儿童/孕妇适合。

完整红线见 `references/fact-boundaries.md`。

### 7. 保存两个交付物

1. **团队阅读版 Markdown**：使用 `assets/director-brief-template.md`。
2. **结构化 manifest**：使用 `assets/brief-manifest.template.json`，记录 source IDs、类型、脚本、claims、blocked_claims 和当前血缘完整度。

文件名建议：

```text
YYYY-MM-DD-<SKU或别名>-<人群名>-短视频编导Brief-vN.md
YYYY-MM-DD-<SKU或别名>-<人群名>-短视频编导Brief-vN.manifest.json
```

已有文件被 WPS/Word 等占用时，不关闭用户应用、不强行覆盖；创建新版本并在旧入口放跳转说明。

### 8. 确定性验收

生成后运行：

```text
python scripts/validate_brief.py <brief.md> --manifest <brief.manifest.json>
```

正式交付必须通过：

- 恰好两个主体部分：人群理解、内容类型与脚本。
- 至少 10 个唯一内容类型。
- 至少 10 条完整脚本，编号连续。
- 每条严格五段，且有台词/字幕和产品动作。
- 场景词没有冒充内容类型。
- 不出现混合事实标签。
- 不出现 2.7、2.8、交付矩阵或摄影执行附录。
- 不出现帧率、焦段、白平衡、机位图等摄影施工参数。

确定性检查通过后，再人工核对所有商品主张是否能追到 SKU、KB、瓶身或审核材料。结构通过不等于事实自动通过。

## 输出与血缘说明

完成后固定汇报：

- `sku_id / matrix_run_id / audience_record_id / audience_pack_id / portrait_id`
- 内容类型覆盖数、脚本数。
- `script_id ↔ type_code` 对照；只有实际调用并落库的才列 `script_id`。
- compiled Brief 路径和 manifest 路径。
- 使用了哪些 KB/source，以及哪些主张被阻断。
- `lineage_status`：`full / partial / local_only`。

当前 MCP 的真实能力：

- `generate_audience_portrait` 可落 `pipeline.audience_portraits`。
- 每次 `generate_director_brief` 可落一条 `pipeline.scripts(kind='director_brief')`，挂 portrait/record/matrix/SKU 血缘。
- 可用 `pipeline_adopt(table='scripts')` 逐条采纳，或用 `experiment_adopt_script` 挂真人 brief 实验臂。

当前不能宣称：

- 汇编的整批 Markdown 已整体落库。
- 已有 `brief_batch_id`、独立 MCP 血缘分支或可检索 batch 父节点。
- 最终 Brief 已直接挂 `audience_pack_id`。

如果只生成本地汇编文件，标 `lineage_status=partial` 或 `local_only`。不要用 `save_decision` 冒充脚本血缘。

## 缺数据和失败分支

| 情况 | 处理 |
|---|---|
| SKU 找不到或同名多个 | 列候选并停止，不猜 |
| 人群包找不到 | 列历史 pack 供选择，不用通用画像替代 |
| 血缘 ID 不一致 | 返回冲突字段并停止 |
| 画像缺失 | 先 `generate_audience_portrait`；失败则 `blocked_missing_portrait`，脚本数为 0 |
| 商品证据不足 | 删除或替换 `PROOF`，用其他内容类型保持类型覆盖 |
| 不是套组 | 不用 `UNBOX_PLAN`，换其他类型 |
| 外部案例不可访问 | 只用已知通用结构，不虚构案例品牌和数据 |
| 人群规模已确认合适 | 不诊断、不提纯、不 sizing |
| 用户要求少于 10 条 | 若是预览则允许并明确非正式；正式交付仍遵守项目下限 |

## 禁止

- 禁止把场景数量当内容类型数量。
- 禁止只换开头凑十条。
- 禁止把产品写成解决疲惫、孤独、家庭关系或厨艺。
- 禁止使用没有来源的价格、优惠、销量、回购率、检测、认证或功效。
- 禁止把真人 Brief 写成 Seedance/Veo 提示词。
- 禁止在正文加入 2.7、2.8、摄影参数、场记和素材备份说明。
- 禁止声称 Skill v1 已经实现新的 MCP batch 血缘。
