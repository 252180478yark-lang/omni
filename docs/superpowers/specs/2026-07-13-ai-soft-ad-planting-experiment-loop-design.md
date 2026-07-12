# AI 软广与种草短视频单变量迭代闭环设计

日期：2026-07-13

状态：六节设计已由用户逐节确认

适用仓库：omni

主要对象：SKU 链路、纯 AI 软广短视频、纯 AI 种草短视频、内容 A/B 实验、投后数据回传

## 1. 背景

SKU 链路已经能够完成卖点分析、人群匹配、人群画像、圈包、创意脚本、角色定妆和 AI 视频生成，也已经具备实验、实验轮、实验臂、素材回传和 winner 锁定的基础设施。

目前缺少的不是另一条孤立的视频生成链，而是两项能力：

1. 把卖点、真实需求、具体痛点、场景、情绪、产品动作和实际人群包画像稳定地交接给内容生成。
2. 把每条内容拆成可锁定、可单独测试的变量，投后根据真实数据保留历史最佳基线，并持续生成下一轮单变量版本。

本设计同时覆盖：

- 软广视频：面向 O/A1，不拆成人群阶段实验，主要评价播放质量。
- 种草视频：面向 A1/A2，主要推动进入 A3，以素材级 A3 转化率为真实北极星。
- A4 成交：只作为种草视频的商业旁证；需要主动优化成交时，另建 harvest 实验，不污染 planting 实验。

O 人群看到种草视频后可以自然跳转到 A3，该结果照常计入真实 A3 数据；但 planting 的内容设计不为了兼顾所有 O 人群而退化成泛认知内容，宽泛 O/A1 的主要内容入口仍是 soft_ad。

产品白底图是两类正式出片的必需输入。

## 2. 当前事实与审计结论

### 2.1 SKU002 当前链路

SKU-002 是 SKU-367991-0002 的别名。审计时的主要血缘为：

- 卖点矩阵：a3e479ce-dbc4-4cf9-ab90-7dc571cd3377，adopted，v19
- 人群报告：4d1ca303-5b0d-468a-acfa-b4a2fc405afb，draft
- 已选人群“舒适休闲”：6cceff70-3d16-4bad-b810-13f08fbe66fd，adopted
- 人群画像：f666bb9e-9e4e-48d2-816f-95c57192dda7，draft
- 圈包 SOP：194bb95f-00ae-41f1-88d0-077f25a717dc，adopted，v4
- 关键词包：ffcf875a-32ea-4d24-b910-bd83ed9b8e3f，adopted，v6
- 云图实际包：SKU002舒适休闲主包AD，外部 ID 482514677
- 实际包画像：services/knowledge-engine/config/audience/SKU002舒适休闲主包AD画像数据.csv

该实际包约 1,000,415 人，尚未推送千川。已有多版软广脚本，但没有已形成有效投后闭环的 experiment、ad metrics 或 winner。

### 2.2 “没有痛点”不是准确根因

SKU002 的旧产物并非没有痛点：

- 卖点矩阵已有需求、使用场景、成分焦虑、口味和烹饪问题等内容。
- 人群匹配理由已经表达“卖点—场景—需求”的关系。
- 人群画像包含生活场景、消费犹豫、下单触发、情绪底色、正向触点和负向阻断。
- 人群包中已有独立痛点和触发场景。

真实问题是这些信息散落在自然语言章节中，缺少稳定字段；现有桥接还会按字符和行数截断，导致算法信号、消费决策和负向情绪阻断在下游丢失。

### 2.3 现有软广与种草链的工程缺口

- 两份软广 skill 高度重复但已经漂移，并存在触发冲突。
- planting prompt 与 planting validator 字段错位，会产生伪告警或漏过真实缺项。
- 产品图硬闸只检查列表非空，没有验证文件、白底、SKU 绑定和最终是否真的传给视频模型。
- target model 目前主要控制提示词写法，实际出片模型可能与之不一致。
- 产品—内容—人群三角审计已有内部实现，但没有成为正式生成硬闸。
- 自动修复逻辑存在写死 SKU002 酱油事实的风险，会污染醋、黑醋和寿喜烧等 SKU。
- planting 当前默认北极星仍是 completion_rate，a3_ratio 只是辅助指标。
- 当前 winner 主要按每臂视频数判断样本是否足够；曝光失衡仅警告，不能满足新的判胜要求。

## 3. 设计目标

### 3.1 必须实现

- 从任一已有 SKU 链路出发生成软广或种草视频。
- 自动继承已采用的人群包，不要求用户重复输入人群包。
- 生成前得到稳定的结构化内容契约。
- 产品白底图缺失或不可用时停止正式出片。
- 每轮只测试一个内容变量。
- 投后回传消耗、展现、播放、三秒观看、完播、CTR、A3 和 ROI 等指标。
- 软广按播放质量迭代；种草按 A3 转化率迭代。
- 保存全部实验历史和当前最佳基线。
- 根据数据形态推荐下一轮只改哪里，并能生成下一轮候选。
- 失败实验不覆盖历史最佳基线。

### 3.2 不做

- 不新建第二套实验状态机。
- 不把软广、种草和收割混进同一个 intent。
- 不承诺每轮试验都单调提升。
- 不自动无限烧出片或投放费用。
- 不因内容补强重新圈人群包。
- 不用投前向量分替代投后北极星。
- 不因单轮 winner 自动生成全局 prompt 规则。
- 本阶段不新建独立前端页面。

## 4. 核心架构

### 4.1 共享内核，两个入口

保留两个独立的用户入口：

- .agents/skills/ai-soft-ad-video
- .agents/skills/ai-planting-video

两个 skill 只负责路由、编排和各自的内容规则，不保存业务状态。公共逻辑由现有 pipeline 和 experiment 基础设施承担。

现有 .claude/skills/soft-ad-ai-video 只保留兼容转发，不再维护独立业务逻辑，避免两份软广 skill 继续漂移。

兼容转发文件不再保留与 canonical skill 重叠的自动触发描述，防止同一句“软广”同时触发两个入口。

### 4.2 状态所有权

真实状态只存在于以下现有结构中：

- pipeline：matrix、audience、portrait、pack、script、asset
- experiment：experiment、round、arm、asset.ad_metrics

每个实验的身份为“SKU × 实际人群包 × intent × track × 北极星”。实际人群包从链路继承并显式写入 experiment，不能只通过某条脚本间接猜测。

状态转换继续使用：

- script：draft → adopted → archived
- experiment round：open → locked
- experiment：running → converged → archived
- asset：draft → adopted/published/discarded

skill 不增加 planting_status 或 soft_ad_status。每次调用都根据真实血缘推导下一动作。

### 4.3 主流程

1. 解析 SKU 别名及已采用链路。
2. 构建并预览内容契约。
3. 返回最靠前的唯一阻塞项，或进入候选生成。
4. 选择本轮唯一变量，生成 2—3 个实验臂脚本。
5. 用户采纳脚本后才挂实验臂。
6. 生成角色定妆、运行三角审计和单变量检查。
7. 使用真实指定模型并携带产品白底图生成视频。
8. 运行投前视觉质检。
9. 投放后按素材和实验臂回传数据。
10. 判断样本、归因窗口和曝光平衡。
11. 锁定 winner 或保留“当前领先”。
12. winner 合入 baseline，生成下一轮单变量施工单。
13. 达到停止条件后标记 converged。

## 5. 内容实验契约

每条候选脚本都必须保存一个机器可读的 content contract。契约分为四层。

### 5.1 永久事实

- schema_version
- sku_id
- matrix_run_id
- audience_record_id
- portrait_id
- audience_pack_id
- 云图外部人群包 ID
- 实际包画像来源、生成时间和摘要版本
- 卖点事实、证据等级、证据来源和可说边界
- 产品白底图文件、哈希和验证结果
- intent、kind、时长、画幅
- 请求的视频模型和模型档案版本

永久事实不能作为内容实验变量。

### 5.2 人群内容原料

必须按字段提取，而不是从长文本头部截取：

- true_need：真实需求
- pain_point：具体痛点
- trigger_scene：触发场景
- hesitation：消费犹豫
- blockers：阻断点
- emotion_base：情绪底色
- positive_triggers：正向情绪触点
- negative_triggers：负向情绪触点
- algorithm_signals.text：文字信号
- algorithm_signals.visual：画面信号
- algorithm_signals.sound：声音信号
- selling_point_links：卖点—痛点—场景—需求关系

缺失字段必须标 missing 或 unknown，禁止补造证据。

### 5.3 当前最佳基线

baseline 保存已经锁定的变量值：

- opening_hook_3s
- pain_point
- emotion
- scene
- story_structure
- selling_point
- proof_method
- product_entry
- product_action
- visual_vector
- text_vector
- sound_vector
- story_pace
- edit_pace

### 5.4 本轮唯一变量

每个 round 只允许一个 swept_variable。每个 arm 只给该变量一个 variable_value。

示例：

- 本轮扫 opening_hook_3s
- A 臂：直接点痛点
- B 臂：先演冲突再点痛点
- C 臂：先展示结果再揭示痛点

该轮的具体痛点、人物、场景、情绪、卖点、产品动作和画面方向必须相同。

### 5.5 画面向量的两级测试

第一层允许把完整画面方向当一个分类变量，例如：

- 家庭生活纪实
- 清爽料理特写

该测试只能回答“哪个整体画面方向更好”。

方向胜出后，再拆分测试：

- actor_signal
- environment_signal
- camera_signal
- product_signal

这样避免把多个画面因素永久混在一个变量中。

### 5.6 变量依赖与组合变量

单变量纪律不能破坏内容逻辑。

- 测 pain_point 时，候选痛点必须能被同一个 selling_point 合理承接。
- 测 scene 时，候选场景必须共享同一个真实需求、痛点和卖点。
- 如果更换痛点必然要更换卖点与证明方式，则本轮变量应定义为 value_proposition_route，取值是完整的“痛点—卖点—证明”路线。
- 如果更换场景必然改变需求，则本轮变量应定义为 scene_need_route。

组合变量只能回答“哪条完整路线更好”，不能声称已经证明其中某一个子因素更好。路线胜出后，再在路线内部拆分子变量。

## 6. 单变量纪律与漂移硬闸

系统在三个位置校验。

### 6.1 生成前

比较各臂 content contract：

- 除 swept_variable 外，其余 baseline 和永久事实必须一致。
- intent、产品图、视频模型、时长和画幅不能偷偷变化。
- 一轮不能同时更换痛点、场景和钩子。

### 6.2 脚本生成后

解析真实脚本并与契约比对：

- 是否擅自换了卖点、痛点、场景、人物或故事结构。
- 是否增加无依据资质、价格、优惠、口碑或成交数字。
- 是否破坏 soft_ad 或 planting 的内容边界。

### 6.3 视频生成后

检查：

- 人物、场景和产品是否执行契约。
- 产品外观是否保持。
- 画面、文字和声音向量是否符合该臂设定。
- 是否出现 AI 崩片、锁脸失败或明显品牌错误。

检测到多变量漂移时返回 multi_variable_drift。系统只自动修正一次；仍不通过则停止，不继续烧视频成本。

### 6.4 AI 生产随机性的控制

一个 arm 表示一个内容变量取值，一个 arm 可以挂多条视频 replica。

- 同一 arm 的 content contract、人物、产品图、模型、时长和画幅保持一致。
- 允许的差异只限于 AI 模型不可避免的采样噪声。
- 若主动测试模型、运镜或锁脸方法，应把它登记为正式 swept variable，不能混在 replica 中。
- winner 在 arm 级聚合，避免把偶然生成得更漂亮的一条视频误判成内容变量胜出。

## 7. 两个 intent 的内容与指标规则

### 7.1 软广 soft_ad

目标：

- 面向 O/A1，不拆成 O→A1 和 A1→A2 两套实验。
- 让用户停下来并愿意继续观看。
- 产品可以较晚出现，植入要轻。

北极星和指标层级：

- 主北极星：completion_rate
- 前置门槛：play_3s_rate
- 规模指标：plays、effective_plays
- 效率指标：每千次展现播放量、每元消耗有效播放量
- 诊断指标：impressions、spend、平均观看时长、CTR
- 商业旁证：A3、GMV、ROI；不参与软广 winner 主排序

判定顺序：

1. 检查窗口、最低样本和曝光平衡。
2. 三秒观看率不达门槛的臂不能成为正式 winner。
3. 通过门槛后按完播率排名。
4. 完播接近时，用三秒观看率、有效播放成本和播放效率辅助。
5. 原始播放量不能脱离展现与消耗单独判胜。

### 7.2 种草 planting

目标：

- 面向 A1/A2，建立“跟我有关”和“凭什么相信”。
- 建立痛点—产品—判断依据的连接。
- 推动进入 A3。

北极星和指标层级：

- 主北极星：a3_ratio，界面显示“A3转化率”
- 规模指标：new_a3
- 效率指标：a3_cost
- 诊断指标：play_3s_rate、completion_rate、CTR、spend、impressions
- 商业旁证：GMV、CVR、ROI

若 A3 提高但 ROI 偏低，保留 planting winner，并从获胜素材派生独立 harvest 实验。harvest 以 CVR 为北极星，不与 planting 同轮比较。

### 7.3 纯 AI 能力边界

种草证明方式必须服从生产方式：

- 可使用：真实可执行的演示、原因解释、使用对比、判断标准。
- 有证据才可使用：权威信息、检测、认证和来源说明。
- 纯 AI 默认禁止：冒充真实消费者证言、假采访、虚构专家或权威背书。

## 8. 上游兼容与 SKU002 补强

### 8.1 三类兼容结果

- directly_usable：字段和证据完整，直接继承。
- migratable：原文已有信息但结构旧，确定性迁入 content contract。
- rerun_required：信息真正缺失、冲突或可信度过低，只重跑该节点的新版本。

旧版本不覆盖，不伪造新字段。

### 8.2 SKU002 处理

- 保留现有云图实际人群包及外部 ID，不重新圈包。
- 从旧 matrix 和 record 迁移已有痛点、需求和场景。
- 旧卖点没有证据等级时标 unknown。
- 当前 portrait 信息丰富，但存在 KB 覆盖不足警告；使用最新规则、实际云图画像和同一 audience record 补跑新 portrait 版本，审阅后采纳。
- 现有 pack 继续使用，同时补实际采用的 portrait 版本和内容继承快照。
- 只有 readiness check 仍发现关键事实缺失时，才补跑对应分析节点。

## 9. 产品白底图与真实出片模型硬闸

### 9.1 产品图检查

产品白底图在首次内容前检时就是必需输入，而不是等到视频渲染时才补。正式生成候选和出片前必须确认：

- 文件可读且为有效图片。
- 背景是白底或干净中性底。
- 图片由用户绑定当前 SKU；身份不确定时停止并请求确认。
- 分辨率足够，瓶型、标签、瓶盖和包装信息可辨认。
- 文件哈希写入 content contract。
- 各实验臂使用相同产品图。

soft_ad 前三秒可以不出现产品，但整条素材仍必须绑定产品图。video_soft_ad 和 video_planting 禁止 allow_no_product 旁路。

### 9.2 模型一致性

系统必须区分：

- 生成脚本所用 LLM
- 请求的视频模型
- 实际出片 provider/model

请求模型、数据库记录和实际调用必须一致。若模型不支持产品 reference-to-video，或运行时清空 product refs，则 fail-close，不允许继续出片。

拆段长度按实际模型档案确定，不能把所有模型统一写死为 15 秒。

## 10. 投后数据契约

### 10.1 共同必传

- asset_id
- experiment_arm_id 或臂码
- external_video_id / external_creative_id
- data_start
- data_end
- attribution_window
- as_of
- source
- spend
- impressions

### 10.2 软广必传

- plays
- play_3s 或 play_3s_rate
- play_complete 或 completion_rate
- 平均观看时长（平台有则传）

### 10.3 种草必传

- a3_ratio
- 推荐同时传 new_a3 和对应分母
- 对应分母统一为 a3_eligible_users；平台没有分母时明确标记 unavailable
- CTR
- 基础播放指标

人群包不重复回传，通过 asset → script → pack 血缘自动确定。

### 10.4 ROI 口径

- GMV 与 spend 都有时，由后端复算统一 ROI。
- 平台直接导出的 ROI 保存为 platform_reported_roi，并带 source=platform_export；它可以作为旁证，但不得覆盖后端统一口径。
- ROI 不参与 soft_ad 或 planting 的主 winner 排序。

### 10.5 多次回传

V1 沿用 pipeline.assets.ad_metrics JSONB 的累计合并，并增加规范化窗口元字段。

软广有原始计数时，优先用聚合计数计算完播率和三秒率；种草同时有 new_a3 与 a3_eligible_users 时，优先用两者计算 pooled A3 转化率。只有平台未提供分子、分母时，才使用平台回传的素材级 rate，并在结果中标明聚合口径。

若未来需要同一素材保存多个窗口快照和趋势，再增加 append-only asset_metric_snapshots 事实表。该事实表不是状态机，本期不创建。

## 11. 判胜、诊断与下一轮建议

### 11.1 可判胜条件

- 至少两个有效实验臂。
- 数据窗口一致并结束。
- 达到 evaluation policy 配置的最低展现、消耗或行为量。
- 各臂曝光和消耗没有超过允许失衡范围。
- 比率指标有足够分母。

现有“每臂 n≥5”只保留为稳定性旁证，不再是唯一闸门。工程门槛不等于统计显著；数据不足只显示“当前领先”。

### 11.2 诊断规则

系统先输出观察事实，再输出待验证假设，禁止写成因果定论。

软广：

- 三秒低：优先测试前三秒钩子、首帧画面、痛点或场景识别。
- 三秒高、完播低：优先测试故事结构、情绪推进、故事节奏或剪辑节奏。
- 三秒和完播高、播放效率低：优先测试画面、文字或声音信号。

种草：

- 观看指标低：先修钩子和场景相关性。
- 观看、点击不错但 A3 低：测试痛点—卖点连接、证明方式或产品动作。
- A3 高、ROI 低：保留种草胜者，进入独立收割实验。
- 曝光或消耗严重失衡：不换变量，先补量或重跑当前轮。

### 11.3 下一变量算法

1. 找当前最明显的漏损位置。
2. 映射到对应变量组。
3. 排除已经测试或锁定的变量。
4. 选一个尚未测试的高优先级变量。
5. 固定完整历史最佳基线。
6. 生成 2—3 个下一轮取值。

推荐顺序不是固定轮播，也不是让 LLM 自由发挥。

### 11.4 历史最佳

每轮保存：

- swept variable
- 各臂 value
- 指标和数据窗口
- 当前领先或正式 winner
- winner 合入后的 baseline
- 决策理由
- 下一轮建议和对应假设

失败臂保留用于复盘，但不进入 baseline。

## 12. 数据模型

复用现有 experiments → experiment_rounds → experiment_arms → assets.ad_metrics，不增加表或状态枚举。

建议的加法字段：

### 12.1 pipeline.scripts

- content_contract JSONB NOT NULL DEFAULT {}
- target_video_model TEXT

content contract 包含 schema version、永久事实、baseline、sweep、变量清单、请求模型和产品图清单。

### 12.2 pipeline.assets

- generation_meta JSONB NOT NULL DEFAULT {}

generation meta 是设计中的 render manifest，保存：

- requested provider/model
- actual provider/model
- aspect ratio
- product refs requested
- product refs actually used
- face refs used
- refs blocked reason
- allow_no_product
- gate results

### 12.3 pipeline.audience_packs

- audience_portrait_id UUID NULL
- execution_meta JSONB NOT NULL DEFAULT {}

用于补齐实际采用画像到人群包的血缘，并保存外部人群包 ID、实际包画像来源、估算人数和执行时间。

### 12.4 pipeline.experiments

- audience_pack_id UUID NULL
- evaluation_policy JSONB NOT NULL DEFAULT {}

显式绑定实际人群包；evaluation policy 保存该实验的归因窗口、最低样本、曝光失衡门槛、guardrails 和 policy version。

### 12.5 pipeline.experiment_rounds

- evaluation_snapshot JSONB NOT NULL DEFAULT {}

保存锁定或判定时的事实、假设、指标快照和下一轮建议。它是审计快照，不是新状态。

现有 experiments.baseline、rounds.swept_variable/baseline_snapshot、arms.variable_value 和 assets.experiment_arm_id 继续作为唯一实验状态来源。

## 13. 服务、工具和 Prompt 改造

### 13.1 内容桥接

- 扩展卖点解析器，解析痛点原料、真需求和完整场景块。
- 用 section-aware 字段抽取替换全局 36 行关键词抢占。
- portrait 内容槽优先于 record 和 pack 的冗余摘要。
- audience pack 固定输出内容继承卡。

### 13.2 生成

- generate_creative_pack 构建、校验并持久化 content contract。
- video_soft_ad 和 video_planting 使用各自 profile。
- 修复 planting prompt 与 validator schema。
- 所有 repair suffix 只使用当前 lineage，不得包含固定 SKU 文案。
- 脚本保存后运行单变量 diff 和三角审计。

### 13.3 出片

- 校验产品图文件和绑定。
- 持久化实际 provider/model 和 refs used。
- 产品 ref 被运行时清除时停止。
- whole-prompt 模式按模型能力拆段。
- 角色定妆全失败时不得返回可继续状态。

### 13.4 实验

- planting 默认 north star 改为 a3_ratio。
- soft_ad 保持 completion_rate，并增加 play_3s_rate guardrail。
- 扩展变量注册表，加入痛点、证明方式、产品出现和动作、文字与声音向量等。
- experiment_status 使用 evaluation policy 进行判胜资格检查。
- experiment_next_version_seed 使用诊断映射和全部历史选择下一变量。

### 13.5 数据回灌

补充默认 CSV 映射：

- A3转化率 / 新增A3占比 → a3_ratio
- 新增A3 / A3人数 → new_a3
- A3分母 / A3可转化人数 → a3_eligible_users
- 3秒播放率 / 三秒观看率 → play_3s_rate
- 3秒播放量 → play_3s
- 平均观看时长 → average_watch_time_seconds
- 平台ROI / 支付ROI → platform_reported_roi

回灌继续先 dry-run，确认臂码、素材和字段映射后再写入。

所有新增 MCP 工具必须使用 audit 装饰器。所有新增 LLM 生成必须使用外置 prompt、返回 trace，并复用现有 OutputFeedback。

## 14. 前端

不新建页面，扩展现有 SKU Pipeline 创意素材区和 A/B 实验看板：

- 内容契约预览
- 当前链路和实际包画像来源
- 唯一阻塞项
- 本轮变量及各臂差异
- 产品图和模型验证状态
- 投后指标排名
- 观察事实、待验证假设
- 下一轮单变量施工单
- 历史 baseline 与 changelog

所有新增产物区继续挂 OutputFeedback。

## 15. 错误处理

错误按执行顺序只返回最靠前的一个：

1. upstream_content_incomplete
2. portrait_confidence_low
3. missing_product_ref
4. product_ref_invalid
5. product_ref_sku_mismatch
6. target_model_mismatch
7. multi_variable_drift
8. triangle_match_low
9. character_sheet_failed
10. product_refs_dropped
11. prescreen_failed
12. attribution_window_open
13. insufficient_sample
14. exposure_imbalance

修复后从当前位置继续，不重跑已经完成且仍然有效的产物。

## 16. 测试与验收

### 16.1 上游与兼容

- SKU002 旧 matrix、record、portrait、pack 作为真实 fixture。
- 旧格式可迁移字段不丢。
- 缺字段标 unknown/missing，不伪造。
- portrait 新旧版本均可解析。

### 16.2 单变量

- 除 swept variable 外完全一致时通过。
- 同时改两个变量返回 multi_variable_drift。
- LLM 擅自改场景或卖点可被生成后校验发现。
- winner baseline 能正确进入下一轮。

### 16.3 产品和模型

- 无图、失效图、非图片、明显非白底、错 SKU 均停止。
- mock 实际视频 provider，断言产品 refs 真正转发。
- refs 被 provider 清除时 fail-close。
- target model 的 prompt profile、持久化值和实际 provider/model 一致。
- seedance、veo、jimeng 使用各自真实时长能力。

### 16.4 Prompt 与质检

- planting 标准输出经 validator 零伪告警。
- 缺关键字段会硬告警或阻断。
- 三角匹配任一关键边低于阈值时禁止烧视频。
- pure AI 不生成假消费者证言或假权威。
- 醋、黑醋、寿喜烧等 SKU 不出现 SKU002 酱油事实。

### 16.5 数据与循环

- 软广按三秒门槛和完播率判定。
- 种草按 a3_ratio 判定。
- A3 CSV 表头能默认映射。
- 曝光或消耗失衡时不能锁 winner。
- 窗口未结束或样本不足时只显示当前领先。
- 第一轮 winner 合入 baseline，第二轮只改变一个新变量。
- 多轮 changelog 能回答“每轮改了哪里、为什么、结果如何、下一步改什么”。

### 16.6 Skill

- ai-soft-ad-video 与 ai-planting-video 触发互不抢占。
- “软广、播放、前三秒”进入 soft-ad。
- “深度种草、A3、建立相信、痛点与卖点连接”进入 planting。
- 两个 skill 均通过 skill quick validation。

## 17. 发布顺序

1. 共享内容契约、解析和单变量校验。
2. 数据模型加法迁移。
3. 实验北极星、指标窗口和判胜升级。
4. 产品图、模型一致性和三角硬闸。
5. 改造 canonical soft-ad skill。
6. 创建 planting skill。
7. 前端现有页面增加预览和诊断卡。
8. 用 SKU002 做只读迁移预检。
9. 补跑并审阅 SKU002 portrait 新版本。
10. 用户提供产品白底图后生成第一轮脚本候选。
11. 用户采纳后出片、投放、回传并验证 Round 1 → Round 2。

## 18. 完成定义

设计完成后的真实用户体验应是：

1. 用户从某个 SKU 已有人群包链路发起软广或种草视频生成。
2. 系统自动继承卖点、人群、画像、人群包和实际画像。
3. 缺产品白底图或关键内容事实时明确阻断。
4. 系统展示本轮唯一变量和 2—3 个候选。
5. 用户采纳后生成具有完整血缘的 AI 视频。
6. 平台数据按素材和实验臂回传。
7. 系统说明当前 winner、客观依据、样本限制和下一版只改哪里。
8. 下一轮固定历史最佳，只测试一个新变量。
9. 循环持续到指标达标、变量收敛、数据不足、瓶颈转移或用户停止。

系统保证历史最佳基线不会被失败实验覆盖，但不承诺每一条新试验都优于上一条。
