'use client'
import { useState } from 'react'
import { useAgentChat } from '@/hooks/useAgentChat'
import { SessionList } from './SessionList'
import { MessageStream } from './MessageStream'
import { InputBar } from './InputBar'
import { AlertCircle } from 'lucide-react'

export function ChatLayout() {
  const [currentId, setCurrentId] = useState<string | null>(null)
  const { connected, session, messages, running, error, sendPrompt, cancel, decideGate } = useAgentChat(currentId)

  return (
    <div className="h-screen flex bg-white">
      <SessionList currentId={currentId} onSelect={(id) => setCurrentId(id || null)} />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-14 px-6 border-b border-gray-100 flex items-center justify-between bg-white">
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-gray-900 truncate">
              {session?.title || (currentId ? '加载中...' : '从左侧选一个对话')}
            </h1>
            {session && (
              <div className="text-[10px] text-gray-400 mt-0.5">
                {session.message_count} 条 · {session.sku_id ? `SKU ${session.sku_id} · ` : ''}
                {connected ? '● 已连接' : '○ 未连接'}
              </div>
            )}
          </div>
        </header>

        {error && (
          <div className="mx-6 mt-3 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-xs text-red-700 flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {currentId ? (
          <>
            <MessageStream messages={messages} onDecideGate={decideGate} />
            <InputBar
              sessionId={currentId}
              running={running}
              onSend={sendPrompt}
              onCancel={cancel}
            />
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
            从左侧选或新建一个对话开始
          </div>
        )}
      </main>
    </div>
  )
}
