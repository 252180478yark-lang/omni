'use client'
import { useEffect, useRef, useState, useCallback } from 'react'
import { ConfigPanel } from './ConfigPanel'
import { ConvPane } from './ConvPane'
import { TracePane } from './TracePane'
import { createSandboxSession, modelToCliFlag } from '@/lib/playground/api'
import { usePlaygroundStore, type ToolCallTrace } from '@/stores/playground'
import type {
  WsClientMessage,
  WsServerMessage,
  ChatMessage,
  PlaygroundSpawnConfig,
} from '@/lib/agent-chat/types'
import { AlertCircle, Trash2 } from 'lucide-react'

export function PlaygroundLayout() {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [initializing, setInitializing] = useState(true)

  const config = usePlaygroundStore((s) => s.config)
  const sessionId = usePlaygroundStore((s) => s.sessionId)
  const setSessionId = usePlaygroundStore((s) => s.setSessionId)
  const messages = usePlaygroundStore((s) => s.messages)
  const running = usePlaygroundStore((s) => s.running)
  const setRunning = usePlaygroundStore((s) => s.setRunning)
  const pendingInput = usePlaygroundStore((s) => s.pendingInput)
  const setPendingInput = usePlaygroundStore((s) => s.setPendingInput)
  const appendMessage = usePlaygroundStore((s) => s.appendMessage)
  const upsertMessage = usePlaygroundStore((s) => s.upsertMessage)
  const appendToolCall = usePlaygroundStore((s) => s.appendToolCall)
  const updateToolCallResult = usePlaygroundStore((s) => s.updateToolCallResult)
  const accumulateTask = usePlaygroundStore((s) => s.accumulateTask)
  const resetConversation = usePlaygroundStore((s) => s.resetConversation)

  // 创建 sandbox session(进入页面就建一个,每次刷新都 fresh)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const { id } = await createSandboxSession()
        if (cancelled) return
        setSessionId(id)
      } catch (e) {
        if (!cancelled) setError(`create sandbox failed: ${(e as Error).message}`)
      } finally {
        if (!cancelled) setInitializing(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [setSessionId])

  // WebSocket 连接
  useEffect(() => {
    if (!sessionId) return
    const proto = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = typeof window !== 'undefined' ? window.location.host : 'localhost:3000'
    const ws = new WebSocket(`${proto}//${host}/ws/agent-chat`)
    wsRef.current = ws
    ws.onopen = () => {
      setConnected(true)
      ws.send(
        JSON.stringify({ kind: 'open_session', session_id: sessionId } satisfies WsClientMessage),
      )
    }
    ws.onmessage = (ev) => {
      let msg: WsServerMessage
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }
      if (msg.kind === 'session_opened') {
        // playground 每次干净开始(不读 history),但兼容拿到 history 时还是写到 messages
        for (const m of msg.history) {
          appendMessage(m)
        }
      } else if (msg.kind === 'chunk') {
        const m = msg.message
        if (m.role === 'tool_call' && m.tool_use_id) {
          // 同步记录到 toolCalls
          const tc: ToolCallTrace = {
            tool_use_id: m.tool_use_id,
            tool_name: m.tool_name || '',
            input: m.tool_args,
            status: 'pending',
            created_at: m.created_at,
          }
          appendToolCall(tc)
        } else if (m.role === 'tool_result' && m.tool_use_id) {
          // 更新对应的 toolCall result
          // raw_result 可能是 string(content) 或 array
          let parsed: unknown = null
          try {
            if (typeof m.raw_result === 'string') {
              parsed = JSON.parse(m.raw_result)
            } else if (Array.isArray(m.raw_result) && m.raw_result.length > 0) {
              const first = m.raw_result[0] as { text?: string }
              if (first?.text) parsed = JSON.parse(first.text)
            } else if (typeof m.raw_result === 'object') {
              parsed = m.raw_result
            }
          } catch {
            parsed = null
          }
          updateToolCallResult(m.tool_use_id, parsed, m.raw_result)
        }
        upsertMessage(m)
      } else if (msg.kind === 'task_done') {
        setRunning(false)
        accumulateTask(msg.duration_ms, msg.total_cost_usd, msg.tokens.input, msg.tokens.output)
      } else if (msg.kind === 'error') {
        setError(msg.error + (msg.detail ? `: ${msg.detail}` : ''))
        setRunning(false)
      }
    }
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setError('websocket_error')
    return () => {
      ws.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  const sendPrompt = useCallback(
    (prompt: string) => {
      const ws = wsRef.current
      if (!ws || ws.readyState !== 1 || !sessionId) return
      setRunning(true)
      setError(null)
      const userMsg: ChatMessage = {
        id: `local-${Date.now()}`,
        session_id: sessionId,
        role: 'user',
        text: prompt,
        created_at: new Date().toISOString(),
      }
      appendMessage(userMsg)

      const cfg: PlaygroundSpawnConfig = {
        model: modelToCliFlag(config.model),
        allowed_tools: config.allowedTools.includes('__none__')
          ? []
          : config.allowedTools.length > 0
            ? config.allowedTools
            : undefined,
        append_system_prompt: config.extraSystemPrompt.trim() || undefined,
        max_turns: config.maxTurns,
      }

      ws.send(
        JSON.stringify({
          kind: 'send_prompt',
          session_id: sessionId,
          prompt,
          config: cfg,
        } satisfies WsClientMessage),
      )
    },
    [sessionId, config, appendMessage, setRunning],
  )

  const cancel = useCallback(() => {
    const ws = wsRef.current
    if (!ws || !sessionId) return
    ws.send(
      JSON.stringify({ kind: 'cancel', session_id: sessionId } satisfies WsClientMessage),
    )
    setRunning(false)
  }, [sessionId, setRunning])

  const handleReset = async () => {
    if (!confirm('清空当前对话 + 重置 trace?')) return
    resetConversation()
    // 拉一个新 session id(不删旧的,留库做留痕)
    try {
      const { id } = await createSandboxSession()
      setSessionId(id)
    } catch (e) {
      setError(`reset failed: ${(e as Error).message}`)
    }
  }

  if (initializing) {
    return (
      <div className="h-[100dvh] flex items-center justify-center bg-white">
        <div className="text-sm text-gray-400">正在创建 sandbox session...</div>
      </div>
    )
  }

  return (
    <div className="h-[100dvh] flex bg-white overflow-hidden">
      <ConfigPanel
        canRun={!running && connected && pendingInput.trim().length > 0}
        onRun={() => {
          const text = pendingInput.trim()
          if (!text || running) return
          sendPrompt(text)
          setPendingInput('')
        }}
      />

      <div className="flex-1 flex flex-col min-w-0">
        {error && (
          <div className="mx-4 mt-3 px-3 py-2 rounded-md bg-red-50 border border-red-200 text-xs text-red-700 flex items-start gap-2">
            <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700">
              ✕
            </button>
          </div>
        )}
        <div className="flex-1 flex min-h-0">
          <ConvPane onSend={sendPrompt} onCancel={cancel} connected={connected} />
        </div>
        {/* 重置入口 */}
        {messages.length > 0 && (
          <button
            onClick={handleReset}
            className="absolute top-3 right-[380px] z-10 text-[10px] inline-flex items-center gap-1 px-2 py-1 rounded bg-white border border-gray-200 text-gray-500 hover:text-red-600 hover:border-red-300"
            title="清空对话 + trace"
          >
            <Trash2 className="w-3 h-3" />
            重置
          </button>
        )}
      </div>

      <TracePane />
    </div>
  )
}
