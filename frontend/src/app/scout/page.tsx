'use client'

import { useEffect, useState, useCallback } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  ScanSearch, Clock, AlertCircle, Activity, RefreshCw,
  CheckCircle2, XCircle, Loader2, Wifi, WifiOff, Play,
} from 'lucide-react'

// ── Types ──────────────────────────────────────────────────────────────────────

interface Runbook {
  id: string
  name: string
  platform: string
  schedule: string
  description: string
  tags: string[]
}

interface Run {
  id: string
  runbook_name: string
  started_at: string
  ended_at: string | null
  status: 'running' | 'success' | 'failed'
  error: string | null
}

interface Anomaly {
  id: number
  sku_id: string
  sku_name: string
  severity: 'urgent' | 'warning' | 'positive'
  rule_id: string
  description: string
  delta_pct: number | null
  detected_at: string
}

interface Session {
  platform: string
  health: 'ok' | 'expired' | 'error' | 'unknown'
  last_login_at: string | null
  updated_at: string
}

const PLATFORMS = ['douyin_compass', 'douyin_shop_admin', 'yuntu']
const PLATFORM_LABELS: Record<string, string> = {
  douyin_compass: '抖店罗盘',
  douyin_shop_admin: '抖店后台',
  yuntu: '巨量云图',
}

// ── API helpers ────────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/omni/scout/${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json()
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function ScoutPage() {
  const [runbooks, setRunbooks] = useState<Runbook[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [anomalies, setAnomalies] = useState<Anomaly[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState<string | null>(null)
  const [relogining, setRelogining] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [rbs, rs, ants] = await Promise.all([
        apiFetch<Runbook[]>('runbooks'),
        apiFetch<Run[]>('runs?limit=20'),
        apiFetch<Anomaly[]>('anomalies?unhandled_only=true&limit=20'),
      ])
      setRunbooks(rbs)
      setRuns(rs)
      setAnomalies(ants)

      const sessionResults = await Promise.allSettled(
        PLATFORMS.map((p) => apiFetch<Session>(`sessions/${p}`)),
      )
      setSessions(
        sessionResults
          .map((r) => (r.status === 'fulfilled' ? r.value : null))
          .filter(Boolean) as Session[],
      )
    } catch (e) {
      // scout-agent may not be running yet
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const interval = setInterval(load, 30000)
    return () => clearInterval(interval)
  }, [load])

  async function triggerRunbook(rbId: string) {
    setTriggering(rbId)
    try {
      await apiFetch(`runbooks/${encodeURIComponent(rbId)}/run`, { method: 'POST' })
      setTimeout(load, 2000)
    } finally {
      setTriggering(null)
    }
  }

  async function relogin(platform: string) {
    setRelogining(platform)
    try {
      await apiFetch(`sessions/${platform}/relogin`, { method: 'POST' })
    } finally {
      setRelogining(null)
    }
  }

  async function dismissAnomaly(id: number) {
    await apiFetch(`anomalies/${id}`, { method: 'PATCH' })
    setAnomalies((prev) => prev.filter((a) => a.id !== id))
  }

  const suiteRunbooks = runbooks.filter((r) => r.id.startsWith('runbook-suite/'))

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <ScanSearch className="w-7 h-7 text-blue-600" />
            巡店监控
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            scout-agent · Playwright 自动巡店 · 异动检测
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {/* Sessions */}
      <Card>
        <CardContent className="p-5">
          <h2 className="text-base font-semibold flex items-center gap-2 mb-4">
            <Wifi className="w-4 h-4 text-blue-600" />
            登录态
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {PLATFORMS.map((platform) => {
              const session = sessions.find((s) => s.platform === platform)
              const health = session?.health ?? 'unknown'
              return (
                <div
                  key={platform}
                  className="flex items-center justify-between p-3 rounded-lg border bg-gray-50"
                >
                  <div>
                    <div className="text-sm font-medium text-gray-800">
                      {PLATFORM_LABELS[platform]}
                    </div>
                    <div className="text-[10px] text-gray-400 mt-0.5">
                      {session?.last_login_at
                        ? `最后登录 ${new Date(session.last_login_at).toLocaleDateString('zh-CN')}`
                        : '未登录'}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <HealthBadge health={health} />
                    {health !== 'ok' && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-6 text-[10px] px-2"
                        disabled={relogining === platform}
                        onClick={() => relogin(platform)}
                      >
                        {relogining === platform ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          '扫码'
                        )}
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Runbook suite */}
      <Card>
        <CardContent className="p-5">
          <h2 className="text-base font-semibold flex items-center gap-2 mb-4">
            <Activity className="w-4 h-4 text-blue-600" />
            Runbook 套件
          </h2>
          {loading ? (
            <div className="text-sm text-gray-400 text-center py-6">加载中…</div>
          ) : suiteRunbooks.length === 0 ? (
            <div className="text-sm text-gray-400 text-center py-6">
              scout-agent 未运行或 runbook 目录为空
            </div>
          ) : (
            <div className="space-y-2">
              {suiteRunbooks.map((rb) => {
                const latestRun = runs.find((r) => r.runbook_name === rb.id)
                return (
                  <div
                    key={rb.id}
                    className="flex items-center justify-between p-3 rounded-lg border border-gray-100 bg-gray-50"
                  >
                    <div className="flex items-center gap-3">
                      <Clock className="w-4 h-4 text-gray-400 shrink-0" />
                      <div>
                        <div className="text-sm font-medium text-gray-700">{rb.name}</div>
                        <div className="text-[10px] text-gray-400">{rb.description}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {latestRun && <RunStatusBadge status={latestRun.status} />}
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs px-2"
                        disabled={triggering === rb.id}
                        onClick={() => triggerRunbook(rb.id)}
                      >
                        {triggering === rb.id ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <>
                            <Play className="w-3 h-3 mr-1" />
                            立即运行
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent runs */}
      <Card>
        <CardContent className="p-5">
          <h2 className="text-base font-semibold flex items-center gap-2 mb-4">
            <Clock className="w-4 h-4 text-gray-600" />
            最近执行记录
          </h2>
          {runs.length === 0 ? (
            <div className="text-sm text-gray-400 text-center py-4">暂无记录</div>
          ) : (
            <div className="space-y-1.5">
              {runs.slice(0, 10).map((run) => (
                <div
                  key={run.id}
                  className="flex items-center justify-between px-3 py-2 rounded-lg text-xs border border-gray-100"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <RunStatusBadge status={run.status} />
                    <span className="text-gray-700 truncate">{run.runbook_name}</span>
                  </div>
                  <span className="text-gray-400 shrink-0 ml-2">
                    {new Date(run.started_at).toLocaleString('zh-CN', {
                      month: 'numeric', day: 'numeric',
                      hour: '2-digit', minute: '2-digit',
                    })}
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Anomalies */}
      <Card>
        <CardContent className="p-5">
          <h2 className="text-base font-semibold flex items-center gap-2 mb-4">
            <AlertCircle className="w-4 h-4 text-rose-600" />
            未处理异动
            {anomalies.length > 0 && (
              <Badge variant="secondary" className="ml-1 text-[10px] bg-rose-100 text-rose-700">
                {anomalies.length}
              </Badge>
            )}
          </h2>
          {anomalies.length === 0 ? (
            <div className="text-sm text-gray-400 text-center py-4">
              {loading ? '加载中…' : '暂无异动'}
            </div>
          ) : (
            <div className="space-y-2">
              {anomalies.map((a) => (
                <div
                  key={a.id}
                  className="flex items-start justify-between p-3 rounded-lg border bg-gray-50 gap-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <SeverityBadge severity={a.severity} />
                      <span className="text-xs font-medium text-gray-700 truncate">
                        {a.sku_name || a.sku_id}
                      </span>
                    </div>
                    <div className="text-xs text-gray-600">{a.description}</div>
                    {a.delta_pct != null && (
                      <div className={`text-[10px] mt-0.5 font-mono ${a.delta_pct < 0 ? 'text-rose-600' : 'text-emerald-600'}`}>
                        {a.delta_pct > 0 ? '+' : ''}{(a.delta_pct * 100).toFixed(1)}%
                      </div>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 text-[10px] px-2 shrink-0 text-gray-400 hover:text-gray-700"
                    onClick={() => dismissAnomaly(a.id)}
                  >
                    已知晓
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function HealthBadge({ health }: { health: string }) {
  if (health === 'ok')
    return (
      <span className="flex items-center gap-1 text-[10px] text-emerald-700">
        <Wifi className="w-3 h-3" /> 有效
      </span>
    )
  if (health === 'expired')
    return (
      <span className="flex items-center gap-1 text-[10px] text-rose-600">
        <WifiOff className="w-3 h-3" /> 已过期
      </span>
    )
  return (
    <span className="flex items-center gap-1 text-[10px] text-gray-400">
      <WifiOff className="w-3 h-3" /> 未知
    </span>
  )
}

function RunStatusBadge({ status }: { status: string }) {
  if (status === 'success')
    return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
  if (status === 'failed')
    return <XCircle className="w-3.5 h-3.5 text-rose-500" />
  return <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />
}

function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, string> = {
    urgent: 'bg-rose-100 text-rose-700 border-rose-200',
    warning: 'bg-amber-100 text-amber-700 border-amber-200',
    positive: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  }
  const labels: Record<string, string> = { urgent: '紧急', warning: '预警', positive: '正向' }
  return (
    <Badge variant="outline" className={`text-[10px] ${map[severity] ?? ''}`}>
      {labels[severity] ?? severity}
    </Badge>
  )
}
