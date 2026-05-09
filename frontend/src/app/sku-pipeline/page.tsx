'use client'

import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Loader2, Sparkles, ChevronDown, ChevronRight, Copy, Download, Users, Target } from 'lucide-react'

interface SkuRow {
  id: string
  name: string
  status: string
  platform_status: string | null
  growth_class: string | null
  in_focus_pool: boolean
  push_tier: string | null
  price_min: number | null
  price_max: number | null
}

interface TraceShape {
  model_provider: string
  model: string
  final_prompt: string
  params: Record<string, any>
  cost_estimate: string
}

interface MatrixResp {
  ok: boolean
  result?: {
    matrix_md: string
    sku_id: string
    matrix_run_id?: string | null
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

interface AudienceRecordSummary {
  id: string | null
  ordinal: number
  name: string
  kb_doc: string | null
  kb_section: string | null
  layer_tags: string[]
  match_reason_count: number
}

interface AudienceResp {
  ok: boolean
  result?: {
    audience_md: string
    sku_id: string
    matrix_run_id?: string | null
    audience_run_id?: string | null
    records?: AudienceRecordSummary[]
    recall_meta?: {
      mode: string
      queries: string[]
      chunk_count: number
    }
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

interface RecordDetail {
  id: string
  name: string
  kb_doc: string | null
  kb_section: string | null
  kb_chunk_text: string | null
  match_reasons: string[]
  layer_tags: string[]
  raw_md_segment: string
  status: string
  selected_for_pack: boolean
}

interface AudienceRunSummary {
  id: string
  matrix_run_id: string | null
  sku_id: string
  version: number
  status: string
  record_count: number
  model_provider: string | null
  model: string | null
  created_at: string
}

interface AudiencePackResp {
  ok: boolean
  result?: {
    pack_md: string
    audience_pack_id: string | null
    audience_record_id: string
    audience_run_id: string | null
    matrix_run_id: string | null
    sku_id: string
    audience_name: string | null
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

interface KeywordPackResp {
  ok: boolean
  result?: {
    keyword_text: string
    keyword_count: number
    target_count: number
    keyword_pack_id: string | null
    sku_id: string
    audience_record_id: string | null
    audience_pack_id: string | null
    warnings: string[]
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

export default function SkuPipelinePage() {
  const [skus, setSkus] = useState<SkuRow[]>([])
  const [skuId, setSkuId] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  // Step 2 state
  const [userInitialPoints, setUserInitialPoints] = useState('')
  const [userReviews, setUserReviews] = useState('')
  const [kbContext, setKbContext] = useState('')
  const [extraContext2, setExtraContext2] = useState('')
  const [running2, setRunning2] = useState(false)
  const [resp2, setResp2] = useState<MatrixResp | null>(null)
  const [showPrompt2, setShowPrompt2] = useState(false)

  // Step 3 state
  const [matrixMd3, setMatrixMd3] = useState('')
  const [extraContext3, setExtraContext3] = useState('')
  const [kbRecallOverride, setKbRecallOverride] = useState('')
  const [showOverride, setShowOverride] = useState(false)
  const [running3, setRunning3] = useState(false)
  const [resp3, setResp3] = useState<AudienceResp | null>(null)
  const [showPrompt3, setShowPrompt3] = useState(false)
  const [showQueries, setShowQueries] = useState(false)
  // Step 3 phase A：N 个人群卡片相关
  const [adoptedRecordIds, setAdoptedRecordIds] = useState<Set<string>>(new Set())
  const [adopting, setAdopting] = useState<string | null>(null)
  const [expandedRecord, setExpandedRecord] = useState<string | null>(null)
  const [recordDetails, setRecordDetails] = useState<Record<string, RecordDetail>>({})
  const [loadingDetail, setLoadingDetail] = useState<string | null>(null)
  // SKU 已收藏人群池（跨多次 audience_run 的 status=adopted 累积）
  const [poolRecords, setPoolRecords] = useState<AudienceRecordSummary[] | null>(null)
  const [poolLoading, setPoolLoading] = useState(false)
  const [showPool, setShowPool] = useState(false)
  // SKU 的 step 3 历史跑次（A.5：让老板下次启动能挑历史 audience_run 加载回 UI）
  const [historyRuns, setHistoryRuns] = useState<AudienceRunSummary[] | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null)

  // Step 4 圈包 SOP（phase B）
  const [record4Id, setRecord4Id] = useState<string>('')
  const [record4Detail, setRecord4Detail] = useState<RecordDetail | null>(null)
  const [loadingRecord4, setLoadingRecord4] = useState(false)
  const [showRecord4Detail, setShowRecord4Detail] = useState(false)
  const [extraContext4, setExtraContext4] = useState('')
  const [running4, setRunning4] = useState(false)
  const [resp4, setResp4] = useState<AudiencePackResp | null>(null)
  const [showPrompt4, setShowPrompt4] = useState(false)
  // Step 4 关键词扩展（phase B+）
  const [seedKw, setSeedKw] = useState('')
  const [targetCountKw, setTargetCountKw] = useState(500)
  const [runningKw, setRunningKw] = useState(false)
  const [respKw, setRespKw] = useState<KeywordPackResp | null>(null)
  const [copiedKw, setCopiedKw] = useState(false)

  useEffect(() => {
    fetch('/api/omni/scout/skus?status=active')
      .then(r => r.json())
      .then(data => {
        const arr: SkuRow[] = Array.isArray(data) ? data : (data.data || data.skus || [])
        setSkus(arr)
        if (arr.length > 0 && !skuId) setSkuId(arr[0].id)
      })
      .catch(e => setError(`SKU 列表加载失败: ${String(e)}`))
  }, [])

  // step 2 跑完 → 自动同步 matrix_md 到 step 3 输入（老板可手改）
  useEffect(() => {
    if (resp2?.result?.matrix_md) {
      setMatrixMd3(resp2.result.matrix_md)
    }
  }, [resp2?.result?.matrix_md])

  const selectedSku = skus.find(s => s.id === skuId)

  const runStep2 = async () => {
    setRunning2(true)
    setResp2(null)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/selling-points-matrix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sku_id: skuId,
          user_initial_points: userInitialPoints,
          user_reviews: userReviews,
          kb_context: kbContext || null,
          extra_context: extraContext2 || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp2(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning2(false)
    }
  }

  const runStep3 = async () => {
    setRunning3(true)
    setResp3(null)
    setError(null)
    setAdoptedRecordIds(new Set())
    setExpandedRecord(null)
    setRecordDetails({})
    try {
      const res = await fetch('/api/omni/sku-pipeline/audience-match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sku_id: skuId,
          matrix_md: matrixMd3,
          extra_context: extraContext3 || null,
          kb_recall_override: kbRecallOverride || null,
          // 自动带上 step 2 拿到的 matrix_run_id（如果有），让链路血缘连起来
          matrix_run_id: resp2?.result?.matrix_run_id || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp3(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning3(false)
    }
  }

  // 收藏某个 audience_record 到 SKU 人群池（status=adopted，**不**动 selected_for_pack）。
  // selected_for_pack 留给 phase B step 4 圈包"挑 1 个出发"那一刻设——勾选 ≠ 即刻挂下游。
  const adoptAudienceRecord = async (recordId: string) => {
    if (!recordId || adopting) return
    setAdopting(recordId)
    try {
      const res = await fetch('/api/omni/sku-pipeline/adopt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          table: 'audience_records',
          run_id: recordId,
          set_selected: false,
        }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setAdoptedRecordIds(prev => {
          const next = new Set(prev)
          next.add(recordId)
          return next
        })
        // 收藏成功 → 让 SKU 人群池下次打开/已展开时自动 refetch
        setPoolRecords(null)
      } else {
        setError(`收藏失败：${json.data?.error || json.error || '未知错误'}`)
      }
    } catch (e) {
      setError(`收藏异常：${String(e)}`)
    } finally {
      setAdopting(null)
    }
  }

  // 拉 SKU 已收藏池（跨多次 audience_run）—— 老板要确认"留着以后用"是真留下了
  const loadPool = async () => {
    if (!skuId) return
    setPoolLoading(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/list-audience-records', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku_id: skuId, selected_only: false, limit: 100 }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        // 只看 status=adopted 的（人群池）
        const adopted = (json.data.records || []).filter((r: any) => r.status === 'adopted')
        setPoolRecords(adopted)
      } else {
        setPoolRecords([])
      }
    } catch (e) {
      console.error('loadPool failed', e)
      setPoolRecords([])
    } finally {
      setPoolLoading(false)
    }
  }

  // SKU 变化时清空 pool / history 缓存（让老板切 SKU 时不串）
  useEffect(() => {
    setPoolRecords(null)
    setShowPool(false)
    setHistoryRuns(null)
    setShowHistory(false)
  }, [skuId])

  // 老板点了"看人群池"或者本次新收藏一条 → 自动 refresh pool（保证池数据是最新的）
  useEffect(() => {
    if (showPool && poolRecords === null && !poolLoading) {
      loadPool()
    }
  }, [showPool, poolRecords, poolLoading])

  // 老板点了"看历史" → lazy load 该 SKU 跑过的所有 audience_run
  const loadHistory = async () => {
    if (!skuId) return
    setHistoryLoading(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/list-audience-runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku_id: skuId, limit: 30 }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setHistoryRuns(json.data.runs || [])
      } else {
        setHistoryRuns([])
      }
    } catch (e) {
      console.error('loadHistory failed', e)
      setHistoryRuns([])
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => {
    if (showHistory && historyRuns === null && !historyLoading) {
      loadHistory()
    }
  }, [showHistory, historyRuns, historyLoading])

  // 加载某次历史 audience_run 全量回 UI（含整段 markdown / N 条 records / 已勾选状态）
  const loadAudienceRun = async (runId: string) => {
    setLoadingRunId(runId)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/get-audience-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audience_run_id: runId }),
      })
      const json = await res.json()
      if (!json.success || !json.data?.ok) {
        setError(`加载失败：${json.data?.error || json.error || '未知错误'}`)
        return
      }
      const { run, records } = json.data as {
        run: any
        records: Array<{
          id: string
          ordinal: number
          name: string
          kb_doc: string | null
          kb_section: string | null
          layer_tags: string[]
          match_reasons: string[]
          status: string
          selected_for_pack: boolean
        }>
      }
      // 把 audience_run 灌回 resp3 state（让 UI 渲染跟刚跑完一致）
      const summaries: AudienceRecordSummary[] = records.map(r => ({
        id: r.id,
        ordinal: r.ordinal,
        name: r.name,
        kb_doc: r.kb_doc,
        kb_section: r.kb_section,
        layer_tags: r.layer_tags || [],
        match_reason_count: (r.match_reasons || []).length,
      }))
      setResp3({
        ok: true,
        result: {
          audience_md: run.audience_md,
          sku_id: run.sku_id,
          matrix_run_id: run.matrix_run_id,
          audience_run_id: run.id,
          recall_meta: run.recall_meta || { mode: '', queries: [], chunk_count: 0 },
          records: summaries,
        },
        trace: undefined,  // 历史加载不带 trace（重跑才有）
      } as any)
      // 同步勾选集合：把 status='adopted' 的所有 record 标为已收藏
      const adopted = new Set<string>()
      for (const r of records) {
        if (r.status === 'adopted' && r.id) adopted.add(r.id)
      }
      setAdoptedRecordIds(adopted)
      setExpandedRecord(null)
      setRecordDetails({})
      setShowHistory(false)  // 加载完关闭历史下拉，让老板看到刚加载的卡片列表
    } catch (e) {
      setError(`加载异常：${String(e)}`)
    } finally {
      setLoadingRunId(null)
    }
  }

  // === Step 4: 选 audience_record + 跑圈包 ===
  const selectRecord4 = async (recordId: string) => {
    setRecord4Id(recordId)
    setRecord4Detail(null)
    setShowRecord4Detail(false)
    setResp4(null)
    if (!recordId) return
    // 复用已缓存的 detail（如果有）
    if (recordDetails[recordId]) {
      setRecord4Detail(recordDetails[recordId])
      return
    }
    setLoadingRecord4(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/get-audience-record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ record_id: recordId }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok && json.data?.record) {
        const detail = json.data.record as RecordDetail
        setRecord4Detail(detail)
        setRecordDetails(prev => ({ ...prev, [recordId]: detail }))
      }
    } catch (e) {
      console.error('selectRecord4 failed', e)
    } finally {
      setLoadingRecord4(false)
    }
  }

  const runStep4 = async () => {
    if (!record4Id) return
    setRunning4(true)
    setResp4(null)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/audience-pack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          audience_record_id: record4Id,
          extra_context: extraContext4 || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp4(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning4(false)
    }
  }

  // SKU 切换时清空 step 4 状态
  useEffect(() => {
    setRecord4Id('')
    setRecord4Detail(null)
    setResp4(null)
    setExtraContext4('')
    setSeedKw('')
    setRespKw(null)
  }, [skuId])

  // 从 resp4.pack_md 第 4 部分抽推荐种子词（auto-fill 到种子词输入框）
  const extractSeedFromPackMd = (md: string): string => {
    if (!md) return ''
    // 找"第 4 部分"之后到"---"之前的段
    const m = md.match(/第\s*4\s*部分[^\n]*\n([\s\S]+?)(?:\n---|\n###|\Z)/)
    if (!m) return ''
    const block = m[1]
    // 抓 bullet (- xxx 或 * xxx) 或 顿号/逗号分隔的清单
    const items: string[] = []
    const bullet = /^[\-\*]\s*([^\n]+)/gm
    let bm: RegExpExecArray | null
    while ((bm = bullet.exec(block)) !== null) {
      const raw = bm[1].trim().replace(/^[「\["'`]|[」\]"'`，。、；;.]+$/g, '')
      // 去掉里面的"等"字尾 / 解释括号
      const cleaned = raw.replace(/[（(].*?[)）]/g, '').trim()
      if (cleaned && cleaned.length >= 2 && cleaned.length <= 20) {
        items.push(cleaned)
      }
    }
    // 如果 bullet 没抓到，尝试逗号/顿号分隔
    if (items.length === 0) {
      const parts = block.split(/[、，,；;]/).map(s => s.trim()).filter(s => s.length >= 2 && s.length <= 20)
      items.push(...parts.slice(0, 10))
    }
    return items.slice(0, 12).join('\n')
  }

  // resp4 跑完 → 自动从 pack_md 第 4 部分抽种子词预填到输入框
  useEffect(() => {
    if (resp4?.result?.pack_md && !seedKw) {
      const auto = extractSeedFromPackMd(resp4.result.pack_md)
      if (auto) setSeedKw(auto)
    }
  }, [resp4?.result?.pack_md])

  const runKeywordPack = async () => {
    if (!seedKw.trim()) return
    setRunningKw(true)
    setRespKw(null)
    setError(null)
    setCopiedKw(false)
    try {
      const res = await fetch('/api/omni/sku-pipeline/keyword-pack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          seed_keywords: seedKw,
          target_count: targetCountKw,
          // 自动挂上 step 4 的链路（如果有）
          audience_record_id: resp4?.result?.audience_record_id || record4Id || null,
          audience_pack_id: resp4?.result?.audience_pack_id || null,
          sku_id: skuId || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setRespKw(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunningKw(false)
    }
  }

  const copyKeywordText = async () => {
    if (!respKw?.result?.keyword_text) return
    await navigator.clipboard.writeText(respKw.result.keyword_text)
    setCopiedKw(true)
    setTimeout(() => setCopiedKw(false), 2000)
  }

  const downloadKeywordTxt = () => {
    if (!respKw?.result?.keyword_text) return
    const blob = new Blob([respKw.result.keyword_text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const skuShort = (skuId || 'unknown').replace(/^SKU-/, '')
    const recordShort = (record4Id || 'norecord').slice(0, 8)
    const count = respKw.result.keyword_count
    a.href = url
    a.download = `keywords_${skuShort}_${recordShort}_${count}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  // 展开某个 record，按需 lazy load 完整字段（kb_chunk_text + match_reasons + raw_md_segment）
  const toggleExpandRecord = async (recordId: string) => {
    if (expandedRecord === recordId) {
      setExpandedRecord(null)
      return
    }
    setExpandedRecord(recordId)
    if (recordDetails[recordId]) return  // 已缓存
    setLoadingDetail(recordId)
    try {
      const res = await fetch('/api/omni/sku-pipeline/get-audience-record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ record_id: recordId }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok && json.data?.record) {
        setRecordDetails(prev => ({ ...prev, [recordId]: json.data.record }))
      }
    } catch (e) {
      // 详情拉不到不阻塞主流程，仅 console
      console.error('load record detail failed', e)
    } finally {
      setLoadingDetail(null)
    }
  }

  const copyText = (text: string | undefined) => {
    if (text) navigator.clipboard.writeText(text)
  }
  const downloadMd = (text: string | undefined, filename: string) => {
    if (!text) return
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  // SKU 选择器（两个 step 共享）
  const SkuPicker = (
    <div>
      <label className="text-sm font-medium mb-1 block">SKU（共 {skus.length} 个 active）</label>
      <select
        className="w-full border rounded px-2 py-2 text-sm bg-background"
        value={skuId}
        onChange={e => setSkuId(e.target.value)}
      >
        {skus.map(s => (
          <option key={s.id} value={s.id}>
            {s.id} — {s.name.substring(0, 30)} {s.in_focus_pool ? '⭐' : ''}
            {s.platform_status === 'on_sale' ? '' : ` [${s.platform_status}]`}
          </option>
        ))}
      </select>
      {selectedSku && (
        <div className="text-xs text-muted-foreground mt-1 space-x-2">
          <Badge variant="outline">{selectedSku.platform_status || 'unknown'}</Badge>
          {selectedSku.growth_class && (
            <Badge variant="outline">{selectedSku.growth_class}</Badge>
          )}
          {selectedSku.price_min !== null && (
            <span>¥{selectedSku.price_min}{selectedSku.price_max && selectedSku.price_max !== selectedSku.price_min ? ` - ¥${selectedSku.price_max}` : ''}</span>
          )}
        </div>
      )}
    </div>
  )

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Sparkles className="w-6 h-6" /> SKU Pipeline 测试
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          单步测试通道。每步可独立跑（不强制走完整链路）；step 2 跑完后 matrix_md 会自动喂到 step 3。
        </p>
      </div>

      <Tabs defaultValue="step2" className="w-full">
        <TabsList variant="line">
          <TabsTrigger value="step2">
            <Sparkles className="w-3 h-3 mr-1" /> Step 2 · 卖点矩阵
          </TabsTrigger>
          <TabsTrigger value="step3">
            <Users className="w-3 h-3 mr-1" /> Step 3 · 人群匹配
          </TabsTrigger>
          <TabsTrigger value="step4">
            <Target className="w-3 h-3 mr-1" /> Step 4 · 圈包 SOP
          </TabsTrigger>
        </TabsList>

        {/* ============== STEP 2: 卖点矩阵 ============== */}
        <TabsContent value="step2" className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">输入</CardTitle>
                <CardDescription>
                  调味品行业专家 prompt — 5 部分输出（产品档案 / 三层卖点地图 / 五心智维度 /
                  结构化标签汇总 / 信息补全建议）
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    ④ 自己观察到的显性卖点（user_initial_points）
                  </label>
                  <Textarea
                    placeholder="例：日式风味、有机、零添加、180 天发酵、玻璃瓶包装、33 年源头工厂..."
                    value={userInitialPoints}
                    onChange={e => setUserInitialPoints(e.target.value)}
                    rows={3}
                    className="text-sm"
                  />
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    ③ 用户评价（user_reviews）
                  </label>
                  <Textarea
                    placeholder="好评关键词 / 差评关键词 / 客服反馈 / 私域反馈，例：「鲜味浓不咸」「玻璃瓶有质感」「滴几滴提鲜」「价格偏贵」「物流泡沫薄」..."
                    value={userReviews}
                    onChange={e => setUserReviews(e.target.value)}
                    rows={4}
                    className="text-sm"
                  />
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    可选补充（kb_context — 竞品 / 品牌故事 / 工艺细节 / 历史血统）
                  </label>
                  <Textarea
                    placeholder="（可空）建议先 search_kb 拿同品类爆款拆解 / 品牌资产再贴这里"
                    value={kbContext}
                    onChange={e => setKbContext(e.target.value)}
                    rows={3}
                    className="text-sm"
                  />
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    额外要求（extra_context）
                  </label>
                  <Textarea
                    placeholder="（可空）例：「这次主推送礼场景」「重点挖儿童辅食角度」"
                    value={extraContext2}
                    onChange={e => setExtraContext2(e.target.value)}
                    rows={2}
                    className="text-sm"
                  />
                </div>

                <Button
                  onClick={runStep2}
                  disabled={running2 || !skuId}
                  className="w-full"
                >
                  {running2 ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（约 60-120s，pro 模型推理慢）</> : '跑卖点矩阵'}
                </Button>

                {error && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">输出</CardTitle>
                  {resp2?.trace && (
                    <CardDescription className="text-xs">
                      {resp2.trace.model_provider}/{resp2.trace.model} · {resp2.trace.cost_estimate}
                    </CardDescription>
                  )}
                </div>
                {resp2?.result?.matrix_md && (
                  <div className="space-x-1">
                    <Button size="sm" variant="outline" onClick={() => copyText(resp2.result?.matrix_md)}>
                      <Copy className="w-3 h-3 mr-1" /> 复制
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => downloadMd(resp2.result?.matrix_md, `${skuId}_selling-points-matrix.md`)}>
                      <Download className="w-3 h-3 mr-1" /> 下载 .md
                    </Button>
                  </div>
                )}
              </CardHeader>
              <CardContent>
                {!resp2 && !running2 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左边填资料后点"跑卖点矩阵"，结果会显示在这里。
                  </div>
                )}
                {running2 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                    LLM 正在生成 5 部分报告...
                  </div>
                )}
                {resp2?.result?.matrix_md && (
                  <>
                    {resp2.result.matrix_run_id && (
                      <div className="mb-3 flex items-center gap-2 text-xs">
                        <Badge variant="outline" className="text-xs">已落库</Badge>
                        <span className="text-muted-foreground">
                          matrix_run_id: <code className="text-[10px]">{resp2.result.matrix_run_id.slice(0, 8)}…</code>
                          <span className="ml-2">step 3 会自动挂这个 id</span>
                        </span>
                      </div>
                    )}
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {resp2.result.matrix_md}
                      </ReactMarkdown>
                    </div>

                    {resp2.trace?.final_prompt && (
                      <div className="mt-6 border-t pt-4">
                        <button
                          className="text-sm font-medium flex items-center gap-1"
                          onClick={() => setShowPrompt2(s => !s)}
                        >
                          {showPrompt2 ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          Final Prompt
                        </button>
                        {showPrompt2 && (
                          <pre className="mt-2 p-3 bg-muted text-xs rounded max-h-96 overflow-auto whitespace-pre-wrap">
                            {resp2.trace.final_prompt}
                          </pre>
                        )}
                      </div>
                    )}
                  </>
                )}
                {resp2 && !resp2.ok && (
                  <div className="text-sm text-red-500">
                    <div>Error: {resp2.error}</div>
                    {resp2.hint && <div className="text-xs text-muted-foreground mt-1">{resp2.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ============== STEP 3: 人群匹配 ============== */}
        <TabsContent value="step3" className="mt-4">
          {/* SKU 状态卡（人群池 + 历史跑次）*/}
          {skuId && (
            <Card className="mb-4">
              <CardContent className="pt-4 space-y-3">
                {/* 已收藏人群池 */}
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2 text-sm">
                    <span>📌</span>
                    <span className="font-medium">{skuId}</span>
                    <span className="text-muted-foreground">已收藏的人群池</span>
                    {poolRecords !== null && (
                      <Badge variant="secondary">{poolRecords.length} 条</Badge>
                    )}
                    {poolRecords === null && !poolLoading && (
                      <span className="text-xs text-muted-foreground">（未加载）</span>
                    )}
                    {poolLoading && (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    )}
                  </div>
                  <div className="space-x-1">
                    <Button
                      size="sm"
                      variant={showPool ? 'default' : 'outline'}
                      onClick={() => setShowPool(s => !s)}
                    >
                      {showPool ? <ChevronDown className="w-3 h-3 mr-1" /> : <ChevronRight className="w-3 h-3 mr-1" />}
                      {showPool ? '收起' : '查看池子'}
                    </Button>
                    {showPool && (
                      <Button size="sm" variant="ghost" onClick={loadPool} disabled={poolLoading}>
                        刷新
                      </Button>
                    )}
                  </div>
                </div>
                {showPool && poolRecords !== null && poolRecords.length === 0 && (
                  <div className="text-xs text-muted-foreground py-3 text-center border border-dashed rounded">
                    池子是空的。在下方跑过 step 3 后，挑你认可的人群点 ⭐ 加入人群池。
                  </div>
                )}
                {showPool && poolRecords !== null && poolRecords.length > 0 && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {poolRecords.map(r => (
                      <div key={r.id || r.ordinal} className="border rounded p-2 text-xs bg-emerald-50/30 dark:bg-emerald-950/20">
                        <div className="flex items-center gap-1 flex-wrap">
                          <span className="font-medium">{r.name}</span>
                          {(r.layer_tags || []).slice(0, 3).map((t, i) => (
                            <Badge key={i} variant="outline" className="text-[9px]">{t}</Badge>
                          ))}
                        </div>
                        {r.kb_doc && (
                          <div className="text-muted-foreground mt-1 truncate">
                            {r.kb_doc}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                <div className="text-[11px] text-muted-foreground">
                  人群池 = SKU 跨多次 step 3 跑过的所有「老板已勾选」人群。后续跑 step 4 圈包时，从这池子里选 1 个出发。
                </div>

                {/* 历史 step 3 跑次（A.5：恢复上次跑过的 audience_run）*/}
                <div className="border-t pt-3">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2 text-sm">
                      <span>📜</span>
                      <span className="text-muted-foreground">历史 step 3 跑次</span>
                      {historyRuns !== null && (
                        <Badge variant="secondary">{historyRuns.length} 次</Badge>
                      )}
                      {historyRuns === null && !historyLoading && (
                        <span className="text-xs text-muted-foreground">（未加载）</span>
                      )}
                      {historyLoading && <Loader2 className="w-3 h-3 animate-spin" />}
                    </div>
                    <div className="space-x-1">
                      <Button
                        size="sm"
                        variant={showHistory ? 'default' : 'outline'}
                        onClick={() => setShowHistory(s => !s)}
                      >
                        {showHistory ? <ChevronDown className="w-3 h-3 mr-1" /> : <ChevronRight className="w-3 h-3 mr-1" />}
                        {showHistory ? '收起' : '查看历史'}
                      </Button>
                      {showHistory && (
                        <Button size="sm" variant="ghost" onClick={loadHistory} disabled={historyLoading}>
                          刷新
                        </Button>
                      )}
                    </div>
                  </div>
                  {showHistory && historyRuns !== null && historyRuns.length === 0 && (
                    <div className="mt-2 text-xs text-muted-foreground py-3 text-center border border-dashed rounded">
                      该 SKU 还没跑过 step 3。下方跑一次后会出现在这里。
                    </div>
                  )}
                  {showHistory && historyRuns !== null && historyRuns.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {historyRuns.map(run => (
                        <div
                          key={run.id}
                          className="flex items-center justify-between gap-2 p-2 border rounded text-xs hover:bg-muted/50"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <Badge variant="outline" className="text-[10px]">v{run.version}</Badge>
                            <Badge
                              variant={run.status === 'adopted' ? 'default' : 'outline'}
                              className="text-[10px]"
                            >
                              {run.status}
                            </Badge>
                            <span className="text-muted-foreground">
                              {run.record_count} 条人群
                            </span>
                            <span className="text-muted-foreground truncate">
                              {new Date(run.created_at).toLocaleString('zh-CN', { hour12: false })}
                            </span>
                            <code className="text-[9px] text-muted-foreground">{run.id.slice(0, 8)}…</code>
                          </div>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={loadingRunId === run.id}
                            onClick={() => loadAudienceRun(run.id)}
                            className="shrink-0"
                          >
                            {loadingRunId === run.id
                              ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 加载中</>
                              : '加载这次'}
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="text-[11px] text-muted-foreground mt-2">
                    每次跑 step 3 = 一行历史。点"加载这次" → N 条候选卡片 + 整段 markdown 全部恢复到下方输出区，已勾选状态会一起带回来。
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">输入</CardTitle>
                <CardDescription>
                  反向匹配 = 拿卖点+场景+心智去 KB 全部 chunks 里实打实挑对口人群。
                  2 部分输出（KB 匹配人群 ≥15 / 跨 ≥10 doc / 标签 ≥30）。KB 共 46 doc，全 KB 多 query 扩散召回。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    matrix_md（step 2 输出 — 必填）
                    {resp2?.result?.matrix_md && (
                      <Badge variant="outline" className="ml-2 text-xs">已自动同步 step 2 结果</Badge>
                    )}
                  </label>
                  <Textarea
                    placeholder="粘贴 step 2 的卖点矩阵 markdown（含三层卖点 + 5 心智 + 标签），或先去 step 2 跑一次自动同步"
                    value={matrixMd3}
                    onChange={e => setMatrixMd3(e.target.value)}
                    rows={10}
                    className="text-sm font-mono"
                  />
                  <div className="text-xs text-muted-foreground mt-1">
                    {matrixMd3.length} 字
                  </div>
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    额外要求（extra_context）
                  </label>
                  <Textarea
                    placeholder="（可空）例：「重点挖跨圈层」「假设里多列银发人群」「对标 X 品牌的人群路径」"
                    value={extraContext3}
                    onChange={e => setExtraContext3(e.target.value)}
                    rows={2}
                    className="text-sm"
                  />
                </div>

                <div>
                  <button
                    className="text-xs text-muted-foreground flex items-center gap-1"
                    onClick={() => setShowOverride(s => !s)}
                  >
                    {showOverride ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    高级：手动覆盖 KB 召回（极少用）
                  </button>
                  {showOverride && (
                    <Textarea
                      placeholder="（可空）老板想跳过自动多 query 召回，直接喂自定义 KB chunks 时贴这里。给了这个，tool 不再调 search_kb"
                      value={kbRecallOverride}
                      onChange={e => setKbRecallOverride(e.target.value)}
                      rows={4}
                      className="text-sm mt-2"
                    />
                  )}
                </div>

                <Button
                  onClick={runStep3}
                  disabled={running3 || !skuId || !matrixMd3.trim()}
                  className="w-full"
                >
                  {running3 ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（多 query 召回 + pro 推理 ~120s）</> : '跑人群匹配'}
                </Button>

                {error && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">输出</CardTitle>
                  {resp3?.trace && (
                    <CardDescription className="text-xs">
                      {resp3.trace.model_provider}/{resp3.trace.model} · {resp3.trace.cost_estimate}
                    </CardDescription>
                  )}
                </div>
                {resp3?.result?.audience_md && (
                  <div className="space-x-1">
                    <Button size="sm" variant="outline" onClick={() => copyText(resp3.result?.audience_md)}>
                      <Copy className="w-3 h-3 mr-1" /> 复制
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => downloadMd(resp3.result?.audience_md, `${skuId}_audience-match.md`)}>
                      <Download className="w-3 h-3 mr-1" /> 下载 .md
                    </Button>
                  </div>
                )}
              </CardHeader>
              <CardContent>
                {!resp3 && !running3 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左边贴 matrix_md 后点"跑人群匹配"，结果会显示在这里。
                  </div>
                )}
                {running3 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                    全 KB 多 query 召回（跨 46 doc）→ pro 模型反向匹配 → 资料诊断 + ≥15 个匹配人群 + 标签汇总...
                  </div>
                )}
                {resp3?.result?.audience_md && (
                  <>
                    {resp3.result.recall_meta && (
                      <div className="mb-4 p-3 bg-muted/50 rounded text-xs space-y-1">
                        <div className="flex items-center justify-between">
                          <div>
                            <span className="font-medium">召回模式：</span>
                            <Badge variant="outline" className="ml-1">
                              {resp3.result.recall_meta.mode === 'multi_query' ? '多 query 自动召回' : '手动覆盖'}
                            </Badge>
                            <span className="ml-3">
                              <span className="font-medium">queries:</span> {resp3.result.recall_meta.queries.length}
                            </span>
                            <span className="ml-3">
                              <span className="font-medium">chunks:</span> {resp3.result.recall_meta.chunk_count}
                            </span>
                          </div>
                          {resp3.result.recall_meta.queries.length > 0 && (
                            <button
                              className="flex items-center gap-1"
                              onClick={() => setShowQueries(s => !s)}
                            >
                              {showQueries ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                              展开 query 清单
                            </button>
                          )}
                        </div>
                        {showQueries && resp3.result.recall_meta.queries.length > 0 && (
                          <ul className="mt-2 list-disc list-inside text-muted-foreground">
                            {resp3.result.recall_meta.queries.map((q, i) => (
                              <li key={i}>{q}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}

                    {/* 落库摘要 + N 个人群卡片（phase A 新） */}
                    {resp3.result.audience_run_id && (
                      <div className="mb-4 p-3 border rounded bg-blue-50/40 dark:bg-blue-950/20 text-xs">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge variant="outline">已落库</Badge>
                          <span>
                            audience_run_id: <code className="text-[10px]">{resp3.result.audience_run_id.slice(0, 8)}…</code>
                          </span>
                          <span className="ml-2">
                            <strong>{resp3.result.records?.length ?? 0}</strong> 条候选人群
                          </span>
                          {adoptedRecordIds.size > 0 && (
                            <Badge variant="secondary" className="text-[10px]">
                              本次已收藏 {adoptedRecordIds.size}
                            </Badge>
                          )}
                          {resp3.result.matrix_run_id && (
                            <span className="ml-2 text-muted-foreground">
                              ← matrix_run_id: <code className="text-[10px]">{resp3.result.matrix_run_id.slice(0, 8)}…</code>
                            </span>
                          )}
                        </div>
                        <div className="text-muted-foreground mt-1">
                          ⭐ 勾选 = 把这条加进 SKU 的人群池（持久化收藏）。**不会**立刻跑下游 step 4 圈包；以后跑圈包时从池子里选 1 个出发即可。
                        </div>
                      </div>
                    )}

                    {(resp3.result.records?.length ?? 0) > 0 && (
                      <div className="space-y-3 mb-4">
                        {resp3.result.records!.map(r => {
                          const adopted = r.id ? adoptedRecordIds.has(r.id) : false
                          const expanded = expandedRecord === r.id
                          const detail = r.id ? recordDetails[r.id] : undefined
                          return (
                            <div
                              key={r.id || r.ordinal}
                              className={`border rounded-lg p-4 transition ${adopted ? 'bg-emerald-50/40 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800' : 'bg-card hover:bg-muted/30'}`}
                            >
                              <div className="flex items-start justify-between gap-2 mb-2">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-xs text-muted-foreground">#{r.ordinal}</span>
                                    <h4 className="font-medium text-sm">{r.name}</h4>
                                    {(r.layer_tags || []).map((t, i) => (
                                      <Badge key={i} variant="secondary" className="text-[10px]">{t}</Badge>
                                    ))}
                                  </div>
                                  {r.kb_doc && (
                                    <div className="text-xs text-muted-foreground mt-1 truncate">
                                      KB 来源：{r.kb_doc}{r.kb_section ? ` · ${r.kb_section}` : ''}
                                    </div>
                                  )}
                                  <div className="text-xs text-muted-foreground mt-1">
                                    匹配理由 {r.match_reason_count} 条
                                  </div>
                                </div>
                                <Button
                                  size="sm"
                                  variant={adopted ? 'default' : 'outline'}
                                  disabled={!r.id || adopting === r.id || adopted}
                                  onClick={() => r.id && adoptAudienceRecord(r.id)}
                                  className="shrink-0"
                                  title={adopted ? '已加入 SKU 人群池，以后跑 step 4 圈包从池里选' : '把这条人群收藏到 SKU 人群池'}
                                >
                                  {adopting === r.id
                                    ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 收藏中</>
                                    : adopted
                                      ? <>✓ 已收藏</>
                                      : <>⭐ 加入人群池</>}
                                </Button>
                              </div>
                              {r.id && (
                                <button
                                  className="text-xs text-muted-foreground flex items-center gap-1"
                                  onClick={() => toggleExpandRecord(r.id!)}
                                >
                                  {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                                  {loadingDetail === r.id ? '加载中...' : '展开 KB 原文 + 匹配理由'}
                                </button>
                              )}
                              {expanded && detail && (
                                <div className="mt-3 prose prose-sm max-w-none dark:prose-invert border-t pt-3">
                                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                    {detail.raw_md_segment}
                                  </ReactMarkdown>
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}

                    {/* 完整原始报告（折叠 — 老板想看 LLM 原始整段时翻这里） */}
                    <details className="mt-4 border-t pt-4">
                      <summary className="text-sm font-medium cursor-pointer select-none">
                        完整原始报告（含第 2 部分标签汇总；含 LLM 原始 markdown）
                      </summary>
                      <div className="mt-3 prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {resp3.result.audience_md}
                        </ReactMarkdown>
                      </div>
                    </details>

                    {resp3.trace?.final_prompt && (
                      <div className="mt-6 border-t pt-4">
                        <button
                          className="text-sm font-medium flex items-center gap-1"
                          onClick={() => setShowPrompt3(s => !s)}
                        >
                          {showPrompt3 ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          Final Prompt（含 KB 召回原文）
                        </button>
                        {showPrompt3 && (
                          <pre className="mt-2 p-3 bg-muted text-xs rounded max-h-96 overflow-auto whitespace-pre-wrap">
                            {resp3.trace.final_prompt}
                          </pre>
                        )}
                      </div>
                    )}
                  </>
                )}
                {resp3 && !resp3.ok && (
                  <div className="text-sm text-red-500">
                    <div>Error: {resp3.error}</div>
                    {resp3.hint && <div className="text-xs text-muted-foreground mt-1">{resp3.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ============== STEP 4: 圈包 SOP ============== */}
        <TabsContent value="step4" className="mt-4">
          {/* SKU 状态卡（已收藏池 — 复用 step 3 的池子）*/}
          {skuId && (
            <Card className="mb-4">
              <CardContent className="pt-4">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2 text-sm">
                    <span>📌</span>
                    <span className="font-medium">{skuId}</span>
                    <span className="text-muted-foreground">已收藏的人群池（step 4 候选）</span>
                    {poolRecords !== null && (
                      <Badge variant="secondary">{poolRecords.length} 条可选</Badge>
                    )}
                    {poolRecords === null && !poolLoading && (
                      <span className="text-xs text-muted-foreground">（点右侧加载）</span>
                    )}
                    {poolLoading && <Loader2 className="w-3 h-3 animate-spin" />}
                  </div>
                  <Button size="sm" variant="outline" onClick={loadPool} disabled={poolLoading}>
                    {poolRecords !== null ? '刷新' : '加载人群池'}
                  </Button>
                </div>
                {poolRecords !== null && poolRecords.length === 0 && (
                  <div className="mt-3 text-xs text-muted-foreground py-3 text-center border border-dashed rounded">
                    池子是空的。先去 step 3 跑一次人群匹配，挑认可的点 ⭐ 加入人群池，再回 step 4。
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">输入</CardTitle>
                <CardDescription>
                  从已收藏人群池选 1 个 → 翻译成巨量云图 8 大维度可勾选标签 + P 优先级 + 引用理由 + 预算两阶段 + A/B 矩阵。flash 模型，约 30-60s。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    选 1 个 audience_record（来自已收藏池）
                  </label>
                  {!poolRecords && (
                    <div className="text-xs text-muted-foreground p-3 border border-dashed rounded">
                      先点上方"加载人群池"拉候选。
                    </div>
                  )}
                  {poolRecords && poolRecords.length > 0 && (
                    <select
                      className="w-full border rounded px-2 py-2 text-sm bg-background"
                      value={record4Id}
                      onChange={e => selectRecord4(e.target.value)}
                    >
                      <option value="">— 请选择 —</option>
                      {poolRecords.map(r => (
                        <option key={r.id || r.ordinal} value={r.id || ''}>
                          #{r.ordinal} {r.name} · {(r.layer_tags || []).slice(0, 3).join('/')}
                        </option>
                      ))}
                    </select>
                  )}
                  {loadingRecord4 && (
                    <div className="text-xs text-muted-foreground mt-1">
                      <Loader2 className="w-3 h-3 inline animate-spin mr-1" />加载选中人群详情...
                    </div>
                  )}
                </div>

                {record4Detail && (
                  <div className="border rounded p-3 bg-muted/30 text-xs space-y-2">
                    <div>
                      <span className="font-medium">人群：</span>{record4Detail.name}
                    </div>
                    {record4Detail.kb_doc && (
                      <div>
                        <span className="font-medium">KB 来源：</span>
                        <span className="text-muted-foreground">{record4Detail.kb_doc}</span>
                      </div>
                    )}
                    <div className="flex gap-1 flex-wrap">
                      {(record4Detail.layer_tags || []).map((t, i) => (
                        <Badge key={i} variant="outline" className="text-[10px]">{t}</Badge>
                      ))}
                    </div>
                    <div>
                      <span className="font-medium">5 条匹配理由：</span>
                      <ol className="mt-1 list-decimal list-inside text-muted-foreground space-y-1">
                        {(record4Detail.match_reasons || []).slice(0, 5).map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ol>
                    </div>
                    <button
                      className="text-xs flex items-center gap-1"
                      onClick={() => setShowRecord4Detail(s => !s)}
                    >
                      {showRecord4Detail ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      展开 KB chunk 原文
                    </button>
                    {showRecord4Detail && (
                      <pre className="mt-2 p-2 bg-background border rounded text-[10px] max-h-60 overflow-auto whitespace-pre-wrap">
                        {record4Detail.kb_chunk_text || '（KB chunk 缺失）'}
                      </pre>
                    )}
                  </div>
                )}

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    额外要求（extra_context）
                  </label>
                  <Textarea
                    placeholder="（可空）例：「测试期预算紧，最多 ¥800/天」「主推送礼场景」「这版圈包要避开同行已饱和标签」"
                    value={extraContext4}
                    onChange={e => setExtraContext4(e.target.value)}
                    rows={2}
                    className="text-sm"
                  />
                </div>

                <Button
                  onClick={runStep4}
                  disabled={running4 || !record4Id}
                  className="w-full"
                >
                  {running4 ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（约 30-60s）</> : '跑圈包 SOP'}
                </Button>

                {error && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">输出</CardTitle>
                  {resp4?.trace && (
                    <CardDescription className="text-xs">
                      {resp4.trace.model_provider}/{resp4.trace.model} · {resp4.trace.cost_estimate}
                    </CardDescription>
                  )}
                </div>
                {resp4?.result?.pack_md && (
                  <div className="space-x-1">
                    <Button size="sm" variant="outline" onClick={() => copyText(resp4.result?.pack_md)}>
                      <Copy className="w-3 h-3 mr-1" /> 复制
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => downloadMd(resp4.result?.pack_md, `${skuId}_audience-pack_${(resp4.result?.audience_pack_id || '').slice(0, 8)}.md`)}>
                      <Download className="w-3 h-3 mr-1" /> 下载 .md
                    </Button>
                  </div>
                )}
              </CardHeader>
              <CardContent>
                {!resp4 && !running4 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左边选 1 个人群后点"跑圈包 SOP"，结果会显示在这里。
                  </div>
                )}
                {running4 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                    LLM 翻译人群 → 巨量云图 8 大维度标签清单 + 预算 + A/B 矩阵...
                  </div>
                )}
                {resp4?.result?.pack_md && (
                  <>
                    {resp4.result.audience_pack_id && (
                      <div className="mb-4 p-3 border rounded bg-blue-50/40 dark:bg-blue-950/20 text-xs">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge variant="outline">已落库</Badge>
                          <span>
                            audience_pack_id: <code className="text-[10px]">{resp4.result.audience_pack_id.slice(0, 8)}…</code>
                          </span>
                          <span className="ml-2 text-muted-foreground">
                            ← record_id: <code className="text-[10px]">{resp4.result.audience_record_id.slice(0, 8)}…</code>
                          </span>
                        </div>
                        <div className="text-muted-foreground mt-1">
                          step 5/6 脚本会自动挂这个 audience_pack_id（人群 + 圈包 + 卖点全链路）。
                        </div>
                      </div>
                    )}

                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {resp4.result.pack_md}
                      </ReactMarkdown>
                    </div>

                    {resp4.trace?.final_prompt && (
                      <div className="mt-6 border-t pt-4">
                        <button
                          className="text-sm font-medium flex items-center gap-1"
                          onClick={() => setShowPrompt4(s => !s)}
                        >
                          {showPrompt4 ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          Final Prompt（含 KB 原文 + matrix）
                        </button>
                        {showPrompt4 && (
                          <pre className="mt-2 p-3 bg-muted text-xs rounded max-h-96 overflow-auto whitespace-pre-wrap">
                            {resp4.trace.final_prompt}
                          </pre>
                        )}
                      </div>
                    )}
                  </>
                )}
                {resp4 && !resp4.ok && (
                  <div className="text-sm text-red-500">
                    <div>Error: {resp4.error}</div>
                    {resp4.hint && <div className="text-xs text-muted-foreground mt-1">{resp4.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Step 4 配套：500 词关键词扩展（phase B+） */}
          {resp4?.result?.pack_md && (
            <Card className="mt-4 border-dashed">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  🔑 500 词关键词扩展（云图数据工厂关键词夹用）
                </CardTitle>
                <CardDescription className="text-xs">
                  上面 step 4 第 4 部分的种子词已自动预填到下方（可改）。点"跑扩展" → 出 N 个一行一词无标点的纯文本，下载 .txt 后导入「云图 → 数据工厂 → 关键词夹 → 新建关键词包」。再到标签工厂转成人群标签 → 回自定义人群引用 → 推千川。<strong>不是直接进千川计划关键词定向</strong>。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="md:col-span-2">
                    <label className="text-sm font-medium mb-1 block">
                      种子关键词（每行 1 个；自动从 step 4 第 4 部分预填，可改）
                    </label>
                    <Textarea
                      placeholder="例：&#10;有机酱油&#10;无糖生抽&#10;赛博朋克&#10;寿喜锅底料&#10;减脂餐调味"
                      value={seedKw}
                      onChange={e => setSeedKw(e.target.value)}
                      rows={6}
                      className="text-sm font-mono"
                    />
                    <div className="text-xs text-muted-foreground mt-1">
                      {seedKw.split(/\n/).filter(s => s.trim()).length} 个种子词
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <label className="text-sm font-medium mb-1 block">
                        目标词数
                      </label>
                      <select
                        className="w-full border rounded px-2 py-2 text-sm bg-background"
                        value={targetCountKw}
                        onChange={e => setTargetCountKw(parseInt(e.target.value, 10))}
                      >
                        <option value={100}>100 词（快测）</option>
                        <option value={300}>300 词</option>
                        <option value={500}>500 词（推荐）</option>
                        <option value={1000}>1000 词（最大）</option>
                      </select>
                    </div>
                    <div className="text-xs text-muted-foreground space-y-1 p-2 bg-muted/30 rounded">
                      <div>挂上下文：</div>
                      <div>• SKU: <code className="text-[10px]">{skuId || '—'}</code></div>
                      <div>• audience_record: <code className="text-[10px]">{(resp4.result?.audience_record_id || record4Id || '—').slice(0, 8)}…</code></div>
                      <div>• audience_pack: <code className="text-[10px]">{(resp4.result?.audience_pack_id || '—').slice(0, 8)}…</code></div>
                    </div>
                    <Button
                      onClick={runKeywordPack}
                      disabled={runningKw || !seedKw.trim()}
                      className="w-full"
                    >
                      {runningKw ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中（约 30-60s）</> : `跑 ${targetCountKw} 词扩展`}
                    </Button>
                  </div>
                </div>

                {respKw?.result?.keyword_text && (
                  <div className="border rounded p-3 bg-emerald-50/30 dark:bg-emerald-950/20 space-y-2">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2 text-xs">
                        <Badge variant="outline">已落库</Badge>
                        <span>
                          实际清洗后 <strong>{respKw.result.keyword_count}</strong> 词 / 目标 {respKw.result.target_count}
                        </span>
                        {respKw.result.keyword_pack_id && (
                          <span className="text-muted-foreground">
                            keyword_pack_id: <code className="text-[10px]">{respKw.result.keyword_pack_id.slice(0, 8)}…</code>
                          </span>
                        )}
                      </div>
                      <div className="space-x-1">
                        <Button size="sm" variant="outline" onClick={copyKeywordText}>
                          <Copy className="w-3 h-3 mr-1" /> {copiedKw ? '✓ 已复制' : '复制全部'}
                        </Button>
                        <Button size="sm" variant="default" onClick={downloadKeywordTxt}>
                          <Download className="w-3 h-3 mr-1" /> 下载 .txt
                        </Button>
                      </div>
                    </div>

                    {(respKw.result.warnings || []).length > 0 && (
                      <div className="text-xs text-amber-700 dark:text-amber-400 p-2 border border-amber-200 dark:border-amber-900 rounded bg-amber-50 dark:bg-amber-950/40">
                        ⚠ {respKw.result.warnings.join(' · ')}
                      </div>
                    )}

                    <Textarea
                      value={respKw.result.keyword_text}
                      readOnly
                      rows={14}
                      className="text-xs font-mono bg-background"
                      onClick={e => (e.target as HTMLTextAreaElement).select()}
                    />
                    <div className="text-[11px] text-muted-foreground">
                      格式：每行 1 词、无标点、无数字、长度 2-15 字。下载后用记事本打开，全选复制 → 导入「云图 → 数据工厂 → 关键词夹 → 新建关键词包」。
                    </div>
                  </div>
                )}

                {runningKw && !respKw && (
                  <div className="text-sm text-muted-foreground py-6 text-center">
                    <Loader2 className="w-5 h-5 mx-auto animate-spin mb-2" />
                    LLM 扩词 → 后处理清洗（去标点 / 去数字 / 去重 / 长度过滤）...
                  </div>
                )}

                {respKw && !respKw.ok && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    Error: {respKw.error}
                    {respKw.hint && <div className="text-xs mt-1">{respKw.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
