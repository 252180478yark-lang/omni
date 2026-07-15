# 种草短视频 Agent 全链路对齐软广设计

日期：2026-07-15

状态：用户已批准，待实施

适用仓库：`omni`

## 1. 本期结论

本期不新建第二套视频链路。种草与软广共用同一套编排、状态、资产、实验和回传底座，只通过内容类型配置分流：

- 软广：`kind=video_soft_ad`、`intent=soft_ad`，面向 O/A1，强调内容可看性与轻植入，以完播率为北极星。
- 种草：`kind=video_planting`、`intent=planting`，面向 A1/A2→A3，强调“人群画像—场景—痛点—产品解决动作—可见结果—可信理由”，以 A3 转化率为北极星。

两类视频共享以下主链：

`血缘检查 → 内容桥提炼 → 脚本候选 → 内容硬闸 → 采纳挂臂 → 角色定妆 → 产品参考图 → 最终提示词 → 投前向量闸 → 视频段生成 → 投后向量闸 → 资产采纳 → 指标回传 → winner → 下一轮单变量`

本期交付边界是 Agent 对话能够跑通到可下载的视频段，并能继续挂臂、回传和迭代。前端页面、自动拼接、配音、字幕和最终 MP4 不在本期范围。

本规格是 `2026-07-13-ai-soft-ad-planting-experiment-loop-design.md` 的窄范围实施规格。两者冲突时，本期以这里的范围为准；总设计中的前端和最终成片能力后续单独实施。

## 2. 目标与非目标

### 2.1 必须实现

1. Agent 能从已有 SKU 血缘继续生成种草视频，不让用户重复填写已有画像、卖点或圈包信息。
2. 用 `gemini-3.1-pro-preview` 从前链路提炼结构化“痛点—解决桥”，再生成种草脚本。
3. 种草脚本必须体现目标人群在真实场景里的具体痛点，以及产品用什么可见动作解决了它。
4. 种草保留自己的方法论：一个相关性模块 `M1/M2` 加一个论证模块 `M3–M9`；不得退化成软广换标题，也不得写成收割广告。
5. 脚本通过种草专属硬闸并被用户采纳后才挂实验臂；视频资产生成时必须带 `experiment_arm_id`。
6. 视频生成前对最终提示词做向量相似预估，生成后对实际视频做向量相似预估；两道闸均须 fail-close。
7. 提示词尽可能保留人物、场景、产品动作、时间线、镜头和声音细节，同时防止超过模型有效承载范围。
8. 投后支持 A3 转化率、CPM、完播率和 3 秒播放率；种草 winner 只按 A3 北极星判断。
9. 指标诊断能确定性推荐下一轮只改哪个变量，并保留所有历史版本和失败资产。
10. 软广现有行为不得因共享改造而回归。

### 2.2 本期不做

- 不增加可见前端界面。
- 不自动拼接视频段，不输出最终 MP4。
- 不自动发布或自动烧投放费用。
- 不用向量分替代真实投后 A3。
- 不在一次实验轮同时改多个内容变量。
- 不因种草内容问题重新圈人群包。
- 不把软广和种草合并成同一套内容 prompt。

## 3. 共享内核与类型配置

新增一个共享的视频意图配置层，编排只读取配置，不在各工具中散落 `if planting` 特例。

| 配置项 | 软广 | 种草 |
|---|---|---|
| kind | `video_soft_ad` | `video_planting` |
| intent | `soft_ad` | `planting` |
| 漏斗任务 | O/A1 内容触达 | A1/A2→A3 认知建立 |
| 默认总时长 | 25–30 秒 | 30–45 秒 |
| 内容核心 | 可看性、生活流、轻植入 | 人群场景、具体痛点、产品解决、可信结果 |
| 方法论 | 软广生活流框架 | `M1/M2 × M3–M9` |
| 硬 CTA/价格 | 禁止 | 禁止 |
| 北极星 | `completion_rate` | `a3_ratio` |
| 诊断指标 | `play_3s_rate`、完播 | `play_3s_rate`、完播、CPM |
| 内容桥 | 可选 | 必填 |
| 投前/投后向量闸 | 共用 | 共用，种草维度有专属语义 |

共享配置至少包含：允许的 `kind/intent` 组合、北极星、诊断指标、硬闸阈值、提示词预算、向量维度、内容 prompt 路径和下一变量映射。配置通过明确扩展点接入共享编排：

- `bridge_extractor`：种草使用痛点—解决桥提炼器；软广使用自己的桥或 no-op。
- `content_gate`：各视频类型只运行自己的内容硬闸。
- `vector_dimensions`：共享向量引擎读取类型维度，不在引擎内部判断 planting。
- `metric_policy`：定义北极星、诊断指标、分母和下一变量策略。
- `prompt_profile`：定义方法 prompt、时长和容量窗口。

因此“共享内核”不等于把种草规则施加给软广，也不允许在各工具里继续堆散落的 `if planting`。

## 4. Agent 对话流程

### 4.1 阶段 A：血缘检查

Agent 先解析并展示本次使用的：

- `sku_id`
- `matrix_run_id`
- `audience_record_id`
- `portrait_id`
- `audience_pack_id`（有则继承，没有不伪造）
- 已采纳卖点及证据来源
- 产品参考图
- 当前脚本、实验、轮次和资产状态

下游只允许沿已采纳的关键血缘继续。缺少能够支持“人群痛点—产品解决”的事实时返回最靠前的阻塞项，不静默用通用营销话术补齐。

### 4.2 阶段 B：提炼痛点—解决桥

提炼模型固定为：

- model：`gemini-3.1-pro-preview`
- temperature：约 `0.2`
- 输出：结构化 JSON
- 输入：前链路画像、卖点矩阵和真实 SKU 字段
- 失败策略：失败即阻塞，不静默降级到 Flash

模型名和参数通过现有模型配置加载，不能散落硬编码；本期配置值固定为上述模型。

它只提炼内容原料，不直接写脚本。每个候选桥必须包含：

```json
{
  "audience_segment": "目标人群及生活状态",
  "portrait_evidence": [{"source": "portrait/record", "field": "字段", "value": "事实"}],
  "pack_calibration_evidence": [{"field": "字段", "value": "只校准人物、语言或视觉质感"}],
  "trigger_scene": "具体到人物、时间、地点和正在做的事",
  "pain_point": "该场景中可被观察到的具体麻烦",
  "pain_consequence": "不解决会造成的实际结果或心理阻力",
  "product_action": "产品在画面里实际执行的动作",
  "visible_result": "动作后观众能看到或听到的变化",
  "product_evidence": [{"source": "sku/matrix", "field": "字段", "value": "事实"}],
  "belief_shift": "看完后应形成的 A3 认知",
  "relevance_module": "M1 或 M2",
  "justification_module": "M3–M9 之一"
}
```

确定性校验要求：

- `pain_point` 必须能追溯到 portrait 或 audience record 证据，不能只凭 audience pack 推导。
- `product_action` 和 `visible_result` 必须能追溯到 SKU 或卖点证据。
- 画像提炼出的痛点不能被云图实际包的校准信息覆盖；实际包只校准人物、语言和视觉质感。
- 不允许把属性名直接当痛点，不允许把卖点口号直接当解决结果。
- 无来源字段标记 `missing` 并阻塞，不由模型补造。

### 4.3 阶段 C：生成脚本候选

脚本继续通过 `generate_creative_pack(kind='video_planting', intent='planting')` 生成，模型保持 `gemini-3.1-pro-preview`。

首轮默认生成两个单变量候选：

- 固定 SKU、人群、角色、卖点、产品证据、时长、目标模型、相关性模块和论证模块。
- 只改变 `pain_scene_bridge` 的表达取值。
- 每条候选分别落库，保存完整血缘、结构化内容契约和校验结果。

种草脚本的内容顺序不是固定台词模板，但必须形成以下语义链：

`前链路人群画像 → 真实生活场景 → 具体痛点 → 产品实际动作 → 可见解决结果 → 为什么可信 → A3 认知`

`M1/M2 × M3–M9` 是这条语义链的表达方法，不是凭空发现痛点的来源。

### 4.4 阶段 D：脚本硬闸与用户采纳

种草脚本必须同时通过：

- `portrait_scene_alignment_score >= 80`
- `pain_specificity_score >= 80`
- `product_solution_fit_score >= 80`
- `product_action_visible = true`
- `solution_result_visible = true`
- `justification_grounded = true`
- `belief_shift_present = true`
- 脚本向量总分及关键“人群↔内容”“产品↔内容”边均 `>= 70`
- 无硬 CTA、无价格促销、无虚构资质、无伪消费者证言

这些是硬闸，不是 warning。失败的脚本保持 `draft`，不能生成定妆或视频。

用户采纳后再调用现有实验能力挂臂。顺序固定为：

1. 脚本生成与硬闸。
2. 用户采纳脚本。
3. 脚本进入本轮实验臂。
4. 后续角色定妆和视频资产均携带该臂 ID。

这样既避免给不合格脚本烧视频，也确保视频从出生起就有实验归属。

首轮两个被采纳的候选必须进入同一个 experiment 和同一个 round，`swept_variable=pain_scene_bridge`，各自的桥取值写入 `variable_value`。为消除“自动找到哪一轮”的歧义，`experiment_adopt_script` 增加可选的 `experiment_id` 和 `round_no`：第一个候选返回这两个值，第二个候选必须显式回传并通过 SKU、intent、track、轮次和 swept variable 一致性校验。只采纳一个候选时可以继续试生成，但该轮只能标记为单臂草稿，不能比较或锁 winner，也不能对外称为 A/B 已建立。

### 4.5 阶段 E：定妆、产品图和最终提示词

沿现有软广链调用：

1. `generate_character_sheets(script_id, experiment_arm_id=...)`
2. 校验产品参考图存在、可读、属于当前 SKU，并会实际传给视频 provider
3. 从脚本提示词块编译“最终送模提示词”
4. 对最终提示词运行投前向量闸
5. `generate_video_segments(script_id, experiment_arm_id=...)`

角色定妆资产保存同一个 `experiment_arm_id`。产品参考图本体是 SKU 共享资产，不复制、不改归属；每次视频生成在引用清单中保存 arm、产品引用 ID、角色引用 ID、文件内容 SHA-256 和实际送给 provider 的内容 SHA-256。

provider 前必须比较 `expected_refs` 与最终请求的 `sent_refs`：角色定妆图必须作为 face refs，产品白底图必须作为 product refs，ID 与哈希完全一致。种草和软广在强制产品引用时禁止使用会清空 refs 的 `force_t2v` 路径；不能为了调用成功而偷偷降级成无参考 T2V。

全部角色定妆失败时顶层调用必须失败；产品参考图缺失、无效、SKU 不符、角色/产品引用未真正进入最终 provider 请求或运行时被清空时必须失败。不得返回可继续的 `ok=true`。

## 5. 提示词细节与容量策略

### 5.1 提示词结构

每个不超过 15 秒的视频段采用三层结构：

1. 固定锚：人物外形、服装、产品包装、空间、光线、画幅、镜头语言和连续性。
2. 连续时间线：按时间戳写人物动作、表情、产品动作、镜头变化、环境反馈、对白/环境声和最终可见结果。
3. 负向约束：人物漂移、手部畸形、产品包装变形、文字乱码、动作跳变、镜头穿帮等。

不得把画像原文、方法论说明或策略分析整段塞给视频模型。送模文本只保留模型能执行的可视、可听和时序指令。

### 5.2 初始容量窗口

模型公开资料没有可验证的精确字符上限，因此本期不把某个固定字数宣称为模型极限。Seedance 档案先使用按段时长线性缩放的可配置初始窗口：

- 硬下限：`ceil(duration_seconds × 50)` 个字符；15 秒时为 750。
- 推荐工作区间：`duration_seconds × 60–87` 个字符；15 秒时约为 900–1305。
- 初始硬上限：`ceil(duration_seconds × 107)` 个字符；15 秒时约为 1605。

字符数按最终送模字符串 Unicode code point 计数，包含时间戳、负向约束和引用指令，不包含 API 外层 JSON 与 system metadata。三个倍率必须放在模型档案或配置中，不能散落硬编码；初始上限只是临时安全阈值，不是模型真实极限。后续真实测试可直接调档案，不改业务逻辑。

编译器按以下优先级保护内容：

`产品和人物一致性 > 产品解决动作 > 时间线和关键镜头 > 场景细节 > 声音细节 > 修饰性描述`

超预算时只合并重复表达，禁止从尾部盲截断。低于下限、时间戳不连续、关键动作缺失、人物/产品锚缺失或出现矛盾时均阻塞。

### 5.3 后续真实容量试探

实现完成后另做 Seedance 阶梯测试，分别记录：

- API 接受上限：请求是否被接收。
- 有效遵循上限：新增细节是否仍被画面稳定执行。

测试以同一脚本逐档增加细节，不能同时换模型、时长、角色或产品。测试结果只更新模型档案和测试记录，不把单次经验写死在业务代码里。

## 6. 双向量闸

### 6.1 投前向量 `pre_video_match`

输入必须是压缩、补全和校验后的最终送模提示词，而不是原始脚本。分别与以下事实比较：

- 前链路人群画像
- 痛点—解决桥
- SKU 与卖点证据

维度为：

- 人群 ↔ 人物/场景
- 痛点 ↔ 冲突/麻烦
- 产品 ↔ 实际动作
- 结果 ↔ 痛点解除
- 论证 ↔ SKU 证据

每个最终提示词段按该段内容契约声明的适用维度评分；臂级总分按段时长加权。所有适用的关键维度必须 `>=70`，臂级总分也必须 `>=70`，并且整组提示词中至少有一个段明确承载产品动作和痛点解除。任何应生成段缺失、任何适用关键维度不通过，整组即失败。

每次投前结果必须绑定：

- `final_prompt_hashes`（有序的逐段哈希）
- `upstream_fact_hash`（画像、痛点桥和 SKU 事实的规范化哈希）
- `intent_profile_version`
- `embedding_model` 与 `embedding_version`

提示词修改、容量压缩、段顺序变化、上游事实变化或 profile/embedding 版本变化都会使旧分数失效，必须重算。未通过或哈希不再匹配时不得调用视频模型。

闸门接口和 Agent 展示统一使用 `0–100` 分。为兼容现有向量闭环，臂上的 `predicted_match_score` 继续保存归一化后的 `0–1` 值；读写边界必须显式换算，不能让 `70` 与 `0.70` 混用。该字段只保存这次最终提示词投前分，用于候选排序，不判 winner。

### 6.2 投后向量 `post_video_match`

视频生成前先建立逻辑 `generation_set`，保存有序的预期段清单、scene/segment 编号、目标时长和 prompt hash。视频生成后必须由 Gemini 读取实际视频文件，先提取可见/可听信号，再与同一组画像、痛点桥和 SKU 事实比较。每个视频段分别输出总分、适用维度分、缺失信号和漂移信号；整组视频按实际时长加权汇总，缺段直接失败。

- 总分或关键边 `<70`：资产保持 `draft`，不得采纳、发布或进入指标聚合。
- 技术问题（脸、产品包装、动作、运镜）可在同一 arm 内重渲染。
- 场景、痛点或产品解决逻辑发生语义变化时，必须生成新脚本并建立新 arm。

投后结果写入资产 `visual_prescreen.post_video_vector_gate`，不得覆盖臂级投前分。

每段投后结果必须绑定 `generation_set_id`、`video_file_hash`、对应的 `final_prompt_hash`、`upstream_fact_hash`、`intent_profile_version`、`judge_model` 和 `judge_version`。任一文件、上游事实或 judge 版本变化都使旧闸失效。

同一 generation set 可对失败段做技术重渲染；每个预期段只选择一个当前有效资产进入 `selected_assets`。只有预期段全部有已选资产且全部通过，group gate 才能从 `draft` 变为 `ready`。生成视频、整组采纳、单段发布、写入投后指标四个服务端入口都必须校验当前 generation set、哈希和 group gate；不能只依赖 Agent 按顺序调用。

Agent 汇报必须把四层分开：

`脚本向量分 → 最终提示词投前分 → 实际视频投后分 → 真实 A3`

## 7. 实验臂与资产状态

脚本和视频的状态语义：

- 脚本未采纳：`draft`，不挂正式视频资产。
- 脚本采纳：进入实验 arm。
- 新生成视频及其 generation set：`draft`。
- 技术不合格视频：`discarded` 或继续同 arm 重渲染，不进入指标。
- 全部预期段投后向量通过：generation set 进入 `ready`。
- 用户认可整组：generation set 及其 selected assets 在同一事务进入 `adopted`。
- 已实际发布：`published`。

现有聚合只读取 `adopted/published` 资产，本期延续这一规则。属于 generation set 的资产还必须是该组的 selected asset，且 group gate 当前有效。所有 discarded 和未选重渲染资产保留血缘供复盘，但永不参与 winner。

属于 generation set 的单段资产禁止用旧的单资产状态入口独立采纳；共享服务 `adopt_video_generation_set(generation_set_id)` 负责整组原子采纳。发布或写指标可以针对 selected asset，但前提是整组已经 `adopted` 且 group gate 仍有效。

`generate_character_sheets` 和 `generate_video_segments` 的顶层返回语义需与真实结果一致：全部失败时 `ok=false`；至少一个可用结果时才可 `ok=true`，部分成功还必须返回 `partial=true`、成功项、失败项和可继续条件；禁止“所有分段失败但顶层 ok=true”。

## 8. 指标、公式与 winner

### 8.1 种草指标口径

- `a3_ratio = new_a3 / a3_eligible_users`
- `cpm = spend / impressions * 1000`
- `play_3s_rate = play_3s / impressions`
- `completion_rate` 优先保留平台回传口径；只有在平台同时提供明确、完整且同口径的分子分母时才重算

指标回传必须支持原始值：

- `new_a3`
- `a3_eligible_users`
- `spend`
- `impressions`
- `play_3s`
- `play_complete`、`completion_denominator` 和 `completion_denominator_type`（平台有则传）
- 完播平台值

rate 统一保存为 `0–1`，百分数字符串在入口规范化；`spend` 统一为人民币元，币种必须显式为 `CNY`。负数、分母为零、混合币种或不同 `completion_denominator_type` 不得聚合。

若同时传入 rate 和完整原始分子分母，系统以原始值重算结果覆盖手填 rate，并在返回中说明口径。只有 rate 但没有对应分母时可以保存平台原值供单素材查看，不能参与臂级聚合。

### 8.2 聚合与判胜

种草北极星固定为 `a3_ratio`。所有臂级指标按分子分母池化，不平均素材 rate：

`arm_a3_ratio = Σnew_a3 / Σa3_eligible_users`

`arm_cpm = Σspend / Σimpressions × 1000`

`arm_play_3s_rate = Σplay_3s / Σimpressions`

`arm_completion_rate = Σplay_complete / Σcompletion_denominator`，且所有参与项的 denominator type 必须相同。

若没有原始分子，但有同口径 rate 和对应分母，可按 `Σ(rate × denominator) / Σdenominator` 加权，并标记 `derived_from_rates=true`；禁止算术平均。

北极星窗口内任一 `adopted/published` 资产缺少 `a3_eligible_users`，该臂 A3 标记 incomplete，不能比较或锁 winner。诊断指标可以在完整子集上展示，但必须返回覆盖率；覆盖率不足 100% 时不自动推荐下一内容变量。CPM、完播和 3 秒率只能帮助诊断，不得替代 A3 判 winner。

沿用现有最低样本门槛，但必须标明它只是工程门槛，不等于统计显著。若臂间曝光最大值/最小值 `>=3`，winner 标记“存疑”，不得自动锁定；缺少 impressions 时不能得出 CPM 或曝光平衡结论。

### 8.3 下一轮单变量映射

“低、正常、高”不能靠运行时猜测。每个实验在创建时从 versioned intent profile 快照以下值到 `evaluation_policy`：`play_3s_floor`、`completion_floor`、`a3_floor`、`cpm_ceiling`、`min_impressions`、`min_a3_eligible_users`、`max_exposure_ratio=3`、rate scale 和 currency。profile 未配置完整阈值时返回 `diagnostic_policy_missing`，只展示事实，不自动选变量。

阈值齐全时按以下固定优先级执行，命中第一条即停止：

1. 数据窗口未结束、A3 分母不足、诊断覆盖率不足或曝光失衡：保持原变量重跑，不推进变量池。
2. `play_3s_rate < play_3s_floor`：选择 ordered candidates 中第一个尚未测试且未锁定的变量，顺序为 `opening_hook_3s → presentation_motif`。
3. 3 秒达标且 `completion_rate < completion_floor`：顺序为 `story_pace → justification_density`。
4. 3 秒和完播达标且 `a3_ratio < a3_floor`：顺序为 `pain_scene_bridge → justification_module`。
5. A3 达标但 `cpm > cpm_ceiling`：不改变内容 baseline，返回 delivery/audience competition 待排查，不编造内容因果。
6. 全部达标：保留 A3 winner；从实验的全局有序变量池选择第一个未测试变量，没有合法变量则标记内容变量已收敛。

ordered candidates 的唯一 tie-break 是配置顺序；没有合法候选时不得临时换另一个变量。

每次锁定只把获胜变量写入 baseline；失败 arm 和旧 baseline 保留。

## 9. 持久化设计

优先复用现有表和状态机：

- `pipeline.scripts`：通过加法迁移新增 `content_contract JSONB NOT NULL DEFAULT '{}'::jsonb`，保存痛点—解决桥、方法模块、硬闸、提示词配置版本和脚本向量结果。
- `pipeline.experiments`：通过加法迁移新增 `evaluation_policy JSONB NOT NULL DEFAULT '{}'::jsonb`，实验创建时快照指标阈值、最小分母、失衡阈值、单位和 profile version。
- `pipeline.experiment_arms.predicted_match_score`：保存最终提示词投前归一化分；现有 `predicted_match_meta` 保存逐段分、四类哈希/版本和有效性。
- 新增 `pipeline.video_generation_sets`：保存 script/experiment/arm、expected segment manifest、selected assets、投前/投后 group gate、profile version 和 `draft/ready/adopted/discarded` 状态。
- `pipeline.assets`：通过加法迁移新增 `generation_set_id` 外键；角色定妆不属于视频段 set，视频段必须属于一个 set。
- `pipeline.assets.experiment_arm_id`：角色定妆和视频均从生成时挂臂。
- `pipeline.assets.visual_prescreen.reference_manifest`：保存 expected/sent 角色与产品引用 ID、哈希和 provider/model。
- `pipeline.assets.visual_prescreen.post_video_vector_gate`：保存实际视频投后分及其文件/事实/judge 绑定。
- `pipeline.assets.ad_metrics`：保存原始投放计数和平台 rate。
- 实验视图：种草以原始 A3 分子分母池化；软广继续按自己的北极星口径。

结构化字段是确定性校验和下游生成的事实源；`script_md` 仍用于给人阅读，但不能成为唯一机器事实源。

本期新生成资产必须满足新 gate version。历史资产继续可读，不回填虚假通过状态；显式标记为 `legacy` 的资产保留原有指标回传行为并返回 legacy warning，避免改造破坏旧软广/种草数据，但不参与本期“种草 Agent 全链路已通过”的验收。

## 10. 错误优先级与 fail-close

同一次 Agent 调用只返回执行顺序中最靠前的主阻塞，并附已通过检查。核心错误码：

1. `upstream_lineage_incomplete`
2. `pain_solution_bridge_invalid`
3. `planting_content_gate_failed`
4. `script_not_adopted`
5. `experiment_arm_missing_or_mismatch`
6. `character_sheet_generation_failed`
7. `missing_product_refs`
8. `product_ref_invalid_or_mismatch`
9. `reference_manifest_mismatch`
10. `prompt_detail_insufficient`
11. `prompt_capacity_exceeded`
12. `pre_video_vector_gate_failed`
13. `vector_gate_stale`
14. `video_segment_generation_failed`
15. `post_video_vector_gate_failed`
16. `generation_set_incomplete`
17. `insufficient_a3_denominator`
18. `metric_coverage_incomplete`
19. `exposure_imbalance`
20. `diagnostic_policy_missing`

任何硬闸失败都不得以 warning 继续烧下一步。修复后从当前阶段续跑，已完成且仍有效的资产不重做。

## 11. Agent 技能行为

新增种草 Agent 入口并复用软广的编排骨架：

- 明确识别“种草、深度种草、A3、痛点解决、看完建立相信”等话术。
- 每个昂贵阶段停下来让用户审：脚本候选、采纳挂臂、定妆/产品图、正式视频生成。
- 每次返回当前血缘、硬闸结果、实验 arm、成功/失败资产和唯一下一步。
- 不把 `sku-pipeline` 前链路 skill 扩成出片 skill；从已有 `audience_pack_id` 或 `audience_record_id` 接续内容链。
- 不调用无血缘的 `generate_video` 作为正式链路兜底。

软广和种草的 Agent 入口可以有不同方法论说明，但底层工具顺序和状态语义必须一致。

## 12. 测试与验收

### 12.1 单元测试

- 类型配置：软广与种草的 kind、intent、北极星和硬闸不串线。
- 痛点桥：来源完整通过；痛点无画像证据、仅有 pack 证据、动作无产品证据时失败；pack 只影响校准字段。
- 内容硬闸：八项门槛分别有失败用例，失败不能进入定妆。
- 提示词编译：细节维度齐全、时间戳连续、字符计数口径一致、容量随时长缩放、超限只压缩重复项、不盲截断。
- 挂臂：两个候选显式进入同一 experiment/round；SKU、intent、track、变量或轮次不一致时拒绝第二个 arm。
- 引用清单：角色/产品 expected refs 与最终 provider sent refs 的 ID/哈希一致；`force_t2v` 清空引用时阻塞。
- 投前向量：逐段使用最终提示词；提示词、事实、profile 或模型版本变化后旧分失效；低于 70 阻塞 provider。
- 投后向量：逐段实际视频低于 70、视频哈希变化或缺段时保持 draft，不能聚合。
- 生成批次：缺段、重复 active 段或任一 selected asset 未通过时 group gate 不 ready；单资产入口不能绕过整组原子采纳。
- 失败语义：全角色失败、全视频段失败都返回 `ok=false`。
- 指标公式：CPM、3 秒率、完播、A3 原始值覆盖 rate；rate scale、CNY、零分母和混合完播分母校验正确。
- 臂级聚合：四项指标均验证 `Σ分子/Σ分母` 或同口径分母加权，拒绝百分比平均；任一 A3 分母缺失使臂不可判胜。
- winner：discarded 不参与；曝光失衡时不能自动锁定。
- 下一变量：evaluation policy 缺失时不猜；阈值齐全时按固定优先级和配置顺序得到唯一变量。

### 12.2 集成测试

使用固定 fixture 跑通：

1. 已有 SKU 血缘 → 痛点桥。
2. 两个种草候选 → 硬闸。
3. 采纳 → 自动挂 A/B arm。
4. 定妆、产品图、投前向量 → 视频段生成。
5. 实际视频投后向量 → generation set draft/ready → 整组 adopted 状态。
6. 两臂回传 A3、花费、展现、3 秒和完播 → 排名、曝光判定和下一轮建议。

同时跑软广回归测试，确认软广仍以完播为北极星且不被种草硬闸误拦。

### 12.3 Agent 路由测试

- “给这个 SKU 做种草短视频，重点解决画像里的具体痛点”进入种草入口。
- “做一条软广，先看前 3 秒和完播”进入软广入口。
- “继续”只在上一步有明确 next step 时推进。
- 缺产品图、脚本未采纳、arm 不匹配时 Agent 准确停在对应阶段。

### 12.4 真实测试（实现后另行执行）

- 用一个真实 SKU 跑 Agent 全链路到视频段。
- 按提示词阶梯测试 API 接受上限和有效遵循上限。
- 真实生成费用执行前展示预计调用次数；每个付费阶段继续遵守人工确认。
- 真实投放回传验证 A3 池化、CPM 公式和曝光失衡标记。

## 13. 完成定义

本期只有在以下条件全部满足时才算完成：

1. Agent 能沿真实 SKU 血缘提炼“人群场景—具体痛点—产品解决”桥。
2. 种草候选通过专属硬闸后，用户采纳才挂 arm。
3. 定妆、产品参考图、最终提示词和视频段均保留脚本与 arm 血缘。
4. 最终提示词投前向量和实际视频投后向量都能按哈希与版本 fail-close。
5. 可下载视频段生成成功；generation set 缺段不能整组采纳，全失败不会伪报成功。
6. 回传的 A3、CPM、完播、3 秒率口径正确，A3 用原始计数池化。
7. winner 只认真实 A3；曝光失衡和样本不足时明确标记，不编因果。
8. 下一轮只改变一个变量，历史 baseline 和失败资产不被覆盖。
9. 软广链回归通过。
10. 本期不包含 UI 和最终 MP4，文档与 Agent 提示不宣称这些能力已完成。
