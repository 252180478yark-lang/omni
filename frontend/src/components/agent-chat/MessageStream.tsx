'use client'
import { useEffect, useRef } from 'react'
import type { ChatMessage } from '@/lib/agent-chat/types'
import { MessageBubble } from './MessageBubble'
import { ToolCallChip } from './ToolCallChip'
import { ToolResultCard } from './ToolResultCard'
import { HumanGateCard } from './HumanGateCard'

interface Props {
  messages: ChatMessage[]
  onDecideGate: (shortId: string, decision: 'approved' | 'rejected', note?: string) => void
}

export function MessageStream({ messages, onDecideGate }: Props) {
  const bottomRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length])

  return (
    <div className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-4 bg-gradient-to-b from-gray-50 to-white">
      {messages.length === 0 && (
        <div className="text-center text-gray-400 text-sm mt-20">
          开始一段对话，让 omni 帮你跑 tool 出结果。
        </div>
      )}
      {messages.map((m) => {
        if (m.role === 'user' || m.role === 'assistant') {
          return <MessageBubble key={m.id} role={m.role} text={m.text || ''} />
        }
        if (m.role === 'tool_call') {
          return (
            <div key={m.id} className="self-start">
              <ToolCallChip
                toolName={m.tool_name || ''}
                args={m.tool_args}
                status={m.tool_status || 'pending'}
              />
            </div>
          )
        }
        if (m.role === 'tool_result') {
          return (
            <div key={m.id} className="self-start ml-11">
              <ToolResultCard
                attachments={m.attachments || []}
                rawResult={m.raw_result}
              />
            </div>
          )
        }
        if (m.role === 'human_gate' && m.gate_short_id) {
          return (
            <HumanGateCard
              key={m.id}
              shortId={m.gate_short_id}
              summary={m.gate_summary || ''}
              decision={m.gate_decision || 'pending'}
              onDecide={(d, n) => onDecideGate(m.gate_short_id!, d, n)}
            />
          )
        }
        return null
      })}
      <div ref={bottomRef} />
    </div>
  )
}
