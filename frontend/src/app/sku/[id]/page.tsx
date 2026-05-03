'use client'

import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useEffect, useState, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Package, ArrowLeft, Plus, Sparkles, TrendingUp, History, Bot,
  CheckCircle2, XCircle, Clock, Loader2, Brain, User, Store, Cloud,
  Wand2, Film, Edit3, Save, RefreshCw, ChevronRight, AlertCircle,
} from 'lucide-react'
import {
  ComposedChart, Line, XAxis, YAxis, Tooltip,
  ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts'
import { ChangeEventForm } from '@/components/change-event-form'
import { VideoFeedbackButton } from '@/components/video-feedback-button'

// ── Types ──────────────────────────────────────────────────────────────────────

interface SkuDetail {
  id: string
  name: string
  category: string | null
  douyin_product_id: string
  status: string
  platform_status: string | null
  growth_class: string | null
  in_focus_pool: boolean
  focus_reason: string | null
  locked_by_user: boolean
  total_stock: number | null
  available_stock: number | null
  updated_at: string
  owner_selling_points?: Array<{ text: string; category?: string; priority?: number }> | null
  owner_notes?: string | null
  price_min?: number | null
  price_max?: number | null
  specifications?: string | null
}

interface Metric {
  date: string
  metric_name: string
  value: number
  source_runbook: string | null
}

interface ChangeEvent {
  id: number
  sku_id: string | null
  asset_type: string
  action_type: string | null
  action_subtype: string | null
  change_description: string
  executed_at: string
  source: string
  merge_status: string
  verification_status: string
  screenshot_path: string | null
  notes: string | null
}

interface Decision {
  id: number
  title: string
  summary: string | null
  status: string
  source_module: string
  created_at: string
}

interface Anomaly {
  id: number
  sku_id: string
  severity: string
  metric_name: string | null
  description: string | null
  detected_at: string
  handled: boolean
}

interface Asset5A {
  date: string
  o_count: number | null
  a1_aware: number | null
  a2_appeal: number | null
  a3_ask: number | null
  a4_act: number | null
  a5_advocate: number | null
  a1_outperform_pct: number | null
  a2_outperform_pct: number | null
  a3_outperform_pct: number | null
  a4_outperform_pct: number | null
  a5_outperform_pct: number | null
}

interface BrandMind {
  date: string
  brand_assoc_count: number | null
  industry_share: number | null
  industry_rank: number | null
  reputation: number | null
  preference: number | null
}

type TabKey = 'overview' | 'actions' | 'diagnosis' | 'content'

const KEY_METRICS = ['gmv_paid', 'uv', 'ctr', 'cvr']
const METRIC_LABELS: Record<string, string> = {
  gmv_paid: 'GMV',
  uv: '访客数',
  ctr: '点击率',
  cvr: '转化率',
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function SkuDetailPage() {
  const params = useParams<{ id: string }>()
  const skuId = params?.id ?? ''
  const [tab, setTab] = useState<TabKey>('overview')
  const [sku, setSku] = useState<SkuDetail | null>(null)
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [events, setEvents] = useState<ChangeEvent[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [assets5a, setAssets5a] = useState<Asset5A[]>([])
  const [brandMind, setBrandMind] = useState<BrandMind[]>([])
  const [anomalies, setAnomalies] = useState<Anomaly[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!skuId) return
    Promise.all([
      fetch(`/api/omni/scout/skus/${skuId}`).then((r) => r.ok ? r.json() : null),
      fetch(`/api/omni/scout/skus/${skuId}/metrics?days=14&metric_names=${KEY_METRICS.join(',')}`).then((r) => r.ok ? r.json() : []),
      fetch(`/api/omni/scout/change-events?sku_id=${skuId}`).then((r) => r.ok ? r.json() : []),
      fetch(`/api/omni/scout/decisions?sku_id=${skuId}`).then((r) => r.ok ? r.json() : []),
      fetch(`/api/omni/scout/skus/${skuId}/5a?days=7`).then((r) => r.ok ? r.json() : []),
      fetch(`/api/omni/scout/skus/${skuId}/brand-mind?days=7`).then((r) => r.ok ? r.json() : []),
      fetch(`/api/omni/scout/anomalies?sku_id=${skuId}&unhandled_only=true&limit=5`).then((r) => r.ok ? r.json() : []),
    ]).then(([s, m, e, d, fa, bm, an]) => {
      setSku(s)
      setMetrics(m)
      setEvents(e)
      setDecisions(d)
      setAssets5a(fa)
      setBrandMind(bm)
      setAnomalies(an)
    }).finally(() => setLoading(false))
  }, [skuId])

  const TABS: { key: TabKey; label: string; icon: React.ComponentType<{ className?: string }>; count?: number }[] = [
    { key: 'overview', label: '概览', icon: TrendingUp },
    { key: 'actions', label: '动作', icon: History, count: events.length },
    { key: 'diagnosis', label: 'AI 诊断', icon: Bot, count: decisions.length },
    { key: 'content', label: '内容工作台', icon: Film },
  ]

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto">
      <Link
        href="/products"
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-600 mb-4"
      >
        <ArrowLeft className="w-4 h-4" /> 返回产品列表
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center text-white shadow">
              <Package className="w-5 h-5" />
            </div>
            <div>
              <div className="font-mono text-xs text-gray-400">{skuId}</div>
              <h1 className="text-xl font-bold text-gray-900">
                {loading ? '加载中…' : (sku?.name ?? skuId)}
              </h1>
            </div>
          </div>
          {sku && (
            <div className="flex items-center gap-2 ml-13 flex-wrap">
              {sku.in_focus_pool && (
                <Badge variant="outline" className="text-[10px] bg-amber-50 text-amber-700 border-amber-200">
                  重点池 · {sku.focus_reason}
                </Badge>
              )}
              {sku.growth_class && (
                <Badge variant="outline" className="text-[10px]">
                  {sku.growth_class}
                </Badge>
              )}
              {sku.available_stock != null && (
                <span className="text-xs text-gray-500">库存 {sku.available_stock.toLocaleString()}</span>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <Link href={`/chat?sku_id=${skuId}`}>
            <Button size="sm" variant="outline" className="gap-1">
              <Brain className="w-4 h-4" />
              在 AI 问答里讨论本 SKU
            </Button>
          </Link>
          <LogEventButton skuId={skuId} skuName={sku?.name} onSaved={() => {
            fetch(`/api/omni/scout/change-events?sku_id=${skuId}`).then(r => r.ok ? r.json() : []).then(setEvents)
          }} />
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 mb-6">
        <div className="flex gap-1">
          {TABS.map((t) => {
            const Icon = t.icon
            const active = tab === t.key
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  active ? 'border-violet-600 text-violet-700' : 'border-transparent text-gray-500 hover:text-gray-900'
                }`}
              >
                <Icon className="w-4 h-4" />
                {t.label}
                {(t.count ?? 0) > 0 && (
                  <Badge variant="secondary" className="ml-1 text-[10px] h-4 px-1.5">
                    {t.count}
                  </Badge>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {tab === 'overview' && <OverviewTab metrics={metrics} loading={loading} sku={sku} assets5a={assets5a} brandMind={brandMind} events={events} anomalies={anomalies} skuId={skuId} onSkuRefresh={(s) => setSku(s)} />}
      {tab === 'actions' && <ActionsTab events={events} loading={loading} />}
      {tab === 'diagnosis' && <DiagnosisTab decisions={decisions} loading={loading} skuId={skuId} onJumpToContent={() => setTab('content')} />}
      {tab === 'content' && <ContentTab skuId={skuId} />}
    </div>
  )
}

// ── Overview Tab ───────────────────────────────────────────────────────────────

function OverviewTab({ metrics, loading, sku, assets5a, brandMind, events, anomalies, skuId, onSkuRefresh }: {
  metrics: Metric[]
  loading: boolean
  sku: SkuDetail | null
  assets5a: Asset5A[]
  brandMind: BrandMind[]
  events: ChangeEvent[]
  anomalies: Anomaly[]
  skuId: string
  onSkuRefresh: (s: SkuDetail) => void
}) {
  const [visibleLines, setVisibleLines] = useState<Record<string, boolean>>({
    gmv_paid: true, uv: true, ctr: true, cvr: true,
  })

  const byMetric = useMemo(() => {
    const map: Record<string, Metric[]> = {}
    for (const m of metrics) {
      if (!map[m.metric_name]) map[m.metric_name] = []
      map[m.metric_name].push(m)
    }
    return map
  }, [metrics])

  if (loading) return <LoadingCard />

  const latest5a = assets5a[0]
  const latestMind = brandMind[0]
  const sorted5a = [...assets5a].sort((a, b) => a.date.localeCompare(b.date))

  const A_STAGES: { key: keyof Asset5A; label: string; outKey: keyof Asset5A | null; bg: string; bgDim: string; text: string }[] = [
    { key: 'o_count',     label: 'O',  outKey: null,                 bg: 'bg-gray-400',   bgDim: 'bg-gray-200',   text: 'text-gray-600'   },
    { key: 'a1_aware',    label: 'A1', outKey: 'a1_outperform_pct', bg: 'bg-blue-400',   bgDim: 'bg-blue-200',   text: 'text-blue-600'   },
    { key: 'a2_appeal',   label: 'A2', outKey: 'a2_outperform_pct', bg: 'bg-cyan-400',   bgDim: 'bg-cyan-200',   text: 'text-cyan-600'   },
    { key: 'a3_ask',      label: 'A3', outKey: 'a3_outperform_pct', bg: 'bg-violet-400', bgDim: 'bg-violet-200', text: 'text-violet-600' },
    { key: 'a4_act',      label: 'A4', outKey: 'a4_outperform_pct', bg: 'bg-amber-400',  bgDim: 'bg-amber-200',  text: 'text-amber-600'  },
    { key: 'a5_advocate', label: 'A5', outKey: 'a5_outperform_pct', bg: 'bg-rose-400',   bgDim: 'bg-rose-200',   text: 'text-rose-600'   },
  ]

  return (
    <div className="space-y-5">
      {/* 老板视角输入：卖点 / 规格 / 价格 / 备注（编排器的种子素材） */}
      <OwnerSellingPointsEditor skuId={skuId} sku={sku} onSaved={onSkuRefresh} />

      {/* Z3: 抖店后台 SKU 主数据 */}
      {sku && (sku.platform_status || sku.total_stock != null || sku.growth_class) && (
        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-medium text-gray-500 mb-3 flex items-center gap-1.5">
              <Store className="w-3.5 h-3.5" /> 抖店主数据
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {sku.platform_status && (
                <div className="text-center p-2 rounded-lg bg-gray-50">
                  <div className="text-xs text-gray-400 mb-0.5">上架状态</div>
                  <div className="text-sm font-semibold text-gray-900">{sku.platform_status}</div>
                </div>
              )}
              {sku.total_stock != null && (
                <div className="text-center p-2 rounded-lg bg-gray-50">
                  <div className="text-xs text-gray-400 mb-0.5">总库存</div>
                  <div className="text-sm font-semibold text-gray-900">{sku.total_stock.toLocaleString()}</div>
                </div>
              )}
              {sku.available_stock != null && (
                <div className="text-center p-2 rounded-lg bg-gray-50">
                  <div className="text-xs text-gray-400 mb-0.5">可售库存</div>
                  <div className={`text-sm font-semibold ${sku.available_stock < 10 ? 'text-rose-600' : 'text-gray-900'}`}>
                    {sku.available_stock.toLocaleString()}
                  </div>
                </div>
              )}
              {sku.growth_class && (
                <div className="text-center p-2 rounded-lg bg-gray-50">
                  <div className="text-xs text-gray-400 mb-0.5">成长分级</div>
                  <div className="text-sm font-semibold text-violet-700">{sku.growth_class}</div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Z1: SPU 5A 心电图 */}
      {latest5a ? (
        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-medium text-gray-500 mb-3 flex items-center gap-1.5">
              <Brain className="w-3.5 h-3.5" /> SPU 5A 资产
              <span className="text-[10px] text-gray-400 ml-1">{latest5a.date}</span>
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              {A_STAGES.map((s) => {
                const val = latest5a[s.key] as number | null
                const history = sorted5a.map((r) => (r[s.key] as number | null) ?? 0)
                const maxH = Math.max(...history, 1)
                const outpct = s.outKey ? (latest5a[s.outKey] as number | null) : null
                const fmtVal = val != null ? (val >= 10000 ? `${(val / 10000).toFixed(1)}w` : val.toLocaleString()) : '—'
                return (
                  <div key={s.key} className="rounded-lg border border-gray-100 p-2 bg-gray-50">
                    <div className={`text-[10px] font-bold mb-0.5 ${s.text}`}>{s.label}</div>
                    <div className="text-sm font-bold text-gray-900">{fmtVal}</div>
                    {outpct != null && (
                      <div className={`text-[9px] font-mono ${outpct >= 0 ? 'text-emerald-600' : 'text-rose-500'}`}>
                        {outpct >= 0 ? '+' : ''}{(outpct * 100).toFixed(0)}%
                      </div>
                    )}
                    <div className="flex items-end gap-0.5 h-4 mt-1">
                      {history.map((v, i) => (
                        <div key={i} className={`flex-1 rounded-t-sm ${i === history.length - 1 ? s.bg : s.bgDim}`}
                          style={{ height: `${Math.max(2, Math.round((v / maxH) * 16))}px` }} />
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
            {latest5a.a1_outperform_pct != null && (
              <div className="mt-3 text-[10px] text-gray-400 text-right">
                百分位 vs 同行：A1 {((latest5a.a1_outperform_pct ?? 0) * 100).toFixed(0)}% ·
                A4 {((latest5a.a4_outperform_pct ?? 0) * 100).toFixed(0)}% ·
                A5 {((latest5a.a5_outperform_pct ?? 0) * 100).toFixed(0)}%
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-4 text-center text-sm text-gray-400">
            <Brain className="w-6 h-6 mx-auto text-gray-300 mb-1.5" />
            运行「yuntu/spu-5a」Runbook 后 SPU 5A 数据会显示在这里
          </CardContent>
        </Card>
      )}

      {/* Z2: 商品级品牌心智 */}
      {latestMind && (latestMind.brand_assoc_count != null || latestMind.reputation != null) ? (
        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-medium text-gray-500 mb-3 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5" /> 品牌心智
              <span className="text-[10px] text-gray-400 ml-1">{latestMind.date}</span>
            </div>
            <div className="grid grid-cols-3 gap-3">
              {latestMind.brand_assoc_count != null && (
                <div className="text-center p-2 rounded-lg bg-purple-50">
                  <div className="text-xs text-gray-400 mb-0.5">联想量</div>
                  <div className="text-lg font-bold text-purple-800">
                    {latestMind.brand_assoc_count >= 10000
                      ? `${(latestMind.brand_assoc_count / 10000).toFixed(1)}w`
                      : latestMind.brand_assoc_count.toLocaleString()}
                  </div>
                  {latestMind.industry_rank != null && (
                    <div className="text-[10px] text-gray-400">行业 #{latestMind.industry_rank}</div>
                  )}
                </div>
              )}
              {latestMind.reputation != null && (
                <div className="text-center p-2 rounded-lg bg-emerald-50">
                  <div className="text-xs text-gray-400 mb-0.5">美誉度</div>
                  <div className="text-lg font-bold text-emerald-800">
                    {(latestMind.reputation * 100).toFixed(1)}%
                  </div>
                </div>
              )}
              {latestMind.preference != null && (
                <div className="text-center p-2 rounded-lg bg-amber-50">
                  <div className="text-xs text-gray-400 mb-0.5">偏爱度</div>
                  <div className="text-lg font-bold text-amber-800">
                    {(latestMind.preference * 100).toFixed(1)}%
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* V06-5: 4-window metric summary cards */}
      {Object.keys(byMetric).length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {KEY_METRICS.filter((m) => byMetric[m]).map((metricName) => {
            const rows = [...byMetric[metricName]].sort((a, b) => a.date.localeCompare(b.date))
            const latest = rows[rows.length - 1]
            const prev = rows[rows.length - 2]
            const last7 = rows.slice(-7)
            const last14 = rows.slice(-14)
            const avg7 = last7.length ? last7.reduce((s, r) => s + r.value, 0) / last7.length : null
            const avg14 = last14.length ? last14.reduce((s, r) => s + r.value, 0) / last14.length : null
            const delta = prev ? (latest.value - prev.value) / Math.abs(prev.value) : null
            const isPct = ['ctr', 'cvr'].includes(metricName)
            const fmt = (v: number) =>
              isPct ? `${(v * 100).toFixed(2)}%`
              : metricName === 'gmv_paid' ? `¥${v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
              : v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
            return (
              <Card key={metricName}>
                <CardContent className="p-3">
                  <div className="text-[10px] text-gray-400 mb-1">{METRIC_LABELS[metricName] ?? metricName}</div>
                  <div className="text-lg font-bold text-gray-900 mb-2">{fmt(latest.value)}</div>
                  <div className="space-y-1">
                    <div className="flex justify-between text-[10px]">
                      <span className="text-gray-400">7日均</span>
                      <span className="text-gray-700">{avg7 != null ? fmt(avg7) : '—'}</span>
                    </div>
                    <div className="flex justify-between text-[10px]">
                      <span className="text-gray-400">14日均</span>
                      <span className="text-gray-700">{avg14 != null ? fmt(avg14) : '—'}</span>
                    </div>
                    <div className="flex justify-between text-[10px]">
                      <span className="text-gray-400">环比</span>
                      <span className={delta != null ? (delta >= 0 ? 'text-emerald-600' : 'text-rose-600') : 'text-gray-400'}>
                        {delta != null ? `${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(1)}%` : '—'}
                      </span>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* V06-6: Anomaly events list */}
      {anomalies.length > 0 && (
        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-medium text-gray-500 mb-3 flex items-center gap-1.5">
              <span className="text-rose-500">⚠</span> 未处理异动（{anomalies.length}）
            </div>
            <div className="space-y-2">
              {anomalies.map((a) => {
                const sev = a.severity === 'urgent' ? 'text-rose-600 bg-rose-50 border-rose-200'
                  : a.severity === 'positive' ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
                  : 'text-amber-700 bg-amber-50 border-amber-200'
                const icon = a.severity === 'urgent' ? '🔴' : a.severity === 'positive' ? '🟢' : '🟡'
                return (
                  <div key={a.id} className={`rounded-lg border px-3 py-2 text-xs ${sev}`}>
                    <span className="mr-1">{icon}</span>
                    {a.description ?? a.metric_name}
                    <span className="ml-2 text-[10px] opacity-60">
                      {new Date(a.detected_at).toLocaleDateString('zh-CN')}
                    </span>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* GMV/UV/CTR/CVR 14-day trend chart */}
      {Object.keys(byMetric).length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center text-sm text-gray-500">
            <TrendingUp className="w-10 h-10 mx-auto text-gray-300 mb-3" />
            <p className="mb-2">暂无指标数据</p>
            <p className="text-xs text-gray-400">
              运行「B-SKU详情」Runbook 后，14 天 GMV/UV/CTR/CVR 趋势会显示在这里
            </p>
          </CardContent>
        </Card>
      ) : (
        <MetricTrendChart
          byMetric={byMetric}
          events={events}
          visibleLines={visibleLines}
          onToggleLine={(k) => setVisibleLines((prev) => ({ ...prev, [k]: !prev[k] }))}
        />
      )}
    </div>
  )
}

const LINE_CFG: { key: string; label: string; color: string; yAxisId: string }[] = [
  { key: 'gmv_paid', label: 'GMV',   color: '#7c3aed', yAxisId: 'gmv' },
  { key: 'uv',       label: '访客数', color: '#0ea5e9', yAxisId: 'uv'  },
  { key: 'ctr',      label: '点击率', color: '#f59e0b', yAxisId: 'pct' },
  { key: 'cvr',      label: '转化率', color: '#10b981', yAxisId: 'pct' },
]

function MetricTrendChart({
  byMetric,
  events,
  visibleLines,
  onToggleLine,
}: {
  byMetric: Record<string, Metric[]>
  events: ChangeEvent[]
  visibleLines: Record<string, boolean>
  onToggleLine: (k: string) => void
}) {
  const allDates = useMemo(() => {
    const dates = new Set<string>()
    for (const rows of Object.values(byMetric)) {
      for (const r of rows) dates.add(r.date)
    }
    return Array.from(dates).sort().slice(-14)
  }, [byMetric])

  const chartData = useMemo(() => allDates.map((date) => {
    const pt: Record<string, number | string> = { date: date.slice(5) }
    for (const { key } of LINE_CFG) {
      const row = byMetric[key]?.find((r) => r.date === date)
      if (row) pt[key] = row.value
    }
    return pt
  }), [allDates, byMetric])

  const eventDates = useMemo(() => {
    const dateSet = new Set(allDates)
    return events
      .map((e) => e.executed_at.slice(0, 10))
      .filter((d) => dateSet.has(d))
  }, [events, allDates])

  const eventByDate = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const e of events) {
      const d = e.executed_at.slice(0, 10)
      if (!map[d]) map[d] = []
      map[d].push(e.change_description.slice(0, 40))
    }
    return map
  }, [events])

  const fmtGmv = (v: number) => v >= 10000 ? `${(v / 10000).toFixed(1)}w` : `${v}`
  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs font-medium text-gray-500 flex items-center gap-1.5">
            <TrendingUp className="w-3.5 h-3.5" /> 14 天趋势
          </div>
          <div className="flex gap-2">
            {LINE_CFG.map(({ key, label, color }) => (
              <button
                key={key}
                onClick={() => onToggleLine(key)}
                className={`text-[10px] px-2 py-0.5 rounded-full border transition-all ${
                  visibleLines[key]
                    ? 'border-transparent text-white font-medium'
                    : 'border-gray-200 text-gray-400 bg-white'
                }`}
                style={visibleLines[key] ? { backgroundColor: color } : {}}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="date" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
            <YAxis yAxisId="gmv" orientation="left" tickFormatter={fmtGmv} tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={40} />
            <YAxis yAxisId="uv"  orientation="left" hide />
            <YAxis yAxisId="pct" orientation="right" tickFormatter={fmtPct} tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={36} />
            <Tooltip
              contentStyle={{ fontSize: 11, borderRadius: 8 }}
              formatter={(value, name) => {
                const num = typeof value === 'number' ? value : Number(value)
                const key = String(name)
                const cfg = LINE_CFG.find((l) => l.key === key)
                if (!cfg) return [String(num), key]
                if (key === 'gmv_paid') return [`¥${num.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`, 'GMV']
                if (['ctr', 'cvr'].includes(key)) return [`${(num * 100).toFixed(2)}%`, cfg.label]
                return [num.toLocaleString('zh-CN'), cfg.label]
              }}
              labelFormatter={(label) => {
                const lbl = String(label ?? '')
                const full = allDates.find((d) => d.slice(5) === lbl) ?? lbl
                const descs = eventByDate[full]
                return descs ? `${lbl} ✏️ ${descs.join(' / ')}` : lbl
              }}
            />
            {Array.from(new Set(eventDates)).map((d) => (
              <ReferenceLine
                key={d}
                x={d.slice(5)}
                yAxisId="gmv"
                stroke="#a78bfa"
                strokeDasharray="3 3"
                strokeWidth={1.5}
                label={{ value: '✏', position: 'top', fontSize: 10 }}
              />
            ))}
            {LINE_CFG.map(({ key, color, yAxisId }) =>
              visibleLines[key] ? (
                <Line
                  key={key}
                  yAxisId={yAxisId}
                  dataKey={key}
                  stroke={color}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                  connectNulls
                />
              ) : null
            )}
          </ComposedChart>
        </ResponsiveContainer>
        {eventDates.length > 0 && (
          <div className="mt-2 text-[10px] text-violet-500 text-right">
            竖线 = 动作变更节点，悬停查看描述
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Actions Tab ────────────────────────────────────────────────────────────────

function ActionsTab({ events, loading }: { events: ChangeEvent[]; loading: boolean }) {
  if (loading) return <LoadingCard />

  if (events.length === 0) {
    return (
      <Card>
        <CardContent className="p-12 text-center text-sm text-gray-500">
          <History className="w-10 h-10 mx-auto text-gray-300 mb-3" />
          <p className="mb-2">暂无动作记录</p>
          <p className="text-xs text-gray-400">
            点击「登记动作」记录你对这个 SKU 做的每一个改动，7 天后系统自动验证效果
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      {events.map((e) => (
        <ActionEventCard key={e.id} event={e} />
      ))}
    </div>
  )
}

interface VerificationResult {
  verdict: string
  kpi_deltas: Record<string, { pre: number; post: number; delta_pct: number }>
  summary: string
  verified_at: string
}

function ActionEventCard({ event: e }: { event: ChangeEvent }) {
  const [expanded, setExpanded] = useState(false)
  const [verification, setVerification] = useState<VerificationResult | null>(null)
  const [loadingVerify, setLoadingVerify] = useState(false)

  async function loadVerification() {
    if (verification || loadingVerify) return
    setLoadingVerify(true)
    try {
      const res = await fetch(`/api/omni/scout/change-events/${e.id}/verification`)
      if (res.ok) setVerification(await res.json())
    } finally {
      setLoadingVerify(false)
    }
  }

  const canExpand = e.verification_status === 'completed'

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-2 gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="outline" className="text-[10px]">{e.asset_type}</Badge>
            {e.action_type && <Badge variant="outline" className="text-[10px] bg-gray-50">{e.action_type}</Badge>}
            <VerificationBadge status={e.verification_status} />
            <SourceIcon source={e.source} />
          </div>
          <span className="text-[10px] text-gray-400 shrink-0">
            {new Date(e.executed_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>
        <div className="text-sm text-gray-800 mb-1">{e.change_description}</div>
        {e.notes && <div className="text-xs text-gray-500 mb-2">{e.notes}</div>}
        {e.screenshot_path && (
          <a href={e.screenshot_path} target="_blank" rel="noopener noreferrer" className="inline-block mt-1 mb-2">
            <img
              src={e.screenshot_path}
              alt="screenshot"
              className="h-10 rounded border border-gray-200 object-cover hover:opacity-80 transition-opacity"
            />
          </a>
        )}

        {canExpand && (
          <button
            className="text-xs text-violet-600 hover:underline mt-1"
            onClick={() => { setExpanded((v) => !v); if (!expanded) loadVerification() }}
          >
            {expanded ? '收起验证结果 ▲' : '查看前后对比 ▼'}
          </button>
        )}

        {expanded && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            {loadingVerify ? (
              <Loader2 className="w-4 h-4 animate-spin text-gray-300" />
            ) : verification ? (
              <VerificationCard result={verification} />
            ) : (
              <span className="text-xs text-gray-400">验证数据暂不可用</span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

const KPI_LABELS: Record<string, string> = { gmv_paid: 'GMV', uv: '访客数', ctr: '点击率', cvr: '转化率' }

function VerificationCard({ result }: { result: VerificationResult }) {
  const verdictConfig: Record<string, { label: string; cls: string }> = {
    positive:    { label: '正向改善', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
    negative:    { label: '负向恶化', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
    neutral:     { label: '基本持平', cls: 'bg-gray-50 text-gray-600 border-gray-200' },
    inconclusive:{ label: '无法归因', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  }
  const vc = verdictConfig[result.verdict] ?? verdictConfig.neutral

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className={`text-xs ${vc.cls}`}>{vc.label}</Badge>
        <span className="text-[10px] text-gray-400">
          验证于 {new Date(result.verified_at).toLocaleDateString('zh-CN')}
        </span>
      </div>

      {/* Before / After grid */}
      <div className="grid grid-cols-4 gap-2">
        {Object.entries(result.kpi_deltas).map(([kpi, d]) => {
          const isPct = ['ctr', 'cvr'].includes(kpi)
          const fmt = (v: number) => isPct ? `${(v * 100).toFixed(2)}%` : v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
          const pct = d.delta_pct
          const color = pct >= 5 ? 'text-emerald-600' : pct <= -5 ? 'text-rose-600' : 'text-gray-500'
          return (
            <div key={kpi} className="text-center p-2 rounded-lg bg-gray-50 border border-gray-100">
              <div className="text-[10px] text-gray-500 mb-1">{KPI_LABELS[kpi] ?? kpi}</div>
              <div className="text-xs text-gray-400">{fmt(d.pre)}</div>
              <div className="text-[10px] text-gray-300">↓</div>
              <div className="text-sm font-semibold text-gray-900">{fmt(d.post)}</div>
              <div className={`text-[10px] font-mono ${color}`}>
                {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
              </div>
            </div>
          )
        })}
      </div>

      {result.summary && (
        <div className="text-xs text-gray-600 bg-gray-50 rounded-lg px-3 py-2 font-mono leading-relaxed">
          {result.summary}
        </div>
      )}
    </div>
  )
}

// ── Diagnosis Tab ──────────────────────────────────────────────────────────────

function DiagnosisTab({ decisions, loading, skuId, onJumpToContent }: {
  decisions: Decision[]
  loading: boolean
  skuId: string
  onJumpToContent: () => void
}) {
  const [items, setItems] = useState<Decision[]>(decisions)
  const [triggering, setTriggering] = useState(false)
  const [triggerDone, setTriggerDone] = useState(false)

  useEffect(() => { setItems(decisions) }, [decisions])

  async function handleTurnIntoBrief(d: Decision) {
    // 用此 AI 结论快速创建一个 SKU 内容编排，然后跳到内容工作台 Tab
    try {
      const r = await fetch('/api/omni/content-studio/sku-orchestrations', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          sku_id: skuId,
          title: `[来自AI诊断] ${d.title}`.slice(0, 100),
          target_purpose: null, // 由 LLM 推荐
        }),
      })
      if (r.ok) {
        onJumpToContent()
      }
    } catch (exc) {
      console.error('create orchestration failed', exc)
    }
  }

  async function handleAction(
    id: number,
    status: 'adopted' | 'rejected',
    title: string,
    summary: string | null,
    rejectedReason?: string,
  ) {
    let linkedEventId: number | undefined
    if (status === 'adopted') {
      const evRes = await fetch('/api/omni/scout/change-events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sku_id: skuId || null,
          asset_type: 'ad',
          change_description: `[AI采纳] ${title}`,
          notes: summary ?? undefined,
        }),
      })
      if (evRes.ok) {
        const ev = await evRes.json()
        linkedEventId = ev.id
      }
    }
    await fetch(`/api/omni/scout/decisions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status,
        rejected_reason: rejectedReason ?? null,
        linked_change_event_id: linkedEventId ?? null,
      }),
    })
    setItems((prev) => prev.map((d) => d.id === id ? { ...d, status } : d))
  }

  async function handleTrigger() {
    setTriggering(true)
    try {
      await fetch(`/api/omni/scout/runbooks/runbook-suite%2FB-sku-detail/run`, { method: 'POST' })
      setTriggerDone(true)
    } finally {
      setTriggering(false)
    }
  }

  if (loading) return <LoadingCard />

  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="p-12 text-center text-sm text-gray-500">
          <Bot className="w-10 h-10 mx-auto text-gray-300 mb-3" />
          <p className="mb-2">暂无 AI 诊断</p>
          <p className="text-xs text-gray-400 mb-4">
            触发深度诊断后，AI 分析结果将显示在这里
          </p>
          <Button
            size="sm"
            variant="outline"
            onClick={handleTrigger}
            disabled={triggering || triggerDone}
            className="text-xs"
          >
            {triggering ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Sparkles className="w-3.5 h-3.5 mr-1" />}
            {triggerDone ? '已触发，稍后刷新' : '启动深度诊断'}
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="outline"
          onClick={handleTrigger}
          disabled={triggering || triggerDone}
          className="text-xs"
        >
          {triggering ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Sparkles className="w-3.5 h-3.5 mr-1" />}
          {triggerDone ? '已触发' : '启动深度诊断'}
        </Button>
      </div>
      {items.map((d) => (
        <DecisionCard key={d.id} decision={d} onAction={handleAction} onTurnIntoBrief={handleTurnIntoBrief} />
      ))}
    </div>
  )
}

function DecisionCard({
  decision: d,
  onAction,
  onTurnIntoBrief,
}: {
  decision: Decision
  onAction: (id: number, status: 'adopted' | 'rejected', title: string, summary: string | null, rejectedReason?: string) => Promise<void>
  onTurnIntoBrief: (decision: Decision) => Promise<void>
}) {
  const [acting, setActing] = useState<string | null>(null)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [turning, setTurning] = useState(false)

  async function act(status: 'adopted' | 'rejected', reason?: string) {
    setActing(status)
    await onAction(d.id, status, d.title, d.summary, reason)
    setActing(null)
    setRejectOpen(false)
    setRejectReason('')
  }

  const isPending = d.status === 'pending'

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px]">{d.source_module}</Badge>
            <DecisionStatusBadge status={d.status} />
          </div>
          <span className="text-[10px] text-gray-400">
            {new Date(d.created_at).toLocaleDateString('zh-CN')}
          </span>
        </div>
        <div className="font-medium text-sm text-gray-900 mb-1">{d.title}</div>
        {d.summary && (
          <div className="text-xs text-gray-600 leading-relaxed line-clamp-3 mb-3">{d.summary}</div>
        )}
        {isPending && !rejectOpen && (
          <div className="flex items-center gap-2 mt-2">
            <Button
              size="sm"
              onClick={() => act('adopted')}
              disabled={!!acting}
              className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700"
            >
              {acting === 'adopted' ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3 mr-1" />}
              采纳
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setRejectOpen(true)}
              disabled={!!acting}
              className="h-7 text-xs text-rose-600 border-rose-200 hover:bg-rose-50"
            >
              <XCircle className="w-3 h-3 mr-1" /> 拒绝
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={!!acting}
              className="h-7 text-xs text-gray-400"
              onClick={() => {}}
            >
              <Clock className="w-3 h-3 mr-1" /> 延后
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={!!acting || turning}
              className="h-7 text-xs text-violet-600 hover:bg-violet-50"
              onClick={async () => {
                setTurning(true)
                try { await onTurnIntoBrief(d) } finally { setTurning(false) }
              }}
              title="把此 AI 诊断作为种子，自动生成 SKU 内容编排"
            >
              {turning ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Wand2 className="w-3 h-3 mr-1" />}
              起内容编排
            </Button>
          </div>
        )}
        {rejectOpen && (
          <div className="mt-2 space-y-2">
            <textarea
              autoFocus
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="填写一句话拒绝原因（必填）"
              rows={2}
              maxLength={100}
              className="w-full text-xs border border-rose-200 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-rose-400"
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => { setRejectOpen(false); setRejectReason('') }}
                className="h-7 text-xs"
              >
                取消
              </Button>
              <Button
                size="sm"
                onClick={() => act('rejected', rejectReason)}
                disabled={!rejectReason.trim() || !!acting}
                className="h-7 text-xs text-rose-600 border-rose-200 hover:bg-rose-50"
                variant="outline"
              >
                {acting === 'rejected' ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <XCircle className="w-3 h-3 mr-1" />}
                确认拒绝
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Log event modal (uses ChangeEventForm) ────────────────────────────────────

function LogEventButton({ skuId, skuName, onSaved }: { skuId: string; skuName?: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false)

  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Plus className="w-4 h-4 mr-1" /> 登记动作
      </Button>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-5">
        <h3 className="text-sm font-semibold text-gray-900 mb-4">登记动作</h3>
        <ChangeEventForm
          skuId={skuId}
          skuName={skuName}
          onSuccess={() => { setOpen(false); onSaved() }}
          onCancel={() => setOpen(false)}
        />
      </div>
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function SourceIcon({ source }: { source: string }) {
  if (source === 'manual') return <span title="手动登记"><User className="w-3 h-3 text-gray-400 inline" /></span>
  if (source === 'shop_admin_log') return <span title="抖店后台自动发现"><Store className="w-3 h-3 text-blue-400 inline" /></span>
  if (source === 'yuntu_log') return <span title="云图自动发现"><Cloud className="w-3 h-3 text-purple-400 inline" /></span>
  return null
}

function VerificationBadge({ status }: { status: string }) {
  if (status === 'positive') return <span title="验证：正向"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" /></span>
  if (status === 'negative') return <span title="验证：负向"><XCircle className="w-3.5 h-3.5 text-rose-500" /></span>
  if (status === 'pending') return <span title="待验证"><Clock className="w-3.5 h-3.5 text-gray-300" /></span>
  return null
}

function DecisionStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: 'bg-amber-50 text-amber-700 border-amber-200',
    adopted: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    rejected: 'bg-gray-50 text-gray-500 border-gray-200',
  }
  const labels: Record<string, string> = { pending: '待决策', adopted: '已采纳', rejected: '已拒绝' }
  return <Badge variant="outline" className={`text-[10px] ${map[status] ?? ''}`}>{labels[status] ?? status}</Badge>
}

function LoadingCard() {
  return (
    <Card>
      <CardContent className="p-12 text-center text-sm text-gray-400">
        <Loader2 className="w-8 h-8 mx-auto animate-spin text-gray-300 mb-3" />
        加载中…
      </CardContent>
    </Card>
  )
}


// ── Content Tab ────────────────────────────────────────────────────────────────
// SKU 内容工作台：内容生成全部走 chat 推进；这里只做产物索引（brief 历史 + 投放回传）

interface BriefSummary {
  id: string
  title: string | null
  sku_id: string | null
  target_purpose: string | null
  created_at: string
  status: string | null
}

interface MaterialSummary {
  id: string
  name: string
  brief_id: string | null
  pipeline_id: string | null
  cpm: number | null
  ctr: number | null
  play_3s_rate: number | null
  cost_per_result: number | null
  created_at: string
}

const PURPOSE_BADGE: Record<string, { label: string; color: string }> = {
  awareness: { label: '曝光', color: 'bg-sky-50 text-sky-700 border-sky-200' },
  planting: { label: '种草', color: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  conversion: { label: '收割', color: 'bg-rose-50 text-rose-700 border-rose-200' },
}

function ContentTab({ skuId }: { skuId: string }) {
  const [briefs, setBriefs] = useState<BriefSummary[]>([])
  const [materials, setMaterials] = useState<MaterialSummary[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!skuId) return
    setLoading(true)
    Promise.all([
      fetch(`/api/omni/content-studio/briefs?sku_id=${skuId}&limit=20`).then((r) => r.ok ? r.json() : { items: [] }).catch(() => ({ items: [] })),
      fetch(`/api/omni/ad-review/materials?sku_id=${skuId}&limit=20`).then((r) => r.ok ? r.json() : { items: [] }).catch(() => ({ items: [] })),
    ]).then(([b, m]) => {
      setBriefs(b.items || b || [])
      setMaterials(m.items || m || [])
    }).finally(() => setLoading(false))
  }, [skuId])

  return (
    <div className="space-y-4">
      {/* 1. 主入口：跳 chat */}
      <Card className="border-violet-200">
        <CardContent className="p-5 bg-gradient-to-br from-violet-50/50 to-purple-50/50">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <h3 className="text-base font-bold text-gray-900 flex items-center gap-2">
                <Brain className="w-5 h-5 text-violet-600" />
                用 AI 问答推进内容生成
              </h3>
              <p className="text-xs text-gray-700 mt-1.5">
                跟 AI 一步步讨论：<span className="text-violet-700 font-medium">卖点 → 人群 → 圈包 SOP → 画像 → 内容场景 → 短视频脚本</span>
              </p>
              <p className="text-[11px] text-gray-500 mt-1">
                关键 AI 回复底部点 <span className="font-medium text-violet-700">「应用为 Brief」</span> 即可沉淀（自动绑当前 SKU），下方就能看到。
              </p>
            </div>
            <Link href={`/chat?sku_id=${skuId}`}>
              <Button className="gap-1.5 bg-violet-600 hover:bg-violet-700 text-white">
                去 AI 问答 <ChevronRight className="w-4 h-4" />
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>

      {/* 2. 本 SKU 的 Brief 历史 */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <Wand2 className="w-4 h-4 text-violet-600" />
              本 SKU 的 Brief 历史
              {briefs.length > 0 && <span className="text-[11px] text-gray-400 font-normal">（{briefs.length}）</span>}
            </h3>
          </div>
          {loading ? (
            <div className="text-center text-xs text-gray-400 py-6">加载中…</div>
          ) : briefs.length === 0 ? (
            <div className="text-center py-8">
              <Wand2 className="w-8 h-8 mx-auto text-gray-200 mb-2" />
              <p className="text-xs text-gray-400 mb-1">还没有 Brief</p>
              <p className="text-[11px] text-gray-400">去 AI 问答里聊出一份，自动沉淀到这里</p>
            </div>
          ) : (
            <div className="space-y-2">
              {briefs.map((b) => <BriefRow key={b.id} brief={b} />)}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 3. 投放回传（绑 brief / sku） */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              <TrendingUp className="w-4 h-4 text-emerald-600" />
              本 SKU 的投放回传
              {materials.length > 0 && <span className="text-[11px] text-gray-400 font-normal">（{materials.length}）</span>}
            </h3>
            <Link href="/ad-review">
              <Button size="sm" variant="ghost" className="text-[11px] h-6">
                去投放复盘 <ChevronRight className="w-3 h-3" />
              </Button>
            </Link>
          </div>
          {loading ? (
            <div className="text-center text-xs text-gray-400 py-6">加载中…</div>
          ) : materials.length === 0 ? (
            <div className="text-center py-8">
              <TrendingUp className="w-8 h-8 mx-auto text-gray-200 mb-2" />
              <p className="text-xs text-gray-400 mb-1">暂无投放回传</p>
              <p className="text-[11px] text-gray-400">在投放复盘上传素材时绑定 brief，数据会聚合到这里</p>
            </div>
          ) : (
            <div className="space-y-2">
              {materials.map((m) => <MaterialRow key={m.id} material={m} />)}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function BriefRow({ brief }: { brief: BriefSummary }) {
  const purpose = brief.target_purpose ? PURPOSE_BADGE[brief.target_purpose] : null
  return (
    <div className="border border-gray-200 rounded-lg hover:border-violet-200 hover:bg-violet-50/30 transition-colors">
      <div className="flex items-center justify-between gap-3 p-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            {purpose && (
              <span className={`text-[10px] px-1.5 py-0.5 border rounded ${purpose.color}`}>{purpose.label}</span>
            )}
            <span className="text-sm font-medium text-gray-900 truncate">{brief.title || brief.id.slice(0, 8)}</span>
          </div>
          <div className="text-[11px] text-gray-400">{new Date(brief.created_at).toLocaleString('zh-CN')}</div>
        </div>
        <div className="flex gap-1.5 shrink-0 items-center">
          <VideoFeedbackButton
            nodeId="briefs.draft"
            inputRef={{ brief_id: brief.id, sku_id: brief.sku_id || undefined }}
            label="反馈"
          />
          <Link href={`/content-studio/briefs/${brief.id}`}>
            <Button size="sm" variant="ghost" className="h-7 text-[11px]">打开 Brief</Button>
          </Link>
          <Link href={`/content-studio?brief_id=${brief.id}`}>
            <Button size="sm" variant="outline" className="h-7 text-[11px]">
              <Film className="w-3 h-3 mr-1" /> 去工坊
            </Button>
          </Link>
        </div>
      </div>
    </div>
  )
}

function MaterialRow({ material }: { material: MaterialSummary }) {
  return (
    <div className="flex items-center justify-between gap-3 p-3 border border-gray-200 rounded-lg hover:border-emerald-200 hover:bg-emerald-50/30 transition-colors">
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-gray-900 truncate mb-1">{material.name}</div>
        <div className="flex items-center gap-3 text-[11px] text-gray-500 flex-wrap">
          {material.cpm != null && <span>CPM: <span className="text-gray-900 font-medium">{material.cpm.toFixed(2)}</span></span>}
          {material.ctr != null && <span>CTR: <span className="text-gray-900 font-medium">{(material.ctr * 100).toFixed(2)}%</span></span>}
          {material.play_3s_rate != null && <span>3s完播: <span className="text-gray-900 font-medium">{(material.play_3s_rate * 100).toFixed(1)}%</span></span>}
          {material.cost_per_result != null && <span>转化成本: <span className="text-gray-900 font-medium">{material.cost_per_result.toFixed(2)}</span></span>}
          {material.brief_id && (
            <Link href={`/content-studio/briefs/${material.brief_id}`} className="text-violet-700 hover:underline">↗ 回链 Brief</Link>
          )}
        </div>
      </div>
    </div>
  )
}

function OwnerSellingPointsEditor({ skuId, sku, onSaved }: {
  skuId: string
  sku: SkuDetail | null
  onSaved: (s: SkuDetail) => void
}) {
  const [editing, setEditing] = useState(false)
  // 防御性解析：后端旧版/未注册 JSONB codec 时可能返回字符串，需要 parse 成 array
  const parseSellingPoints = (raw: unknown): Array<{ text: string }> => {
    let v: unknown = raw
    if (typeof v === 'string') {
      try { v = JSON.parse(v) } catch { v = [] }
    }
    if (!Array.isArray(v)) return []
    return v.map((s) => ({ text: typeof s === 'string' ? s : (s?.text || '') }))
  }
  const [items, setItems] = useState<Array<{ text: string }>>(
    parseSellingPoints(sku?.owner_selling_points),
  )
  const [notes, setNotes] = useState(sku?.owner_notes || '')
  const [priceMin, setPriceMin] = useState<string>(sku?.price_min != null ? String(sku.price_min) : '')
  const [priceMax, setPriceMax] = useState<string>(sku?.price_max != null ? String(sku.price_max) : '')
  const [specs, setSpecs] = useState(sku?.specifications || '')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setItems(parseSellingPoints(sku?.owner_selling_points))
    setNotes(sku?.owner_notes || '')
    setPriceMin(sku?.price_min != null ? String(sku.price_min) : '')
    setPriceMax(sku?.price_max != null ? String(sku.price_max) : '')
    setSpecs(sku?.specifications || '')
  }, [sku])

  const save = async () => {
    setSaving(true)
    try {
      const cleaned = items.map((it) => ({ text: it.text.trim() })).filter((it) => it.text)
      const body: Record<string, unknown> = {
        owner_selling_points: cleaned,
        owner_notes: notes,
        specifications: specs,
      }
      if (priceMin) body.price_min = parseFloat(priceMin)
      if (priceMax) body.price_max = parseFloat(priceMax)
      const r = await fetch(`/api/omni/scout/skus/${skuId}/owner-info`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (r.ok) {
        const updated = await r.json()
        onSaved(updated)
        setEditing(false)
      }
    } finally {
      setSaving(false)
    }
  }

  const sellingPointsCount = items.filter((it) => it.text.trim()).length

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
            <Edit3 className="w-4 h-4 text-amber-600" />
            老板视角输入
            <span className="text-[11px] text-gray-400 font-normal">（编排器的种子素材）</span>
          </h3>
          {!editing ? (
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
              <Edit3 className="w-3.5 h-3.5 mr-1" /> 编辑
            </Button>
          ) : (
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={saving}>取消</Button>
              <Button size="sm" onClick={save} disabled={saving}>
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Save className="w-3.5 h-3.5 mr-1" />}
                保存
              </Button>
            </div>
          )}
        </div>

        {!editing ? (
          <div className="space-y-2 text-xs">
            {sellingPointsCount > 0 ? (
              <div>
                <div className="text-gray-500 mb-1">老板手填卖点 ({sellingPointsCount})</div>
                <ul className="space-y-0.5 text-gray-700">
                  {items.filter((it) => it.text.trim()).map((it, i) => (
                    <li key={i}>• {it.text}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="text-gray-400 italic">尚未填写卖点 — 点「编辑」开始</div>
            )}
            {notes && (
              <div>
                <div className="text-gray-500 mb-1">备注</div>
                <div className="text-gray-700 whitespace-pre-wrap">{notes}</div>
              </div>
            )}
            {(priceMin || priceMax) && (
              <div className="text-gray-500">
                价格区间：<span className="text-gray-700">{priceMin || '?'} - {priceMax || '?'}</span>
              </div>
            )}
            {specs && (
              <div>
                <div className="text-gray-500 mb-1">规格</div>
                <div className="text-gray-700 whitespace-pre-wrap">{specs}</div>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="text-[11px] text-gray-500 mb-1 block">卖点（每行一条）</label>
              <textarea
                className="w-full text-xs border rounded px-2 py-1.5 min-h-[100px] font-mono"
                placeholder="例：&#10;0添加生抽&#10;180 天纯酿工艺&#10;江浙妈妈复购第一名"
                value={items.map((it) => it.text).join('\n')}
                onChange={(e) => setItems(e.target.value.split('\n').map((t) => ({ text: t })))}
              />
            </div>
            <div>
              <label className="text-[11px] text-gray-500 mb-1 block">规格（每行一种，可写多种）</label>
              <textarea
                className="w-full text-xs border rounded px-2 py-1.5 min-h-[60px] font-mono"
                placeholder="例：&#10;500ml*2瓶 送200ml*2瓶（家庭装）&#10;200ml 试吃装&#10;外卖小包 10ml*10"
                value={specs}
                onChange={(e) => setSpecs(e.target.value)}
              />
            </div>
            <div>
              <label className="text-[11px] text-gray-500 mb-1 block">备注（场景/原料/工艺等任意文字）</label>
              <textarea
                className="w-full text-xs border rounded px-2 py-1.5 min-h-[60px]"
                placeholder="例：主打居家烹饪场景；原料黄豆来自东北；工艺与日本龟甲万对标"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[11px] text-gray-500 mb-1 block">价格下限（元）</label>
                <input
                  type="number"
                  className="w-full text-xs border rounded px-2 py-1.5"
                  value={priceMin}
                  onChange={(e) => setPriceMin(e.target.value)}
                />
              </div>
              <div>
                <label className="text-[11px] text-gray-500 mb-1 block">价格上限（元）</label>
                <input
                  type="number"
                  className="w-full text-xs border rounded px-2 py-1.5"
                  value={priceMax}
                  onChange={(e) => setPriceMax(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

