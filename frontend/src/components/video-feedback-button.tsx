'use client'

import { useState } from 'react'
import { Loader2, MessageSquareWarning, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  /**
   * prompt_nodes.id —— 决定反馈进哪个节点的规则集。
   *   - 'content.scene_to_video'：对生成视频不满意（最常用）
   *   - 'content.script'：对脚本不满意
   *   - 'briefs.draft'：对 brief 整体不满意
   */
  nodeId: string
  /** 业务侧引用——存进 prompt_feedbacks.input_ref，方便回查上下文 */
  inputRef: Record<string, string | number | null | undefined>
  /** 按钮文案。默认"反馈" */
  label?: string
  /** 紧凑模式（小尺寸圆角）。 */
  compact?: boolean
}

/**
 * 通用"对此 LLM 输出反馈"按钮。
 * 点开弹一个简易输入框，提交到 POST /api/omni/prompt/feedback。
 * 反馈会汇总到 prompt-lab，供老板提炼成 prompt 规则补丁。
 */
export function VideoFeedbackButton({ nodeId, inputRef, label = '反馈', compact = true }: Props) {
  const [open, setOpen] = useState(false)
  const [complaint, setComplaint] = useState('')
  const [severity, setSeverity] = useState<'minor' | 'must_fix'>('must_fix')
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    if (!complaint.trim()) {
      setErr('请填一句话说明哪里不对')
      return
    }
    setErr(null)
    setSubmitting(true)
    try {
      const cleanRef: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(inputRef)) {
        if (v != null && v !== '') cleanRef[k] = v
      }
      const r = await fetch('/api/omni/prompt/feedback', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          node_id: nodeId,
          input_ref: cleanRef,
          rating: -1,
          severity,
          complaint: complaint.trim(),
        }),
      })
      if (!r.ok) throw new Error(`feedback ${r.status}`)
      setDone(true)
      setTimeout(() => {
        setDone(false)
        setOpen(false)
        setComplaint('')
      }, 1500)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) {
    return (
      <Button
        size="sm"
        variant="ghost"
        className={compact ? 'h-7 text-[11px] text-amber-700 hover:text-amber-800 hover:bg-amber-50' : ''}
        onClick={() => setOpen(true)}
      >
        <MessageSquareWarning className="w-3 h-3 mr-1" /> {label}
      </Button>
    )
  }

  return (
    <div className="border border-amber-200 bg-amber-50/60 rounded-lg p-3 space-y-2 text-xs">
      {done ? (
        <div className="flex items-center gap-2 text-emerald-700">
          <CheckCircle2 className="w-4 h-4" /> 已记录到 prompt-lab，可去提炼规则
        </div>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <span className="font-medium text-amber-900">这次哪里不满意？</span>
            <button
              type="button"
              className="text-[11px] text-gray-500 hover:text-gray-700"
              onClick={() => { setOpen(false); setComplaint(''); setErr(null) }}
            >
              取消
            </button>
          </div>
          <textarea
            className="w-full border border-amber-200 rounded px-2 py-1.5 text-xs min-h-[60px] focus:outline-none focus:border-amber-400"
            placeholder="例：开头 3 秒不抓人 / 卖点没讲清 / 镜头切太快 / 跟产品调性不符 …"
            value={complaint}
            onChange={(e) => setComplaint(e.target.value)}
            autoFocus
          />
          <div className="flex items-center justify-between">
            <div className="flex gap-1.5">
              <button
                type="button"
                onClick={() => setSeverity('must_fix')}
                className={`px-2 py-0.5 rounded border text-[11px] ${severity === 'must_fix' ? 'bg-rose-100 border-rose-300 text-rose-700' : 'bg-white border-gray-200 text-gray-500'}`}
              >
                必须改
              </button>
              <button
                type="button"
                onClick={() => setSeverity('minor')}
                className={`px-2 py-0.5 rounded border text-[11px] ${severity === 'minor' ? 'bg-amber-100 border-amber-300 text-amber-700' : 'bg-white border-gray-200 text-gray-500'}`}
              >
                小问题
              </button>
            </div>
            <Button size="sm" onClick={submit} disabled={submitting} className="h-7 text-[11px]">
              {submitting ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : null}
              提交反馈
            </Button>
          </div>
          {err && <div className="text-rose-600 text-[11px]">{err}</div>}
        </>
      )}
    </div>
  )
}
