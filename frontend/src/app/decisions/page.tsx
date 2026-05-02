'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  ClipboardCheck, CheckCircle2, XCircle, Clock,
  Inbox, Sparkles, Loader2, ArrowRight,
} from 'lucide-react'
import { useDecisionStore } from '@/stores/decisionStore'

// ── Types ─────────────────────────────────────────────────────────────────────��

interface BackendDecision {
  id: number
  source_module: string
  sku_id: string | null
  sku_name: string | null
  type: string | null
  title: string
  summary: string | null
  full_content: string | null
  status: string
  created_at: string
  adopted_at: string | null
}

type FilterKey = 'all' | 'pending' | 'adopted' | 'rejected'

const STATUS_FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '待处理' },
  { key: 'adopted', label: '已采纳' },
  { key: 'rejected', label: '已拒绝' },
]

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  pending:   { label: '待处理', cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  adopted:   { label: '已采纳', cls: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
  rejected:  { label: '已拒绝', cls: 'bg-rose-100 text-rose-700 border-rose-200' },
  postponed: { label: '已暂缓', cls: 'bg-blue-100 text-blue-700 border-blue-200' },
  executing: { label: '执行中', cls: 'bg-violet-100 text-violet-700 border-violet-200' },
  verified:  { label: '已验证', cls: 'bg-teal-100 text-teal-700 border-teal-200' },
  strategy:  { label: '可复用策略', cls: 'bg-purple-100 text-purple-700 border-purple-200' },
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function DecisionsPage() {
  const [decisions, setDecisions] = useState<BackendDecision[]>([])
  const [loading, setLoading] = useState(true)
  const [backendOk, setBackendOk] = useState(false)
  const [filter, setFilter] = useState<FilterKey>('all')
  const [patching, setPatching] = useState<number | null>(null)

  // Zustand local store as fallback (shows when backend is unavailable)
  const localDecisions = useDecisionStore((s) => s.decisions)
  const hydrateFromBackend = useDecisionStore((s) => s.hydrateFromBackend)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      fetch('/api/omni/scout/decisions?limit=100').then((r) => {
        if (!r.ok) throw new Error()
        return r.json() as Promise<BackendDecision[]>
      }),
      // Sync backend → local store so SaveToDecisionButton 写入的本地记录能拿到 backendId
      hydrateFromBackend(),
    ])
      .then(([data]) => {
        if (cancelled) return
        setDecisions(data)
        setBackendOk(true)
      })
      .catch(() => {
        if (!cancelled) setBackendOk(false)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [hydrateFromBackend])

  async function handlePatch(id: number, status: 'adopted' | 'rejected') {
    setPatching(id)
    try {
      const reason = status === 'rejected'
        ? (window.prompt('拒绝原因（可选）：') ?? '')
        : undefined
      await fetch(`/api/omni/scout/decisions/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, rejected_reason: reason }),
      })
      setDecisions((prev) => prev.map((d) => d.id === id ? { ...d, status } : d))
    } finally {
      setPatching(null)
    }
  }

  const filtered = useMemo(() => {
    if (!backendOk) return []
    return filter === 'all' ? decisions : decisions.filter((d) => d.status === filter)
  }, [decisions, filter, backendOk])

  const counts = useMemo(() => ({
    all: decisions.length,
    pending: decisions.filter((d) => d.status === 'pending').length,
    adopted: decisions.filter((d) => d.status === 'adopted').length,
    rejected: decisions.filter((d) => d.status === 'rejected').length,
  }), [decisions])

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <ClipboardCheck className="w-7 h-7 text-emerald-600" />
            决策日志
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            所有 AI 给的建议都存在这里，跟踪采纳与命中率
          </p>
        </div>
        <Link href="/review" className="text-xs text-violet-600 hover:underline flex items-center gap-1">
          周末复盘 <ArrowRight className="w-3 h-3" />
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <StatCard label="总决策数" value={backendOk ? counts.all : localDecisions.length} icon={<Inbox className="w-4 h-4" />} />
        <StatCard label="待处理" value={backendOk ? counts.pending : localDecisions.filter(d => d.status === 'pending').length}
          icon={<Clock className="w-4 h-4 text-amber-600" />} />
        <StatCard label="已采纳" value={backendOk ? counts.adopted : localDecisions.filter(d => d.status === 'adopted').length}
          icon={<CheckCircle2 className="w-4 h-4 text-emerald-600" />} />
        <StatCard label="已验证/策略" value={backendOk ? decisions.filter(d => d.status === 'verified' || d.type === 'strategy').length : 0}
          icon={<Sparkles className="w-4 h-4 text-teal-600" />} />
      </div>

      {/* Filter bar */}
      {backendOk && (
        <div className="flex gap-1.5 mb-4 flex-wrap">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition ${
                filter === f.key
                  ? 'bg-violet-600 text-white shadow'
                  : 'bg-white border border-gray-200 text-gray-600 hover:border-violet-300'
              }`}
            >
              {f.label}
              <span className="ml-1.5 text-[10px] opacity-70">{counts[f.key]}</span>
            </button>
          ))}
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-gray-300" />
        </div>
      ) : backendOk ? (
        filtered.length === 0 ? (
          <Card>
            <CardContent className="p-12 text-center text-sm text-gray-500">
              <ClipboardCheck className="w-10 h-10 mx-auto text-gray-300 mb-3" />
              {counts.all === 0 ? '暂无决策记录' : '该筛选下没有记录'}
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-3">
            {filtered.map((d) => (
              <DecisionCard
                key={d.id}
                decision={d}
                patching={patching === d.id}
                onAdopt={() => handlePatch(d.id, 'adopted')}
                onReject={() => handlePatch(d.id, 'rejected')}
              />
            ))}
          </div>
        )
      ) : (
        /* Fallback: local zustand store */
        <div className="space-y-3">
          <div className="text-xs text-gray-400 mb-2 border border-dashed rounded-lg p-2 text-center">
            scout-agent 未连接，显示本地暂存记录
          </div>
          {localDecisions.length === 0 ? (
            <Card>
              <CardContent className="p-12 text-center text-sm text-gray-500">
                到「智能问答」或「圆桌讨论」点击「存入决策日志」按钮可保存记录
              </CardContent>
            </Card>
          ) : (
            localDecisions.map((d) => (
              <Card key={d.id}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant="outline" className="text-[10px]">{d.source}</Badge>
                    <Badge variant="outline" className={`text-[10px] ${STATUS_BADGE[d.status]?.cls}`}>
                      {STATUS_BADGE[d.status]?.label ?? d.status}
                    </Badge>
                  </div>
                  <div className="text-sm font-medium text-gray-900">{d.title}</div>
                  {d.summary && <div className="text-xs text-gray-500 mt-1 line-clamp-2">{d.summary}</div>}
                </CardContent>
              </Card>
            ))
          )}
        </div>
      )}
    </div>
  )
}

// ── Components ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">{icon}{label}</div>
        <div className="text-2xl font-bold text-gray-900">{value}</div>
      </CardContent>
    </Card>
  )
}

function DecisionCard({ decision: d, patching, onAdopt, onReject }: {
  decision: BackendDecision
  patching: boolean
  onAdopt: () => void
  onReject: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const badge = STATUS_BADGE[d.status] ?? { label: d.status, cls: 'bg-gray-100 text-gray-600 border-gray-200' }

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="outline" className="text-[10px]">{d.source_module}</Badge>
            <Badge variant="outline" className={`text-[10px] ${badge.cls}`}>{badge.label}</Badge>
            {d.sku_id && (
              <Link href={`/sku/${d.sku_id}`} className="text-[10px] text-violet-600 hover:underline">
                {d.sku_name || d.sku_id}
              </Link>
            )}
          </div>
          <span className="text-[10px] text-gray-400 shrink-0">
            {new Date(d.created_at).toLocaleString('zh-CN')}
          </span>
        </div>

        <div className="font-medium text-sm text-gray-900 mb-1">{d.title}</div>
        {d.summary && (
          <div className={`text-xs text-gray-600 leading-relaxed ${expanded ? '' : 'line-clamp-2'}`}>
            {d.summary}
          </div>
        )}
        {expanded && d.full_content && d.full_content !== d.summary && (
          <div className="mt-3 pt-3 border-t border-gray-100 text-xs text-gray-500 whitespace-pre-wrap font-mono leading-relaxed bg-gray-50 p-2 rounded">
            {d.full_content}
          </div>
        )}

        <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-100">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="text-xs text-gray-500 hover:text-violet-600"
          >
            {expanded ? '收起' : '展开'}
          </button>
          {d.status === 'pending' && (
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={onReject} disabled={patching}
                className="text-xs h-7 px-3">
                {patching ? <Loader2 className="w-3 h-3 animate-spin" /> : <XCircle className="w-3.5 h-3.5 mr-1" />}
                拒绝
              </Button>
              <Button size="sm" onClick={onAdopt} disabled={patching}
                className="text-xs h-7 px-3 bg-emerald-600 hover:bg-emerald-700">
                {patching ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5 mr-1" />}
                采纳
              </Button>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
