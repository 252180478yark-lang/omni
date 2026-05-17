'use client'
import { useState, useEffect } from 'react'
import { useAgentChat } from '@/hooks/useAgentChat'
import { useNotification } from '@/hooks/useNotification'
import { SessionList } from './SessionList'
import { MessageStream } from './MessageStream'
import { InputBar } from './InputBar'
import { AlertCircle, Menu, X } from 'lucide-react'

export function ChatLayout() {
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const { permission, requestPermission, notify } = useNotification()

  useEffect(() => {
    if (permission === 'default') requestPermission()
  }, [permission, requestPermission])

  const { connected, session, messages, running, error, sendPrompt, cancel, decideGate } = useAgentChat(currentId, {
    onTaskDone: (_sid, dur) => {
      if (typeof document !== 'undefined' && document.hidden) {
        notify('omni 任务完成', { body: `用时 ${(dur / 1000).toFixed(0)}s` })
      }
    },
    onGateNew: (gate) => {
      if (typeof document !== 'undefined' && document.hidden) {
        notify('需要你点头', { body: `${gate.tool_name}：${gate.summary.slice(0, 80)}` })
      }
    },
  })

  const handleSelect = (id: string) => {
    setCurrentId(id || null)
    setMobileNavOpen(false)
  }

  return (
    <div className="h-[100dvh] flex bg-white overflow-hidden">
      {/* Mobile backdrop */}
      {mobileNavOpen && (
        <div
          onClick={() => setMobileNavOpen(false)}
          className="md:hidden fixed inset-0 bg-black/40 z-40"
        />
      )}

      <SessionList
        currentId={currentId}
        onSelect={handleSelect}
        mobileOpen={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
      />

      <main className="flex-1 flex flex-col min-w-0">
        <header className="h-14 px-3 md:px-6 border-b border-gray-100 flex items-center justify-between bg-white gap-2">
          <button
            onClick={() => setMobileNavOpen(true)}
            className="md:hidden p-2 -ml-1 rounded-md text-gray-600 hover:bg-gray-100"
            aria-label="打开会话列表"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="text-sm font-semibold text-gray-900 truncate">
              {session?.title || (currentId ? '加载中...' : '从左侧选一个对话')}
            </h1>
            {session && (
              <div className="text-[10px] text-gray-400 mt-0.5 truncate">
                {session.message_count} 条 · {session.sku_id ? `SKU ${session.sku_id} · ` : ''}
                {connected ? '● 已连接' : '○ 未连接'}
              </div>
            )}
          </div>
        </header>

        {error && (
          <div className="mx-3 md:mx-6 mt-3 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-xs text-red-700 flex items-start gap-2">
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
          <div className="flex-1 flex items-center justify-center text-gray-400 text-sm px-6 text-center">
            {mobileNavOpen ? '' : '点左上角菜单选或新建一个对话开始'}
          </div>
        )}
      </main>
    </div>
  )
}
