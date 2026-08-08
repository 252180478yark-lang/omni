import type { SystemGraphNode, SystemGraphSnapshot } from '@/lib/system-command-center/runtime-model'

export type WorkbenchRiskLevel = 'R0' | 'R1' | 'R2' | 'R3'

export interface WorkbenchEvidenceRef {
  id: string
  label: string
  source: string
  observedAt: string | null
}

export interface WorkbenchActionCard {
  observations: string[]
  inference: string
  action: string
  evidenceRefs: WorkbenchEvidenceRef[]
  toolPlan: string[]
  riskLevel: WorkbenchRiskLevel
  expectedImpact: string
  approvalRequired: boolean
  evidenceState: 'sufficient' | 'insufficient' | 'unavailable'
  nextEvidenceStep?: string
}

function observedEvidence(node: SystemGraphNode): boolean {
  return node.state.existence === 'observed' && Boolean(node.evidence?.length || node.sources?.length)
}

export function buildWorkbenchActionCard(
  snapshot: SystemGraphSnapshot | null,
  question: string,
): WorkbenchActionCard {
  const normalizedQuestion = question.trim()
  if (!snapshot) {
    return {
      observations: [],
      inference: '系统图依赖当前不可用，不能形成事实性结论。',
      action: '恢复事实快照后再生成建议。',
      evidenceRefs: [],
      toolPlan: ['system-graph.snapshot'],
      riskLevel: 'R0',
      expectedImpact: '只读补证，不创建 operation。',
      approvalRequired: false,
      evidenceState: 'unavailable',
      nextEvidenceStep: '检查 Knowledge Engine 与系统图 collector 的最近成功时间。',
    }
  }

  const evidenceNodes = snapshot.content.nodes.filter(observedEvidence).slice(0, 2)
  if (!evidenceNodes.length) {
    return {
      observations: [],
      inference: '当前对象没有可用且带来源的事实证据，依据不足。',
      action: '先刷新系统图或选择带证据的经营对象。',
      evidenceRefs: [],
      toolPlan: ['system-graph.refresh', 'system-graph.snapshot'],
      riskLevel: 'R0',
      expectedImpact: '只补充证据，不新增事实、不创建写 operation。',
      approvalRequired: false,
      evidenceState: 'insufficient',
      nextEvidenceStep: '刷新 collector，并确认节点 provenance 与 freshness 后重试。',
    }
  }

  const evidenceRefs = evidenceNodes.map((node) => ({
    id: node.id,
    label: node.label,
    source: node.sources?.[0] || node.evidence?.[0]?.path || 'system-graph',
    observedAt: snapshot.generated_at_utc || null,
  }))
  return {
    observations: evidenceNodes.map((node) => `${node.label}：${node.state.health} / ${node.state.lifecycle}`),
    inference: normalizedQuestion
      ? `围绕“${normalizedQuestion.slice(0, 80)}”，目前只能确认上述证据覆盖的系统事实；业务因果仍需真实经营数据验证。`
      : '目前只能确认上述证据覆盖的系统事实；业务因果仍需真实经营数据验证。',
    action: '打开蓝图核对来源，再决定是否创建具体经营动作。',
    evidenceRefs,
    toolPlan: ['system-graph.snapshot', 'runtime-traces.active'],
    riskLevel: 'R0',
    expectedImpact: '只读核验当前证据与运行状态，不触发外部写入。',
    approvalRequired: false,
    evidenceState: 'sufficient',
  }
}

