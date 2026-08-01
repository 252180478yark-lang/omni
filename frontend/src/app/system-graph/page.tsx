'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Archive, CheckCircle2, GitBranch, Loader2, RefreshCw, Save, Sparkles } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

type PlanState = 'draft' | 'reviewing' | 'frozen' | 'stale' | 'archived'
type Decision = 'reuse' | 'modify' | 'add' | 'not_do' | 'unknown'
type EvidenceClass = 'observed_fact' | 'recommendation' | 'hypothesis'
type ReviewStatus = 'pending' | 'accepted' | 'rejected' | 'rewritten'

interface PlanItem {
  item_id: string
  layer: string
  target_ref: string
  decision: Decision
  evidence_class: EvidenceClass
  evidence_refs: string[]
  recommendation: string
  rationale: string
  missing_evidence: string
  verification: string
  risk: string
  critical: boolean
  review_status: ReviewStatus
  review_note: string
}

interface Plan {
  plan_id: string
  feature_id: string
  base_snapshot_id: string
  revision: number
  state: PlanState
  items: PlanItem[]
  snapshot_status: 'complete' | 'partial'
  missing_sources: string[]
  updated_at_utc: string
  archived_reason: string
}

interface PlanSummary {
  facts: number
  recommendations: number
  hypotheses: number
  pending_reviews: number
  critical_unknowns: number
  snapshot_status: string
  missing_sources: string[]
}

interface ListResponse {
  plans: Plan[]
  summaries: Record<string, PlanSummary>
}

const DECISIONS: Decision[] = ['reuse', 'modify', 'add', 'not_do', 'unknown']
const REVIEWS: ReviewStatus[] = ['pending', 'accepted', 'rejected', 'rewritten']

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/omni/system-graph${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    cache: 'no-store',
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.message || body.error || `请求失败（${response.status}）`)
  return body as T
}

function stateLabel(state: PlanState) {
  return ({ draft: '草稿', reviewing: '共创确认中', frozen: '已冻结', stale: '事实已变化', archived: '已归档' } as const)[state]
}

function evidenceLabel(value: EvidenceClass) {
  return ({ observed_fact: '已观察事实', recommendation: '建议', hypothesis: '假设' } as const)[value]
}

export default function SystemGraphPlanPage() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [summaries, setSummaries] = useState<Record<string, PlanSummary>>({})
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [featureId, setFeatureId] = useState('')
  const [snapshotId, setSnapshotId] = useState('')
  const [rebaseSnapshotId, setRebaseSnapshotId] = useState('')
  const [intent, setIntent] = useState('')

  const selected = plans.find((plan) => plan.plan_id === selectedId) || null
  const summary = selected ? summaries[selected.plan_id] : null

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      // Keep the primary read boundary literal so the deterministic graph
      // collector can prove page -> catch-all BFF -> REST without guessing.
      const response = await fetch('/api/omni/system-graph/integration-plans', {
        credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json' },
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(body.message || body.error || `请求失败（${response.status}）`)
      const result = body as ListResponse
      setPlans(result.plans)
      setSummaries(result.summaries)
      setSelectedId((current) => current || result.plans[0]?.plan_id || '')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法读取候选计划')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const replacePlan = (plan: Plan, nextSummary?: PlanSummary) => {
    setPlans((current) => [plan, ...current.filter((item) => item.plan_id !== plan.plan_id)])
    if (nextSummary) setSummaries((current) => ({ ...current, [plan.plan_id]: nextSummary }))
    setSelectedId(plan.plan_id)
  }

  const create = async () => {
    if (!featureId.trim() || !snapshotId.trim() || !intent.trim()) {
      setError('请填写功能 ID、事实快照 ID 和需求意图。')
      return
    }
    setSaving(true)
    setError('')
    try {
      const result = await api<{ plan: Plan; summary: PlanSummary }>('/integration-plans', {
        method: 'POST',
        body: JSON.stringify({ feature_id: featureId.trim(), base_snapshot_id: snapshotId.trim(), intent: intent.trim(), items: [] }),
      })
      replacePlan(result.plan, result.summary)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '创建失败')
    } finally {
      setSaving(false)
    }
  }

  const updateItem = (itemId: string, patch: Partial<PlanItem>) => {
    if (!selected) return
    const plan = { ...selected, items: selected.items.map((item) => item.item_id === itemId ? { ...item, ...patch } : item) }
    replacePlan(plan)
  }

  const saveReview = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      const result = await api<{ plan: Plan; summary: PlanSummary }>(`/integration-plans/${selected.plan_id}`, {
        method: 'PATCH',
        body: JSON.stringify({ expected_revision: selected.revision, current_snapshot_id: selected.base_snapshot_id, items: selected.items }),
      })
      replacePlan(result.plan, result.summary)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败')
      await load()
    } finally {
      setSaving(false)
    }
  }

  const rebase = async () => {
    if (!selected || !rebaseSnapshotId.trim()) {
      setError('请填写新的不可变事实快照 ID。')
      return
    }
    setSaving(true)
    setError('')
    try {
      const result = await api<{ plan: Plan; summary: PlanSummary }>(`/integration-plans/${selected.plan_id}/rebase`, {
        method: 'POST',
        body: JSON.stringify({
          expected_revision: selected.revision,
          base_snapshot_id: rebaseSnapshotId.trim(),
          items: selected.items,
        }),
      })
      replacePlan(result.plan, result.summary)
      setRebaseSnapshotId('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '重基线失败')
      await load()
    } finally {
      setSaving(false)
    }
  }

  const confirm = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      const result = await api<{ plan: Plan; summary: PlanSummary }>(`/integration-plans/${selected.plan_id}/confirm`, {
        method: 'POST',
        body: JSON.stringify({
          expected_revision: selected.revision,
          current_snapshot_id: selected.base_snapshot_id,
          request_id: crypto.randomUUID(),
          confirmed: true,
        }),
      })
      replacePlan(result.plan, result.summary)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '确认失败')
      await load()
    } finally {
      setSaving(false)
    }
  }

  const archive = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      const result = await api<{ plan: Plan; summary: PlanSummary }>(`/integration-plans/${selected.plan_id}/archive`, {
        method: 'POST',
        body: JSON.stringify({ expected_revision: selected.revision, reason: 'owner_archived' }),
      })
      replacePlan(result.plan, result.summary)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '归档失败')
    } finally {
      setSaving(false)
    }
  }

  const canConfirm = useMemo(() => {
    if (!selected || selected.state !== 'reviewing') return false
    return selected.items.every((item) => {
      if (item.critical && item.decision === 'unknown') return false
      if (['add', 'modify'].includes(item.decision)) return ['accepted', 'rewritten'].includes(item.review_status)
      return true
    })
  }, [selected])

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-6 py-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-gray-900">
            <GitBranch className="h-7 w-7 text-violet-600" /> 系统图谱 · 功能接入共创
          </h1>
          <p className="mt-1 text-sm text-gray-500">先基于不可变事实快照决定复用、修改或新增；确认前不会修改产品代码或业务数据。</p>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={loading} aria-label="刷新候选计划">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新
        </Button>
      </div>

      {error && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{error}
        </div>
      )}

      <Card>
        <CardContent className="grid gap-3 p-5 md:grid-cols-4">
          <label className="text-sm">功能 ID<input aria-label="功能 ID" value={featureId} onChange={(event) => setFeatureId(event.target.value)} className="mt-1 w-full rounded-lg border px-3 py-2" placeholder="feature-id" /></label>
          <label className="text-sm">事实快照 ID<input aria-label="事实快照 ID" value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)} className="mt-1 w-full rounded-lg border px-3 py-2 font-mono text-xs" placeholder="sha256:..." /></label>
          <label className="text-sm">需求意图<input aria-label="需求意图" value={intent} onChange={(event) => setIntent(event.target.value)} className="mt-1 w-full rounded-lg border px-3 py-2" placeholder="要解决什么问题" /></label>
          <Button onClick={() => void create()} disabled={saving} className="self-end"><Sparkles className="mr-2 h-4 w-4" />创建候选节点</Button>
        </CardContent>
      </Card>

      {loading ? (
        <div aria-label="正在加载候选计划" className="flex min-h-48 items-center justify-center text-gray-500"><Loader2 className="mr-2 h-5 w-5 animate-spin" />正在读取事实与计划…</div>
      ) : error && plans.length === 0 ? (
        <div className="rounded-xl border border-rose-100 bg-white p-8 text-center text-sm text-gray-500">候选计划未加载。请修复上方错误后重试。</div>
      ) : plans.length === 0 ? (
        <div className="rounded-xl border border-dashed bg-white p-10 text-center text-sm text-gray-500">暂无候选计划。填写上方三项后，系统会生成覆盖页面、Skill、模型、API、服务、数据和权限的影响判断表。</div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
          <aside className="space-y-2" aria-label="候选计划列表">
            {plans.map((plan) => (
              <button key={plan.plan_id} onClick={() => setSelectedId(plan.plan_id)} className={`w-full rounded-xl border p-3 text-left ${selectedId === plan.plan_id ? 'border-violet-400 bg-violet-50' : 'bg-white hover:border-gray-300'}`}>
                <div className="flex items-center justify-between gap-2"><span className="truncate text-sm font-medium">{plan.feature_id}</span><Badge variant="secondary">{stateLabel(plan.state)}</Badge></div>
                <div className="mt-2 font-mono text-[11px] text-gray-400">r{plan.revision} · {plan.plan_id}</div>
              </button>
            ))}
          </aside>

          {selected && (
            <section className="space-y-4">
              <Card><CardContent className="p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div><h2 className="font-semibold">{selected.feature_id}</h2><p className="mt-1 break-all font-mono text-xs text-gray-400">{selected.base_snapshot_id}</p></div>
                  <div className="flex gap-2"><Badge>{stateLabel(selected.state)}</Badge><Badge variant={selected.snapshot_status === 'complete' ? 'secondary' : 'destructive'}>{selected.snapshot_status === 'complete' ? '快照完整' : '快照部分可用'}</Badge></div>
                </div>
                {selected.missing_sources.length > 0 && <p className="mt-3 text-xs text-amber-700">缺失来源：{selected.missing_sources.join('、')}</p>}
                {summary && <div className="mt-4 grid grid-cols-2 gap-2 text-xs md:grid-cols-5"><span>事实 {summary.facts}</span><span>建议 {summary.recommendations}</span><span>假设 {summary.hypotheses}</span><span>待确认 {summary.pending_reviews}</span><span>关键未知 {summary.critical_unknowns}</span></div>}
              </CardContent></Card>

              <div className="space-y-3">
                {selected.items.map((item) => (
                  <Card key={item.item_id}><CardContent className="grid gap-3 p-4 md:grid-cols-[110px_1fr_150px_150px]">
                    <div><div className="text-sm font-semibold">{item.layer}</div><Badge variant="outline" className="mt-2">{evidenceLabel(item.evidence_class)}</Badge>{item.critical && <div className="mt-2 text-xs text-rose-600">关键项</div>}</div>
                    <div className="space-y-2"><input aria-label={`${item.layer} 目标`} className="w-full rounded border px-2 py-1.5 font-mono text-xs" value={item.target_ref} onChange={(event) => updateItem(item.item_id, { target_ref: event.target.value })} /><textarea aria-label={`${item.layer} 说明`} className="w-full rounded border px-2 py-1.5 text-xs" value={item.rationale || item.recommendation || item.missing_evidence} onChange={(event) => item.evidence_class === 'hypothesis' ? updateItem(item.item_id, { missing_evidence: event.target.value }) : updateItem(item.item_id, { rationale: event.target.value })} /><div className="text-[11px] text-gray-400">证据 {item.evidence_refs.length} 条 · {item.verification}</div></div>
                    <label className="text-xs">接法<select aria-label={`${item.layer} 接法`} className="mt-1 w-full rounded border px-2 py-2" value={item.decision} onChange={(event) => updateItem(item.item_id, { decision: event.target.value as Decision })}>{DECISIONS.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
                    <label className="text-xs">老板确认<select aria-label={`${item.layer} 确认`} className="mt-1 w-full rounded border px-2 py-2" value={item.review_status} onChange={(event) => { const review_status = event.target.value as ReviewStatus; updateItem(item.item_id, { review_status, ...(review_status === 'rejected' ? { decision: 'not_do' as Decision } : {}) }) }}>{REVIEWS.map((value) => <option key={value} value={value}>{value}</option>)}</select><input aria-label={`${item.layer} 确认说明`} className="mt-2 w-full rounded border px-2 py-1.5" value={item.review_note} onChange={(event) => updateItem(item.item_id, { review_note: event.target.value })} placeholder="改写时必填" /></label>
                  </CardContent></Card>
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void saveReview()} disabled={saving || !['draft', 'reviewing'].includes(selected.state)}><Save className="mr-2 h-4 w-4" />保存本轮判断</Button>
                <Button onClick={() => void confirm()} disabled={saving || !canConfirm} variant="default"><CheckCircle2 className="mr-2 h-4 w-4" />确认并冻结接入合同</Button>
                <Button onClick={() => void archive()} disabled={saving || selected.state === 'archived'} variant="outline"><Archive className="mr-2 h-4 w-4" />归档</Button>
              </div>
              {selected.state === 'stale' && (
                <Card>
                  <CardContent className="flex flex-wrap items-end gap-3 p-4">
                    <label className="min-w-72 flex-1 text-xs">新快照 ID<input aria-label="新快照 ID" className="mt-1 w-full rounded border px-2 py-2 font-mono" value={rebaseSnapshotId} onChange={(event) => setRebaseSnapshotId(event.target.value)} placeholder="sha256:..." /></label>
                    <Button onClick={() => void rebase()} disabled={saving || !rebaseSnapshotId.trim()} variant="outline"><RefreshCw className="mr-2 h-4 w-4" />重基线并重新确认</Button>
                  </CardContent>
                </Card>
              )}
              {!canConfirm && selected.state === 'reviewing' && <p className="text-xs text-amber-700">仍有关键 unknown，或 add/modify 项尚未接受；当前不能冻结。</p>}
            </section>
          )}
        </div>
      )}
    </div>
  )
}
