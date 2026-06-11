'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Loader2, ThumbsUp, ThumbsDown } from 'lucide-react'

/**
 * 产物点评组件 — 挂在每个 LLM 生成结果下方（反馈飞轮铁律 D 的页面级出口）。
 *
 * 老板原话需求：「生成的结果我需要有一个评论界面——明显质量不合格的，
 * 我直接说为什么不合格、怎么不合格，反推迭代让 tools 越来越好用」。
 *
 * 数据通路：POST /api/omni/feedback/rate-tool → KE /api/v1/mcp/tool-calls/rate-recent
 * （按 tool_name 取最近一条 tool_call 评分）→ mcp.tool_calls.user_rating + rating_category
 * → 每周 feedback_digest cron 聚类 → 诊断官《改进提议》。
 */

// 反馈分类 7 类（与 mcp.tool_calls.rating_category / CLAUDE.md 反馈飞轮对齐）
const CATEGORIES: { value: string; label: string }[] = [
  { value: 'prompt_bad', label: '提示词不对' },
  { value: 'tradeoff_wrong', label: '取舍重点错' },
  { value: 'factual_error', label: '事实数据错' },
  { value: 'tone_off', label: '语气风格不对' },
  { value: 'wrong_tool', label: '调错/漏调工具' },
  { value: 'incomplete', label: '答得不完整' },
  { value: 'other', label: '其他' },
]

export interface OutputFeedbackProps {
  /** mcp tool 名（按它取最近一条 tool_call 评分），如 generate_audience_portrait */
  toolName: string
  /** 引导文案，默认「这个产物怎么样？」 */
  label?: string
  className?: string
}

type Phase = 'idle' | 'good_done' | 'bad_panel' | 'submitting' | 'done' | 'error'

export default function OutputFeedback({ toolName, label, className }: OutputFeedbackProps) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [category, setCategory] = useState<string>('')
  const [note, setNote] = useState('')
  const [goodNote, setGoodNote] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  // 失败重试时回到哪个动作（good 直提 / bad 面板提交）
  const [lastAction, setLastAction] = useState<'good' | 'bad' | null>(null)

  const submit = async (rating: 'good' | 'bad', cat?: string, noteText?: string) => {
    setPhase('submitting')
    setErrorMsg(null)
    setLastAction(rating)
    try {
      const res = await fetch('/api/omni/feedback/rate-tool', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_name: toolName,
          rating,
          category: cat || null,
          note: (noteText || '').slice(0, 500),
        }),
      })
      const json = await res.json()
      if (json.success) {
        setPhase(rating === 'good' ? 'good_done' : 'done')
      } else {
        setErrorMsg(json.error || '提交失败')
        setPhase('error')
      }
    } catch (e) {
      setErrorMsg(String(e))
      setPhase('error')
    }
  }

  // 终态：已记录
  if (phase === 'done') {
    return (
      <div className={`mt-4 border-t pt-3 text-xs text-emerald-700 dark:text-emerald-400 ${className || ''}`}>
        ✓ 已记录，会进每周改进提议
      </div>
    )
  }

  // 👍 提交成功：已记录 + 可选补一句（再提交一次覆盖同条评分的 note）
  if (phase === 'good_done') {
    return (
      <div className={`mt-4 border-t pt-3 space-y-2 ${className || ''}`}>
        <div className="text-xs text-emerald-700 dark:text-emerald-400">已记录 ✓</div>
        <div className="flex items-center gap-2">
          <input
            className="flex-1 border rounded px-2 py-1 text-xs bg-background"
            placeholder="想补一句？（可选，回车或点发送）"
            value={goodNote}
            maxLength={500}
            onChange={e => setGoodNote(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && goodNote.trim()) submit('good', undefined, goodNote.trim())
            }}
          />
          <Button
            size="sm"
            variant="outline"
            className="text-xs h-7"
            disabled={!goodNote.trim()}
            onClick={() => submit('good', undefined, goodNote.trim())}
          >
            发送
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className={`mt-4 border-t pt-3 space-y-3 ${className || ''}`}>
      {/* 紧凑一行：引导语 + 👍 👎 */}
      <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
        <span>{label || '这个产物怎么样？'}</span>
        <Button
          size="sm"
          variant="outline"
          className="text-xs h-7 px-2"
          disabled={phase === 'submitting'}
          onClick={() => submit('good')}
          title="质量 OK，直接记一条好评"
        >
          {phase === 'submitting' && lastAction === 'good'
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : <ThumbsUp className="w-3.5 h-3.5" />}
        </Button>
        <Button
          size="sm"
          variant={phase === 'bad_panel' ? 'default' : 'outline'}
          className="text-xs h-7 px-2"
          disabled={phase === 'submitting'}
          onClick={() => {
            setPhase(phase === 'bad_panel' ? 'idle' : 'bad_panel')
            setErrorMsg(null)
          }}
          title="不合格——展开说为什么、怎么不合格"
        >
          <ThumbsDown className="w-3.5 h-3.5" />
        </Button>
        <span className="text-[10px]">（评分按 {toolName} 最近一次调用记账，进每周改进提议）</span>
      </div>

      {/* 👎 展开面板：7 分类 chip 单选 + 具体说明 */}
      {(phase === 'bad_panel' || (phase === 'error' && lastAction === 'bad') || (phase === 'submitting' && lastAction === 'bad')) && (
        <div className="border rounded p-3 bg-muted/30 space-y-3">
          <div>
            <div className="text-xs font-medium mb-1.5">哪类问题？（单选）</div>
            <div className="flex gap-1.5 flex-wrap">
              {CATEGORIES.map(c => {
                const selected = category === c.value
                return (
                  <button
                    key={c.value}
                    type="button"
                    className={`text-xs px-2 py-1 rounded-full border transition-colors ${selected ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background hover:bg-muted'}`}
                    onClick={() => setCategory(selected ? '' : c.value)}
                  >
                    {selected && '✓ '}{c.label}
                  </button>
                )
              })}
            </div>
          </div>
          <Textarea
            placeholder="为什么不合格、怎么不合格——写得越具体，改得越准"
            value={note}
            maxLength={500}
            onChange={e => setNote(e.target.value)}
            rows={3}
            className="text-sm"
          />
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={phase === 'submitting' || !category}
              onClick={() => submit('bad', category, note.trim())}
              className="text-xs h-7"
            >
              {phase === 'submitting'
                ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 提交中</>
                : '提交反馈'}
            </Button>
            {!category && (
              <span className="text-[10px] text-muted-foreground">先选一类问题</span>
            )}
            <span className="text-[10px] text-muted-foreground ml-auto">{note.length}/500</span>
          </div>
        </div>
      )}

      {/* 失败 + 重试 */}
      {phase === 'error' && (
        <div className="text-xs text-red-600 dark:text-red-400 p-2 border border-red-200 dark:border-red-900 rounded bg-red-50 dark:bg-red-950/30 flex items-center gap-2 flex-wrap">
          <span>提交失败：{errorMsg}</span>
          {lastAction === 'good' && (
            <Button size="sm" variant="outline" className="text-xs h-6" onClick={() => submit('good')}>
              重试
            </Button>
          )}
          {/* bad 路径面板还在上面，改完直接再点提交即可 */}
        </div>
      )}
    </div>
  )
}
