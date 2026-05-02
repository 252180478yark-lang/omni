'use client'

import { useCallback, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

/**
 * 行内反馈组件 — 挂在每个 LLM 生成结果下方。
 *
 * 使用流程:
 *   用户点 👍 / 👎 → 写"哪里不对" → 后端提炼成规则草稿 → 用户确认入库
 *
 * 设计原则:
 *   - 不阻塞用户,所有操作 optimistic
 *   - 默认收起,只显示一排小按钮
 *   - 最小化打扰 (👍 一键完成)
 */
export interface PromptFeedbackProps {
  nodeId: string
  /** 业务侧引用（campaign_id / pipeline_id / chat_msg_id …） */
  inputRef?: Record<string, unknown>
  /** 刚生成的内容（供用户对比；过长会被截断） */
  output?: string
  /** 可选: 本次 LLM 实际使用的 prompt（供"查看本次 prompt"调试） */
  fullPrompt?: string
  /** 可选: 打开节点抽屉的回调（父组件提供） */
  onOpenDrawer?: (nodeId: string) => void
  className?: string
}

type Phase = 'idle' | 'complaint' | 'distilling' | 'review' | 'done'

export function PromptFeedback({
  nodeId,
  inputRef,
  output,
  fullPrompt,
  onOpenDrawer,
  className,
}: PromptFeedbackProps) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [feedbackId, setFeedbackId] = useState<string | null>(null)
  const [complaint, setComplaint] = useState('')
  const [severity, setSeverity] = useState<'minor' | 'must_fix' | 'ignorable'>('must_fix')
  const [draft, setDraft] = useState<string | null>(null)
  const [scopeApply, setScopeApply] = useState<'all' | 'current'>('all')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const log = useCallback(
    async (rating: 1 | -1): Promise<string | null> => {
      try {
        const resp = await fetch('/api/omni/prompt/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            node_id: nodeId,
            input_ref: inputRef || null,
            full_prompt: fullPrompt || null,
            output: output || null,
            rating,
          }),
        })
        const body = await resp.json()
        if (!body.success) throw new Error(body.error || 'feedback failed')
        return body.data.id as string
      } catch (err) {
        setError(String(err))
        return null
      }
    },
    [nodeId, inputRef, fullPrompt, output],
  )

  const handleThumbUp = useCallback(async () => {
    setBusy(true)
    const id = await log(1)
    if (id) {
      setFeedbackId(id)
      setPhase('done')
    }
    setBusy(false)
  }, [log])

  const handleThumbDown = useCallback(() => {
    setPhase('complaint')
  }, [])

  const handleSubmitComplaint = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      // 1. 先记一条反馈（带 complaint + severity）
      const resp = await fetch('/api/omni/prompt/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          node_id: nodeId,
          input_ref: inputRef || null,
          full_prompt: fullPrompt || null,
          output: output || null,
          rating: -1,
          severity,
          complaint: complaint.trim() || null,
        }),
      })
      const body = await resp.json()
      if (!body.success) throw new Error(body.error || 'feedback failed')
      const fbId: string = body.data.id
      setFeedbackId(fbId)

      // 2. 若用户写了 complaint,让 LLM 提炼成规则草稿
      if (complaint.trim() && severity !== 'ignorable') {
        setPhase('distilling')
        const distillResp = await fetch(
          `/api/omni/prompt/feedback/${fbId}/distill`,
          { method: 'POST' },
        )
        const distillBody = await distillResp.json()
        if (distillBody.success) {
          const d = distillBody.data?.draft as string | null
          if (d) {
            setDraft(d)
            setPhase('review')
          } else {
            // 模型判断无可复用结论 (SKIP),直接完成
            setPhase('done')
          }
        } else {
          // 提炼失败不挡流程,让用户直接手写规则
          setDraft('')
          setPhase('review')
        }
      } else {
        setPhase('done')
      }
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }, [nodeId, inputRef, fullPrompt, output, complaint, severity])

  const handleConfirmRule = useCallback(async () => {
    if (!draft?.trim() || !feedbackId) return
    setBusy(true)
    setError(null)
    try {
      const scope =
        scopeApply === 'current' && inputRef && Object.keys(inputRef).length > 0
          ? inputRef
          : null
      const resp = await fetch('/api/omni/prompt/rules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          node_id: nodeId,
          rule_text: draft.trim(),
          scope,
          created_from: feedbackId,
          enabled: true,
        }),
      })
      const body = await resp.json()
      if (!body.success) throw new Error(body.error || 'rule create failed')
      setPhase('done')
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }, [draft, feedbackId, inputRef, nodeId, scopeApply])

  const handleSkipRule = useCallback(() => {
    setPhase('done')
  }, [])

  return (
    <div
      className={[
        'rounded-md border border-muted-foreground/20 bg-muted/20 p-2 text-xs',
        className || '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {phase === 'idle' && (
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground">对这次生成满意吗?</span>
          <Button
            variant="outline"
            size="sm"
            onClick={handleThumbUp}
            disabled={busy}
            className="h-7 px-2"
          >
            👍 满意
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleThumbDown}
            disabled={busy}
            className="h-7 px-2"
          >
            👎 不满意
          </Button>
          <div className="ml-auto flex items-center gap-2 text-muted-foreground">
            {onOpenDrawer && (
              <button
                type="button"
                onClick={() => onOpenDrawer(nodeId)}
                className="underline decoration-dotted hover:text-foreground"
              >
                本节点已生效规则 / 历史反馈 →
              </button>
            )}
          </div>
        </div>
      )}

      {phase === 'complaint' && (
        <div className="space-y-2">
          <div className="text-muted-foreground">这次哪里不对?（写下来会变成下次的规则）</div>
          <Textarea
            placeholder="例: 复盘把 CPM 当原因了,应该追到 CTR/CVR"
            value={complaint}
            onChange={(e) => setComplaint(e.target.value)}
            rows={2}
            className="text-xs"
          />
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">严重程度:</span>
              {(['minor', 'must_fix', 'ignorable'] as const).map((s) => (
                <label
                  key={s}
                  className={[
                    'cursor-pointer rounded border px-2 py-0.5',
                    severity === s
                      ? 'border-foreground bg-foreground/10 text-foreground'
                      : 'border-muted-foreground/30 text-muted-foreground',
                  ].join(' ')}
                >
                  <input
                    type="radio"
                    name={`sev-${nodeId}`}
                    className="hidden"
                    checked={severity === s}
                    onChange={() => setSeverity(s)}
                  />
                  {s === 'minor' ? '小毛病' : s === 'must_fix' ? '必须改' : '一次性/忽略'}
                </label>
              ))}
            </div>
            <div className="ml-auto flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPhase('idle')}
                className="h-7"
              >
                取消
              </Button>
              <Button
                size="sm"
                onClick={handleSubmitComplaint}
                disabled={busy}
                className="h-7"
              >
                {busy ? '提交中…' : '提交'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {phase === 'distilling' && (
        <div className="text-muted-foreground">正在用 LLM 把你的吐槽提炼成可复用规则…</div>
      )}

      {phase === 'review' && (
        <div className="space-y-2">
          <div className="text-muted-foreground">
            建议规则（会在下次该节点所有生成时自动带上，你可以编辑）:
          </div>
          <Textarea
            value={draft ?? ''}
            onChange={(e) => setDraft(e.target.value)}
            rows={2}
            className="text-xs"
          />
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-muted-foreground">适用范围:</span>
            {(
              [
                ['all', '本节点全部'],
                ['current', '仅当前 scope'],
              ] as const
            ).map(([v, label]) => (
              <label
                key={v}
                className={[
                  'cursor-pointer rounded border px-2 py-0.5',
                  scopeApply === v
                    ? 'border-foreground bg-foreground/10 text-foreground'
                    : 'border-muted-foreground/30 text-muted-foreground',
                ].join(' ')}
              >
                <input
                  type="radio"
                  name={`scope-${nodeId}`}
                  className="hidden"
                  checked={scopeApply === v}
                  onChange={() => setScopeApply(v as 'all' | 'current')}
                />
                {label}
              </label>
            ))}
            <div className="ml-auto flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleSkipRule}
                className="h-7"
                disabled={busy}
              >
                丢弃
              </Button>
              <Button
                size="sm"
                onClick={handleConfirmRule}
                disabled={busy || !draft?.trim()}
                className="h-7"
              >
                {busy ? '入库中…' : '入库生效'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {phase === 'done' && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <span>✓ 已记录</span>
          {onOpenDrawer && (
            <button
              type="button"
              onClick={() => onOpenDrawer(nodeId)}
              className="underline decoration-dotted hover:text-foreground"
            >
              查看本节点规则 →
            </button>
          )}
        </div>
      )}

      {error && <div className="mt-1 text-red-500">错误: {error}</div>}
    </div>
  )
}
