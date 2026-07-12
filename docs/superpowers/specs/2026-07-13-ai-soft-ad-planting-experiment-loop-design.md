# AI 软广与种草短视频单变量迭代闭环设计

日期：2026-07-13

状态：用户已终审认可；实施计划已拆分，待选择执行方式

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
- 种草不依赖单一内容模板；使用可版本化的叙事、证明、呈现三层框架库和兼容路由。
- 新实验先用 4 条低成本文本路线预筛为 2 条正式候选，再用真实 A3 数据判 winner。
- 产品白底图缺失或不可用时停止正式出片。
- 生成通过整片质检、可直接进入投放测试的最终 MP4，而不是把视频段当成完成品。
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
4. 确定本轮唯一变量：新 planting 实验若未锁定框架，以 4 条为目标生成文本路线并预筛 Top 2，以 content_framework_route 作为复合变量；其余情况按历史诊断选择一个原子变量。
5. 新 planting 实验由用户确认 manifest 中的路线后，再为通过硬闸的 2—3 个取值生成正式实验臂脚本；已有实验直接按下一变量施工单生成。
6. 用户采纳脚本后才挂实验臂。
7. 生成角色定妆、运行三角审计和单变量检查。
8. 使用真实指定模型并携带产品白底图生成视频段。
9. 拼接、标准化并落库最终 MP4。
10. 对最终整片运行投前视觉质检。
11. 投放后按素材和实验臂回传数据。
12. 判断样本、归因窗口和曝光平衡。
13. 锁定 winner 或保留“当前领先”。
14. winner 合入 baseline，生成下一轮单变量施工单。
15. 达到停止条件后标记 converged。

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
- framework_library_version、production_track（pure_ai / future_real_material）和证据资格快照

永久事实不能作为内容实验变量。请求的视频模型属于每个 arm 必须持久化的生成事实，默认同样固定；唯一例外是 track=ai_video 且本轮显式登记 swept_variable=target_model 的技术实验。此时只允许各臂的请求模型和模型档案版本不同，产品图、人物、时长、画幅和全部内容语义仍保持一致；实际 provider/model 继续按臂留痕。该轮只能回答“哪种出片模型更适合当前固定内容”，不能当作内容框架 winner。

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

- content_framework_route：由 N/P/V 和 framework_library_version 确定性生成的只读派生 route id；不允许脱离三个子字段独立编辑
- framework_library_version
- narrative_framework
- proof_framework
- presentation_motif
- opening_hook_3s
- pain_point
- emotion
- scene.semantic：目标人群、需求与情境语义
- scene.execution_instances：同一语义下实际使用的一个或多个场景实例
- role_semantics：人物与目标人群的身份关系、需求和行为语义
- production_cast_form：无人、单人、双人或多人等生产呈现形式
- story_structure
- selling_point
- proof_method
- product_entry
- product_action.core_use：全片稳定的倒、蘸、拌、烹调等核心使用动作
- product_action.proof_execution：为当前证明框架拍摄的比较、展示或解释动作
- visual_vector
- text_vector.semantic：口播、字幕和画面文字共同表达的主张语义
- text_vector.presentation：字幕密度、位置、节奏和口语化程度等呈现方式
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

第一层的“完整画面方向”统一使用 presentation_motif，不再另建 visual_direction 变量。例如：

- 多场景生活纪实 → V6
- 清爽料理桌面特写 → V3

该测试只能回答“哪个整体呈现母题更好”，并按 presentation_motif ownership 允许必要的镜头、声音和 production_cast_form 变化。

母题胜出后，再在该母题内部拆分测试：

- actor_signal
- environment_signal
- camera_signal
- product_signal

历史 visual_direction 确定性迁为 presentation_motif 或标 unknown，不与 presentation_motif 并列进入变量池。这样避免把多个画面因素永久混在一个变量中。

### 5.6 变量依赖与组合变量

单变量纪律不能破坏内容逻辑。

- 测 pain_point 时，候选痛点必须能被同一个 selling_point 合理承接。
- 测 scene 时，候选场景必须共享同一个真实需求、痛点和卖点。
- 如果更换痛点必然要更换卖点与证明方式，则本轮变量应定义为 value_proposition_route，取值是完整的“痛点—卖点—证明”路线。
- 如果更换场景必然改变需求，则本轮变量应定义为 scene_need_route。

组合变量只能回答“哪条完整路线更好”，不能声称已经证明其中某一个子因素更好。路线胜出后，再在路线内部拆分子变量。

框架相关变量使用以下固定语义：

- content_framework_route：冷启动或结构重置时使用的复合变量，取值是完整的 `narrative_framework + proof_framework + presentation_motif` 路线。
- narrative_framework：只改变叙事组织方式及其声明的派生结构；证明框架、呈现母题、痛点、卖点和 product_action.core_use 保持不变。
- proof_framework：只改变判断依据怎样成立及 product_action.proof_execution；叙事框架、呈现母题、痛点、卖点和 product_action.core_use 保持不变。
- presentation_motif：只改变原生呈现方式及其声明的生产字段；叙事语义、证明逻辑、痛点、卖点、text_vector.semantic 和 product_action.core_use 保持不变。

content_framework_route 胜出后，系统把其 route id 和三个子值一起写入 baseline。后续修改任一子字段时，content_framework_route 由三个子字段和 framework_library_version 重新计算，禁止把 route id 作为可独立编辑的第二份真值，避免基线互相矛盾。

改变框架时允许发生与该变量直接依赖的结构变化，例如切换 narrative_framework 后时间轴顺序、转场语句和镜头衔接会随之变化；这些变化必须写入 dependency_allowlist。痛点、卖点、证据事实、product_action.core_use 或目标人群等不在允许列表里的变化，仍然判定为 multi_variable_drift。

宏变量与派生字段的所有权固定如下：

| swept variable | 可随之改变的派生字段 | 必须保持不变 |
|---|---|---|
| content_framework_route | narrative_framework、proof_framework、presentation_motif，以及三者各自允许的派生字段 | 人群、痛点、卖点、证据事实、价值命题、产品图、intent、scene.semantic、role_semantics、text_vector.semantic、product_action.core_use |
| narrative_framework | story_structure、时间轴顺序、转场语句、scene.execution_instances、叙事所需的 story_pace 微调 | proof_framework、presentation_motif、scene.semantic、role_semantics、production_cast_form、痛点、卖点、证据事实、核心产品动作 |
| proof_framework | proof_method、证明段组织、product_action.proof_execution | narrative_framework、presentation_motif、痛点、卖点、product_action.core_use 和原始证据事实 |
| presentation_motif | production_cast_form、visual_vector、text_vector.presentation、sound_vector、camera_signal、edit_pace 中与该母题直接相关的呈现字段 | narrative_framework、proof_framework、role_semantics、text_vector.semantic、脚本语义、痛点、卖点、证据事实、产品结论 |

旧字段不是第二套框架真值：story_structure 是 narrative_framework 的具体编译结果，proof_method 是 proof_framework 的具体执行方式，visual_vector、text_vector.presentation 和 sound_vector 是 presentation_motif 的具体信号实现。text_vector.semantic 属于内容事实，不归呈现母题所有。测试宏变量时派生字段按上表联动；测试某个派生字段时对应宏变量必须锁定，且同一轮不能同时把宏变量和派生字段登记为两个 swept variable。

ownership registry 必须覆盖全部标准 swept variable，而不只覆盖框架变量。最低定义如下；实现可以继续拆细，但不能缺省放行：

| swept variable | 允许修改的路径 | 关键固定项 |
|---|---|---|
| opening_hook_3s | hook 文案、首帧、0—3 秒动作与节拍 | 痛点语义、卖点、框架路线、场景语义 |
| pain_point | pain_point 及对应问题表述 | true_need、selling_point、proof_framework；无法承接时升格 value_proposition_route |
| emotion | 表演情绪、情绪措辞、音乐情绪 | 事实主张、痛点、卖点、场景语义 |
| scene | scene.semantic、scene.execution_instances | true_need、痛点、卖点、框架路线；需求随场景改变时升格 scene_need_route |
| story_structure | 节点顺序、转场、结构内节拍 | narrative_framework、内容语义、证明和产品动作 |
| selling_point | 选中的卖点及其证据引用 | 痛点、proof_framework、核心产品动作；证明框架也要变时升格 value_proposition_route |
| proof_method | proof_method、product_action.proof_execution | proof_framework、原始证据、痛点、卖点 |
| product_entry | 首次露出时间、入画方式和对应镜头 | 核心使用动作、脚本语义、卖点和证明 |
| product_action | product_action.core_use；仅限同一需求与场景可承接的动作候选 | 卖点、proof_framework、场景语义；无法固定时使用组合变量 |
| visual_vector | actor/environment/camera/product signal 的指定视觉路径 | 脚本语义、text_vector.semantic、sound_vector |
| text_vector | 只允许 text_vector.presentation | text_vector.semantic；主张变化必须登记为对应内容变量 |
| sound_vector | BGM、环境声、音效和声音风格 | 口播语义、画面语义和卖点主张 |
| story_pace | 各叙事任务的时长分配和停顿 | 总时长、节点语义、edit_pace |
| edit_pace | 切点密度、转场速度和镜头平均长度 | 节点语义、story_pace、总时长 |

## 6. 单变量纪律与漂移硬闸

系统在三个位置校验。

### 6.1 生成前

比较各臂 content contract：

- 除 swept_variable 及其在 ownership 表声明的 dependency_allowlist 外，其余 baseline 和永久事实必须一致。
- intent、产品图、视频模型、时长和画幅不能偷偷变化。
- 一轮不能同时更换痛点、场景和钩子。

### 6.2 脚本生成后

解析真实脚本并与契约比对：

- 是否擅自换了卖点、痛点、场景、人物或故事结构；若故事结构变化来自 narrative_framework，则必须严格落在该轮 dependency_allowlist 内。
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
- 若主动测试模型、运镜或锁脸方法，应把它登记为正式 swept variable，不能混在 replica 中。测试模型时适用 5.1 的 arm-scoped 生成事实例外，不放宽任何内容字段。
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

## 8. 种草短视频生成器

本节定义用户真正调用的 ai-planting-video 生成功能。它不是“只写一份脚本”的 skill，而是跨多个对话步骤完成“内容方案 → 用户采纳 → AI 出片 → 成片质检 → 实验挂臂”的全链路生成器。

### 8.1 用户怎样调用

典型触发语句：

- 给 SKU-002 生成种草短视频。
- 用这个人群包和产品白底图做两条 A/B 种草片。
- 按 A3 目标给这个人群做深度种草。
- 采纳 B 方案并正式出片。
- 继续这条种草实验的下一版。

用户只需给 SKU 或现有链路锚点，以及当前 SKU 的产品白底图。人群包、卖点、人群画像、痛点和实际包画像由 skill 沿血缘自动继承。

“生成种草短视频”的完成标准是产出通过质检的最终 MP4 asset，并挂到 script、audience pack 和 experiment arm。只产出文案、分镜或未拼接视频段不算完成。

### 8.2 输入契约

必需输入：

- sku_id，或能反查到 sku_id 的 audience_pack_id
- product_ref：当前 SKU 产品白底图

有默认值的输入：

- target_model：默认 seedance
- duration_seconds：默认 30；证据确实需要双判断依据时允许 45
- aspect_ratio：默认 9:16
- route_shortlist_target：V1 默认为 4，表示只生成文本的冷启动路线目标数，不直接烧视频；硬闸后只剩 2—3 条时全部保留并标 route_pool_limited，少于 2 条才阻断
- script_candidate_count：默认 2，用户明确要求时最多 3；只有通过硬闸的路线才能进入正式脚本与出片候选

可选输入：

- idea_seed：用户指定的生活事件或创意方向
- swept_variable：用户指定本轮测试变量
- variable_values：用户指定的 A/B/C 取值
- extra_context：本轮临时限制

用户没有指定 swept variable 时：

1. 如果上游仍有多条互斥的“痛点—卖点—证明”路线，先测试 value_proposition_route，先固定内容命题再选表达框架。
2. 内容命题已固定、但尚无已采纳框架路线时，首轮测试 content_framework_route。
3. 用户已经明确指定并锁定一条框架路线时，首轮测试 opening_hook_3s。
4. 已有投后历史时，由下一变量算法选择，不重置为第一轮。

### 8.3 框架库的证据层级与适用边界

外部研究只为冷启动提供先验，不直接证明某个框架在抖音、某个 SKU 或 SKU002 人群包上一定有效。证据按以下层级使用：

| 层级 | 用途 | 不能推出什么 |
|---|---|---|
| A. 平台效果研究与广告编码研究 | 确认前三秒、平台原生表达、结构清晰和产品实际使用等方向值得进入候选池 | 不能保证复制到抖音后 A3 一定提升 |
| B. 官方品类玩法手册 | 提供食品饮料中已经被平台反复使用的菜谱、演示、日常场景、问题解决、配料解释和 ASMR 等形式 | 不能把官方示例当成固定模板或行业真理 |
| C. 学术机制研究 | 解释叙事代入、自我连接、戏剧冲突和高唤醒情绪为什么可能影响注意、记忆或分享 | 不能据此预测具体素材的 A3 转化率 |
| D. omni 自有投后数据 | 在同一 SKU、同一真实人群包、同一 intent 和可比窗口下判定当前路线与变量取值 | 这是唯一可以锁定本地 winner 的依据 |

框架库的主要外部先验来自：

- [TikTok 官方六类叙事框架](https://ads.tiktok.com/business/en-US/blog/get-creative-6-storytelling-frameworks)
- [TikTok Creative Accelerator：演示、真实评价、教程、技巧和产品来源](https://ads.tiktok.com/business/creativecenter/quicktok/online/tiktok_creative_accelerator/pc/en)
- [TikTok 食品饮料创意指南：菜谱、演示、故事、问题解决、配料、味觉与 ASMR](https://ads.tiktok.com/business/creativecenter/quicktok/online/creative-tips-for-food-and-Beverage/pc/en)
- [TikTok 食品杂货指南：15—30 秒菜谱与日常情境](https://ads.tiktok.com/business/en/guides/food-and-grocery-guide)
- [TikTok 对 3,500 条广告的创意最佳实践分析](https://ads.tiktok.com/business/en-US/blog/creative-best-practices-top-performing-ads)
- [TikTok 转化型创意分析](https://ads.tiktok.com/business/en-US/blog/creative-that-drives-conversions)
- [巨量引擎 O-5A 人群经营与 A1/A2 种草语境](https://www.oceanengine.com/help/629)
- [巨量学品牌种草方法页面](https://school.oceanengine.com/page/Page9qKMzh6iQB)
- [Green 与 Brock：叙事运输机制](https://pubmed.ncbi.nlm.nih.gov/11079236/)
- [Escalas：叙事加工与自我—品牌连接](https://myscp.onlinelibrary.wiley.com/doi/10.1207/s15327663jcp1401%262_19)
- [Deighton 等：广告的戏剧式加工](https://ideas.repec.org/a/oup/jconrs/v16y1989i3p335-43.html)
- [Berger 与 Milkman：情绪唤醒与内容传播](https://doi.org/10.1509/jmr.10.0353)

所有平台与学术结论在界面中只标“外部先验”。真正决定保留哪条路线的是后续素材级 A3 转化率；投前向量分、框架先验分和 AI 质检分都不能判 winner。

### 8.4 分层内容框架库

种草内容不使用一条固定故事模板，也不维护一张相互重复的平面模板清单。生成公式固定为：

`时间功能骨架 × 叙事框架 × 证明框架 × 呈现母题 × content contract`

时间功能骨架负责确保前三秒、相关性、产品桥接、判断依据和 A3 收口都存在；叙事框架负责怎样组织故事；证明框架负责“凭什么相信”；呈现母题负责画面、声音和平台原生感。content contract 则固定真实需求、痛点、卖点、场景、证据边界和实际人群包。

registry 中每张框架卡必须保存 `id`、`framework_library_version`、`layer`、`fit_tags`、`required_evidence`、`eligible_production_tracks`、`source_refs`、`evidence_level` 和 `dependency_ownership`。来源字段用于解释为什么进入候选池，不得被转写成“已验证能提升本 SKU”。

#### 8.4.1 叙事框架

| ID | 名称 | 核心组织方式 |
|---|---|---|
| N1 | pain_solution 痛点命名/问题解决 | 先让人认出问题，再用产品动作和判断依据解决 |
| N2 | routine_integration 日常/习惯嵌入 | 把产品放进一段本来就会发生的生活流程，不以讲卖点开场 |
| N3 | result_reverse 结果前置/倒推过程 | 先给菜品或生活结果，再倒推关键选择与使用动作 |
| N4 | micro_drama 微型冲突/发现与解决 | 用一个真实微冲突推动人物发现问题和改变做法 |
| N5 | recipe_step 菜谱/步骤教学 | 以一道菜或一个具体操作步骤承载产品选择标准 |
| N6 | comment_qa 评论问答/真实 FAQ | 从真实高频疑问进入，用演示或原因解释回答 |
| N7 | origin_behind_scenes 产品来源/幕后故事 | 从可验证来源、工艺或幕后过程建立理解与信任 |
| N8 | multi_scene_use 多场景用途展示 | 用多个相邻生活场景证明产品如何融入目标人群日常 |

#### 8.4.2 证明框架

| ID | 名称 | 证据要求 |
|---|---|---|
| P1 | demonstration 实际使用演示 | 必须是产品可以真实完成的动作与可见结果 |
| P2 | comparison 并排对比 | 比较口径、条件和画面必须可执行且不偷换标准 |
| P3 | reason_why 原因解释 | 只能使用已继承的配料、工艺、规格或产品事实 |
| P4 | choice_standard 内行选择标准 | 标准必须能从真实事实推导，不虚构专家身份 |
| P5 | real_review 真实体验/味觉测试 | 框架目录中的真人素材扩展位；当前纯 AI V1 不可选。未来只有真实人物、真实素材和可追溯授权时可启用 |
| P6 | authority_evidence 资质/标准/权威证据 | 只有链路中存在可核验来源时可用，缺证据时硬阻断 |

#### 8.4.3 呈现母题

| ID | 名称 | 主要画面与声音语言 |
|---|---|---|
| V1 | recipe_montage 菜谱快剪 | 连续料理步骤、节奏型切换、关键动作字幕 |
| V2 | native_direct_narration 原生直述 | 像平台原生分享一样直接说一件具体的事 |
| V3 | tabletop_macro 桌面微距 | 产品、食材、质地和动作细节的桌面近景 |
| V4 | food_asmr 食物 ASMR | 倒、蘸、拌、煎炒和入口前后的真实声音主导 |
| V5 | skit_dialogue 双人/多人情景剧 | 用人物关系与短对话承载微冲突或问题命名 |
| V6 | multi_scene_voiceover 多场景配音叙事 | 多个生活片段由同一条叙事线和声音线串联 |

#### 8.4.4 兼容矩阵

不生成 8×6×6 的笛卡尔积。路由器只从以下被允许的组合中选候选；表中未列组合不能通过一次性参数绕过。用户可以提出新组合，但必须补齐适用理由、证据要求和 ownership，经审阅写入新的 framework_library_version 后才能用于实验。

| 叙事框架 | 可配证明框架 | 可配呈现母题 | 特别限制 |
|---|---|---|---|
| N1 | P1 / P3 / P4 | V2 / V5 / V6 | 痛点必须来自 content contract |
| N2 | P1 / P3 | V4 / V6 | 产品动作必须自然嵌入日常流程 |
| N3 | P1 / P2 | V1 / V3 / V6 | 前置的是结果或菜品，不是前三秒硬贴产品 |
| N4 | P1 / P3 / P4 | V5 / V6 | 冲突必须小而真，不制造夸张羞辱或焦虑 |
| N5 | P1 / P3 / P4 | V1 / V3 / V4 | 教程必须能在目标时长内真实执行 |
| N6 | P1 / P3 / P4 | V2 / V3 | 问题必须来自真实评论、搜索或画像阻断点；没有来源时标“画像疑问”而非伪装评论 |
| N7 | P3 / P6 | V3 / V6 | 来源、工艺、资质或权威信息必须可验证 |
| N8 | P1 / P2 | V1 / V4 / V6 | 多场景共享同一需求和卖点，不能变成卖点拼盘 |

P5 在当前纯 AI V1 的 eligible=false，不计入“至少两条合格路线”；未来接入真人素材 track 后再单独定义其兼容关系。P6 在证据校验通过前不得进入脚本生成。框架库必须有 version，历史实验继续引用当时版本，不能因后来增删框架而重写旧臂。

### 8.5 框架路由、冷启动与单变量迭代

#### 8.5.1 冷启动路由

当 content contract 已经固定、但尚无已采纳框架路线时：

1. 用真实需求、痛点、场景、情绪、卖点证据、生产模式和时长过滤兼容矩阵。
2. 对每条可行路线按人群相关性、卖点承接、证据诚实性、AI 生产可行性和与其他路线的差异度分别打 0—2 分；证据硬闸优先于总分。
3. 以 4 条为目标选出彼此有实质差异的路线；不能用同一叙事只换一个近义镜头凑数。硬闸后只有 2—3 条时不造假凑 4，少于 2 条时阻断。
4. 为全部入选路线各生成一份只读文本候选，固定同一痛点、卖点、场景命题、时长、产品动作边界和产品图。
5. 依次执行证据校验、产品—内容—人群三角审计、生产可行性检查和向量预筛。
6. 只把通过硬闸且预筛最高的 2 条展示为默认待采纳候选；其余通过硬闸的路线保留为可展开备选，不直接烧视频生成成本。
7. 把整次预筛持久化为一个 draft route manifest；它不可出片、不可挂实验臂。
8. 用户确认至少两条路线后，从 manifest 派生完整 render-candidate scripts；这些脚本以 `swept_variable=content_framework_route`，arm value 使用稳定 route id，例如 `N1+P3+V2@framework-v1`。用户审阅并正式采纳脚本后，才在 8.8 注册 Round 1 实验臂。

route manifest 复用现有 pipeline.scripts，不新增状态表：`status=draft`，`content_contract.artifact_role=route_manifest`，`render_eligible=false`。它保存 contract hash、framework_library_version、router/generator/prompt/embedding model version、全部文本候选及输出 hash、硬闸、评分、Top 2 和排除原因。派生的正式脚本通过 parent_script_id 指向 manifest，`artifact_role=render_candidate`。

shortlist 的资格与规则初排由 versioned registry 的结构化标签计算，LLM 只负责把已选路线实例化为文本。缺失事实按 unknown 处理，不让 LLM 推断补分。通过证据、兼容、生产可行性和三角阈值硬闸后，Top 2 使用固定排序键：`route_fit_total desc → triangle_score desc → vector_score desc → route_id asc`。向量只参与末级投前排序，不改变硬闸。

可复现性分两层承诺：同一结构化 contract 与 framework_library_version 的规则候选集可复现；LLM 文本和向量结果不承诺重新生成后逐字一致。系统用 `manifest_key = hash(contract + framework/router/generator/prompt/embedding versions + reroute_revision)` 幂等复用已经持久化的 route manifest 和 prescreen snapshot，默认 `reroute_revision=0`。用户明确要求“重新路由/换一版”时递增 revision，创建带 parent_script_id 的新 manifest 版本，不覆盖旧快照。

向量分只用于减少冷启动烧钱，不能淘汰用户明确要求保留且通过硬闸的路线，也不能代替投后 A3 判胜。路由器必须返回每条路线被选中、被排除和被硬阻断的具体原因。

#### 8.5.2 路线胜出后的拆分测试

Round 1 的 content_framework_route 是明确标注的复合变量，只能得出“整条路线在当前条件下领先”。锁定 winner 后：

1. 将 winner 的 content_framework_route、narrative_framework、proof_framework、presentation_motif 和 framework_library_version 原子写入 baseline。
2. 固定获胜内容命题、真实证据、product_action.core_use 和未被选择的两个框架层；测试 proof_framework 时只允许 product_action.proof_execution 按 ownership 联动。
3. 后续每轮只测试一个变量；可选顺序由投后漏损位置决定，而不是机械轮播。
4. 若改一个框架必然迫使痛点、卖点和证明事实一起改变，改用 content_framework_route 或 value_proposition_route，不伪装成原子变量。

框架层的原子测试示例：

- 测 narrative_framework：固定 P3、V2、痛点、卖点和 product_action.core_use，只比较 N1 与另一个兼容 N。
- 测 proof_framework：固定 N1、V2 和全部语义，只比较 P1 与 P3。
- 测 presentation_motif：固定 N1、P3 和完整脚本语义，只比较 V2 与 V6。

若兼容矩阵中不存在保持其余两层不变的合法备选，该原子变量本轮不可测试，系统选择其他变量，不能为了凑 A/B 破坏内容逻辑。

#### 8.5.3 数据回传后的变量映射

| 数据形态 | 优先检查与下一轮变量 | 不应做的事 |
|---|---|---|
| 三秒率低 | opening_hook_3s，或在语义固定时测试 presentation_motif | 直接换卖点并宣称钩子已修好 |
| 三秒率尚可、完播低 | narrative_framework、story_pace 或 edit_pace，一轮只选一个 | 同时改故事、镜头、BGM |
| 完播尚可、A3 低 | proof_framework、pain_point—selling_point bridge 或 product_action，一轮只选一个 | 用强购买 CTA 污染 planting intent |
| A3 高、ROI 低 | 保留 planting winner，另建 harvest 实验 | 把 planting winner 判失败或改用 ROI 排名 |
| 展现/消耗严重失衡 | 保持同一轮、补量或重跑 | 换新变量后把两轮混为一次比较 |

每轮 winner 合并进历史最佳 baseline；失败臂完整保留但不晋级。系统生成下一版时必须同时读取当前 baseline、全部已测变量、失败取值、数据窗口和本轮诊断，避免循环回到已经失败的路线。

### 8.6 默认 30 秒时间功能骨架

下表是覆盖内容任务的时间骨架，不是一条固定叙事模板。N1—N8 决定每个任务怎样被组织；例如 N3 可用菜品结果做前三秒入口，N5 可用步骤结果进入教学，N4 可用人物微冲突进入，但都必须完成相同的功能任务和产品桥接。

| 时间 | 内容任务 | 硬约束 |
|---|---|---|
| 0—3 秒 | 用可见痛点、情绪动作、场景冲突、结果画面或真实疑问让目标人群立刻认出“这是我” | 可以出现原生使用中的产品或菜品，但不做包装硬特写、不先喊品牌或卖点、不喊卖货口号 |
| 3—8 秒 | 建立相关性，命名问题、日常目标或未被说出的不适 | 人物身份、场景和问题具体；产品若出现，必须服务于动作或故事而非陈列 |
| 8—15 秒 | 让产品进入或完成需求—产品桥接 | 产品不是展示台道具，必须发生倒、蘸、拌、烹调等合理动作 |
| 15—24 秒 | 用所选 proof_framework 给出一个判断依据 | 全片产品功能介绍不超过一句，不堆卖点 |
| 24—30 秒 | 让情绪和场景落回生活，形成可记住的判断或未来使用画面 | 不用价格和强购买 CTA；允许搜索、收藏、评论或场景联想型 A3 触发 |

45 秒版本保持相同功能任务，只在证据确实需要时延长判断依据段；不能为了凑时长增加第二个故事、第二条价值命题或多套卖点。

8—15 秒是默认桥接窗口，不是所有路线的强制首次露出时间。N2、N3、N5 或 V4 可以把原生使用动作前置；只要前三秒仍完成相关性任务且没有变成硬卖货。product_entry 在基线中保存真实取值，后续可以在同一路线、同一语义和同一产品动作下作为独立变量测试。

### 8.7 每个候选脚本必须产出什么

每个 A/B/C arm 在脚本审阅阶段必须同时输出：

1. 本方案要把谁从什么障碍推向 A3。
2. 本轮唯一变量、该臂取值，以及与其他臂的唯一差异。
3. 框架路线卡：route id、framework_library_version、N/P/V 三层取值、适配理由、外部先验层级和证据硬闸结果。
4. 继承的卖点证据、具体痛点、场景、情绪和实际包信号。
5. 30 秒或 45 秒的完整时间轴脚本。
6. 6—9 个连续剧情节点，标明人物、动作、台词、声音和产品是否出场。
7. 角色定妆清单。
8. 产品出现计划：首次出现时间、每次使用动作、外观参考来源。
9. 按真实目标模型能力拆分的连续 AI 视频提示词。
10. 文字、画面、声音和产品动作四路信号。
11. metrics、自检结果、三角匹配结果和所有阻断告警。

脚本阶段必须展示一张“变量差异卡”。如果系统不能证明两臂只差本轮变量及其 dependency_allowlist 内的必要变化，就不允许用户采纳为正式 A/B。

### 8.8 从脚本到最终视频

用户采纳至少两个不同取值后，skill 继续执行：

1. 调 experiment_adopt_script，把脚本从 draft 变为 adopted，并挂到同一 open round 的不同 arm。
2. 调 generate_character_sheets，为各臂生成并验证角色定妆照。
3. 运行产品—内容—人群三角匹配、单变量 diff 和 content vector prescreen；前两者可以按策略阻断，向量只返回排序旁证，不作为硬闸。
4. 调 generate_video_segments，传入 product_ref、全部有效角色图和 experiment_arm_id。
5. 对每个视频段检查真实 provider/model、产品 refs used、人物连续性和产品动作。
6. 多段视频按剧情顺序确定性拼接成一个最终 MP4；统一分辨率、帧率、编码和音轨，不擅自新增转场、字幕或营销元素。
7. 最终 MP4 以 asset_type=video、scene_no=NULL 保存；generation_meta.asset_role=final，并记录全部 segment asset ids。
8. 对最终整条视频运行 visual prescreen，而不只检查单段。
9. gate 通过后返回最终 asset_id、文件地址、实验臂码和回传字段模板。

现有 generate_video_segments 只生成视频段，因此本功能必须补一个确定性的 assemble/finalize 能力。若目标模型一次直接生成完整视频，则跳过拼接，但仍要创建 final asset 并运行整片质检。

### 8.9 用户可见的阶段

skill 自身不保存状态，但必须向用户明确显示当前阶段：

- READY：血缘、内容契约和产品图已齐。
- ROUTE_REVIEW：route manifest 已落库；以 4 条为目标的文本路线已预筛，2 条默认候选等待确认，池不足时显示原因。
- SCRIPT_REVIEW：已从 manifest 派生正式 A/B render-candidate scripts，等待采纳。
- RENDERING：已采纳，正在定妆和生成视频段。
- ASSEMBLING：正在拼接和标准化最终 MP4。
- PRESCREEN_REVIEW：最终视频正在或已经完成投前质检。
- READY_FOR_TEST：成片和实验臂均就绪，可进入投放。
- METRICS_PENDING：等待回传。
- NEXT_ROUND_READY：已根据数据生成下一轮施工单。

这些是从真实 artifact 派生的用户界面阶段，不新增数据库状态枚举。

### 8.10 生成功能的返回值

框架预筛阶段返回：

- framework_library_version
- route_manifest_script_id、manifest_key 和 parent manifest id（若为重路由版本）
- 最多 4 条路线的 route id、N/P/V 组成、适配分、硬闸和排除原因；不足 4 条时返回 route_pool_limited 原因
- 默认展示的 2 条候选及向量、三角和生产可行性旁证
- 明确提示“投前分只用于排序，A3 才判 winner”

脚本审阅阶段返回：

- content contract 摘要
- candidate scripts
- variable diff 与 dependency allowlist
- validation gates
- script ids
- 下一动作“采纳至少两个不同取值”

正式出片阶段返回：

- final video asset ids 和文件地址
- segment asset ids
- 实际 provider/model
- product refs requested/used
- character sheet asset ids
- prescreen 结果
- experiment id、round no、arm ids 和 arm codes
- 投放命名建议与数据回传模板

只有 final video asset 存在且 prescreen 通过时，skill 才能说“种草短视频已生成完成”。

### 8.11 软广的复用边界

ai-soft-ad-video 复用同一套产品图验证、定妆、视频段生成、最终拼接、整片质检、框架变量契约和实验挂臂能力，但使用 soft_ad 自己的框架库、内容骨架与播放质量指标。planting 的 N/P/V 枚举不直接复制给 soft_ad；两者只共享路由接口和单变量状态机。不能为了共享渲染器而让软广使用 planting 的产品浓度和 A3 判断依据。

## 9. 上游兼容与 SKU002 补强

### 9.1 三类兼容结果

- directly_usable：字段和证据完整，直接继承。
- migratable：原文已有信息但结构旧，确定性迁入 content contract。
- rerun_required：信息真正缺失、冲突或可信度过低，只重跑该节点的新版本。

旧版本不覆盖，不伪造新字段。

### 9.2 SKU002 处理

- 保留现有云图实际人群包及外部 ID，不重新圈包。
- 从旧 matrix 和 record 迁移已有痛点、需求和场景。
- 旧卖点没有证据等级时标 unknown。
- 当前 portrait 信息丰富，但存在 KB 覆盖不足警告；使用最新规则、实际云图画像和同一 audience record 补跑新 portrait 版本，审阅后采纳。
- 现有 pack 继续使用，同时补实际采用的 portrait 版本和内容继承快照。
- 只有 readiness check 仍发现关键事实缺失时，才补跑对应分析节点。

### 9.3 旧 planting M1—M9 的确定性迁移

旧模块不再作为新实验的并行变量体系，但历史脚本必须能解释。迁移表固定为：

| 旧模块 | 新框架字段 | 迁移规则 |
|---|---|---|
| M1 Slice of Life | N2 routine_integration | 若旧脚本明确为多场景用途，再迁为 N8；不能仅凭模块名猜成 N8 |
| M2 Problem-Naming | N1 pain_solution | 保留原问题命名文本为 opening/pain framing，不新增痛点 |
| M3 Insider Reveal | P4 choice_standard | 只迁移可执行的选择标准；旧“内行身份”没有可验证来源时丢弃身份主张 |
| M4 Origin Story | P3 reason_why，proof_method=origin_story | 旧 M4 是判断依据层，默认不再生成第二个 narrative_framework；只有旧脚本明确以来源故事为主叙事且没有与 M1/M2 产生双叙事时，才可人工审阅迁为 N7 |
| M5 Comparison Frame | P2 comparison | 保留旧比较对象、口径和条件；缺任一项则标 unknown |
| M6 Reason-Why | P3 reason_why | 只迁移有事实来源的理由 |
| M7 Testimonial | P5 real_review | 当前纯 AI V1 标 ineligible，不把旧证言改写成 AI 人物 |
| M8 Demonstration | P1 demonstration | 保留真实可执行的动作与结果 |
| M9 Authority Endorsement | P6 authority_evidence | 缺可核验机构、标准或资质来源时硬阻断复用 |

旧组合必须先按“M1/M2 → narrative、M3—M9 → proof”拆层，再运行新兼容矩阵和证据资格校验。映射后不兼容、P5 在纯 AI 下不可用、P6 缺证据，或出现两个 narrative_framework 时，只能作为历史展示，不能生成当前 content_framework_route，也不能成为新实验 baseline。

旧 M 体系没有独立 presentation_motif。迁移时只从旧脚本已有镜头、声音和结构化字段确定性识别 V1—V6；无法确定时标 `presentation_motif=unknown`。只有 N/P/V 完整、组合兼容且证据合格的旧产物才能生成 route id；其余产物保留查看并在需要续跑时重走新 router。旧 `selected_combo`、原文和迁移结果同时保留，禁止覆盖历史。

## 10. 产品白底图与真实出片模型硬闸

### 10.1 产品图检查

产品白底图在首次内容前检时就是必需输入，而不是等到视频渲染时才补。正式生成候选和出片前必须确认：

- 文件可读且为有效图片。
- 背景是白底或干净中性底。
- 图片由用户绑定当前 SKU；身份不确定时停止并请求确认。
- 分辨率足够，瓶型、标签、瓶盖和包装信息可辨认。
- 文件哈希写入 content contract。
- 各实验臂使用相同产品图。

soft_ad 前三秒可以不出现产品，但整条素材仍必须绑定产品图。video_soft_ad 和 video_planting 禁止 allow_no_product 旁路。

### 10.2 模型一致性

系统必须区分：

- 生成脚本所用 LLM
- 请求的视频模型
- 实际出片 provider/model

请求模型、数据库记录和实际调用必须一致。若模型不支持产品 reference-to-video，或运行时清空 product refs，则 fail-close，不允许继续出片。

拆段长度按实际模型档案确定，不能把所有模型统一写死为 15 秒。

## 11. 投后数据契约

### 11.1 共同必传

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

### 11.2 软广必传

- plays
- play_3s 或 play_3s_rate
- play_complete 或 completion_rate
- 平均观看时长（平台有则传）

### 11.3 种草必传

- a3_ratio
- 推荐同时传 new_a3 和对应分母
- 对应分母统一为 a3_eligible_users；平台没有分母时明确标记 unavailable
- CTR
- 基础播放指标

人群包不重复回传，通过 asset → script → pack 血缘自动确定。

### 11.4 ROI 口径

- GMV 与 spend 都有时，由后端复算统一 ROI。
- 平台直接导出的 ROI 保存为 platform_reported_roi，并带 source=platform_export；它可以作为旁证，但不得覆盖后端统一口径。
- ROI 不参与 soft_ad 或 planting 的主 winner 排序。

### 11.5 多次回传

V1 沿用 pipeline.assets.ad_metrics JSONB 的累计合并，并增加规范化窗口元字段。

软广有原始计数时，优先用聚合计数计算完播率和三秒率；种草同时有 new_a3 与 a3_eligible_users 时，优先用两者计算 pooled A3 转化率。只有平台未提供分子、分母时，才使用平台回传的素材级 rate，并在结果中标明聚合口径。

若未来需要同一素材保存多个窗口快照和趋势，再增加 append-only asset_metric_snapshots 事实表。该事实表不是状态机，本期不创建。

## 12. 判胜、诊断与下一轮建议

### 12.1 可判胜条件

- 至少两个有效实验臂。
- 数据窗口一致并结束。
- 达到 evaluation policy 配置的最低展现、消耗或行为量。
- 各臂曝光和消耗没有超过允许失衡范围。
- 比率指标有足够分母。

现有“每臂 n≥5”只保留为稳定性旁证，不再是唯一闸门。工程门槛不等于统计显著；数据不足只显示“当前领先”。

### 12.2 诊断规则

系统先输出观察事实，再输出待验证假设，禁止写成因果定论。

软广：

- 三秒低：优先测试 opening_hook_3s；若钩子语义已验证，再在语义固定时测试首帧或 presentation_motif，一轮只选一个。
- 三秒高、完播低：优先测试 narrative_framework、情绪推进、story_pace 或 edit_pace，一轮只选一个。
- 三秒和完播高、播放效率低：优先测试 presentation_motif、visual_vector、text_vector.presentation 或 sound_vector，一轮只选一个。

种草：

- 三秒低：优先测试 opening_hook_3s；若开头语义相同但原生感弱，再测试 presentation_motif。
- 三秒尚可、完播低：优先测试 narrative_framework、story_pace 或 edit_pace，一轮只选一个。
- 完播尚可但 A3 低：优先测试 proof_framework、痛点—卖点—产品桥或 product_action，一轮只选一个。
- A3 高、ROI 低：保留种草胜者，进入独立收割实验。
- 曝光或消耗严重失衡：不换变量，先补量或重跑当前轮。

### 12.3 下一变量算法

1. 找当前最明显的漏损位置。
2. 映射到对应变量组。
3. 排除已经测试、已经失败或按策略锁定的变量与取值。
4. 对框架子变量，只保留能与另外两个已锁定 N/P/V 字段组成合法兼容路线的取值。
5. 若某原子变量不足两个合法取值，则跳过该变量；确实需要同时联动多个框架层时，升格为 content_framework_route，而不是暗改其他轴。
6. 选一个尚未测试的高优先级变量。
7. 固定完整历史最佳基线、数据口径和未被扫变量。
8. 生成 2—3 个下一轮取值，并在生成前后运行变量所有权 diff。

推荐顺序不是固定轮播，也不是让 LLM 自由发挥。

### 12.4 历史最佳

每轮保存：

- swept variable
- 各臂 value
- 指标和数据窗口
- 当前领先或正式 winner
- winner 合入后的 baseline
- 决策理由
- 下一轮建议和对应假设
- 该结论是“复合路线领先”还是“原子变量取值领先”

失败臂保留用于复盘，但不进入 baseline。

## 13. 数据模型

复用现有 experiments → experiment_rounds → experiment_arms → assets.ad_metrics，不增加表或状态枚举。

建议的加法字段：

### 13.1 pipeline.scripts

- content_contract JSONB NOT NULL DEFAULT {}
- target_video_model TEXT

content contract 包含 schema version、永久事实、framework library/version、route id、N/P/V、证据资格、baseline、sweep、dependency_allowlist、变量清单、请求模型和产品图清单。

同一张 scripts 表承载两种 artifact_role：

- route_manifest：保存 4→2 预筛快照，render_eligible=false，禁止 experiment_adopt_script 和出片。
- render_candidate：从 manifest 派生的完整候选脚本，parent_script_id 指向 manifest；只有通过正式 validator 后才可采纳和出片。

artifact_role、render_eligible、manifest_key 和 prescreen snapshot 均放在 content_contract，不新增状态枚举。

### 13.2 pipeline.assets

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
- asset_role：segment 或 final
- segment_asset_ids：final asset 使用的全部视频段
- assembly 参数和整片音视频探测结果

### 13.3 pipeline.audience_packs

- audience_portrait_id UUID NULL
- execution_meta JSONB NOT NULL DEFAULT {}

用于补齐实际采用画像到人群包的血缘，并保存外部人群包 ID、实际包画像来源、估算人数和执行时间。

### 13.4 pipeline.experiments

- audience_pack_id UUID NULL
- evaluation_policy JSONB NOT NULL DEFAULT {}

显式绑定实际人群包；evaluation policy 保存该实验的归因窗口、最低样本、曝光失衡门槛、guardrails 和 policy version。

### 13.5 pipeline.experiment_rounds

- evaluation_snapshot JSONB NOT NULL DEFAULT {}

保存锁定或判定时的事实、假设、指标快照和下一轮建议。它是审计快照，不是新状态。

现有 experiments.baseline、rounds.swept_variable/baseline_snapshot、arms.variable_value 和 assets.experiment_arm_id 继续作为唯一实验状态来源。

### 13.6 框架基线的原子合并语义

不为框架路由新增表。arm.variable_value 在 content_framework_route 轮保存稳定 route id；该 id 是 N/P/V + framework_library_version 的只读派生键。完整主值、证据资格和 dependency_allowlist 保存在该 arm 对应 script.content_contract 中。

锁定 winner 时不能沿用简单的 `baseline[swept_variable] = variable_value` 处理所有情况：

- content_framework_route 胜出：在同一事务中从获胜脚本写入 N/P/V、framework_library_version，并先删除再替换三层 ownership allowlist 内的全部派生路径，包括 story_structure、proof_method、product_action.proof_execution、scene.execution_instances、production_cast_form、visual_vector、text_vector.presentation、sound_vector、story_pace 和 edit_pace；最后确定性生成 content_framework_route。不能让新主值继续携带旧路线的派生实现。
- narrative_framework、proof_framework 或 presentation_motif 胜出：更新该主字段，并先删除再替换该字段 ownership allowlist 内的获胜派生路径；其余两层主值与派生字段保持不变，再确定性重算 content_framework_route。
- 其他 swept variable 胜出：只 patch 变量 registry 明确拥有的路径；registry 未登记路径一律不合并。
- 重算后的组合必须再次通过兼容矩阵；不兼容则拒绝锁定，不做隐式修补。
- 失败臂、旧 baseline_snapshot 和旧 route id 全部保留，不能被新 route 覆盖。

这样 experiments.baseline 仍是唯一当前最佳来源，script.content_contract 是该臂当时完整事实，experiment_rounds.evaluation_snapshot 是判定时审计快照，三者职责不重叠。

## 14. 服务、工具和 Prompt 改造

### 14.1 内容桥接

- 扩展卖点解析器，解析痛点原料、真需求和完整场景块。
- 用 section-aware 字段抽取替换全局 36 行关键词抢占。
- portrait 内容槽优先于 record 和 pack 的冗余摘要。
- audience pack 固定输出内容继承卡。

### 14.2 生成

- 建立带 version 的 planting framework registry，保存 N1—N8、P1—P6、V1—V6、兼容矩阵、证据资格和宏变量所有权。
- 建立确定性 framework router：先硬闸，再按契约适配度以 4 条为目标选文本路线；LLM 负责实例化内容，不负责绕过兼容规则。
- 建立 framework compatibility/evidence validator；不足两条合格路线时阻断，不随机兜底。
- 建立 route manifest 的幂等保存、续跑与派生服务；manifest 本身在采纳和出片入口 fail-close。
- generate_creative_pack 构建、校验并持久化 content contract。
- video_soft_ad 和 video_planting 使用各自 profile。
- 修复 planting prompt 与 validator schema。
- 所有 repair suffix 只使用当前 lineage，不得包含固定 SKU 文案。
- 脚本保存后运行单变量 diff、宏变量 ownership diff 和三角审计；向量只生成 prescreen 排序旁证。

### 14.3 出片

- 校验产品图文件和绑定。
- 持久化实际 provider/model 和 refs used。
- 产品 ref 被运行时清除时停止。
- whole-prompt 模式按模型能力拆段。
- 角色定妆全失败时不得返回可继续状态。
- 增加确定性的 assemble/finalize 能力，把视频段按时间顺序拼成最终 MP4。
- 拼接后统一视频编码、分辨率、帧率和音轨，并用媒体探测校验时长、画幅、视频流和音频流。
- 最终整片单独落 asset，整片 prescreen 通过后才进入 READY_FOR_TEST。

### 14.4 实验

- planting 默认 north star 改为 a3_ratio。
- soft_ad 保持 completion_rate，并增加 play_3s_rate guardrail。
- 扩展变量注册表，加入 content_framework_route、narrative_framework、proof_framework、presentation_motif、痛点、证明方式、产品出现和动作、文字与声音向量等。
- experiment_lock_winner 按 13.6 原子合并框架基线，并在子字段获胜后重算 route id。
- experiment_status 使用 evaluation policy 进行判胜资格检查。
- experiment_next_version_seed 使用诊断映射、兼容矩阵和全部历史选择下一变量；曝光失衡时保持原 round 变量，不推进变量池。

### 14.5 数据回灌

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

### 14.6 Skill 与渐进披露结构

canonical skill 结构固定为：

- `.agents/skills/ai-planting-video/SKILL.md`：只保留触发、总流程、硬闸、阶段路由和何时读取哪份 reference，控制在 500 行以内。
- `.agents/skills/ai-planting-video/references/planting-framework-library.md`：N/P/V 框架卡、兼容矩阵、证据要求、迁移映射和示例。
- `.agents/skills/ai-planting-video/references/experiment-state-machine.md`：冷启动 4→2、采纳、挂臂、回传、判胜、baseline 合并和下一轮单变量规则。
- `.agents/skills/ai-planting-video/references/content-contract-schema.md`：字段、变量所有权、dependency_allowlist 和 diff 约定。
- `.agents/skills/ai-soft-ad-video`：保持独立触发与自己的内容库，但复用相同实验状态机和 contract 语义。
- `.claude/skills/soft-ad-ai-video`：只做兼容路由，不复制业务规则。

SKILL.md 不复制框架全文；只有进入路线选择时才读 framework library，进入实验续跑时才读 experiment state machine，进入契约校验时才读 content contract schema。

## 15. 前端

不新建页面，扩展现有 SKU Pipeline 创意素材区和 A/B 实验看板：

- 内容契约预览
- 当前链路和实际包画像来源
- 4→2 框架预筛卡：N/P/V、兼容性、证据资格、入选/淘汰原因和“仅投前旁证”提示
- 唯一阻塞项
- 本轮变量及各臂差异
- 产品图和模型验证状态
- 投后指标排名
- 观察事实、待验证假设
- 下一轮单变量施工单
- 历史 baseline 与 changelog

所有新增产物区继续挂 OutputFeedback。

## 16. 错误处理

错误按执行顺序只返回最靠前的一个：

1. upstream_content_incomplete
2. portrait_confidence_low
3. missing_product_ref
4. product_ref_invalid
5. product_ref_sku_mismatch
6. framework_route_incompatible
7. proof_evidence_missing
8. insufficient_eligible_routes
9. route_manifest_not_renderable
10. target_model_mismatch
11. multi_variable_drift
12. triangle_match_low
13. character_sheet_failed
14. product_refs_dropped
15. segment_generation_failed
16. assembly_failed
17. final_media_invalid
18. prescreen_failed
19. attribution_window_open
20. insufficient_sample
21. exposure_imbalance

framework_route_incompatible 和 proof_evidence_missing 默认是单条路线的排除原因；只在用户强制指定该路线，或排除后使合格路线少于两条时升级为本次流程的顶层错误。insufficient_eligible_routes 和 route_manifest_not_renderable 始终是顶层阻断。所有框架与 manifest 错误必须在正式视频生成前返回。修复后从当前位置继续，不重跑已经完成且仍然有效的产物。

## 17. 测试与验收

### 17.1 上游与兼容

- SKU002 旧 matrix、record、portrait、pack 作为真实 fixture。
- 旧格式可迁移字段不丢。
- 缺字段标 unknown/missing，不伪造。
- portrait 新旧版本均可解析。
- 旧 planting M1—M9 按 9.3 确定性迁移；未知 V 字段不靠猜测补齐。

### 17.2 单变量

- 除 swept variable 外完全一致时通过。
- 同时改两个变量返回 multi_variable_drift。
- LLM 擅自改场景或卖点可被生成后校验发现。
- winner baseline 能正确进入下一轮。
- Round 1 扫 content_framework_route 时，N/P/V 和 ownership 表内的必要派生差异不会被误报；额外改变痛点、卖点、人群或价值路线仍报漂移。
- 扫 narrative_framework、proof_framework 或 presentation_motif 时，另外两层保持固定，且新组合仍通过兼容校验。
- presentation_motif 允许声明内的镜头、剪辑和声音变化，但任何脚本语义变化都会被拦截。
- dependency_allowlist 之外的变化不能以“框架自然联动”为理由放行。

### 17.3 框架路由

- N1—N8、P1—P6、V1—V6 的 ID 唯一，registry 与兼容矩阵可按 version 加载。
- 同一结构化 content contract 与 framework_library_version 得到可复现的规则候选集；LLM 文本不宣称重新生成后逐字可复现。
- 同一 manifest_key 重试会复用已持久化的文本、向量、三角结果和 Top 2 排序；明确“重新路由”才创建带 parent_script_id 的新 manifest。
- Top 2 严格按 `route_fit_total → triangle_score → vector_score → route_id` 排序，前置硬闸失败的路线永不参与排名。
- router 永不自动输出兼容矩阵之外的组合；不足两条合格路线时返回 insufficient_eligible_routes。
- 纯 AI 自动排除 P5；P6 无可验证来源时返回 proof_evidence_missing。
- 合格池充足时冷启动生成 4 条文本路线；只有通过硬闸的 Top 2 默认进入正式脚本与渲染。合格池只有 2—3 条时不凑数，少于 2 条时阻断。
- 向量高分只能改变预筛排序，不能锁 winner，也不能越过证据或兼容硬闸。
- 每条路线保存 framework_library_version、route id、N/P/V、入选/淘汰理由和证据资格。
- 已锁定两个框架层后，第三层不足两个兼容取值时跳过该原子变量，不偷偷改动其他层。
- route manifest 可以恢复 ROUTE_REVIEW，但 experiment_adopt_script 和出片入口必须返回 route_manifest_not_renderable；只有它派生的 render_candidate 可继续。
- 旧 M 组合迁移后重新过兼容与证据校验；不兼容、P5/P6 不合格或 V unknown 时只保留历史展示，不生成新 route id。

### 17.4 产品和模型

- 无图、失效图、非图片、明显非白底、错 SKU 均停止。
- mock 实际视频 provider，断言产品 refs 真正转发。
- refs 被 provider 清除时 fail-close。
- target model 的 prompt profile、持久化值和实际 provider/model 一致。
- seedance、veo、jimeng 使用各自真实时长能力。
- 多段结果能按顺序拼接成一个最终 MP4。
- 最终 MP4 的时长、9:16 画幅、视频流和音轨通过媒体探测。
- 缺段、乱序、无视频流或拼接失败时不能创建 READY_FOR_TEST 的 final asset。

### 17.5 Prompt 与质检

- planting 标准输出经 validator 零伪告警。
- 缺关键字段会硬告警或阻断。
- 三角匹配任一关键边低于阈值时禁止烧视频。
- pure AI 不生成假消费者证言或假权威。
- 醋、黑醋、寿喜烧等 SKU 不出现 SKU002 酱油事实。

### 17.6 数据与循环

- 软广按三秒门槛和完播率判定。
- 种草按 a3_ratio 判定。
- A3 CSV 表头能默认映射。
- 曝光或消耗失衡时不能锁 winner。
- 曝光或消耗失衡时保持原 swept variable 和 baseline 重跑，不错误推进到下一变量。
- 窗口未结束或样本不足时只显示当前领先。
- content_framework_route winner 在同一事务中原子替换 N/P/V、framework_library_version、全部 ownership 派生字段并重算 route id；不存在“新框架 + 旧 proof/画面”的陈旧组合。
- N/P/V 子变量 winner 只更新该主字段及其 ownership 派生路径，再确定性重算 route id；不兼容时拒绝锁定。
- 第一轮 winner 合入 baseline，第二轮只改变一个新变量。
- 多轮 changelog 能回答“每轮改了哪里、为什么、结果如何、下一步改什么”。
- changelog 明确区分“整条复合路线领先”和“某个原子变量取值领先”。

### 17.7 Skill

- ai-soft-ad-video 与 ai-planting-video 触发互不抢占。
- “软广、播放、前三秒”进入 soft-ad。
- “深度种草、A3、建立相信、痛点与卖点连接”进入 planting。
- 两个 skill 均通过 skill quick validation。
- ai-planting-video 的 SKILL.md 保持精简，并只在对应阶段读取三份 reference；reference 缺失时明确阻断而非回退到内置旧框架。
- 正向触发、近似表达和负向越界样例均通过触发测试，软广与种草不会因共享状态机而互相抢占。

## 18. 发布顺序

1. 共享内容契约、解析和单变量校验。
2. 建立 versioned framework registry、兼容矩阵、证据硬闸、4→2 router 和宏变量 ownership diff。
3. 完成旧 M1—M9 确定性迁移器与只读兼容测试。
4. 数据模型加法迁移与框架 baseline 原子合并。
5. 实验北极星、指标窗口、判胜和下一变量算法升级。
6. 产品图、模型一致性和三角硬闸。
7. 视频 assemble/finalize 与最终整片质检。
8. 改造 canonical soft-ad skill。
9. 创建 planting skill 及三份渐进披露 reference。
10. 前端现有页面增加框架预筛、变量差异和诊断卡。
11. 用 SKU002 做只读迁移预检。
12. 补跑并审阅 SKU002 portrait 新版本。
13. 用户提供产品白底图后以 4 条为目标生成文本路线，并确认 Top 2 第一轮脚本候选。
14. 用户采纳后生成最终 MP4、投放、回传并验证 Round 1 → Round 2。

## 19. 完成定义

设计完成后的真实用户体验应是：

1. 用户从某个 SKU 已有人群包链路发起软广或种草视频生成。
2. 系统自动继承卖点、人群、画像、人群包和实际画像。
3. 缺产品白底图或关键内容事实时明确阻断。
4. 新种草实验先从兼容框架库以 4 条为目标生成文本路线，经硬闸与投前排序后展示默认 Top 2，并明确本轮唯一变量；已有实验直接按历史诊断生成 2—3 个单变量候选。
5. 用户采纳后生成具有完整血缘、通过整片质检的最终 MP4。
6. 平台数据按素材和实验臂回传。
7. 系统说明当前 winner、客观依据、样本限制和下一版只改哪里。
8. 复合框架路线胜出后先原子锁定 N/P/V；下一轮固定历史最佳，只测试一个新变量。
9. 循环持续到指标达标、变量收敛、数据不足、瓶颈转移或用户停止。

系统保证历史最佳基线不会被失败实验覆盖，但不承诺每一条新试验都优于上一条。
