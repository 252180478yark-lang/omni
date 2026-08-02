# Omni AI Workbench 并行开发顺序

- 状态：PLAN ONLY（未授权启动产品开发）
- 版本：v1.0
- 日期：2026-08-02
- PRD：`2026-08-02-omni-unified-ai-workbench-prd-v1.3`
- 基线：`origin/main=c8c8eec71d9d970272de84649cf31f87fd148441`
- 当前实施状态：W0 本地候选 `GRAPH_DIFF_READY / ready_for_ci`；W1 未启动、未获产品写权限
- 目标：在不产生 shared writer、共享运行资源和交付真值冲突的前提下，最大化 W1–W7 的并行开发。

## 1. 执行结论

采用“串行 Gate + 并行 Lane + 串行汇合”的开发方式：

1. W0 先清除所有权冲突并冻结不可变基线。
2. 串行冻结跨 Lane 共享合同和集成插槽。
3. W1 Shell/IA 与 W5 Codex Host Core 在各自 Gate 满足时并行。
4. W2 蓝图/建议与 W3 运行中心在 W1 及各自主 PRD Gate 满足后并行。
5. W4 审批执行与 W6 Desktop 收敛在各自上游完成后并行。
6. W7 由一个集成 owner 串行完成全链路 pilot、回归和交付证据。

峰值是 4 条逻辑施工 Lane；每条 Lane 可以由一个 Agent 或一个小组负责。共享 migration、顶层路由注册、Feature Registry 生成物、Shell 集成文件和 Delivery Gate 始终只有一个 writer。

当前仍不能启动任何产品代码 Lane：前序 delivery、指纹和 successor handoff 已在 W0 本地候选中闭环，但 W0 尚未取得默认分支 CI attestation，W1 也尚未建立独立合同或 WorkspaceLease。当前只允许评审/交付 W0 候选和对后续 Lane 做只读发现。

## 2. 依赖 DAG

```text
G0  W0 所有权交接与基线冻结（串行，本地候选已闭环；待正式交付）
 |
G1  共享合同/扩展插槽冻结（串行）
 |
 +------------------------------+
 |                              |
P1-A W1 Shell / 5+5 IA          P1-B W5 Codex Host Core
 |                              |  [需 S10 + migration + Host trust Gate]
 +---------------+--------------+
                 |
G2  集成点 1：Shell 插槽、context/provider/artifact 合同对齐（串行）
                 |
 +---------------+--------------+
 |                              |
P2-C W2 蓝图 / 建议             P2-D W3 运行中心 / operation
[需 S3/S7 Gate]                 [需 S2.5/S8 + migration Gate]
 |                              |
 +---------------+--------------+
                 |
G3  集成点 2：运行事件、蓝图证据、Codex operation 绑定（串行）
                 |
 +---------------+--------------+
 |                              |
P3-E W4 审批与恰好一次执行       P3-F W6 Desktop 收敛
[依赖 W3]                       [依赖 W1 + W5 + S11]
 |                              |
 +---------------+--------------+
                 |
G4  W7 Pilot / 回归 / 遥测 / CI attestation（串行）
```

任何并行 Lane 未满足自己的 Gate 时，只阻塞该 Lane；不得用静态 demo、手写 COMPLETE 或共用 dirty 文件代替。

## 3. 当前可执行状态

| 阶段 | 当前状态 | 现在允许做什么 | 禁止做什么 |
|---|---|---|---|
| G0 / W0 | `GRAPH_DIFF_READY / ready_for_ci` | 评审、精确暂存、不可变提交与获授权后的 Delivery Gate | 产品代码、migration、运行配置、未建合同的 W1 owner lock |
| P1-A / W1 | 未启动 | 只读发现和起草 impact contract | 修改 Shell、sidebar、registry |
| P1-B / W5 | Gate 未满足 | 只读核查 S10、Host trust、migration、runner 契约 | 默认启用本地 Codex、修改 Host/session 产品代码 |
| P2-C / W2 | 等待 W1 + S3/S7 | 只读核查 graph freshness/capability | 用 demo 数据冒充系统事实 |
| P2-D / W3 | 等待 W1 + S2.5/S8 | 只读核查 operation/event 真源 | 新建第二 operation writer、共享 migration |
| P3-E / W4 | 等待 W3 | 审批/CAS 契约核查 | 真实 R3 副作用 |
| P3-F / W6 | 等待 W1 + W5 + S11 | Desktop 只读审计 | 修改 dirty Desktop、物理退役旧 renderer |
| G4 / W7 | 等待 W1–W6 | 验收计划 | 宣称 pilot 或正式交付 |

## 4. Gate 顺序

### G0：W0 所有权交接

必须同时满足：

- `HEAD == origin/main == frozen_base_commit`。
- W1 目标路径指纹与 manifest 完全一致。
- primary dirty `app-sidebar.tsx` 原字节保留，仅继承用户确认的“SKU 圈包链路”语义。
- `2026-07-30-system-convergence-s0-s3-foundation`、`2026-08-01-system-convergence-s4-s6-static`、`2026-08-01-system-convergence-s4-s6-gap-closure` 与 `2026-08-01-system-convergence-s7-s14` 的可信 main CI delivery attestation 已 live 验证。
- 历史 `2026-08-01-system-convergence-s8-s10` 候选仍是 `VERIFIED_NOT_DELIVERED`；它对两个 Feature Registry 文件的路径声明由后续已交付 S7-S14 精确覆盖并在 W0 manifest 中显式 supersede，不改写旧合同或工作树。
- 目标路径只有一个新 v3 owner，无 scope overlap、owner ambiguity 或 active lease conflict。
- W0 合同按 `DISCOVERED → IMPACT_LOCKED → IMPLEMENTING → VERIFYING → GRAPH_DIFF_READY` 前向完成；仓库 YAML 不自写 `COMPLETE`。
- W1 只有在 W0 正式交付、独立 W1 schema-v3 合同到 `IMPACT_LOCKED`、29 个指纹重新匹配且 WorkspaceLease 生效后才获得产品写权限。

### G1：共享合同冻结

由单一 Foundation owner 冻结以下接口，其他 Lane 只能消费：

- `WorkbenchContextSnapshot`：workspace/object/task/surface/revision，不可变绑定。
- `ResolvedAgentProvider`：provider、runner mode、fallback reason、accepted_at。
- `AgentArtifactProjection`：artifact/session/operation/hash/status/safe summary。
- `RunOperation/Event`：operation、attempt、cursor、checkpoint、partial failure、idempotency。
- `WorkbenchIAProjection`：单一 feature_id/owner/renderer、canonical route、aliases、mode/group。
- UI 扩展插槽：assistant、blueprint、run center、approval、artifact drawer，不允许后续 Lane反复修改 `AppShell`。

若需要数据库变化，先清除 `migration_baseline_unknown`，然后由唯一 Migration owner 通过 `scripts/apply_migrations.py` 创建加法 migration，并验证 clean/existing/restarted DB 的 head/checksum 一致。其他 Lane 不得各自新增相邻 migration。

### G2/G3：串行汇合

汇合点只做共享文件接线和跨 Lane 契约测试：

- 不吸收 Lane 内部功能实现。
- 每个接线 diff 必须进入独立 integration contract。
- 先刷新主线 commit，再让下游 Lane 从新的不可变基线继续。
- 发现共享类型或接口变化时，先更新合同和 consumer matrix，不直接在多个 Lane 热修。

## 5. Lane 定义

### Lane A：W1 Shell 与 5+5 IA

- 建议 change_id：`2026-08-02-omni-unified-ai-workbench-w1-shell-ia`
- 可开始条件：G0、G1 通过。
- 唯一 writer：
  - `frontend/src/components/app-shell.tsx`
  - `frontend/src/components/app-sidebar.tsx`
  - `frontend/src/app/layout.tsx`
  - `frontend/src/app/globals.css`
  - `frontend/src/app/page.tsx`
  - `frontend/src/components/beginner-guide.tsx`
  - `frontend/src/lib/feature-registry.ts`
  - `frontend/src/generated/feature-registry.v1.json`
  - `services/knowledge-engine/config/features/**`
- 交付：新 Shell、工作/开发模式、5+5 IA、19 项能力覆盖、Prompt/Eval 入口、旧 URL alias、回滚 flag。
- 禁止：修改 `agent-chat/**`、Host Bridge、runtime service、approval worker、Desktop。
- Done：W1 AC 全过、coverage=100%、无 orphan/重复 owner/alias 环，候选到 `GRAPH_DIFF_READY`；正式完成仍需 CI attestation。

### Lane B：W5 Codex Host Core

- 建议 change_id：`2026-08-02-omni-unified-ai-workbench-w5-codex-host`
- 可开始条件：G0、G1、主 PRD S10 delivery/capability、migration 与 Host trust Gate 通过。
- 唯一 writer：
  - `frontend/src/lib/agent-chat/**`
  - `frontend/src/hooks/useAgentChat.ts`
  - `frontend/src/components/agent-chat/**`
  - `frontend/src/app/api/omni/host-bridge/**`
  - `services/host-bridge/**`
  - Agent session/context/artifact service 与测试的明确合同路径
- 交付：immutable context revision、provider 披露、Host/local 单一 runner owner、artifact normalize、opaque project identity、恢复测试。
- 禁止：修改 Shell/sidebar/Feature Registry、共享 migration、Desktop dirty 文件、加入 bypass approvals/sandbox 参数。
- Done：上下文错绑、静默 provider 切换、raw project path 暴露均为 0；真实 Host restart/recovery e2e 通过并到 `GRAPH_DIFF_READY`。

### Lane C：W2 蓝图与只读建议

- 建议 change_id：`2026-08-02-omni-unified-ai-workbench-w2-blueprint`
- 可开始条件：W1 CI-attested 可消费基线 + 主 PRD S3/S7 delivery/capability Gate。
- 唯一 writer：
  - 新建 `frontend/src/components/workbench-blueprint/**`
  - 新建 blueprint/assistant 页面、BFF 与目标测试路径
  - graph query/read projection 的明确合同路径
- 只读复用：`frontend/src/components/system-command-center/**` 与现有 System Graph 真源；默认不直接修改。
- 交付：观察/推断/动作分层、provenance、freshness、渐进展开、unavailable/stale 状态。
- 禁止：生成静态假节点、写 operation、修改 runtime/approval writer。
- Done：AC-FR003/004、四态和 visual/e2e 通过；collector 失败保持 unknown/unavailable。

### Lane D：W3 运行中心与 operation

- 建议 change_id：`2026-08-02-omni-unified-ai-workbench-w3-run-center`
- 可开始条件：W1 CI-attested 可消费基线 + 主 PRD S2.5/S8 delivery/capability + migration Gate。
- 唯一 writer：
  - `services/knowledge-engine/app/services/runtime_*.py`
  - runtime router/schema 的明确路径
  - `frontend/src/app/api/omni/runtime-*/**`
  - 新建 `frontend/src/components/workbench-runtime/**`
  - 新建 run-center 页面和测试
- 交付：operation/event/cursor/checkpoint 投影、断线恢复、重试、取消、部分失败、人话摘要。
- 禁止：第二 operation writer、审批 worker、Shell/sidebar、直接修改蓝图组件。
- Done：AC-FR005/006-01、断线/重复/partial failure fault injection 通过，无第二 writer。

### Lane E：W4 审批与恰好一次执行

- 建议 change_id：`2026-08-02-omni-unified-ai-workbench-w4-approval`
- 可开始条件：W3 CI-attested 可消费基线 + approval operation/CAS worker capability Gate。
- 唯一 writer：
  - `services/knowledge-engine/app/routers/approval_operations.py`
  - `services/knowledge-engine/app/services/approval_operations.py`
  - `services/knowledge-engine/app/workers/approval_operations.py`
  - approval UI/BFF/security test 的明确路径
- 交付：frozen payload、TTL、revoke、CAS claim、receipt、重复消费防护。
- 禁止：真实外部动作；先使用 inert mock/沙箱副作用验证。
- Done：AC-FR006-02、重复副作用=0、过期/撤销/重放测试通过。

### Lane F：W6 Desktop 收敛

- 建议 change_id：`2026-08-02-omni-unified-ai-workbench-w6-desktop`
- 可开始条件：W1 + W5 CI-attested 可消费基线、主 PRD S11、Desktop 独立 clean worktree/contract/fingerprint。
- 唯一 writer：隔离后的 `E:/agent/omni-desktop` 目标合同路径。
- 交付：Web renderer 复用、capability manifest、BrowserView/IPC/恢复/托盘/快捷键保留、旧 renderer flag 回退。
- 禁止：直接写当前 dirty Desktop、物理删除旧 renderer、复制 bypass 参数。
- Done：浏览器/Desktop cross-surface e2e 通过，旧 renderer 可恢复。

### Integration Lane：共享接线唯一 owner

只在 G2/G3/G4 串行运行，负责：

- `frontend/src/components/OutputFeedback.tsx`
- 顶层 Shell 插槽最终接线
- Feature Registry 的跨 Lane 聚合与生成
- `services/knowledge-engine/app/main.py`
- MCP `server.py` / `doctor.py` 注册
- 公共 schema/types 与唯一 migration
- 跨 Lane e2e、OpenAPI/doctor、graph diff 和 CI candidate validation

业务 Lane 如果发现必须修改这些文件，立即停止并向 Integration Lane 提交 contract delta；不得自行写入。

## 6. 并行波次与合并顺序

| 顺序 | 波次 | 可并行内容 | 合并/继续条件 |
|---|---|---|---|
| 0 | G0 | 不并行 | W0 唯一 owner、指纹与 handoff 全绿 |
| 1 | G1 | 各 Lane 可并行做只读发现，但共享合同由一个 owner 串行写 | shared contract revision 冻结并产生 immutable foundation commit |
| 2 | P1 | Lane A（W1）与满足 Gate 的 Lane B（W5 Core） | 各自独立 `GRAPH_DIFF_READY` + CI attestation；B 被阻塞时不阻塞 A |
| 3 | G2 | 不并行 | Shell/context/provider/artifact 接口 e2e 通过，生成新的消费基线 |
| 4 | P2 | Lane C（W2）与 Lane D（W3） | 各自 Gate、合同、测试和 CI attestation 通过 |
| 5 | G3 | 不并行 | blueprint、runtime、Codex operation 绑定与跨 Lane e2e 通过 |
| 6 | P3 | Lane E（W4）与 Lane F（W6） | 审批安全测试、Desktop cross-surface 测试分别通过 |
| 7 | G4/W7 | 不并行 | P0 AC、回归、遥测、graph diff、commit-mode CI attestation 全部成立 |

推荐 merge train：`G0 → G1 → (A || B) → G2 → (C || D) → G3 → (E || F) → G4/W7`。

每次 merge 后，下游 Lane 必须重新 fetch、记录新的 full commit SHA、刷新 merge-base/fingerprint/ownership，再继续；不得把旧分支测试结果投影到新主线。

## 7. 资源隔离合同

每条可写 Lane 必须拥有：

- 独立 `change_id` 和 worktree。
- 唯一的 protected path owner。
- 有效 `WorkspaceLease`，路径 glob 只覆盖本 Lane。
- 独立 `RuntimeAllocation`：ports、database/schema、volumes、Redis namespace、scheduler/worker identity、compose project、build/source identity。
- 独立测试数据和 artifact 目录。

禁止并行共享：

- writable database/schema；
- migration runner；
- Docker volume；
- Redis namespace；
- scheduler/worker；
- 固定 Host 端口；
- Feature Registry 生成文件；
- Shell/Sidebar/OutputFeedback；
- MCP/REST 顶层注册文件；
- CI delivery attestation 输出路径。

只读复用必须在合同中标 `reuse`，并证明不存在隐式写入。

## 8. 分支与交付规则

每条 Lane：

1. 从最近一次已通过 Gate 的 immutable commit 建分支和 worktree。
2. 初始化 schema v3 impact/completion contract。
3. 填满 feature_ref、before_snapshot、base_commit、risk、paths、edges、tests、rollback。
4. 获取 WorkspaceLease/RuntimeAllocation。
5. 只在 `IMPACT_LOCKED` 后修改产品代码。
6. `IMPLEMENTING → VERIFYING → GRAPH_DIFF_READY` 逐级推进，不跳级。
7. 本地只到 `GRAPH_DIFF_READY`；只有 commit-mode CI 的外部 attestation 才是 COMPLETE。
8. 下游只消费已通过约定 Gate 的不可变提交，不消费别人的 dirty worktree。

## 9. 必须立即停止的情况

- 目标路径出现新 dirty writer、多个 v3 owner 或 scope overlap。
- HEAD、origin/main、merge-base、blob/SHA-256 与冻结值不一致。
- 需要修改本 Lane 未声明的共享文件。
- RuntimeAllocation 指向共享 DB、volume、Redis、scheduler 或未知端口 owner。
- migration baseline、Host trust 或主 PRD delivery Gate 仍 unknown/blocked。
- collector 失败却被写成 missing，或 demo 数据被展示成 fact。
- 测试、doctor、OpenAPI、migration、graph diff 或 commit-mode validation 失败。
- R3 动作没有真实 Human Gate、幂等键、冻结 payload 与服务端复核。

停止时保留现场，不执行 `reset`、`clean`、`force`、stash drop、批量移动或覆盖 primary/其他 worktree 文件。

## 10. Agent 任务卡最小格式

每个开发 Agent 启动前必须拿到：

```yaml
lane: A-F-or-integration
change_id: exact-change-id
base_commit: full-40-char-sha
depends_on: [immutable-attested-commits]
allowed_paths: [exact-paths-or-safe-globs]
forbidden_shared_paths: [paths-owned-by-other-lanes]
feature_refs: [stable-feature-ref]
workspace_lease: required
runtime_allocation: required-or-not-applicable-with-reason
verification: [exact-commands]
stop_conditions: [writer-drift, fingerprint-drift, gate-failure]
handoff: GRAPH_DIFF_READY-plus-CI-attestation
```

缺少任一项时，该 Agent 只能做只读发现，不能修改产品代码。
