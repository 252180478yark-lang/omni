'use client'

import { useEffect, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Inbox, CheckCircle2, XCircle, RefreshCw, Loader2, Clock,
} from 'lucide-react'

interface GateRow {
  id: string
  short_id: string
  tool_call_id: string
  tool_name: string | null
  summary: string
  args_preview: Record<string, unknown> | null
  timeout_seconds: number
  created_at: string
  age_seconds: number
}

interface ListResp {
  success: boolean
  data: GateRow[]
  total: number
  error?: string
}

function fmtAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

function fmtTimeout(s: number): string {
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

export default function InboxPage() {
  const [rows, setRows] = useState<GateRow[]>([])
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try {
      const resp = await fetch('/api/omni/inbox')
      const data: ListResp = await resp.json()
      if (data.success) {
        setRows(data.data)
      } else {
        window.alert(data.error ?? '加载失败')
      }
    } catch (err) {
      window.alert('网络异常：' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  async function actOn(id: string, kind: 'approve' | 'reject') {
    const note =
      kind === 'reject'
        ? (window.prompt('驳回理由（必填）：') ?? '').trim()
        : (window.prompt('备注（可选）：') ?? '').trim()
    if (kind === 'reject' && !note) {
      window.alert('驳回必须填理由')
      return
    }
    setActing(id)
    try {
      const resp = await fetch(`/api/omni/inbox/${id}/${kind}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note }),
      })
      const data = await resp.json()
      if (data.success && data.ok) {
        // 从列表删掉这一条，避免双批
        setRows((prev) => prev.filter((r) => r.id !== id))
      } else {
        window.alert(data.hint ?? data.error ?? `${kind} 失败`)
      }
    } catch (err) {
      window.alert('网络异常：' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setActing(null)
    }
  }

  return (
    <div className="px-6 py-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <Inbox className="w-7 h-7 text-amber-600" />
            待批
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            omni 要做的事得你点头 / 不点超时自动驳
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {/* Empty / Loading */}
      {loading ? (
        <div className="flex justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-gray-300" />
        </div>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="p-12 text-center">
            <Inbox className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <div className="text-sm text-gray-500">暂无待批</div>
            <div className="text-xs text-gray-400 mt-1">
              omni 跑到 require_approval 的 tool 时会出现在这里
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => (
            <Card key={r.id} className="hover:border-amber-300 transition">
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <code className="text-xs text-gray-400 font-mono">{r.short_id}</code>
                      <Badge className="bg-amber-100 text-amber-700 border-amber-200">
                        {r.tool_name ?? '?'}
                      </Badge>
                      <span className="text-xs text-gray-400 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {fmtAge(r.age_seconds)} · 超时 {fmtTimeout(r.timeout_seconds)}
                      </span>
                    </div>
                    <div className="text-sm text-gray-900 mb-2">{r.summary}</div>
                    {r.args_preview && (
                      <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto whitespace-pre-wrap break-words">
                        {JSON.stringify(r.args_preview, null, 2)}
                      </pre>
                    )}
                  </div>
                  <div className="flex flex-col gap-2 shrink-0">
                    <Button
                      size="sm"
                      className="bg-emerald-600 hover:bg-emerald-700 text-white"
                      disabled={acting === r.id}
                      onClick={() => actOn(r.id, 'approve')}
                    >
                      <CheckCircle2 className="w-4 h-4 mr-1" />
                      批
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="border-rose-300 text-rose-700 hover:bg-rose-50"
                      disabled={acting === r.id}
                      onClick={() => actOn(r.id, 'reject')}
                    >
                      <XCircle className="w-4 h-4 mr-1" />
                      驳
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
