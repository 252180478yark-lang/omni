'use client'

import { useCallback, useEffect, useId, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface Rule {
  id: string
  node_id: string
  rule_text: string
  scope: Record<string, unknown> | null
  hit_count: number
  last_hit_at: string | null
  enabled: boolean
  created_at: string
}

interface FeedbackPreview {
  id: string
  node_id: string
  rating: number | null
  severity: string | null
  complaint: string | null
  distilled: string | null
  applied_as: string | null
  created_at: string
  prompt_preview: string | null
  output_preview: string | null
}

interface NodeDetail {
  node: {
    id: string
    title: string
    description: string | null
    page: string | null
    category: string | null
  }
  rules: Rule[]
  recent_feedbacks: FeedbackPreview[]
}

export interface PromptNodeDrawerProps {
  nodeId: string | null
  onClose: () => void
  readOnly?: boolean
}

/** 节点详情抽屉 — 查看/编辑/删除规则 + 翻阅反馈历史 + 手动加规则 */
export function PromptNodeDrawer({ nodeId, onClose, readOnly = false }: PromptNodeDrawerProps) {
  const [detail, setDetail] = useState<NodeDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [newRule, setNewRule] = useState('')
  const [busy, setBusy] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const onCloseRef = useRef(onClose)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!nodeId) return

    returnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const frame = window.requestAnimationFrame(() => {
      panelRef.current?.querySelector<HTMLElement>('[data-prompt-drawer-close]')?.focus()
    })
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return

      const panel = panelRef.current
      if (!panel) return
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )).filter((element) => element.getAttribute('aria-hidden') !== 'true')
      if (focusable.length === 0) {
        event.preventDefault()
        panel.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement
      if (event.shiftKey && (active === first || !panel.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      window.cancelAnimationFrame(frame)
      document.removeEventListener('keydown', handleKeyDown)
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus()
      returnFocusRef.current = null
    }
  }, [nodeId])

  const load = useCallback(async (id: string) => {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch(`/api/omni/prompt/nodes/${encodeURIComponent(id)}`, {
        cache: 'no-store',
      })
      const body = await resp.json()
      if (!body.success) throw new Error(body.error || 'load failed')
      setDetail(body.data as NodeDetail)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (nodeId) {
      void load(nodeId)
    } else {
      setDetail(null)
    }
  }, [nodeId, load])

  const toggleRule = useCallback(
    async (rule: Rule) => {
      if (readOnly) return
      setBusy(true)
      try {
        await fetch(`/api/omni/prompt/rules/${rule.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !rule.enabled }),
        })
        if (nodeId) await load(nodeId)
      } finally {
        setBusy(false)
      }
    },
    [nodeId, load, readOnly],
  )

  const deleteRule = useCallback(
    async (rule: Rule) => {
      if (readOnly) return
      if (!confirm(`删除规则: "${rule.rule_text.slice(0, 40)}…"?`)) return
      setBusy(true)
      try {
        await fetch(`/api/omni/prompt/rules/${rule.id}`, { method: 'DELETE' })
        if (nodeId) await load(nodeId)
      } finally {
        setBusy(false)
      }
    },
    [nodeId, load, readOnly],
  )

  const editRule = useCallback(
    async (rule: Rule) => {
      if (readOnly) return
      const next = prompt('编辑规则:', rule.rule_text)?.trim()
      if (!next || next === rule.rule_text) return
      setBusy(true)
      try {
        await fetch(`/api/omni/prompt/rules/${rule.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rule_text: next }),
        })
        if (nodeId) await load(nodeId)
      } finally {
        setBusy(false)
      }
    },
    [nodeId, load, readOnly],
  )

  const createManualRule = useCallback(async () => {
    if (readOnly || !nodeId || !newRule.trim()) return
    setBusy(true)
    try {
      await fetch('/api/omni/prompt/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          node_id: nodeId,
          rule_text: newRule.trim(),
          enabled: true,
        }),
      })
      setNewRule('')
      await load(nodeId)
    } finally {
      setBusy(false)
    }
  }, [nodeId, newRule, load, readOnly])

  if (!nodeId) return null

  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="flex-1 bg-black/40 backdrop-blur-[1px]"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={detail?.node.description ? descriptionId : undefined}
        tabIndex={-1}
        className="h-full w-full max-w-[560px] overflow-y-auto border-l bg-background p-4 shadow-xl sm:p-6"
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="text-sm text-muted-foreground">Prompt 节点</div>
            <div id={titleId} className="text-lg font-semibold">
              {detail?.node.title || nodeId}
            </div>
            {detail?.node.description && (
              <div id={descriptionId} className="mt-1 text-xs text-muted-foreground">
                {detail.node.description}
              </div>
            )}
            {detail?.node.page && (
              <div className="mt-1 text-xs text-muted-foreground">
                入口: <code>{detail.node.page}</code>
              </div>
            )}
          </div>
          <Button data-prompt-drawer-close variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
        </div>

        {loading && <div className="mt-4 text-sm text-muted-foreground" role="status">加载中…</div>}
        {error && <div className="mt-4 text-sm text-red-500" role="alert">{error}</div>}

        {readOnly ? (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900" role="status">
            只读检查模式：规则写操作已关闭。
          </div>
        ) : null}

        {detail && (
          <div className="mt-4 space-y-6">
            {/* 规则列表 */}
            <section>
              <div className="mb-2 flex items-center justify-between text-sm font-medium">
                <span>已生效补丁规则 ({detail.rules.length})</span>
              </div>
              {detail.rules.length === 0 && (
                <div className="rounded border border-dashed px-3 py-4 text-xs text-muted-foreground">
                  还没有规则。在生成结果下方点 👎 提反馈，或在下方手动添加。
                </div>
              )}
              <div className="space-y-2">
                {detail.rules.map((r, i) => (
                  <div
                    key={r.id}
                    className={[
                      'rounded border p-2 text-xs',
                      r.enabled ? 'border-muted-foreground/30' : 'border-dashed opacity-60',
                    ].join(' ')}
                  >
                    <div className="flex items-start gap-2">
                      <span className="shrink-0 text-muted-foreground">{i + 1}.</span>
                      <div className="flex-1">
                        <div className="whitespace-pre-wrap">{r.rule_text}</div>
                        <div className="mt-1 flex flex-wrap gap-3 text-[10px] text-muted-foreground">
                          <span>命中 {r.hit_count} 次</span>
                          {r.last_hit_at && (
                            <span>
                              最近 {new Date(r.last_hit_at).toLocaleString('zh-CN')}
                            </span>
                          )}
                          {r.scope && Object.keys(r.scope).length > 0 && (
                            <span>
                              scope: <code>{JSON.stringify(r.scope)}</code>
                            </span>
                          )}
                        </div>
                      </div>
                      {!readOnly ? <div className="flex shrink-0 gap-1">
                        <button
                          className="text-[11px] text-muted-foreground hover:text-foreground"
                          onClick={() => editRule(r)}
                          disabled={busy}
                        >
                          编辑
                        </button>
                        <button
                          className="text-[11px] text-muted-foreground hover:text-foreground"
                          onClick={() => toggleRule(r)}
                          disabled={busy}
                        >
                          {r.enabled ? '禁用' : '启用'}
                        </button>
                        <button
                          className="text-[11px] text-red-500 hover:underline"
                          onClick={() => deleteRule(r)}
                          disabled={busy}
                        >
                          删除
                        </button>
                      </div> : null}
                    </div>
                  </div>
                ))}
              </div>

              {!readOnly ? <div className="mt-3 space-y-2">
                <div className="text-xs text-muted-foreground">手动添加规则:</div>
                <Textarea
                  value={newRule}
                  onChange={(e) => setNewRule(e.target.value)}
                  placeholder="例: 禁止归因到 CPM，必须追溯到 CTR 或 CVR"
                  rows={2}
                  className="text-xs"
                />
                <div className="flex justify-end">
                  <Button
                    size="sm"
                    onClick={createManualRule}
                    disabled={busy || !newRule.trim()}
                  >
                    添加
                  </Button>
                </div>
              </div> : null}
            </section>

            {/* 反馈历史 */}
            <section>
              <div className="mb-2 text-sm font-medium">
                最近反馈 ({detail.recent_feedbacks.length})
              </div>
              {detail.recent_feedbacks.length === 0 && (
                <div className="rounded border border-dashed px-3 py-4 text-xs text-muted-foreground">
                  暂无反馈记录
                </div>
              )}
              <div className="space-y-1">
                {detail.recent_feedbacks.map((f) => {
                  const emoji = f.rating === 1 ? '👍' : f.rating === -1 ? '👎' : '•'
                  const dateLabel = new Date(f.created_at).toLocaleString('zh-CN')
                  return (
                    <div
                      key={f.id}
                      className="rounded border border-muted-foreground/20 p-2 text-[11px]"
                    >
                      <div className="flex items-center gap-2">
                        <span>{emoji}</span>
                        <span className="text-muted-foreground">{dateLabel}</span>
                        {f.severity && (
                          <span className="rounded bg-muted px-1.5">
                            {f.severity === 'must_fix'
                              ? '必须改'
                              : f.severity === 'minor'
                                ? '小毛病'
                                : '一次性'}
                          </span>
                        )}
                        {f.applied_as && (
                          <span className="text-green-600">→ 已入库为规则</span>
                        )}
                      </div>
                      {f.complaint && (
                        <div className="mt-1 whitespace-pre-wrap text-muted-foreground">
                          吐槽: {f.complaint}
                        </div>
                      )}
                      {f.distilled && f.distilled !== 'SKIP' && (
                        <div className="mt-1 text-muted-foreground">
                          提炼: <em>{f.distilled}</em>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
