'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Activity, ThumbsUp, ThumbsDown, RotateCcw, X,
  CheckCircle2, Clock, Loader2,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ToolCallRow {
  id: string
  tool_name: string
  status: string
  require_approval: boolean
  duration_ms: number | null
  user_rating: string | null
  rating_note: string | null
  model_used: string | null
  error: string | null
  created_at: string
  completed_at: string | null
  args?: Record<string, unknown>
  result?: Record<string, unknown>
}

interface Summary24h {
  total: number
  success_rate: number
  avg_duration_ms: number | null
  pending_count: number
  rating_dist: Record<string, number>
}

interface ListResp {
  success: boolean
  data: ToolCallRow[]
  total: number
  summary_24h: Summary24h
}

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  completed: { label: '完成',   cls: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
  pending:   { label: '待批',   cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  approved:  { label: '已批',   cls: 'bg-blue-100 text-blue-700 border-blue-200' },
  rejected:  { label: '驳回',   cls: 'bg-rose-100 text-rose-700 border-rose-200' },
  error:     { label: '错',     cls: 'bg-red-100 text-red-700 border-red-200' },
  orphaned:  { label: '孤儿',   cls: 'bg-gray-100 text-gray-700 border-gray-200' },
}

const RATING_BADGE: Record<string, { icon: string; cls: string }> = {
  good: { icon: '👍', cls: 'bg-green-50 text-green-700 border-green-200' },
  bad:  { icon: '👎', cls: 'bg-red-50 text-red-700 border-red-200' },
  redo: { icon: '🔁', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
}

function fmtDur(ms: number | null): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60_000).toFixed(1)}min`
}

function fmtTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diffMin = Math.floor((now.getTime() - d.getTime()) / 60_000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  if (diffMin < 1440) return `${Math.floor(diffMin / 60)} 小时前`
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AgentLogPage() {
  const [rows, setRows] = useState<ToolCallRow[]>([])
  const [summary, setSummary] = useState<Summary24h | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [openRow, setOpenRow] = useState<ToolCallRow | null>(null)
  const [rating, setRating] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try {
      const qs = statusFilter ? `?status=${statusFilter}&limit=100` : '?limit=100'
      const resp = await fetch(`/api/omni/agent-log${qs}`)
      const data: ListResp = await resp.json()
      if (data.success) {
        setRows(data.data)
        setSummary(data.summary_24h)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [statusFilter])

  async function openDetail(id: string) {
    setOpenId(id)
    setOpenRow(null)
    try {
      const resp = await fetch(`/api/omni/agent-log/${id}`)
      const data = await resp.json()
      if (data.success) {
        setOpenRow(data.data)
      } else {
        setOpenId(null)
        window.alert(data.error ?? '加载详情失败')
      }
    } catch (err) {
      setOpenId(null)
      window.alert('网络异常：' + (err instanceof Error ? err.message : String(err)))
    }
  }

  async function submitRating(id: string, r: 'good' | 'bad' | 'redo') {
    setRating(id)
    try {
      const note = r !== 'good' ? (window.prompt('备注（可选）：') ?? '') : ''
      const resp = await fetch(`/api/omni/agent-log/${id}/rate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating: r, note }),
      })
      const data = await resp.json()
      if (data.success && data.ok) {
        setRows((prev) => prev.map((x) => x.id === id ? { ...x, user_rating: r, rating_note: note } : x))
        if (openRow?.id === id) setOpenRow({ ...openRow, user_rating: r, rating_note: note })
      } else {
        window.alert(data.hint ?? data.error ?? '评分失败')
      }
    } catch (err) {
      window.alert('网络异常：' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setRating(null)
    }
  }

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <Activity className="w-7 h-7 text-violet-600" />
            Agent 日志
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            看 omni 跑了啥 / 给好坏打分 / 自动累积到 patterns.md
          </p>
        </div>
      </div>

      {/* 24h Summary */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard label="24h 调用" value={summary.total} icon={<Activity className="w-4 h-4" />} />
          <StatCard label="成功率" value={`${(summary.success_rate * 100).toFixed(0)}%`} icon={<CheckCircle2 className="w-4 h-4 text-emerald-600" />} />
          <StatCard label="平均耗时" value={fmtDur(summary.avg_duration_ms)} icon={<Clock className="w-4 h-4 text-blue-600" />} />
          <StatCard label="待批 / 评分" value={`${summary.pending_count} / 👍${summary.rating_dist.good ?? 0} 👎${summary.rating_dist.bad ?? 0}`} icon={<ThumbsUp className="w-4 h-4 text-violet-600" />} />
        </div>
      )}

      {/* Status filter */}
      <div className="flex gap-1.5 mb-4 flex-wrap">
        {[
          { key: '',         label: '全部' },
          { key: 'completed', label: '完成' },
          { key: 'pending',   label: '待批' },
          { key: 'error',     label: '错误' },
        ].map((f) => (
          <button
            key={f.key}
            onClick={() => setStatusFilter(f.key)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${
              statusFilter === f.key
                ? 'bg-violet-600 text-white shadow'
                : 'bg-white border border-gray-200 text-gray-600 hover:border-violet-300'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Main table */}
      {loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-gray-300" />
        </div>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center text-sm text-gray-500">
            没记录
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => (
            <div
              key={r.id}
              className="flex items-center gap-3 px-4 py-3 bg-white border border-gray-200 rounded-lg hover:border-violet-300 hover:shadow-sm transition cursor-pointer"
              onClick={() => openDetail(r.id)}
            >
              <code className="text-xs text-gray-400 font-mono w-16 truncate">{r.id.slice(0, 8)}</code>
              <span className="font-medium text-gray-900 flex-1 truncate">{r.tool_name}</span>
              <Badge className={STATUS_BADGE[r.status]?.cls ?? 'bg-gray-100'}>
                {STATUS_BADGE[r.status]?.label ?? r.status}
              </Badge>
              <span className="text-xs text-gray-500 w-16 text-right">{fmtDur(r.duration_ms)}</span>
              <span className="text-xs text-gray-400 w-24 text-right">{fmtTime(r.created_at)}</span>
              {r.user_rating && (
                <Badge className={RATING_BADGE[r.user_rating]?.cls}>
                  {RATING_BADGE[r.user_rating]?.icon}
                </Badge>
              )}
              <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                <Button size="sm" variant="ghost" disabled={rating === r.id || r.user_rating === 'good'}
                        onClick={() => submitRating(r.id, 'good')}>
                  <ThumbsUp className="w-3.5 h-3.5" />
                </Button>
                <Button size="sm" variant="ghost" disabled={rating === r.id || r.user_rating === 'bad'}
                        onClick={() => submitRating(r.id, 'bad')}>
                  <ThumbsDown className="w-3.5 h-3.5" />
                </Button>
                <Button size="sm" variant="ghost" disabled={rating === r.id || r.user_rating === 'redo'}
                        onClick={() => submitRating(r.id, 'redo')}>
                  <RotateCcw className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Detail drawer (right side panel, simple inline implementation) */}
      {openId && (
        <div className="fixed inset-0 z-40" onClick={() => { setOpenId(null); setOpenRow(null) }}>
          <div className="absolute inset-0 bg-black/30" />
          <div
            className="absolute top-0 right-0 h-full w-full md:w-[640px] bg-white shadow-2xl overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900">tool_call 详情</h3>
              <button onClick={() => { setOpenId(null); setOpenRow(null) }} className="text-gray-400 hover:text-gray-700">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              {openRow == null ? (
                <Loader2 className="w-6 h-6 animate-spin text-gray-300 mx-auto my-12" />
              ) : (
                <>
                  <DetailRow label="ID"       value={openRow.id} mono />
                  <DetailRow label="tool"     value={openRow.tool_name} />
                  <DetailRow label="status"   value={openRow.status} />
                  <DetailRow label="model"    value={openRow.model_used ?? '—'} />
                  <DetailRow label="耗时"     value={fmtDur(openRow.duration_ms)} />
                  <DetailRow label="开始"     value={fmtTime(openRow.created_at)} />
                  <DetailRow label="评分"     value={openRow.user_rating ?? '未评'} />
                  {openRow.rating_note && <DetailRow label="备注" value={openRow.rating_note} />}
                  {openRow.error && <DetailRow label="错误" value={openRow.error} mono />}
                  <DetailJson label="args"   value={openRow.args} />
                  <DetailJson label="result" value={openRow.result} />
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({ label, value, icon }: { label: string; value: string | number; icon: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="p-4 flex items-center gap-3">
        <div className="text-gray-400">{icon}</div>
        <div>
          <div className="text-xs text-gray-500">{label}</div>
          <div className="text-lg font-semibold text-gray-900">{value}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="text-gray-500 w-16 shrink-0">{label}</span>
      <span className={`flex-1 ${mono ? 'font-mono text-xs' : 'text-gray-900'}`}>{value}</span>
    </div>
  )
}

function DetailJson({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null
  return (
    <div>
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto whitespace-pre-wrap break-words">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}
