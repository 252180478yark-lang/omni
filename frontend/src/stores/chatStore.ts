import { create } from 'zustand'

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

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  outputMode?: OutputMode
  sources?: SourceRef[]
  images?: ImageResult[]
  video?: VideoResult
  timestamp: number
  loading?: boolean
}

interface ChatState {
  kbId: string
  sessionId: string
  outputMode: OutputMode
  messages: ChatMessage[]
  streaming: boolean
  abortController: AbortController | null

  setKbId: (id: string) => void
  setOutputMode: (mode: OutputMode) => void
  addUserMessage: (content: string, mode: OutputMode) => string
  startAssistant: (id: string, mode: OutputMode) => void
  appendToken: (id: string, token: string) => void
  finishAssistant: (id: string, sources: SourceRef[]) => void
  finishAssistantImage: (id: string, images: ImageResult[]) => void
  finishAssistantVideo: (id: string, video: VideoResult) => void
  failAssistant: (id: string, error: string) => void
  setStreaming: (v: boolean) => void
  setAbort: (ctrl: AbortController | null) => void
  clearMessages: () => void
}

let _msgCounter = 0
function uid() {
  return `msg-${Date.now()}-${++_msgCounter}`
}

function sessionUid() {
  return `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export const useChatStore = create<ChatState>((set, get) => ({
  kbId: '',
  sessionId: sessionUid(),
  outputMode: 'text',
  messages: [],
  streaming: false,
  abortController: null,

  setKbId: (id) => set({ kbId: id }),
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

  finishAssistant: (id, sources) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, loading: false, sources } : m,
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
}))
