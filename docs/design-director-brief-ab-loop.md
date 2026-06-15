# 编导 Brief A/B 单变量迭代闭环 — 总施工方案（设计稿·待老板审）

> 2026-06-15 设计 workflow（5 组件规格 + 2 对抗 review + 综合）产出。已吸收全部高/中危漏洞修法。
> 代码库 `E:\agent\omni`。节拍=真实投放天/周，**不跑 agent loop**；loop = 持久化状态机 + 数据飞轮回流桥（harness engineering）。
> 落地后施工历史进 `docs/build-log.md`。

---

## 0. 四个拍板决定怎么落地

| 老板决定 | 落地点 |
|---|---|
| ① 北极星按广告类型分 | `INTENT_NORTH_STAR` 单一常量（`metric_registry.py`），key 全取自 `ad_metrics` 白名单；视图按 `experiments.north_star_metric` 动态从 JSONB 取值 |
| ② A/B 粒度 = flight 内扫一变量 | `experiment_rounds.swept_variable` + `UNIQUE(experiment_id, round_no)` 强制单变量；winner 锁进 `experiments.baseline` JSONB，下轮继承 |
| ③ 首版全做 | ①状态机表+视图 ②brief 加 intent ③实验 tools ④沉淀桥 ⑤前端看板 全部在本方案 |
| ④ 节拍真实天/周 | 6 个状态机 tool 全确定性 SQL（排名/判winner/汇总/建议下变量）；LLM 只在 `generate_director_brief`（生成 K 臂）+ `experiment_distill`（提炼规则）两点 |

**新增 MCP tool = 7**（6 状态机 + 1 沉淀桥）。**doctor wanted：89 → 96**（实测库内现值是 89，CLAUDE.md 头部写的 81 是 stale，本次顺手修对）。

---

## 1. 对抗 review 高/中危漏洞 — 已吸收的修法（施工必须按此）

### 跨组件统一（最致命，三方 spec 各写各的）
- **【P0】维度字段名统一为 `intent`**（不是 `ad_type`）。全链路一套英文枚举 `planting / harvest / soft_ad / hard_ad`。`scripts.intent` 额外允许 `generic`（无意图历史行）；`experiments.intent` 不允许 generic。
- **【P0】render scope 加 `intent` 键**（`portrait_brief.py:552`）。当前 `{"sku_id","target_model"}` 缺 `intent` → 任何带 intent 的 prompt_rule 因 `@>` 不匹配**永远命不中且 fail-open 无报错**（白沉淀）。改 `{"sku_id","intent","target_model"}`。
- **【P0】north-star key 全取自 `ad_metrics` 白名单 + tool 层校验**。唯一权威映射：
```python
# metric_registry.py —— 唯一一份，D2/D3/D4 全 import，禁第二份
INTENT_NORTH_STAR = {
    "planting":  ("completion_rate", "higher", ["like_rate", "a3_ratio"]),
    "harvest":   ("roi",             "higher", ["cvr", "gmv"]),
    "soft_ad":   ("completion_rate", "higher", ["new_followers"]),
    "hard_ad":   ("roi",             "higher", ["cvr"]),
}
```
`experiment_create` 落库前用 `ad_metrics_validation._WHITELIST` 校验，不在则 `{ok:False,error:"bad_north_star_metric"}`。

### 数据模型（D1 对抗发现）
- **【高】asset→arm 写入通道补上**：`record_ad_metrics` 加 `experiment_arm_id` 入参，命中 asset 时一并写 `assets.experiment_arm_id + experiment_id`。否则视图永远空。
- **【高】winner 排序一律用 avg，砍 `north_star_agg` 列**：sum 会把"投得多"误判成"取值好"。视图同吐 avg+sum（展示），**winner SQL 只 ORDER BY avg**。
- **【中】采纳三表**（experiments + experiment_rounds + experiment_arms）；`UNIQUE(experiment_id, round_no)` 强制单变量纪律。
- **【中】砍 `current_round_no` 冗余**（派生 MAX）；砍 `arms.asset_id` 单数列（一臂多视频走 assets.experiment_arm_id 一对多）。
- **【中】baseline 推进加 round 快照 + 覆盖告警**（已存在变量返 warning 不静默 `||` 覆盖）。
- **【低】三方 migration 052 撞车 → 合流成一份 `052_experiment_lab.sql`**（纯加法）。

### 沉淀桥（D4 对抗发现）
- **【P1】rule_text 默认纯模板，LLM 润色 opt-in**（`polish=False` 默认，镜像 `diagnose_audience_pack`）。事实 100% 来自 baseline。
- **【P1】白名单子集校验 > 黑名单**：polish 时润色后实词必须 ⊆ {baseline 值词 ∪ 模板词 ∪ 虚词白名单}，否则降级回模板。黑名单补**比较级盲区**（更/优于/有效/明显/抓住/吸引/打动）。
- **【P1】最低样本硬门槛**：`n<3` 不生成规则只入观察区；`n∈[3,5)` → `[待验证]`+"倾向"；`n≥5` 正式。
- **【P1】人读框架每行 observation 带免责句**："未排除平台分发量级/冷启动差异，差距方向仅供参考"。
- **【中】判重锚加列 `source_experiment_id + source_round_var`**（不复用 `created_from`——会触发 prompt_feedbacks.applied_as 回写炸链）。

---

## 2. 施工六阶段

### ① migration `052_experiment_lab.sql`（新建，纯加法幂等）
三表 DDL：
```sql
CREATE TABLE IF NOT EXISTS pipeline.experiments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sku_id VARCHAR(64) NOT NULL,
    portrait_id UUID REFERENCES pipeline.audience_portraits(id) ON DELETE SET NULL,
    audience_record_id UUID, audience_run_id UUID, matrix_run_id UUID,
    intent TEXT NOT NULL CHECK (intent IN ('planting','harvest','soft_ad','hard_ad')),
    north_star_metric TEXT NOT NULL,
    north_star_direction TEXT NOT NULL DEFAULT 'higher_better'
        CHECK (north_star_direction IN ('higher_better','lower_better')),
    title TEXT, baseline JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','converged','archived')),
    notes TEXT, actor_id VARCHAR(64) DEFAULT 'yark', adopted_by VARCHAR(64) DEFAULT 'yark',
    winning_framework_md TEXT, framework_distilled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS pipeline.experiment_rounds (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experiment_id UUID NOT NULL REFERENCES pipeline.experiments(id) ON DELETE CASCADE,
    sku_id VARCHAR(64) NOT NULL, round_no INTEGER NOT NULL CHECK (round_no >= 1),
    swept_variable TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','locked')),
    winning_arm_id UUID, baseline_snapshot JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (experiment_id, round_no)
);
CREATE TABLE IF NOT EXISTS pipeline.experiment_arms (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    round_id UUID NOT NULL REFERENCES pipeline.experiment_rounds(id) ON DELETE CASCADE,
    experiment_id UUID NOT NULL, sku_id VARCHAR(64) NOT NULL,
    round_no INTEGER NOT NULL CHECK (round_no >= 1),
    swept_variable TEXT NOT NULL, variable_value TEXT NOT NULL,
    arm_label TEXT NOT NULL CHECK (arm_label ~ '^[A-Z]$'),
    script_id UUID REFERENCES pipeline.scripts(id) ON DELETE SET NULL,
    hypothesis TEXT, is_winner BOOLEAN NOT NULL DEFAULT FALSE,
    is_baseline_locked BOOLEAN NOT NULL DEFAULT FALSE, forced BOOLEAN NOT NULL DEFAULT FALSE,
    decided_reason TEXT, notes TEXT, actor_id VARCHAR(64) DEFAULT 'yark', adopted_by VARCHAR(64) DEFAULT 'yark',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (round_id, arm_label)
);
ALTER TABLE pipeline.assets
  ADD COLUMN IF NOT EXISTS experiment_id UUID REFERENCES pipeline.experiments(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS experiment_arm_id UUID REFERENCES pipeline.experiment_arms(id) ON DELETE SET NULL;
ALTER TABLE pipeline.scripts ADD COLUMN IF NOT EXISTS intent TEXT;
ALTER TABLE pipeline.scripts ADD CONSTRAINT scripts_intent_check
    CHECK (intent IS NULL OR intent IN ('planting','harvest','soft_ad','hard_ad','generic'));
ALTER TABLE knowledge.prompt_rules
  ADD COLUMN IF NOT EXISTS source_experiment_id UUID,
  ADD COLUMN IF NOT EXISTS source_round_var TEXT;
```
汇总视图 `pipeline.v_experiment_round_results`：按 `north_star_metric` 动态从 `assets.ad_metrics` JSONB 取值（正则容忍尾部 `%`），`avg` 为 winner 唯一排序口径，`n_videos<5` 标 `preliminary`，只算 `status IN ('published','adopted')` 的 asset。`v_asset_full_lineage` 纯加法重建补 intent/arm/is_winner。

**验收**：052 幂等跑两遍无错；手插 experiment+round+2arm+assets 带 completion_rate，视图 avg 正确、n<5 标 preliminary；存量行不受影响。

### ② brief 加 intent + 4 个 profile（改存量，不加 tool）
- `portrait_brief.py`：`generate_director_brief` 加 `intent="generic"` 形参 + 热加载 `brief_intent_profiles/{intent}.md`（照抄 target_model 模式）+ render scope 加 intent 键 + result/scripts.intent 透传。
- `director_brief.user.md`：加 `## ⓪ 投放意图方法论锚` 占位。
- 新建 `config/prompts/brief_intent_profiles/{planting,harvest,soft_ad,hard_ad}.md`（蒸馏自 creative_pack 三档，禁重写方法论）。
  - planting：禁硬转化，卖点≤1句嵌剧情，前5s禁品牌；北极星 completion_rate
  - harvest：强CTA必给，1-2成交卖点前3s亮，可上信任锚；北极星 roi
  - soft_ad：品牌名≤1次，零产品讲解，结尾开放；北极星 completion_rate+new_followers
  - hard_ad：复用 harvest + ≤15行硬广增量层
- profile 故意不进 doctor `_check_prompts`（同 video_model_profiles，热加载缺了回退 generic）。

**验收**：`intent` 不传 → 行为与今天完全一致（零回归）；传 harvest → user_msg 含 profile + scripts.intent 落 'harvest'；render scope 含 intent 键。

### ③ 实验 tools + 确定性状态机（6 新 tool）
新建 `app/services/experiment_lab.py`（含 `SWEEP_VARIABLE_POOL`：opening_hook_3s→intent→main_selling_point→emotion_touchpoint→target_model→bgm_direction→idea_seed）+ `app/mcp/tools/experiment.py`。全 `@tool_with_audit(require_approval=False)`、确定性、不返 trace、不走 Gate：

| tool | 要点 |
|---|---|
| `experiment_create(sku_id, intent, portrait_id?, audience_record_id?, north_star_metric?)` | north_star 缺省按 INTENT_NORTH_STAR 自动 + 校验白名单 |
| `experiment_register_round(experiment_id, swept_variable, arms=[{variable_value, script_id}], round_no?)` | **只登记已生成 brief 的 script_id，tool 内零 LLM**；arms≥2、value 去重 |
| `experiment_status(experiment_id, round_no?)` | 查视图，R-14 三段分层（observation/hypothesis 待验证/next_variable 确定性差集）+ can_lock 闸 + metric_scale_warning |
| `experiment_lock_winner(experiment_id, round_no, winning_arm_id, force=False)` | n<5 且 !force → 拦（R-15）；force 留痕；事务改 baseline |
| `experiment_list(sku_id?, status?, limit=30)` / `experiment_get(experiment_id)` | 只读 |

`record_ad_metrics` 加 `experiment_arm_id` 入参（改签名不加 tool）。

**验收**：6 tool 进 doctor wanted；全流程 create→register 2arm→挂 asset 回传→status 排名+preliminary→n<5 lock 被拦→补够 lock 成功→baseline 合并；status 无"主因是X"。

### ④ 沉淀桥 `experiment_distill`（第 7 新 tool，LLM tool 必返 trace）
新建 prompt `experiment_distill.{system,user}.md`；`prompt_rules.create_rule`/`prompt_rule_save`/`prompt_rule_list` 透传 source_experiment_id/round_var。
签名 `experiment_distill(experiment_id, dry_run=True, polish=False)`：
1. 前置校验 status='converged'、baseline 非空、north_star 白名单。
2. 每锁定变量 → 候选 rule（**默认纯模板**`这个 SKU 的{intent}编导 brief，{var}固定用「{value}」`；polish 才 LLM 润色 + 白名单子集校验）。n<3 不出规则；n∈[3,5) 标待验证。
3. observation（指标差距）与 rule_text 物理分离（R-14），差距进 winning_framework_md + 免责句。
4. `dry_run=True` 默认零写库，返候选 + 框架预览（标 already_distilled/value_changed）；`dry_run=False` 逐条 `prompt_rule_save(node='pipeline.director_brief', scope={sku_id,intent}, enabled=False, source_*=)` + 写 framework（不覆盖）。
5. 点亮：老板 `prompt_rule_set_enabled(True)` → 下条该 SKU 该 intent 的 brief 经 render scope `@>` 命中。

**验收**：dry_run 零写库；契约测试 rule.scope key == render 注入 key == experiment 字段三者相等；scope 命中用例（含 intent 不匹配/缺键/NULL 永命中）；polish 注入伪因果被降级回模板；n=2 不出规则。

### ⑤ 前端 A/B 看板（step37）
- `frontend/src/app/sku-pipeline/page.tsx`：加 step37 tab + state + 7 handler。
- 新建 6 route `api/omni/sku-pipeline/experiment-{create,list,status,register-arm,lock-winner,distill}/route.ts`（照 director-brief 范式）。
- `ad-metrics/page.tsx`：加 useSearchParams 预选 asset（"录投后数据"深链）。
- 布局：左 1/3 选/建实验+登记臂；右 2/3 各臂并排卡片（brief摘要+north-star真值+n+待验证徽章）+排名+锁winner+收敛后沉淀按钮。**前端零判定**（winner 取后端）。
- OutputFeedback 挂 experiment_status / experiment_distill 两处。

### ⑥ doctor/registry/tool-meta 收尾
- `doctor.py` wanted +7 → **89→96**；`_check_prompts` 加 experiment_distill；CLAUDE.md 头部 81→96 修对。
- `audit.py` TOOL_REGISTRY：`@tool_with_audit` 自动注册（确认装饰器+import 副作用）。
- omni-desktop `tool-meta.ts`（跨仓 TODO 进 PR 描述）：新域 **🧪实验台账** 7 条中文名。
- **验收**：`docker exec omni-knowledge-engine python -m app.mcp.doctor` 输出 `all 96 ok`。

---

## 3. 复用 vs 新建
**复用零改**：021 多版本/denorm/draft-adopted；assets.ad_metrics JSONB 当北极星真值源（不建指标表）；ad_metrics_validation._WHITELIST；prompt_rule_save/set_enabled/render_rules_suffix；@tool_with_audit；前端 SkuPicker/OutputFeedback/LineageTree/director-brief route；target_model 热加载模式。
**改存量**：record_ad_metrics(+arm)；generate_director_brief/save_creative_pack(+intent)；portrait_brief.py:552 scope(+intent)；create_rule/prompt_rule_*(+source)；director_brief.user.md；ad-metrics page(+searchParams)；doctor.py(89→96)。
**净新建**：migration 052；experiment_lab.py；experiment.py(7 tool)；4 intent profile；experiment_distill 2 prompt；前端 step37+6 route；INTENT_NORTH_STAR；3 表+1 视图。

---

## 4. 风险 / 未决点
| # | 项 | 处置 |
|---|---|---|
| 1 | 比率口径未钉死（0..1 vs 0..100）跨回传混口径 avg 出垃圾 | **待老板拍板**：v1 不强制+warning，还是 052 强制率类钉 0..1 |
| 2 | 小样本无统计显著：n≥5 是工程门槛非统计证明，抖音冷启动波动可能让 winner 是噪声 | 靠逐条点亮+[待验证]+混杂因子免责软兜底，不做 t-test。**老板需知悉 winner=当前领先≠证明更好** |
| 3 | intent 方法论 4 档是 creative_pack 蒸馏摘要 | 实测后改热加载档案，先上轻量 |
| 4 | 平台分发不均是混杂因子（给某臂多灌量它就赢） | 沉淀侧免责句已加；登记臂时无法强制等量投放，靠老板自律单变量纪律 |
| 5 | tool-meta.ts 跨仓 omni-desktop | PR 描述列 TODO |
