'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { PromptNodeDrawer } from '@/components/prompt-node-drawer'

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
  const [nodes, setNodes] = useState<NodeStat[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeNode, setActiveNode] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/omni/prompt/nodes', { cache: 'no-store' })
      const body = await resp.json()
      if (!body.success) throw new Error(body.error || 'load failed')
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

      {loading && <div className="text-sm text-muted-foreground">加载中…</div>}
      {error && <div className="text-sm text-red-500">{error}</div>}

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
