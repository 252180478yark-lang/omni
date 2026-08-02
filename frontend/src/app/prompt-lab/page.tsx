'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Database, Inbox, RefreshCw } from 'lucide-react'

import { PromptNodeDrawer } from '@/components/prompt-node-drawer'
import { isWorkbenchFlagEnabled } from '@/lib/workbench-flags'

interface NodeStat {
  id: string
  title: string
  description: string | null
  page: string | null
  category: string | null
  enabled: boolean
  rule_count: number
  hits_7d: number
  fb_total_7d: number
  fb_negative_7d: number
  fb_total_prev_7d: number
  fb_negative_prev_7d: number
  neg_rate_7d: number | null
  neg_rate_prev_7d: number | null
  last_hit_at: string | null
}

const CATEGORY_LABELS: Record<string, string> = {
  ad_review: '投放复盘',
  content_studio: '内容工坊',
  chat: '智能问答',
  analysis: '多模态分析',
  knowledge: '知识采集',
  news: '资讯',
}

export default function PromptLabPage() {
  const readOnly = isWorkbenchFlagEnabled('unified_shell')
  const [nodes, setNodes] = useState<NodeStat[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeNode, setActiveNode] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/omni/prompt/nodes', { cache: 'no-store' })
      const body = await resp.json() as {
        success?: boolean
        data?: { nodes?: unknown }
        error?: unknown
      }
      if (!resp.ok || body.success !== true) throw new Error(String(body.error || 'load failed'))
      if (!Array.isArray(body.data?.nodes)) throw new Error('节点响应结构不兼容')
      setNodes(body.data.nodes as NodeStat[])
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const grouped = useMemo(() => {
    const out: Record<string, NodeStat[]> = {}
    for (const n of nodes) {
      const c = n.category || 'other'
      out[c] = out[c] || []
      out[c].push(n)
    }
    return out
  }, [nodes])

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Prompt 实验室</h1>
          <p className="text-xs text-muted-foreground">
            每个节点对应一个用户可见的 LLM 功能。在功能页面点 👎 提反馈后，规则会累积在这里，
            下次生成时自动带上以提升准确性。
          </p>
        </div>
        <button
          onClick={() => void load()}
          className="rounded border border-muted-foreground/30 px-2 py-1 text-xs hover:border-foreground"
        >
          刷新
        </button>
      </div>

      {readOnly ? (
        <div
          className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
          role="status"
          data-testid="prompt-lab-read-only-status"
        >
          开发工作台只读展示 Prompt 节点、规则与反馈状态；规则新增、编辑、启停和删除需从受控管理员流程执行。
        </div>
      ) : null}

      {loading && <div className="text-sm text-muted-foreground" role="status">加载中…</div>}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">
          <p className="font-medium">Prompt 节点读取失败</p>
          <p className="mt-1 break-words text-xs">{error}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-medium hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-600"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            重试读取
          </button>
        </div>
      )}

      {!loading && !error && nodes.length === 0 && (
        <section
          className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-slate-700"
          role="status"
          aria-labelledby="prompt-lab-empty-title"
          data-testid="prompt-lab-empty-state"
        >
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-slate-500 shadow-sm">
              <Inbox className="h-5 w-5" aria-hidden="true" />
            </span>
            <div className="space-y-2">
              <h2 id="prompt-lab-empty-title" className="font-semibold text-slate-900">暂无已登记的 Prompt 节点</h2>
              <p className="text-sm">
                节点接口已成功响应，但当前没有真实节点。本页不会临时生成假节点，也不代表高级评测后端已经就绪。
              </p>
              <p className="flex items-start gap-1.5 text-xs text-slate-600">
                <Database className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                请先确认 P0 数据库迁移已执行、知识服务已连接并完成真实节点登记；节点由后端合同创建，不在本页伪造。
              </p>
              <button
                type="button"
                onClick={() => void load()}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-800 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-600"
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                重新读取节点
              </button>
            </div>
          </div>
        </section>
      )}

      {Object.entries(grouped).map(([cat, items]) => (
        <section key={cat} className="space-y-2">
          <h2 className="text-sm font-semibold text-muted-foreground">
            {CATEGORY_LABELS[cat] || cat}
          </h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {items.map((n) => {
              const negPct = formatRateChange(n.neg_rate_prev_7d, n.neg_rate_7d)
              return (
                <button
                  key={n.id}
                  onClick={() => setActiveNode(n.id)}
                  className="group rounded border border-muted-foreground/30 p-3 text-left hover:border-foreground"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{n.title}</span>
                    {n.rule_count > 0 && (
                      <span className="rounded bg-muted px-1.5 text-[11px]">
                        {n.rule_count} 条规则
                      </span>
                    )}
                  </div>
                  {n.description && (
                    <div className="mt-1 text-xs text-muted-foreground">
                      {n.description}
                    </div>
                  )}
                  <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                    <span>7 天命中 {n.hits_7d}</span>
                    <span>
                      7 天反馈 {n.fb_total_7d}
                      {n.fb_negative_7d > 0 && (
                        <span className="text-orange-600">
                          {' '}
                          ({n.fb_negative_7d} 不满意)
                        </span>
                      )}
                    </span>
                    {negPct && <span>👎 率 {negPct}</span>}
                    {n.page && <code className="text-[10px]">{n.page}</code>}
                  </div>
                </button>
              )
            })}
          </div>
        </section>
      ))}

      <PromptNodeDrawer
        nodeId={activeNode}
        readOnly={readOnly}
        onClose={() => {
          setActiveNode(null)
          void load()
        }}
      />
    </div>
  )
}

function formatRateChange(prev: number | null, cur: number | null): string | null {
  if (cur === null && prev === null) return null
  if (cur === null) return null
  const pct = (v: number) => `${Math.round(v * 100)}%`
  if (prev === null) return pct(cur)
  return `${pct(prev)} → ${pct(cur)}`
}
