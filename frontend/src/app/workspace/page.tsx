'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  ScanSearch, Inbox, Package, ClipboardCheck, Sparkles,
  ArrowRight, CheckCircle2, XCircle, Loader2, AlertCircle,
  TrendingDown, TrendingUp, CalendarDays, Brain, Truck,
} from 'lucide-react'

interface Run {
  id: string
  runbook_name: string
  started_at: string
  status: 'running' | 'success' | 'failed'
}

interface Anomaly {
  id: number
  sku_id: string
  sku_name: string
  severity: 'urgent' | 'warning' | 'positive'
  rule_id: string
  description: string
  delta_pct: number | null
}

interface Decision {
  id: number
  title: string
  status: string
  created_at: string
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

interface ShopTodo {
  metric: string
  label: string
  value: number | null
  link: string
}

interface StrategyCard {
  scene: string
  scene_label: string
  flow_count: number | null
  outperform_pct: number
  suggestion: string
}

export default function WorkspacePage() {
  const [runs, setRuns] = useState<Run[]>([])
  const [anomalies, setAnomalies] = useState<Anomaly[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [assets5a, setAssets5a] = useState<Asset5A[]>([])
  const [shopTodos, setShopTodos] = useState<ShopTodo[]>([])
  const [strategyCards, setStrategyCards] = useState<StrategyCard[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch('/api/omni/scout/runs?limit=10').then((r) => r.ok ? r.json() : []),
      fetch('/api/omni/scout/anomalies?unhandled_only=true&limit=5').then((r) => r.ok ? r.json() : []),
      fetch('/api/omni/scout/decisions?limit=10').then((r) => r.ok ? r.json() : []),
      fetch('/api/omni/scout/dashboard/5a?days=7').then((r) => r.ok ? r.json() : []),
      fetch('/api/omni/scout/dashboard/shop-todos').then((r) => r.ok ? r.json() : []),
      fetch('/api/omni/scout/dashboard/strategy-cards').then((r) => r.ok ? r.json() : []),
    ]).then(([r, a, d, fa, st, sc]) => {
      setRuns(r)
      setAnomalies(a)
      setDecisions(d)
      setAssets5a(fa)
      setShopTodos(st)
      setStrategyCards(sc)
    }).finally(() => setLoading(false))
  }, [])

  // Summarise today's runbook suite runs
  const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).replace(/\//g, '-')
  const todayRuns = runs.filter((r) => r.started_at.startsWith(today.slice(0, 10)))
  const suiteRuns = todayRuns.filter((r) => r.runbook_name.startsWith('runbook-suite/'))
  const successCount = suiteRuns.filter((r) => r.status === 'success').length
  const failedCount = suiteRuns.filter((r) => r.status === 'failed').length
  const runningCount = suiteRuns.filter((r) => r.status === 'running').length

  const pendingDecisions = decisions.filter((d) => d.status === 'pending')
  const adoptedThisWeek = decisions.filter((d) => {
    const diff = Date.now() - new Date(d.created_at).getTime()
    return d.status === 'adopted' && diff < 7 * 86400000
  })
  const isSunday = new Date().getDay() === 0

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <Inbox className="w-7 h-7 text-violet-600" />
            工作台
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            每天先看这里：异动推送 · 决策待办 · 本周复盘
          </p>
        </div>
        <span className="text-xs text-gray-400">
          {new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}
        </span>
      </div>

      {/* 今日巡店 */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <ScanSearch className="w-4 h-4 text-blue-600" />
              今日巡店
            </h2>
            <Link href="/scout" className="text-xs text-violet-600 hover:underline flex items-center gap-1">
              详情 <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin text-gray-300" />
          ) : suiteRuns.length === 0 ? (
            <div className="text-sm text-gray-500">
              今日尚未运行巡店任务。Runbook 计划于每天 08:30 自动触发，或前往巡店页面手动触发。
            </div>
          ) : (
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5 text-sm">
                <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                <span className="font-medium text-emerald-700">{successCount}</span>
                <span className="text-gray-500">成功</span>
              </div>
              {failedCount > 0 && (
                <div className="flex items-center gap-1.5 text-sm">
                  <XCircle className="w-4 h-4 text-rose-500" />
                  <span className="font-medium text-rose-700">{failedCount}</span>
                  <span className="text-gray-500">失败</span>
                </div>
              )}
              {runningCount > 0 && (
                <div className="flex items-center gap-1.5 text-sm">
                  <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
                  <span className="font-medium text-blue-700">{runningCount}</span>
                  <span className="text-gray-500">运行中</span>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 今天值得关注 */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-amber-600" />
              今天值得关注
              {anomalies.length > 0 && (
                <Badge variant="secondary" className="ml-1 text-[10px] bg-rose-100 text-rose-700">
                  {anomalies.length}
                </Badge>
              )}
            </h2>
            <Link href="/scout" className="text-xs text-violet-600 hover:underline flex items-center gap-1">
              全部异动 <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin text-gray-300" />
          ) : anomalies.length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-200 p-4 text-center text-sm text-gray-400">
              暂无异动。巡店 runbook 发现异常后会自动推送到这里。
            </div>
          ) : (
            <div className="space-y-2">
              {anomalies.map((a) => (
                <Link
                  key={a.id}
                  href={`/sku/${a.sku_id}`}
                  className="flex items-start gap-3 p-3 rounded-lg border border-gray-100 hover:border-violet-200 hover:bg-violet-50/30 transition"
                >
                  <SeverityIcon severity={a.severity} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-800 truncate">{a.sku_name || a.sku_id}</div>
                    <div className="text-xs text-gray-500 line-clamp-1">{a.description}</div>
                  </div>
                  {a.delta_pct != null && (
                    <div className={`text-xs font-mono shrink-0 ${a.delta_pct < 0 ? 'text-rose-600' : 'text-emerald-600'}`}>
                      {a.delta_pct > 0 ? '+' : ''}{(a.delta_pct * 100).toFixed(1)}%
                    </div>
                  )}
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 决策状态 */}
      <Card className={isSunday ? 'border-amber-300 ring-1 ring-amber-200' : ''}>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <ClipboardCheck className="w-4 h-4 text-emerald-600" />
              本周决策状态
              {isSunday && (
                <Badge variant="outline" className="text-[10px] bg-amber-50 text-amber-700 border-amber-200 ml-1">
                  今天复盘日
                </Badge>
              )}
            </h2>
            <div className="flex items-center gap-2">
              {isSunday && (
                <Link href="/review" className="text-xs text-amber-700 font-medium hover:underline flex items-center gap-1">
                  <CalendarDays className="w-3.5 h-3.5" />
                  开始复盘
                </Link>
              )}
              <Link href="/decisions" className="text-xs text-violet-600 hover:underline flex items-center gap-1">
                查看全部 <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
          </div>
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin text-gray-300" />
          ) : (
            <div className="grid grid-cols-3 gap-4">
              <StatCard label="待决策" value={pendingDecisions.length} color="text-amber-700" />
              <StatCard label="本周采纳" value={adoptedThisWeek.length} color="text-emerald-700" />
              <StatCard label="总记录" value={decisions.length} color="text-gray-700" />
            </div>
          )}
        </CardContent>
      </Card>

      {/* 5A 心电图卡 (V05-7) */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <Brain className="w-4 h-4 text-purple-600" />
              品牌 5A 资产
              {assets5a.length > 0 && (
                <span className="text-[10px] text-gray-400 font-normal ml-1">
                  {assets5a[0]?.date}
                </span>
              )}
            </h2>
          </div>
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin text-gray-300" />
          ) : assets5a.length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-200 p-4 text-center text-sm text-gray-400">
              运行「H-品牌资产」Runbook 后数据会显示在这里
            </div>
          ) : (
            <FiveAChart rows={assets5a} />
          )}
        </CardContent>
      </Card>

      {/* 6 待办数实时卡 (V05-8) */}
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold flex items-center gap-2">
              <Truck className="w-4 h-4 text-blue-600" />
              店铺待办
            </h2>
          </div>
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin text-gray-300" />
          ) : shopTodos.length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-200 p-4 text-center text-sm text-gray-400">
              运行「抖店后台-待办数」Runbook 后数据会显示在这里
            </div>
          ) : (
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
              {shopTodos.map((t) => (
                <a
                  key={t.metric}
                  href={t.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-center p-2 rounded-lg bg-gray-50 hover:bg-blue-50 border border-gray-100 hover:border-blue-200 transition group"
                >
                  <div className={`text-2xl font-bold ${t.value != null && t.value > 0 ? 'text-rose-600' : 'text-gray-900'}`}>
                    {t.value ?? '—'}
                  </div>
                  <div className="text-[10px] text-gray-500 mt-0.5 group-hover:text-blue-600">{t.label}</div>
                </a>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 6 场景化策略卡 (V05-9) */}
      {(strategyCards.length > 0 || !loading) && (
        <Card>
          <CardContent className="p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-semibold flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-violet-600" />
                5A 场景策略
              </h2>
            </div>
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin text-gray-300" />
            ) : strategyCards.length === 0 ? (
              <div className="rounded-lg border border-dashed border-gray-200 p-4 text-center text-sm text-gray-400">
                运行「H-品牌资产」Runbook 后场景流转数据会显示在这里
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {strategyCards.map((c) => {
                  const beat = c.outperform_pct > 0
                  return (
                    <div key={c.scene} className={`rounded-xl border p-3 ${beat ? 'border-emerald-200 bg-emerald-50/40' : 'border-rose-200 bg-rose-50/30'}`}>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-semibold text-gray-800">{c.scene_label}</span>
                        <span className={`text-[10px] font-mono font-bold ${beat ? 'text-emerald-700' : 'text-rose-600'}`}>
                          {beat ? `超同行 ${(c.outperform_pct * 100).toFixed(0)}%` : `低同行 ${Math.abs(c.outperform_pct * 100).toFixed(0)}%`}
                        </span>
                      </div>
                      {c.flow_count != null && (
                        <div className="text-[10px] text-gray-500 mb-1.5">流转量 {c.flow_count.toLocaleString()}</div>
                      )}
                      <div className="text-[10px] text-gray-600 leading-relaxed">{c.suggestion}</div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* 快捷入口 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <QuickLink
          href="/products"
          icon={<Package className="w-5 h-5" />}
          label="我的产品"
          desc="SKU 全景：指标趋势 / 动作日志 / AI 诊断"
          color="from-violet-500 to-purple-600"
        />
        <QuickLink
          href="/scout"
          icon={<ScanSearch className="w-5 h-5" />}
          label="巡店监控"
          desc="Runbook 执行状态 · 登录态 · 手动触发"
          color="from-blue-500 to-cyan-600"
        />
        <QuickLink
          href="/decisions"
          icon={<ClipboardCheck className="w-5 h-5" />}
          label="决策日志"
          desc="所有 AI 输出 · 采纳与命中率统计"
          color="from-emerald-500 to-teal-600"
        />
      </div>
    </div>
  )
}

// ── 5A sparkline ──────────────────────────────────────────────────────────────

const A_STAGES: { key: keyof Asset5A; label: string; bg: string; bgDim: string; text: string }[] = [
  { key: 'o_count',      label: 'O',  bg: 'bg-gray-400',   bgDim: 'bg-gray-200',   text: 'text-gray-600'   },
  { key: 'a1_aware',    label: 'A1', bg: 'bg-blue-400',   bgDim: 'bg-blue-200',   text: 'text-blue-600'   },
  { key: 'a2_appeal',   label: 'A2', bg: 'bg-cyan-400',   bgDim: 'bg-cyan-200',   text: 'text-cyan-600'   },
  { key: 'a3_ask',      label: 'A3', bg: 'bg-violet-400', bgDim: 'bg-violet-200', text: 'text-violet-600' },
  { key: 'a4_act',      label: 'A4', bg: 'bg-amber-400',  bgDim: 'bg-amber-200',  text: 'text-amber-600'  },
  { key: 'a5_advocate', label: 'A5', bg: 'bg-rose-400',   bgDim: 'bg-rose-200',   text: 'text-rose-600'   },
]
const OUTPERFORM_KEYS: (keyof Asset5A)[] = [
  'a1_outperform_pct', 'a2_outperform_pct', 'a3_outperform_pct',
  'a4_outperform_pct', 'a5_outperform_pct',
]

function FiveAChart({ rows }: { rows: Asset5A[] }) {
  const latest = rows[0]
  if (!latest) return null
  const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date))

  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
      {A_STAGES.map((s, idx) => {
        const val = latest[s.key] as number | null
        const history = sorted.map((r) => (r[s.key] as number | null) ?? 0)
        const maxH = Math.max(...history, 1)
        const outpct = idx > 0 ? (latest[OUTPERFORM_KEYS[idx - 1]] as number | null) : null
        const fmtVal = val != null ? (val >= 10000 ? `${(val / 10000).toFixed(1)}w` : val.toLocaleString()) : '—'

        return (
          <div key={s.key} className="rounded-lg border border-gray-100 p-2.5 bg-gray-50">
            <div className={`text-[10px] font-bold mb-1 ${s.text}`}>{s.label}</div>
            <div className="text-base font-bold text-gray-900 leading-none mb-1">{fmtVal}</div>
            {outpct != null && (
              <div className={`text-[9px] font-mono mb-1.5 ${outpct >= 0 ? 'text-emerald-600' : 'text-rose-500'}`}>
                {outpct >= 0 ? '+' : ''}{(outpct * 100).toFixed(0)}%
              </div>
            )}
            <div className="flex items-end gap-0.5 h-5">
              {history.map((v, i) => (
                <div
                  key={i}
                  className={`flex-1 rounded-t-sm ${i === history.length - 1 ? s.bg : s.bgDim}`}
                  style={{ height: `${Math.max(2, Math.round((v / maxH) * 20))}px` }}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === 'urgent') return <TrendingDown className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
  if (severity === 'warning') return <AlertCircle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
  return <TrendingUp className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
}

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="text-center p-3 rounded-lg bg-gray-50">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </div>
  )
}

function QuickLink({ href, icon, label, desc, color }: {
  href: string; icon: React.ReactNode; label: string; desc: string; color: string
}) {
  return (
    <Link href={href} className="group block rounded-xl border border-gray-200 bg-white p-4 hover:border-violet-200 hover:shadow-md transition-all">
      <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${color} flex items-center justify-center text-white mb-3 shadow`}>
        {icon}
      </div>
      <div className="font-medium text-sm text-gray-900">{label}</div>
      <div className="text-xs text-gray-500 mt-1 leading-relaxed">{desc}</div>
    </Link>
  )
}
