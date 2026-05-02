'use client'

/**
 * /review — 周末复盘页（PRD 故事 7）
 *
 * 展示本周（或历史周）的：
 *   - 决策汇总卡（已执行/已验证/待执行）
 *   - AI 命中率（正向/负向/持平/不可归因）
 *   - 已验证动作列表（按效果排序，可展开前后对比卡）
 *   - 本周亮点 vs 本周教训
 *   - 归档为可复用策略
 */

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  ArrowLeft, ArrowRight, ChevronDown, ChevronUp,
  TrendingUp, TrendingDown, Minus, HelpCircle,
  Sparkles, BookMarked, Loader2, Trophy, AlertTriangle,
  CheckCircle2,
} from 'lucide-react'

// ── Types ──────────────────────────────────────────────────────────────────────

interface VerifiedEvent {
  id: number
  sku_id: string | null
  sku_name: string | null
  asset_type: string
  action_type: string | null
  change_description: string
  executed_at: string
  verdict: string
  kpi_deltas: Record<string, { pre: number; post: number; delta_pct: number }>
  verify_summary: string
  verified_at: string
}

interface WeeklyReview {
  week_start: string
  verified_events: VerifiedEvent[]
  verdict_counts: Record<string, number>
  hit_rate: number
  status_counts: Record<string, number>
  anomaly_count: number
  total_verified: number
}

const KPI_LABELS: Record<string, string> = { gmv_paid: 'GMV', uv: '访客', ctr: 'CTR', cvr: 'CVR' }

// ── Page ───────────────────────────────────────────────────────────────────────

export default function ReviewPage() {
  const [weeksAgo, setWeeksAgo] = useState(0)
  const [data, setData] = useState<WeeklyReview | null>(null)
  const [loading, setLoading] = useState(true)
  const [archiving, setArchiving] = useState<number | null>(null)

  useEffect(() => {
    setLoading(true)
    fetch(`/api/omni/scout/weekly-review?weeks_ago=${weeksAgo}`)
      .then((r) => r.ok ? r.json() : null)
      .then(setData)
      .finally(() => setLoading(false))
  }, [weeksAgo])

  const highlights = data?.verified_events.filter((e) => e.verdict === 'positive') ?? []
  const lessons = data?.verified_events.filter((e) => e.verdict === 'negative') ?? []
  const neutral = data?.verified_events.filter((e) => e.verdict === 'neutral' || e.verdict === 'inconclusive') ?? []

  const weekLabel = weeksAgo === 0 ? '本周' : weeksAgo === 1 ? '上周' : `${weeksAgo} 周前`

  return (
    <div className="px-6 py-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/workspace" className="text-sm text-gray-500 hover:text-violet-600 flex items-center gap-1">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <Sparkles className="w-6 h-6 text-amber-500" />
              周末复盘
            </h1>
            <p className="text-sm text-gray-500 mt-0.5">
              查看 AI 命中率，把有效手段沉淀成策略
            </p>
          </div>
        </div>
        {/* Week navigator */}
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8 w-8 p-0"
            onClick={() => setWeeksAgo((w) => w + 1)}>
            <ArrowLeft className="w-4 h-4" />
          </Button>
          <span className="text-sm font-medium text-gray-700 w-16 text-center">{weekLabel}</span>
          <Button variant="outline" size="sm" className="h-8 w-8 p-0"
            disabled={weeksAgo === 0}
            onClick={() => setWeeksAgo((w) => Math.max(0, w - 1))}>
            <ArrowRight className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-gray-300" />
        </div>
      ) : !data ? (
        <Card>
          <CardContent className="p-12 text-center text-sm text-gray-500">
            scout-agent 未连接或暂无数据
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <SummaryCard
              label="已验证动作"
              value={data.total_verified}
              icon={<CheckCircle2 className="w-4 h-4 text-emerald-600" />}
            />
            <SummaryCard
              label="AI 命中率"
              value={`${data.hit_rate}%`}
              icon={<Trophy className="w-4 h-4 text-amber-500" />}
              highlight={data.hit_rate >= 50}
            />
            <SummaryCard
              label="待验证决策"
              value={data.status_counts['pending'] ?? 0}
              icon={<Sparkles className="w-4 h-4 text-violet-500" />}
            />
            <SummaryCard
              label="异动触发"
              value={data.anomaly_count}
              icon={<AlertTriangle className="w-4 h-4 text-rose-500" />}
            />
          </div>

          {/* Hit rate bar */}
          {data.total_verified > 0 && (
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-sm font-semibold text-gray-800">验证结果分布</h2>
                  <span className="text-xs text-gray-500">共 {data.total_verified} 条</span>
                </div>
                <VerdictBar counts={data.verdict_counts} total={data.total_verified} />
              </CardContent>
            </Card>
          )}

          {/* Highlights */}
          {highlights.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="w-4 h-4 text-emerald-600" />
                <h2 className="text-sm font-semibold text-gray-800">本周亮点（正向）</h2>
                <Badge variant="outline" className="text-[10px] bg-emerald-50 text-emerald-700 border-emerald-200">
                  {highlights.length} 条
                </Badge>
              </div>
              <div className="space-y-3">
                {highlights.map((e) => (
                  <VerifiedEventCard
                    key={e.id}
                    event={e}
                    onArchive={async () => {
                      setArchiving(e.id)
                      try {
                        await fetch('/api/omni/scout/strategies', {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ change_event_id: e.id }),
                        })
                      } finally {
                        setArchiving(null)
                      }
                    }}
                    archiving={archiving === e.id}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Lessons */}
          {lessons.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <TrendingDown className="w-4 h-4 text-rose-600" />
                <h2 className="text-sm font-semibold text-gray-800">本周教训（负向）</h2>
                <Badge variant="outline" className="text-[10px] bg-rose-50 text-rose-700 border-rose-200">
                  {lessons.length} 条
                </Badge>
              </div>
              <div className="space-y-3">
                {lessons.map((e) => (
                  <VerifiedEventCard key={e.id} event={e} />
                ))}
              </div>
            </section>
          )}

          {/* Neutral / inconclusive */}
          {neutral.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <Minus className="w-4 h-4 text-gray-500" />
                <h2 className="text-sm font-semibold text-gray-800">持平 / 无法归因</h2>
              </div>
              <div className="space-y-2">
                {neutral.map((e) => (
                  <VerifiedEventCard key={e.id} event={e} compact />
                ))}
              </div>
            </section>
          )}

          {data.total_verified === 0 && (
            <Card>
              <CardContent className="p-12 text-center text-sm text-gray-500">
                <Sparkles className="w-10 h-10 mx-auto text-gray-300 mb-3" />
                <p>{weekLabel}暂无已验证动作</p>
                <p className="text-xs text-gray-400 mt-1">
                  登记动作 7 天后系统自动完成验证，届时这里会显示前后对比卡
                </p>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

// ── Components ─────────────────────────────────────────────────────────────────

function SummaryCard({ label, value, icon, highlight }: {
  label: string; value: string | number; icon: React.ReactNode; highlight?: boolean
}) {
  return (
    <Card className={highlight ? 'border-amber-200 bg-amber-50/30' : ''}>
      <CardContent className="p-3">
        <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">{icon}{label}</div>
        <div className="text-2xl font-bold text-gray-900">{value}</div>
      </CardContent>
    </Card>
  )
}

function VerdictBar({ counts, total }: { counts: Record<string, number>; total: number }) {
  const VERDICTS = [
    { key: 'positive', label: '正向', color: 'bg-emerald-400' },
    { key: 'neutral', label: '持平', color: 'bg-gray-300' },
    { key: 'inconclusive', label: '不可归因', color: 'bg-amber-300' },
    { key: 'negative', label: '负向', color: 'bg-rose-400' },
  ]
  return (
    <div className="space-y-2">
      <div className="flex rounded-full overflow-hidden h-3 gap-0.5">
        {VERDICTS.map(({ key, color }) => {
          const pct = total > 0 ? ((counts[key] ?? 0) / total * 100) : 0
          return pct > 0 ? (
            <div key={key} className={`${color} transition-all`} style={{ width: `${pct}%` }} />
          ) : null
        })}
      </div>
      <div className="flex gap-4 flex-wrap">
        {VERDICTS.map(({ key, label, color }) => (
          <div key={key} className="flex items-center gap-1.5 text-xs text-gray-600">
            <div className={`w-2.5 h-2.5 rounded-sm ${color}`} />
            {label} ({counts[key] ?? 0})
          </div>
        ))}
      </div>
    </div>
  )
}

function VerifiedEventCard({ event: e, onArchive, archiving, compact }: {
  event: VerifiedEvent
  onArchive?: () => void
  archiving?: boolean
  compact?: boolean
}) {
  const [expanded, setExpanded] = useState(!compact)

  const verdictIcon = e.verdict === 'positive' ? (
    <TrendingUp className="w-4 h-4 text-emerald-500 shrink-0" />
  ) : e.verdict === 'negative' ? (
    <TrendingDown className="w-4 h-4 text-rose-500 shrink-0" />
  ) : e.verdict === 'inconclusive' ? (
    <HelpCircle className="w-4 h-4 text-amber-400 shrink-0" />
  ) : (
    <Minus className="w-4 h-4 text-gray-400 shrink-0" />
  )

  return (
    <Card>
      <CardContent className="p-4">
        {/* Header row */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-start gap-2 flex-1 min-w-0">
            {verdictIcon}
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 flex-wrap mb-0.5">
                {e.sku_name && (
                  <Link href={`/sku/${e.sku_id}`} className="text-xs font-medium text-violet-700 hover:underline">
                    {e.sku_name}
                  </Link>
                )}
                <Badge variant="outline" className="text-[10px]">{e.asset_type}</Badge>
              </div>
              <div className="text-sm text-gray-800 line-clamp-1">{e.change_description}</div>
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {onArchive && e.verdict === 'positive' && (
              <Button
                variant="outline"
                size="sm"
                className="h-6 text-[10px] px-2 text-amber-700 border-amber-200 hover:bg-amber-50"
                onClick={onArchive}
                disabled={archiving}
              >
                {archiving ? <Loader2 className="w-3 h-3 animate-spin" /> : (
                  <><BookMarked className="w-3 h-3 mr-1" />归档策略</>
                )}
              </Button>
            )}
            {e.kpi_deltas && (
              <button
                className="text-gray-400 hover:text-gray-700 p-1"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
            )}
          </div>
        </div>

        {/* Before/after grid */}
        {expanded && e.kpi_deltas && (
          <div className="grid grid-cols-4 gap-2 mt-3 pt-3 border-t border-gray-100">
            {Object.entries(e.kpi_deltas).map(([kpi, d]) => {
              const isPct = ['ctr', 'cvr'].includes(kpi)
              const fmt = (v: number) => isPct
                ? `${(v * 100).toFixed(2)}%`
                : v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
              const pct = d.delta_pct
              const color = pct >= 5 ? 'text-emerald-600' : pct <= -5 ? 'text-rose-600' : 'text-gray-500'
              return (
                <div key={kpi} className="text-center p-2 rounded-lg bg-gray-50 border border-gray-100">
                  <div className="text-[10px] text-gray-500 mb-1">{KPI_LABELS[kpi] ?? kpi}</div>
                  <div className="text-[10px] text-gray-400">{fmt(d.pre)}</div>
                  <div className="text-[10px] text-gray-300">↓</div>
                  <div className="text-sm font-semibold text-gray-900">{fmt(d.post)}</div>
                  <div className={`text-[10px] font-mono ${color}`}>
                    {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {expanded && e.verify_summary && (
          <div className="text-[11px] text-gray-500 mt-2 font-mono leading-relaxed bg-gray-50 px-3 py-1.5 rounded">
            {e.verify_summary}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
