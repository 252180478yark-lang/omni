'use client'
import { useEffect, useRef } from 'react'
import { Send, Square, MessageSquare, DollarSign, Clock, Hash } from 'lucide-react'
import { usePlaygroundStore } from '@/stores/playground'
import { MessageBubble } from '@/components/agent-chat/MessageBubble'
import { ToolCallChip } from '@/components/agent-chat/ToolCallChip'
import { JsonAttachment } from '@/components/agent-chat/attachments/JsonAttachment'
import { MarkdownAttachment } from '@/components/agent-chat/attachments/MarkdownAttachment'

interface Props {
  /** ConfigPanel 点"运行"或 textarea 回车都走这个 */
  onSend: (prompt: string) => void
  onCancel: () => void
  connected: boolean
}

export function ConvPane({ onSend, onCancel, connected }: Props) {
  const input = usePlaygroundStore((s) => s.pendingInput)
  const setInput = usePlaygroundStore((s) => s.setPendingInput)
  const messages = usePlaygroundStore((s) => s.messages)
  const running = usePlaygroundStore((s) => s.running)
  const tokensIn = usePlaygroundStore((s) => s.tokensIn)
  const tokensOut = usePlaygroundStore((s) => s.tokensOut)
  const toolApiCostUsd = usePlaygroundStore((s) => s.toolApiCostUsd)
  const totalLatencyMs = usePlaygroundStore((s) => s.totalLatencyMs)
  const toolCalls = usePlaygroundStore((s) => s.toolCalls)
  const bottomRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length])

  const handleSend = () => {
    const text = input.trim()
    if (!text || running) return
    onSend(text)
    setInput('')
  }

  return (
    <main className="flex-1 flex flex-col min-w-0 bg-white">
      {/* Status bar */}
      <header className="h-14 px-4 border-b border-gray-100 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-violet-600" />
          <h2 className="text-sm font-semibold text-gray-900">对话</h2>
          <span
            className={`text-[10px] ml-2 px-1.5 py-0.5 rounded ${
              connected ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'
            }`}
          >
            {connected ? '● 连接' : '○ 断开'}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-gray-600">
          <span className="inline-flex items-center gap-1">
            <Hash className="w-3 h-3 text-gray-400" />
            {tokensIn.toLocaleString()} / {tokensOut.toLocaleString()} tok
          </span>
          <span className="inline-flex items-center gap-1">
            <DollarSign className="w-3 h-3 text-gray-400" />
            {toolApiCostUsd > 0 ? `$${toolApiCostUsd.toFixed(4)}` : '—'}
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock className="w-3 h-3 text-gray-400" />
            {totalLatencyMs > 0 ? `${(totalLatencyMs / 1000).toFixed(1)}s` : '—'}
          </span>
          <span className="text-gray-400">·</span>
          <span>{toolCalls.length} tool calls</span>
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-3 bg-gradient-to-b from-gray-50/40 to-white">
        {messages.length === 0 && (
          <div className="mt-20 text-center text-gray-400 text-sm">
            左侧调好配置 + 下方输入 prompt 开测.
            <div className="mt-2 text-[11px] text-gray-300">
              示例:&quot;调 list_skus 看头 10 个&quot; / &quot;给 SKU-376253-0012 跑全链路&quot;
            </div>
          </div>
        )}
        {messages.map((m) => {
          if (m.role === 'user' || m.role === 'assistant') {
            return <MessageBubble key={m.id} role={m.role} text={m.text || ''} />
          }
          if (m.role === 'tool_call') {
            // 找对应的 tool_call trace 看看有没有 trace 字段
            const tc = toolCalls.find((t) => t.tool_use_id === m.tool_use_id)
            const hasTrace = !!tc?.trace_field
            return (
              <div key={m.id} className="self-start flex flex-col gap-1">
                <ToolCallChip
                  toolName={m.tool_name || ''}
                  args={m.tool_args}
                  status={m.tool_status || 'pending'}
                />
                {hasTrace && (
                  <div className="ml-3 text-[10px] text-violet-600">
                    → 右侧 TracePane 查看次级 LLM 调用详情
                  </div>
                )}
              </div>
            )
          }
          if (m.role === 'tool_result') {
            return (
              <div key={m.id} className="self-start ml-11">
                <ToolResultBlock raw={m.raw_result} />
              </div>
            )
          }
          return null
        })}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-100 bg-white px-4 py-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            placeholder="输入 prompt 测 tool/skill,回车发送 (Shift+Enter 换行)"
            rows={2}
            className="flex-1 resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:border-violet-400 max-h-40 font-mono"
          />
          {running ? (
            <button
              onClick={onCancel}
              className="shrink-0 w-9 h-9 rounded-lg bg-red-500 text-white flex items-center justify-center hover:bg-red-600"
              title="停止"
            >
              <Square className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim() || !connected}
              className="shrink-0 w-9 h-9 rounded-lg bg-violet-600 text-white flex items-center justify-center hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed"
              title="发送"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </main>
  )
}

/** 把 tool_result raw 渲染:JSON / markdown 都展开 */
function ToolResultBlock({ raw }: { raw: unknown }) {
  // 解析 string 形式的 JSON
  let parsed: unknown = null
  if (typeof raw === 'string') {
    try {
      parsed = JSON.parse(raw)
    } catch {
      parsed = null
    }
  } else if (Array.isArray(raw) && raw.length > 0) {
    const first = raw[0] as { type?: string; text?: string }
    if (first?.text) {
      try {
        parsed = JSON.parse(first.text)
      } catch {
        return (
          <div className="rounded-lg border border-gray-200 bg-white p-3 max-w-2xl">
            <div className="text-[10px] text-gray-400 mb-1">tool_result (text)</div>
            <pre className="text-[11px] whitespace-pre-wrap text-gray-800">{first.text}</pre>
          </div>
        )
      }
    }
  } else if (typeof raw === 'object' && raw !== null) {
    parsed = raw
  }

  if (parsed && typeof parsed === 'object') {
    const obj = parsed as Record<string, unknown>
    const ok = obj.ok
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-3 max-w-2xl flex flex-col gap-2">
        <div className="flex items-center gap-2 text-[10px]">
          <span className={ok === false ? 'text-red-600' : 'text-emerald-700'}>
            {ok === false ? '✗ failed' : '✓ ok'}
          </span>
          {typeof obj.next_step_hint === 'object' && obj.next_step_hint !== null && (
            <span className="text-gray-400">
              · 建议下一步:{(obj.next_step_hint as { suggested_tool?: string }).suggested_tool || '—'}
            </span>
          )}
        </div>
        {typeof (obj.result as { brief_md?: string })?.brief_md === 'string' && (
          <MarkdownAttachment markdown={(obj.result as { brief_md: string }).brief_md} />
        )}
        <JsonAttachment data={parsed} />
      </div>
    )
  }

  return <JsonAttachment data={raw} />
}
