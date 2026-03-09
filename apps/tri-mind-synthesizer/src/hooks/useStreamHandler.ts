import { useEffect, useRef, useCallback } from 'react'
import { useChatStore } from '../stores/chatStore'
import { ipc } from '../lib/ipc'
import { DebateEvent, StreamChunk } from '../lib/types'

/**
 * 流式数据处理 Hook
 * 
 * 1. 监听 debate-stream：流式内容，用 RAF 节流更新 UI
 * 2. 监听 debate-event：轮次完成/辩论完成事件
 */
export function useStreamHandler() {
  const { appendStreamChunk, finalizeStream, sessionId } = useChatStore()

  // 用 ref 缓冲高频 chunk，定时刷新到 store
  const pendingChunks = useRef<Map<string, string>>(new Map())
  const rafId = useRef<number | null>(null)
  // 非当前会话的流/事件缓存，切回会话时回放，避免丢字
  const queuedChunksBySession = useRef<Map<string, StreamChunk[]>>(new Map())
  const queuedEventsBySession = useRef<Map<string, DebateEvent[]>>(new Map())
  const replayedChunkCountBySession = useRef<Map<string, number>>(new Map())
  const replayedEventCountBySession = useRef<Map<string, number>>(new Map())
  // 每个会话的最新流式快照，支持反复切换后恢复现场
  const latestBufferBySession = useRef<Map<string, Map<string, string>>>(new Map())
  const activeStreamingSessions = useRef<Set<string>>(new Set())

  const flushBuffers = useCallback(() => {
    const chunks = pendingChunks.current
    if (chunks.size === 0) return

    chunks.forEach((content, modelId) => {
      if (content) {
        appendStreamChunk(modelId, content)
      }
    })
    chunks.clear()
  }, [appendStreamChunk])

  const scheduleFlush = useCallback(() => {
    if (rafId.current !== null) return
    rafId.current = requestAnimationFrame(() => {
      flushBuffers()
      rafId.current = null
    })
  }, [flushBuffers])

  const queueChunkForSession = useCallback((targetSessionId: string, chunk: StreamChunk) => {
    const existing = queuedChunksBySession.current.get(targetSessionId) || []
    existing.push(chunk)
    queuedChunksBySession.current.set(targetSessionId, existing)
  }, [])

  const queueEventForSession = useCallback((targetSessionId: string, event: DebateEvent) => {
    const existing = queuedEventsBySession.current.get(targetSessionId) || []
    existing.push(event)
    queuedEventsBySession.current.set(targetSessionId, existing)
  }, [])

  const appendLatestBuffer = useCallback((targetSessionId: string, modelId: string, content: string) => {
    if (!content) return
    const sessionBuffers = latestBufferBySession.current.get(targetSessionId) || new Map<string, string>()
    const prev = sessionBuffers.get(modelId) || ''
    sessionBuffers.set(modelId, prev + content)
    latestBufferBySession.current.set(targetSessionId, sessionBuffers)
  }, [])

  const processDebateEvent = useCallback((event: DebateEvent, fromReplay = false) => {
    const store = useChatStore.getState()
    const currentSessionId = store.sessionId
    const eventSessionId = event.sessionId

    // 非当前会话事件进入缓存，切回时回放
    if (!fromReplay && currentSessionId && eventSessionId !== currentSessionId) {
      queueEventForSession(eventSessionId, event)
      if (event.type === 'debate-complete' || event.type === 'error') {
        activeStreamingSessions.current.delete(eventSessionId)
      }
      return
    }

    // 如果当前没有在生成，忽略事件（旧会话残留）
    if (!fromReplay && !store.isGenerating) return
    
    if (event.type === 'round-complete' && event.round) {
      console.log(`第 ${event.round} 轮完成，保存快照`)
      store.saveRoundSnapshot(event.round)
    } else if (event.type === 'debate-complete') {
      console.log('辩论完成')
      activeStreamingSessions.current.delete(eventSessionId)
      if (!store.isVerdictGenerating && !store.verdictContent) {
        useChatStore.setState({ isGenerating: false })
      }
    } else if (event.type === 'error') {
      console.error('辩论错误:', event.error)
      activeStreamingSessions.current.delete(eventSessionId)
      store.setError(event.error || '未知错误')
    }
  }, [queueEventForSession])

  const processStreamChunk = useCallback((chunk: StreamChunk, fromReplay = false) => {
    const currentSessionId = useChatStore.getState().sessionId
    if (!chunk.done) {
      activeStreamingSessions.current.add(chunk.sessionId)
    }
    appendLatestBuffer(chunk.sessionId, chunk.modelId, chunk.content)
    // 非当前会话数据进入缓存，切回时回放
    if (!fromReplay && currentSessionId && chunk.sessionId !== currentSessionId) {
      queueChunkForSession(chunk.sessionId, chunk)
      return
    }
    // 会话切换瞬间 currentSessionId 可能为 null，也缓存以防丢失
    if (!fromReplay && !currentSessionId) {
      queueChunkForSession(chunk.sessionId, chunk)
      return
    }

    if (chunk.modelId === '__verdict__') {
      if (!chunk.done) {
        const key = '__verdict__'
        const prev = pendingChunks.current.get(key) || ''
        pendingChunks.current.set(key, prev + chunk.content)
        scheduleFlush()
      } else {
        flushBuffers()
        useChatStore.getState().finalizeVerdict(chunk.usage)
      }
    } else if (chunk.modelId === '__error__') {
      console.error('辩论错误:', chunk.error)
      useChatStore.getState().setError(chunk.error || '未知错误')
    } else {
      if (!chunk.done) {
        if (chunk.content) {
          const prev = pendingChunks.current.get(chunk.modelId) || ''
          pendingChunks.current.set(chunk.modelId, prev + chunk.content)
          scheduleFlush()
        }
      } else {
        flushBuffers()
        if (chunk.error) {
          useChatStore.getState().setModelError(chunk.modelId, chunk.error)
        } else {
          finalizeStream(chunk.modelId, chunk.usage)
        }
      }
    }
  }, [appendLatestBuffer, finalizeStream, flushBuffers, queueChunkForSession, scheduleFlush])

  useEffect(() => {
    // ========== 监听流式数据 ==========
    const cleanupStream = ipc.onDebateStream?.((chunk: StreamChunk) => {
      processStreamChunk(chunk)
    })

    // ========== 监听辩论事件 ==========
    const cleanupEvent = ipc.onDebateEvent?.((event) => {
      processDebateEvent(event)
    })

    return () => {
      cleanupStream?.()
      cleanupEvent?.()
      if (rafId.current !== null) {
        cancelAnimationFrame(rafId.current)
      }
    }
  }, [appendStreamChunk, processDebateEvent, processStreamChunk, finalizeStream, flushBuffers, scheduleFlush])

  // 会话切换后回放缓存的后台流/事件，补齐切走期间遗漏内容
  useEffect(() => {
    if (!sessionId) return

    // 先恢复该会话的最新流式快照，避免反复切换丢中间内容
    const latest = latestBufferBySession.current.get(sessionId)
    if (latest && latest.size > 0) {
      const restoredBuffers = new Map<string, string>()
      const verdict = latest.get('__verdict__') || ''
      latest.forEach((content, modelId) => {
        if (modelId !== '__verdict__') {
          restoredBuffers.set(modelId, content)
        }
      })
      useChatStore.setState((state) => ({
        ...state,
        streamBuffers: restoredBuffers.size > 0 ? restoredBuffers : state.streamBuffers,
        verdictContent: verdict || state.verdictContent,
        isGenerating: activeStreamingSessions.current.has(sessionId) || state.isGenerating,
      }))
    }

    const queuedChunks = queuedChunksBySession.current.get(sessionId)
    if (queuedChunks && queuedChunks.length > 0) {
      const offset = replayedChunkCountBySession.current.get(sessionId) || 0
      for (let i = offset; i < queuedChunks.length; i++) {
        processStreamChunk(queuedChunks[i], true)
      }
      replayedChunkCountBySession.current.set(sessionId, queuedChunks.length)
    }

    const queuedEvents = queuedEventsBySession.current.get(sessionId)
    if (queuedEvents && queuedEvents.length > 0) {
      const offset = replayedEventCountBySession.current.get(sessionId) || 0
      for (let i = offset; i < queuedEvents.length; i++) {
        processDebateEvent(queuedEvents[i], true)
      }
      replayedEventCountBySession.current.set(sessionId, queuedEvents.length)
    }
  }, [sessionId, processDebateEvent, processStreamChunk])
}
