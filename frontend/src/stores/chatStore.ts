import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export type OutputMode = 'text' | 'image' | 'video' | 'analyze'

export interface SourceRef {
  index: number
  chunk_id: string
  content: string
  title: string | null
  source_url: string | null
  score: number
}

export interface ImageResult {
  url: string
  revised_prompt?: string
}

export interface VideoResult {
  task_id: string
  status: string
  video_url?: string
  estimated_seconds?: number
}

export interface RetrievalMeta {
  graph_rag_used: boolean
  graph_context_preview: string
  kb_count?: number
  crag_verdict?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  outputMode?: OutputMode
  sources?: SourceRef[]
  images?: ImageResult[]
  video?: VideoResult
  retrieval?: RetrievalMeta
  timestamp: number
  loading?: boolean
}

interface ChatState {
  kbId: string
  kbIds: string[]
  sessionId: string
  outputMode: OutputMode
  messages: ChatMessage[]
  streaming: boolean
  abortController: AbortController | null

  setKbId: (id: string) => void
  setKbIds: (ids: string[]) => void
  toggleKbId: (id: string) => void
  setOutputMode: (mode: OutputMode) => void
  addUserMessage: (content: string, mode: OutputMode) => string
  startAssistant: (id: string, mode: OutputMode) => void
  appendToken: (id: string, token: string) => void
  finishAssistant: (id: string, sources: SourceRef[], retrieval?: RetrievalMeta) => void
  finishAssistantImage: (id: string, images: ImageResult[]) => void
  finishAssistantVideo: (id: string, video: VideoResult) => void
  failAssistant: (id: string, error: string) => void
  setStreaming: (v: boolean) => void
  setAbort: (ctrl: AbortController | null) => void
  clearMessages: () => void
  /** 从外部（如加载历史会话）整体替换当前会话上下文 */
  loadSession: (sessionId: string, messages: ChatMessage[], kbIds?: string[]) => void
}

let _msgCounter = 0
function uid() {
  return `msg-${Date.now()}-${++_msgCounter}`
}

function sessionUid() {
  return `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      kbId: '',
      kbIds: [],
      sessionId: sessionUid(),
      outputMode: 'text',
      messages: [],
      streaming: false,
      abortController: null,

      setKbId: (id) => set({ kbId: id, kbIds: [id] }),
      setKbIds: (ids) => set({ kbIds: ids, kbId: ids[0] || '' }),
      toggleKbId: (id) =>
        set((s) => {
          const next = s.kbIds.includes(id)
            ? s.kbIds.filter((k) => k !== id)
            : [...s.kbIds, id]
          return { kbIds: next, kbId: next[0] || '' }
        }),
      setOutputMode: (mode) => set({ outputMode: mode }),

      addUserMessage: (content, mode) => {
        const id = uid()
        set((s) => ({
          messages: [
            ...s.messages,
            { id, role: 'user', content, outputMode: mode, timestamp: Date.now() },
          ],
        }))
        return id
      },

      startAssistant: (id, mode) =>
        set((s) => ({
          messages: [
            ...s.messages,
            { id, role: 'assistant', content: '', outputMode: mode, timestamp: Date.now(), loading: true },
          ],
        })),

      appendToken: (id, token) =>
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === id ? { ...m, content: m.content + token } : m,
          ),
        })),

      finishAssistant: (id, sources, retrieval) =>
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === id ? { ...m, loading: false, sources, retrieval } : m,
          ),
        })),

      finishAssistantImage: (id, images) =>
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === id ? { ...m, loading: false, images, content: images.length ? `已生成 ${images.length} 张图片` : '图片生成失败' } : m,
          ),
        })),

      finishAssistantVideo: (id, video) =>
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === id ? { ...m, loading: false, video, content: video.status === 'completed' ? '视频已生成' : `视频任务已提交（预计 ${video.estimated_seconds || 120}s）` } : m,
          ),
        })),

      failAssistant: (id, error) =>
        set((s) => ({
          messages: s.messages.map((m) =>
            m.id === id ? { ...m, content: `⚠ ${error}`, loading: false } : m,
          ),
        })),

      setStreaming: (v) => set({ streaming: v }),
      setAbort: (ctrl) => set({ abortController: ctrl }),
      clearMessages: () => set({ messages: [], sessionId: sessionUid() }),

      loadSession: (sessionId, messages, kbIds) =>
        set(() => ({
          sessionId,
          messages,
          ...(kbIds ? { kbIds, kbId: kbIds[0] || '' } : {}),
          streaming: false,
          abortController: null,
        })),
    }),
    {
      name: 'omni-chat-store',
      version: 1,
      storage: createJSONStorage(() => (typeof window !== 'undefined' ? window.localStorage : undefined as unknown as Storage)),
      // 只持久化这几个字段；流/abortController 这种运行态不持久化
      partialize: (state) => ({
        kbId: state.kbId,
        kbIds: state.kbIds,
        sessionId: state.sessionId,
        outputMode: state.outputMode,
        messages: state.messages,
      }),
      // 恢复时：把残留 loading=true 的 assistant 消息标记为已中断，防止永远转圈
      onRehydrateStorage: () => (state) => {
        if (!state) return
        if (Array.isArray(state.messages)) {
          state.messages = state.messages.map((m) =>
            m.loading
              ? {
                  ...m,
                  loading: false,
                  content: m.content && m.content.length > 0 ? m.content : '⚠ 上次会话被中断，已停止',
                }
              : m,
          )
        }
      },
    },
  ),
)
