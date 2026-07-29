'use client'

import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Film, Loader2, RefreshCw } from 'lucide-react'
import OutputFeedback from '@/components/OutputFeedback'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

type UnknownRecord = Record<string, unknown>

interface P0VideoProductionPanelProps {
  skuId: string
}

const TOOL_BY_OPERATION: Record<string, string> = {
  preflight: 'p0_preflight_video_production',
  inputs: 'p0_list_video_production_inputs',
  orders: 'p0_list_video_production_orders',
  order: 'p0_get_video_production_order',
  create: 'p0_create_video_production_order',
  generateBridge: 'p0_generate_planting_bridge_candidates',
  bridgeReview: 'p0_generate_planting_bridge_candidates',
  buildSpec: 'p0_build_video_content_spec',
  generateScripts: 'p0_generate_video_script_candidates',
  reviewScripts: 'p0_review_video_script_candidates',
  selectScript: 'p0_select_video_script',
  preparePrompt: 'p0_prepare_video_prompt',
  assessCandidateVector: 'p0_assess_video_candidate_vector_match',
  assessExecutionVector: 'p0_assess_video_execution_vector_match',
  assessMatch: 'p0_assess_video_content_match',
  requestApproval: 'p0_request_video_generation_approval',
  startGeneration: 'p0_start_video_generation',
  recoverGeneration: 'p0_recover_video_generation',
  rawQa: 'p0_run_raw_video_qa',
  compose: 'p0_compose_video_final',
  finalQa: 'p0_run_final_video_qa',
  release: 'p0_release_video_package',
  cancel: 'p0_cancel_video_production',
}

const P0_BEAT_CONTRACT_VERSION = '2026-07-29.p0.v4'

const STATUS_LABEL: Record<string, string> = {
  truth_ready: '事实已冻结',
  spec_ready: 'ContentSpec 已就绪',
  awaiting_script_selection: '等待脚本选择',
  prompt_ready: 'Prompt 已冻结',
  awaiting_generation_approval: '等待付费生成审批',
  generating: '生成中/可恢复',
  raw_qa: 'Raw QA',
  raw_passed: 'Raw 通过',
  raw_rejected: 'Raw 驳回',
  final_qa: '终片 QA',
  ready_to_release: '等待发布确认',
  final_rejected: '终片驳回',
  released: '已发布包',
  cancelled: '已取消',
}

function asRecord(value: unknown): UnknownRecord {
  if (typeof value === 'string') {
    try {
      return asRecord(JSON.parse(value))
    } catch {
      return {}
    }
  }
  return value && typeof value === 'object' && !Array.isArray(value) ? value as UnknownRecord : {}
}

function asArray(value: unknown): UnknownRecord[] {
  if (typeof value === 'string') {
    try {
      return asArray(JSON.parse(value))
    } catch {
      return []
    }
  }
  return Array.isArray(value) ? value.map(asRecord) : []
}

function textArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(item => typeof item === 'string' ? item.trim() : '').filter(Boolean)
    : []
}

function bridgeCandidatesOf(value: UnknownRecord): UnknownRecord[] {
  const result = asRecord(value.result)
  const bridgeReview = asRecord(value.bridge_review)
  const candidates = [
    asArray(result.bridges),
    asArray(value.bridges),
    asArray(bridgeReview.bridges),
  ]
  return candidates.find(items => items.length > 0) || []
}

function upstreamFactHashOf(value: UnknownRecord): string {
  const result = asRecord(value.result)
  const bridgeReview = asRecord(value.bridge_review)
  const candidates = [value.upstream_fact_hash, result.upstream_fact_hash, bridgeReview.upstream_fact_hash]
  return candidates.find(item => typeof item === 'string' && item.trim()) as string || ''
}

function bridgeKey(bridge: UnknownRecord, index: number): string {
  return String(bridge.id || bridge.bridge_id || bridge.candidate_id || index)
}

function evidenceText(value: unknown): string {
  const entries = asArray(value)
  if (!entries.length) return '未提供证据'
  return entries.map(entry => [entry.source, entry.field, entry.value].filter(Boolean).map(String).join(' · ')).join('\n')
}

function candidateOf(review: UnknownRecord): UnknownRecord {
  return asRecord(asRecord(review.content_contract).p0_candidate)
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

function messageOf(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function firstBlockerOf(value: UnknownRecord, fallback: string): string {
  const blocker = value.first_blocker
  if (typeof blocker === 'string' && blocker.trim()) return blocker
  const blockerRecord = asRecord(blocker)
  return messageOf(blockerRecord.message || blockerRecord.reason || blockerRecord.code, fallback)
}

export default function P0VideoProductionPanel({ skuId }: P0VideoProductionPanelProps) {
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [preflight, setPreflight] = useState<UnknownRecord | null>(null)
  const [inputs, setInputs] = useState<UnknownRecord | null>(null)
  const [orders, setOrders] = useState<UnknownRecord[]>([])
  const [order, setOrder] = useState<UnknownRecord | null>(null)
  const [selectedAudienceId, setSelectedAudienceId] = useState('')
  const [selectedReferenceId, setSelectedReferenceId] = useState('')
  const [selectedPortraitId, setSelectedPortraitId] = useState('')
  const [selectedPackId, setSelectedPackId] = useState('')
  const [bridgeCandidates, setBridgeCandidates] = useState<UnknownRecord[]>([])
  const [selectedBridgeKey, setSelectedBridgeKey] = useState('')
  const [bridgeFactHash, setBridgeFactHash] = useState('')
  const [spokenCopyGoal, setSpokenCopyGoal] = useState('一句自然、完整且可与画面同步的口播。')
  const [approvalHash, setApprovalHash] = useState('')
  const [voiceoverAudioRef, setVoiceoverAudioRef] = useState('')
  const [bgmAudioRef, setBgmAudioRef] = useState('')
  const [bgmAuthorizationNote, setBgmAuthorizationNote] = useState('')
  const [allowNoBgm, setAllowNoBgm] = useState(false)
  const [noBgmScopeNote, setNoBgmScopeNote] = useState('')
  const [lastTool, setLastTool] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<UnknownRecord | null>(null)

  const resetBridgeReview = () => {
    setBridgeCandidates([])
    setSelectedBridgeKey('')
    setBridgeFactHash('')
  }

  const request = async (operation: string, payload: UnknownRecord = {}): Promise<UnknownRecord> => {
    const response = await fetch(`/api/omni/sku-pipeline/p0-video/${operation}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const json = asRecord(await response.json().catch(() => ({})))
    if (!response.ok || !json.success) {
      throw new Error(messageOf(json.error, `请求失败 (${response.status})`))
    }
    return asRecord(json.data)
  }

  const refreshOrder = async (productionOrderId: string) => {
    const data = await request('order', { production_order_id: productionOrderId })
    if (!data.ok) throw new Error(messageOf(data.error, '订单读取失败'))
    setOrder(data)
    return data
  }

  const load = async () => {
    if (!skuId) return
    setLoading(true)
    setError(null)
    try {
      const [nextPreflight, nextInputs, nextOrders] = await Promise.all([
        request('preflight'),
        request('inputs', { sku_id: skuId }),
        request('orders', { sku_id: skuId }),
      ])
      setPreflight(nextPreflight)
      setInputs(nextInputs)
      const listed = asArray(nextOrders.orders)
      setOrders(listed)
      const audience = asArray(nextInputs.audience_records)[0]
      const reference = asArray(nextInputs.product_references)[0]
      if (audience) setSelectedAudienceId(String(audience.id || ''))
      if (reference) setSelectedReferenceId(String(reference.id || ''))
      if (listed[0]?.id) await refreshOrder(String(listed[0].id))
      else setOrder(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setOrder(null)
    setOrders([])
    setPreflight(null)
    setInputs(null)
    setSelectedAudienceId('')
    setSelectedReferenceId('')
    setSelectedPortraitId('')
    setSelectedPackId('')
    setApprovalHash('')
    setLastResult(null)
    resetBridgeReview()
    if (!skuId) return
    void load()
    // skuId is the deliberate refresh boundary for this embedded workbench.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skuId])

  const execute = async (operation: string, payload: UnknownRecord, refresh = true) => {
    setBusy(operation)
    setError(null)
    try {
      const data = await request(operation, payload)
      setLastTool(TOOL_BY_OPERATION[operation] || null)
      setLastResult(data)
      if (!data.ok) {
        setError(firstBlockerOf(data, messageOf(data.error, '操作未通过')))
        return data
      }
      if (operation === 'generateBridge' || operation === 'bridgeReview') {
        const generatedCandidates = bridgeCandidatesOf(data)
        const upstreamFactHash = upstreamFactHashOf(data)
        if (!generatedCandidates.length || !upstreamFactHash) {
          setError('桥接候选返回不完整：缺少结构化候选或上游事实哈希，不能构建 ContentSpec。')
          return data
        }
        setBridgeCandidates(generatedCandidates)
        setSelectedBridgeKey('')
        setBridgeFactHash(upstreamFactHash)
      }
      const currentOrderId = String(asRecord(order?.order).id || '')
      const returnedOrderId = String(asRecord(data.order).id || payload.production_order_id || '')
      if (operation === 'create' && returnedOrderId) {
        resetBridgeReview()
        await refreshOrder(returnedOrderId)
        const latestOrders = await request('orders', { sku_id: skuId })
        setOrders(asArray(latestOrders.orders))
      } else if (refresh && (payload.production_order_id || currentOrderId)) {
        await refreshOrder(String(payload.production_order_id || currentOrderId))
      }
      if (operation === 'requestApproval') setApprovalHash(String(data.approval_hash || ''))
      return data
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
      return { ok: false, error: caught instanceof Error ? caught.message : String(caught) }
    } finally {
      setBusy(null)
    }
  }

  const productionOrder = asRecord(order?.order)
  const status = String(productionOrder.status || '')
  const productionOrderId = String(productionOrder.id || '')
  const contractVersion = String(productionOrder.contract_version || '')
  const contractSuperseded = Boolean(productionOrderId && contractVersion !== P0_BEAT_CONTRACT_VERSION)
  const scriptReviews = asArray(order?.script_reviews)
  const attempts = asArray(order?.generation_attempts)
  const timelines = asArray(order?.timelines)
  const matchReports = asArray(order?.content_match_reports)
  const vectorMatchReports = asArray(order?.vector_match_reports)
  const lastAttempt = attempts.length ? attempts[attempts.length - 1] : null
  const lastAttemptId = String(lastAttempt?.id || '')
  const chosenPortraits = useMemo(
    () => asArray(inputs?.audience_portraits).filter(item => String(item.audience_record_id || '') === selectedAudienceId),
    [inputs, selectedAudienceId],
  )
  const chosenPacks = useMemo(
    () => asArray(inputs?.audience_packs).filter(item => String(item.audience_record_id || '') === selectedAudienceId),
    [inputs, selectedAudienceId],
  )
  const selectedBridge = useMemo(
    () => bridgeCandidates.find((bridge, index) => bridgeKey(bridge, index) === selectedBridgeKey) || null,
    [bridgeCandidates, selectedBridgeKey],
  )
  const truthSnapshot = asRecord(asRecord(order?.truth_snapshot).snapshot)
  const bridgeContext = asRecord(truthSnapshot.planting_bridge_context)
  const frozenPortrait = asRecord(truthSnapshot.audience_portrait)
  const frozenPortraitId = String(frozenPortrait.id || bridgeContext.audience_portrait_id || productionOrder.audience_portrait_id || '')
  const frozenBridgeFacts = asRecord(bridgeContext.facts)
  const frozenLineage = asRecord(frozenBridgeFacts.lineage)
  const frozenPackId = String(frozenLineage.audience_pack_id || productionOrder.audience_pack_id || '')
  const contentSpec = asRecord(order?.content_spec)
  const frozenContentSpec = asRecord(contentSpec.spec)
  const frozenBridge = asRecord(frozenContentSpec.pain_solution_bridge)
  const frozenBridgeFactHash = String(frozenContentSpec.upstream_fact_hash || contentSpec.upstream_fact_hash || '')
  const hasFrozenBridge = Object.keys(frozenBridge).length > 0 && !!frozenBridgeFactHash
  const hasSelectedBridge = !!selectedBridge && !!bridgeFactHash
  const selectedPortraitIsAdopted = chosenPortraits.some(item => String(item.id || '') === selectedPortraitId)
  const selectedPackIsAdopted = chosenPacks.some(item => String(item.id || '') === selectedPackId)
  const portraitSelectionBlocker = !selectedAudienceId
    ? '先选择已采纳人群。'
    : !chosenPortraits.length
      ? '该人群没有已采纳画像；不能创建 P0 订单。'
      : !selectedPortraitIsAdopted
        ? '选择一个已采纳人群画像后才能创建 P0 订单。'
        : ''
  const packSelectionBlocker = !selectedAudienceId
    ? '先选择已采纳人群。'
    : !chosenPacks.length
      ? '该人群没有已采纳人群包；不能创建 P0 订单。'
      : !selectedPackIsAdopted
        ? '选择一个已采纳人群包后才能创建 P0 订单。'
        : ''
  const bridgeFirstBlocker = !frozenPortraitId
    ? '此订单没有已采纳人群画像。不能生成痛点桥、不能构建 ContentSpec，请新建含已采纳画像的订单。'
    : !frozenPackId
      ? '此订单没有已采纳人群包。不能生成痛点桥、不能构建 ContentSpec，请新建含已采纳包的订单。'
    : !hasFrozenBridge && !bridgeCandidates.length
      ? '先生成两条基于画像与上游事实的痛点—产品解决桥。'
      : !hasFrozenBridge && !selectedBridge
        ? '先明确选择一条桥接候选，不能自动采用。'
        : !hasFrozenBridge && !bridgeFactHash
          ? '候选缺少上游事实哈希，不能冻结 ContentSpec。'
          : ''
  const baselineReady = preflight?.status === 'ready' && !!asRecord(preflight?.baseline_manifest).status
  const canCreate = baselineReady && !!selectedAudienceId && !!selectedReferenceId && selectedPortraitIsAdopted && selectedPackIsAdopted && !busy
  const canGenerateScripts = hasFrozenBridge && !!frozenPortraitId && !!frozenPackId && !busy

  if (!skuId) {
    return (
      <Card>
        <CardHeader><CardTitle>内容质量原子（P0）</CardTitle><CardDescription>先在页面顶部选择一个 SKU，才能读取其已采纳的人群和产品参考图。</CardDescription></CardHeader>
      </Card>
    )
  }

  if (loading) {
    return (
      <Card><CardContent className="flex items-center gap-2 py-8 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> 正在恢复 P0 基线、可用输入和历史订单…</CardContent></Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2"><Film className="h-4 w-4" /> 内容质量原子 · P0 种草视频</CardTitle>
            <CardDescription>只生产一条 12–15 秒、单人单场景的种草视频；电商视觉和 AI 插镜不进入此链路。</CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={!!busy}><RefreshCw className="mr-1 h-3.5 w-3.5" /> 刷新</Button>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          <div className="rounded-lg border p-3 text-xs">
            <div className="font-medium">① 基线 Preflight</div>
            <div className="mt-1 flex items-center gap-1">
              {baselineReady ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" /> : <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />}
              <span>{baselineReady ? '可复现，允许创建订单' : '已阻断，不能创建订单'}</span>
            </div>
          </div>
          <div className="rounded-lg border p-3 text-xs"><div className="font-medium">② 输入 Admission</div><div className="mt-1 text-muted-foreground">已采纳人群 {asArray(inputs?.audience_records).length} 个；画像 {asArray(inputs?.audience_portraits).length} 个；人群包 {asArray(inputs?.audience_packs).length} 个；产品参考图 {asArray(inputs?.product_references).length} 张。</div></div>
          <div className="rounded-lg border p-3 text-xs"><div className="font-medium">③ 当前订单</div><div className="mt-1">{status ? <Badge variant="outline">{STATUS_LABEL[status] || status}</Badge> : <span className="text-muted-foreground">尚未创建</span>}</div></div>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-destructive/40"><CardContent className="flex gap-2 py-4 text-sm text-destructive"><AlertTriangle className="h-4 w-4 shrink-0" /> <span>{error}</span></CardContent></Card>
      )}

      {contractSuperseded && (
        <Card className="border-amber-400/50">
          <CardHeader>
            <CardTitle className="text-sm">旧版脚本不能继续出片</CardTitle>
            <CardDescription>
              这笔订单是 {contractVersion || 'unknown'}；当前 P0 已升级为“已采纳画像 + 已采纳人群包 → 结构化痛点桥 → 内容/向量闸”，并保留短节拍、逐拍口播和字幕校验。
              旧候选会保留审计记录，但不能拿去触发付费生成；请新建订单重新生成 A/B。
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {!baselineReady && preflight && (
        <Card className="border-amber-400/50"><CardHeader><CardTitle className="text-sm">基线未通过</CardTitle><CardDescription>先处理下方 blocker；页面不会把当前运行库或历史分支当成 canonical source。</CardDescription></CardHeader><CardContent><pre className="max-h-52 overflow-auto rounded bg-muted p-3 text-xs">{pretty(preflight.blockers || preflight)}</pre></CardContent></Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>新建生产订单</CardTitle><CardDescription>只允许已采纳的人群、画像、人群包和产品参考图进入 TruthSnapshot。</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <label className="block text-xs font-medium">人群记录
              <select className="mt-1 w-full rounded-md border bg-background p-2 text-sm" value={selectedAudienceId} onChange={event => { setSelectedAudienceId(event.target.value); setSelectedPortraitId(''); setSelectedPackId(''); resetBridgeReview() }}>
                <option value="">选择已采纳人群</option>
                {asArray(inputs?.audience_records).map(item => <option key={String(item.id)} value={String(item.id)}>{String(item.name || item.id)}</option>)}
              </select>
            </label>
            <label className="block text-xs font-medium">产品参考图
              <select className="mt-1 w-full rounded-md border bg-background p-2 text-sm" value={selectedReferenceId} onChange={event => setSelectedReferenceId(event.target.value)}>
                <option value="">选择已采纳参考图</option>
                {asArray(inputs?.product_references).map(item => <option key={String(item.id)} value={String(item.id)}>{String(item.notes || item.file_url || item.id)}</option>)}
              </select>
            </label>
            <label className="block text-xs font-medium">已采纳人群画像（必选）
              <select className="mt-1 w-full rounded-md border bg-background p-2 text-sm" value={selectedPortraitId} onChange={event => { setSelectedPortraitId(event.target.value); resetBridgeReview() }} disabled={!selectedAudienceId || !chosenPortraits.length}>
                <option value="">选择已采纳画像</option>
                {chosenPortraits.map(item => <option key={String(item.id)} value={String(item.id)}>{String(item.audience_name || item.id)}</option>)}
              </select>
            </label>
            <label className="block text-xs font-medium">已采纳人群包（必选）
              <select className="mt-1 w-full rounded-md border bg-background p-2 text-sm" value={selectedPackId} onChange={event => { setSelectedPackId(event.target.value); resetBridgeReview() }} disabled={!selectedAudienceId || !chosenPacks.length}>
                <option value="">选择已采纳人群包</option>
                {chosenPacks.map(item => <option key={String(item.id)} value={String(item.id)}>{`${String(item.audience_name || '人群包')} · v${String(item.version || '—')} · ${String(item.id).slice(0, 8)}`}</option>)}
              </select>
            </label>
            {portraitSelectionBlocker && <p className="rounded border border-amber-400/50 bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950/20 dark:text-amber-200">阻断：{portraitSelectionBlocker}</p>}
            {packSelectionBlocker && <p className="rounded border border-amber-400/50 bg-amber-50 p-2 text-xs text-amber-900 dark:bg-amber-950/20 dark:text-amber-200">阻断：{packSelectionBlocker}</p>}
            <Button className="w-full" disabled={!canCreate} onClick={() => void execute('create', {
              sku_id: skuId,
              audience_record_id: selectedAudienceId,
              audience_portrait_id: selectedPortraitId,
              audience_pack_id: selectedPackId,
              product_reference_asset_ids: [selectedReferenceId],
              baseline_manifest: preflight?.baseline_manifest,
            })}>
              {busy === 'create' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} 冻结事实并创建订单
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>历史订单</CardTitle><CardDescription>刷新或重进页面后，只读取已落库状态，不重新推断。</CardDescription></CardHeader>
          <CardContent className="space-y-2">
            {!orders.length && <p className="text-sm text-muted-foreground">暂无订单；这是正常的空状态。</p>}
            {orders.map(item => (
              <button key={String(item.id)} type="button" onClick={() => void refreshOrder(String(item.id))} className={`w-full rounded border p-2 text-left text-xs ${String(item.id) === productionOrderId ? 'border-primary bg-primary/5' : 'hover:bg-muted'}`}>
                <div className="flex items-center justify-between gap-2"><span className="font-mono">{String(item.id).slice(0, 12)}…</span><Badge variant="outline">{STATUS_LABEL[String(item.status)] || String(item.status)}</Badge></div>
              </button>
            ))}
          </CardContent>
        </Card>
      </div>

      {productionOrderId && (
        <>
          <Card>
            <CardHeader><CardTitle>订单状态与可执行动作</CardTitle><CardDescription>订单 {productionOrderId} · {String(order?.next_action || '没有下一步动作')}</CardDescription></CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Badge>{STATUS_LABEL[status] || status}</Badge>
              {status !== 'released' && status !== 'cancelled' && <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void execute('cancel', { production_order_id: productionOrderId })}>取消并保留审计</Button>}
            </CardContent>
          </Card>

          {(status === 'truth_ready' || (!order?.content_spec && status === 'spec_ready')) && (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>前置内容审核：画像 → 痛点—产品解决桥</CardTitle>
                  <CardDescription>脚本不能直接从 SKU 卖点或一句口号生成。先以冻结的已采纳画像和前置事实生成两条结构化桥，由你明确选择一条；系统不会自动采用。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  {!frozenPortraitId ? (
                    <p className="rounded border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">首个阻断项：{bridgeFirstBlocker}</p>
                  ) : (
                    <>
                      {!bridgeCandidates.length && <Button disabled={!!busy} onClick={() => void execute('bridgeReview', { production_order_id: productionOrderId })}>{busy === 'bridgeReview' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} 生成两条画像驱动的桥接候选</Button>}
                      {bridgeCandidates.length > 0 && (
                        <div className="grid gap-3 lg:grid-cols-2">
                          {bridgeCandidates.map((bridge, index) => {
                            const key = bridgeKey(bridge, index)
                            const isSelected = key === selectedBridgeKey
                            return (
                              <button key={key} type="button" aria-pressed={isSelected} onClick={() => setSelectedBridgeKey(key)} className={`rounded-lg border p-3 text-left text-xs ${isSelected ? 'border-primary bg-primary/5 ring-1 ring-primary/30' : 'hover:bg-muted/60'}`}>
                                <div className="mb-2 flex items-center justify-between gap-2"><strong>桥接候选 {index + 1}</strong><Badge variant={isSelected ? 'default' : 'outline'}>{isSelected ? '已选择' : '点击选择'}</Badge></div>
                                <div className="grid gap-2 sm:grid-cols-2">
                                  <BridgeField label="目标人群" value={bridge.audience_segment} />
                                  <BridgeField label="触发场景" value={bridge.trigger_scene} />
                                  <BridgeField label="具体痛点" value={bridge.pain_point} />
                                  <BridgeField label="不解决的后果" value={bridge.pain_consequence} />
                                  <BridgeField label="产品动作" value={bridge.product_action} />
                                  <BridgeField label="画面可见结果" value={bridge.visible_result} />
                                  <BridgeField label="相信它的理由" value={bridge.belief_shift} />
                                  <BridgeField label="模块" value={`${String(bridge.relevance_module || '—')} / ${String(bridge.justification_module || '—')}`} />
                                </div>
                                <div className="mt-3 grid gap-2 border-t pt-2 sm:grid-cols-3">
                                  <BridgeField label="画像/人群证据" value={evidenceText(bridge.portrait_evidence)} pre />
                                  <BridgeField label="包校准证据" value={evidenceText(bridge.pack_calibration_evidence)} pre />
                                  <BridgeField label="产品/卖点证据" value={evidenceText(bridge.product_evidence)} pre />
                                </div>
                              </button>
                            )
                          })}
                        </div>
                      )}
                      {bridgeCandidates.length > 0 && <p className="font-mono text-xs text-muted-foreground">上游事实哈希：{bridgeFactHash || '缺失'}</p>}
                      {bridgeFirstBlocker && <p className="rounded border border-amber-400/50 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/20 dark:text-amber-200">首个阻断项：{bridgeFirstBlocker}</p>}
                    </>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader><CardTitle>ContentSpec</CardTitle><CardDescription>唯一产品动作和痛点桥来自你选定的结构化候选；事实白名单、禁项和媒体约束从冻结事实自动生成。</CardDescription></CardHeader>
                <CardContent className="grid gap-3 md:grid-cols-2">
                  <BridgeField label="已选桥接的产品动作" value={selectedBridge?.product_action || '先在上方选择桥接候选'} />
                  <BridgeField label="上游事实哈希" value={bridgeFactHash || '先生成并选择桥接候选'} pre />
                  <label className="text-xs font-medium md:col-span-2">口播目标<Textarea className="mt-1" value={spokenCopyGoal} onChange={event => setSpokenCopyGoal(event.target.value)} rows={3} /></label>
                  <Button className="md:col-span-2" disabled={!!busy || !hasSelectedBridge || !frozenPortraitId} onClick={() => void execute('buildSpec', {
                    production_order_id: productionOrderId,
                    product_action: String(selectedBridge?.product_action || ''),
                    pain_solution_bridge: selectedBridge || {},
                    upstream_fact_hash: bridgeFactHash,
                    spoken_copy_goal: spokenCopyGoal,
                  })}>{busy === 'buildSpec' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} 用已选桥接冻结 ContentSpec</Button>
                </CardContent>
              </Card>
            </>
          )}

          {status === 'spec_ready' && <ActionCard title="双候选脚本" description={canGenerateScripts ? '生成两条仅首 3 秒钩子不同的候选。' : '阻断：必须先冻结包含已采纳画像、结构化痛点桥和上游事实哈希的 ContentSpec。'} onClick={() => void execute('generateScripts', { production_order_id: productionOrderId })} busy={busy === 'generateScripts'} disabled={!canGenerateScripts} action="生成两条候选" />}

          {scriptReviews.length > 0 && (
            <Card>
              <CardHeader><CardTitle>脚本候选与独立审稿</CardTitle><CardDescription>确定性事实门和独立 critic 都必须通过，才能选择。</CardDescription></CardHeader>
              <CardContent className="space-y-3">
                {scriptReviews.map(review => {
                  const candidate = candidateOf(review)
                  const passed = String(review.review_status) === 'passed'
                  const vector = vectorMatchReports.find(item => String(item.script_id || '') === String(review.script_id) && String(item.stage || '') === 'candidate')
                  const vectorReport = asRecord(vector?.report)
                  const vectorStatus = String(vector?.report_status || vectorReport.status || '')
                  const vectorScore = vectorReport.overall_score_100
                  const criticGate = asRecord(review.critic_gate)
                  const formalContentGate = asRecord(criticGate.formal_content_gate)
                  const formalVectorGate = asRecord(vectorReport.formal_pre_video_vector_gate)
                  const contentGateFailures = textArray(formalContentGate.failed_checks)
                  const vectorGateFailures = textArray(formalVectorGate.failed_checks)
                  return <div key={String(review.script_id)} className="rounded border p-3 text-xs"><div className="flex items-center justify-between"><strong>候选 {String(review.candidate_slot)}</strong><Badge variant={passed ? 'default' : 'outline'}>{String(review.review_status || 'pending_review')}</Badge></div><p className="mt-2">钩子：{String(candidate.opening_hook_3s || '—')}</p><p>口播：{String(candidate.spoken_copy || '—')}</p>{Object.keys(formalContentGate).length > 0 && <p className={`mt-2 rounded p-2 ${formalContentGate.pass === true ? 'bg-emerald-50 text-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-200' : 'bg-amber-50 text-amber-900 dark:bg-amber-950/20 dark:text-amber-200'}`}>正式内容闸：{formalContentGate.pass === true ? '通过' : `未通过${contentGateFailures.length ? `（${contentGateFailures.join('、')}）` : ''}`}</p>}{passed && <p className="mt-2 rounded bg-muted p-2">{vectorStatus === 'scored' ? `真实三路向量预匹配：${String(vectorScore ?? '—')}/100（仅排序，不判 winner）` : vectorStatus === 'unscored' ? `真实三路向量预匹配：未评分（${String(vectorReport.error || 'embedding unavailable')}）` : '真实三路向量预匹配：尚未运行'}{Object.keys(formalVectorGate).length > 0 ? `；正式五维预匹配：${formalVectorGate.pass === true ? '通过' : `未通过${vectorGateFailures.length ? `（${vectorGateFailures.join('、')}）` : ''}`}` : ''}</p>}{status === 'awaiting_script_selection' && passed && <Button size="sm" className="mt-2" disabled={!!busy || !vectorStatus} onClick={() => void execute('selectScript', { production_order_id: productionOrderId, script_id: review.script_id })}>选择这条</Button>}</div>
                })}
                {status === 'awaiting_script_selection' && <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={!!busy} onClick={() => void execute('reviewScripts', { production_order_id: productionOrderId })}>{busy === 'reviewScripts' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} 运行独立审稿</Button><Button variant="outline" disabled={!!busy} onClick={() => void execute('assessCandidateVector', { production_order_id: productionOrderId })}>{busy === 'assessCandidateVector' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} 运行真实向量预匹配</Button></div>}
              </CardContent>
            </Card>
          )}

          {scriptReviews.some(review => asArray(candidateOf(review).beat_plan).length > 0) && (
            <Card>
              <CardHeader>
                <CardTitle>短节拍表</CardTitle>
                <CardDescription>12 秒成片拆成 4 拍；15 秒拆成 5 拍。这里展示的是同一厨房、同一人物内的镜头/动作/口播节奏，不是多次付费生成。</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3 text-xs">
                {scriptReviews.map(review => {
                  const candidate = candidateOf(review)
                  const beats = asArray(candidate.beat_plan)
                  if (!beats.length) return null
                  return (
                    <div key={`beats-${String(review.script_id)}`} className="rounded border p-3">
                      <div className="mb-2 font-medium">候选 {String(review.candidate_slot)}：前 3 秒钩子 — {String(candidate.opening_hook_3s || '—')}</div>
                      <div className="space-y-1">
                        {beats.map((beat, index) => (
                          <div key={`${String(review.script_id)}-${index}`} className="grid gap-1 rounded bg-muted/50 p-2 md:grid-cols-[72px_1fr]">
                            <span className="font-mono text-muted-foreground">{String(beat.start_seconds ?? '?')}–{String(beat.end_seconds ?? '?')}s</span>
                            <span>
                              {String(beat.visual || '—')}；动作：{String(beat.action || '—')}；
                              {String(beat.spoken_copy || '仅环境声')}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          )}

          {status === 'awaiting_script_selection' && scriptReviews.some(review => review.selected) && <ActionCard title="冻结可执行 Prompt" description="把已选择脚本、产品参考图和 Seedance 路由编译成不可变 PromptSource。" onClick={() => void execute('preparePrompt', { production_order_id: productionOrderId })} busy={busy === 'preparePrompt'} action="编译 Prompt" />}

          {(status === 'prompt_ready' || status === 'awaiting_generation_approval') && (
            <Card>
              <CardHeader><CardTitle>实际执行内容 ↔ 人群</CardTitle><CardDescription>真实三路向量用于人工诊断；P0 v4 必须使用冻结画像和人群包校准来源，并通过正式五维预匹配，才能展示付费生成 Payload。它们都不自动选脚本或判 winner。</CardDescription></CardHeader>
              <CardContent className="space-y-3">
                {!vectorMatchReports.some(report => String(report.stage || '') === 'planned') && <Button variant="outline" disabled={!!busy} onClick={() => void execute('assessExecutionVector', { production_order_id: productionOrderId })}>{busy === 'assessExecutionVector' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} 运行真实三路向量预匹配</Button>}
                {vectorMatchReports.filter(report => String(report.stage || '') === 'planned').map(report => <pre key={String(report.id)} className="max-h-64 overflow-auto rounded bg-muted p-3 text-xs">{pretty(report.report)}</pre>)}
                {!matchReports.length && <Button variant="outline" disabled={!!busy} onClick={() => void execute('assessMatch', { production_order_id: productionOrderId })}>{busy === 'assessMatch' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} 生成词面审计辅助证据</Button>}
                {matchReports.map(report => <pre key={String(report.id)} className="max-h-64 overflow-auto rounded bg-muted p-3 text-xs">{pretty(report.report)}</pre>)}
                <div className="flex flex-wrap gap-2">
                  <Button disabled={!!busy} onClick={() => void execute('requestApproval', { production_order_id: productionOrderId })}>{busy === 'requestApproval' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} 展示付费生成 Payload</Button>
                  {approvalHash && <Button variant="destructive" disabled={!!busy} onClick={() => void execute('startGeneration', { production_order_id: productionOrderId, approval_hash: approvalHash })}>请求付费生成（进入 Human Gate）</Button>}
                </div>
                {approvalHash && <p className="font-mono text-xs text-muted-foreground">审批 hash：{approvalHash}</p>}
              </CardContent>
            </Card>
          )}

          {status === 'generating' && lastAttemptId && <ActionCard title="恢复远端生成" description="只轮询原 remote task，不会创建第二次付费请求。" onClick={() => void execute('recoverGeneration', { production_order_id: productionOrderId, attempt_id: lastAttemptId })} busy={busy === 'recoverGeneration'} action="恢复/轮询" />}
          {status === 'raw_qa' && lastAttemptId && <ActionCard title="Raw 视频 QA" description="技术探针、黑帧/冻结、语义和产品参考图核验全部留痕。" onClick={() => void execute('rawQa', { production_order_id: productionOrderId, attempt_id: lastAttemptId })} busy={busy === 'rawQa'} action="运行 Raw QA" />}

          {status === 'raw_passed' && lastAttemptId && (
            <Card>
              <CardHeader><CardTitle>终片音频、字幕与 BGM</CardTitle><CardDescription>原生音频优先；无原生音频可提供 owner 配音。BGM 必须有授权依据，否则显式确认本版为 VO + 字幕、无 BGM 范围。</CardDescription></CardHeader>
              <CardContent className="space-y-3">
                <Input value={voiceoverAudioRef} onChange={event => setVoiceoverAudioRef(event.target.value)} placeholder="可选：owner 配音音频路径或静态 URL（Raw 无音频时必填）" />
                <Input value={bgmAudioRef} onChange={event => setBgmAudioRef(event.target.value)} placeholder="可选：已授权 BGM 路径或静态 URL" />
                {bgmAudioRef && <Textarea value={bgmAuthorizationNote} onChange={event => setBgmAuthorizationNote(event.target.value)} placeholder="BGM 授权依据（必填，写入时间线 manifest）" rows={2} />}
                {!bgmAudioRef && <label className="flex items-start gap-2 text-xs"><input className="mt-0.5" type="checkbox" checked={allowNoBgm} onChange={event => setAllowNoBgm(event.target.checked)} /> 本版明确交付“VO + 字幕、无 BGM”范围</label>}
                {!bgmAudioRef && allowNoBgm && <Textarea value={noBgmScopeNote} onChange={event => setNoBgmScopeNote(event.target.value)} placeholder="为什么本版不加 BGM；这是必填的范围确认记录" rows={2} />}
                <Button disabled={!!busy} onClick={() => void execute('compose', { production_order_id: productionOrderId, attempt_id: lastAttemptId, voiceover_audio_ref: voiceoverAudioRef || null, bgm_audio_ref: bgmAudioRef || null, bgm_authorization_note: bgmAuthorizationNote || null, allow_no_bgm: allowNoBgm, no_bgm_scope_note: noBgmScopeNote || null })}>{busy === 'compose' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null} 生成终片草稿</Button>
              </CardContent>
            </Card>
          )}

          {status === 'final_qa' && <ActionCard title="终片 QA" description="确认视频流、音频流、字幕、时长、哈希与 BGM 范围/授权都完整。" onClick={() => void execute('finalQa', { production_order_id: productionOrderId })} busy={busy === 'finalQa'} action="运行终片 QA" />}
          {status === 'ready_to_release' && <ActionCard title="发布包" description="仅建立可下载终片和不可变 manifest；不会自动对外发布。" onClick={() => void execute('release', { production_order_id: productionOrderId })} busy={busy === 'release'} action="请求发布（进入 Human Gate）" destructive />}

          {timelines.length > 0 && <Card><CardHeader><CardTitle>后期阶段账本</CardTitle></CardHeader><CardContent><pre className="max-h-64 overflow-auto rounded bg-muted p-3 text-xs">{pretty(timelines)}</pre></CardContent></Card>}
        </>
      )}

      {lastResult && lastTool && (
        <Card>
          <CardHeader><CardTitle>最近一次 P0 操作</CardTitle></CardHeader>
          <CardContent><pre className="max-h-80 overflow-auto rounded bg-muted p-3 text-xs">{pretty(lastResult)}</pre><OutputFeedback toolName={lastTool} label="这次 P0 产物/审核记录是否合格？" /></CardContent>
        </Card>
      )}
    </div>
  )
}

function BridgeField({ label, value, pre = false }: { label: string; value: unknown; pre?: boolean }) {
  const text = typeof value === 'string' && value.trim() ? value : String(value || '—')
  return (
    <div>
      <div className="text-muted-foreground">{label}</div>
      <div className={pre ? 'mt-0.5 whitespace-pre-wrap break-words' : 'mt-0.5 break-words'}>{text}</div>
    </div>
  )
}

function ActionCard({ title, description, action, onClick, busy, disabled = false, destructive = false }: { title: string; description: string; action: string; onClick: () => void; busy: boolean; disabled?: boolean; destructive?: boolean }) {
  return <Card><CardHeader><CardTitle>{title}</CardTitle><CardDescription>{description}</CardDescription></CardHeader><CardContent><Button variant={destructive ? 'destructive' : 'default'} disabled={busy || disabled} onClick={onClick}>{busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}{action}</Button></CardContent></Card>
}
