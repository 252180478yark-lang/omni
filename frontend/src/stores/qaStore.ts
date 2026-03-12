import { create } from 'zustand'

export interface SourceRef {
  index: number
  chunk_id: string
  content: string
  title: string | null
  source_url: string | null
  score: number
}

export interface QAMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: SourceRef[]
  timestamp: number
  loading?: boolean
}

interface QAState {
  kbId: string
  messages: QAMessage[]
  streaming: boolean
  abortController: AbortController | null

  setKbId: (id: string) => void
  addUserMessage: (content: string) => string
  startAssistant: (id: string) => void
  appendToken: (id: string, token: string) => void
  finishAssistant: (id: string, sources: SourceRef[]) => void
  failAssistant: (id: string, error: string) => void
  setStreaming: (v: boolean) => void
  setAbort: (ctrl: AbortController | null) => void
  clearMessages: () => void
}

let _msgCounter = 0
function uid() {
  return `msg-${Date.now()}-${++_msgCounter}`
}

export const useQAStore = create<QAState>((set) => ({
  kbId: '',
  messages: [],
  streaming: false,
  abortController: null,

  setKbId: (id) => set({ kbId: id }),

  addUserMessage: (content) => {
    const id = uid()
    set((s) => ({
      messages: [
        ...s.messages,
        { id, role: 'user', content, timestamp: Date.now() },
      ],
    }))
    return id
  },

  startAssistant: (id) =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id, role: 'assistant', content: '', timestamp: Date.now(), loading: true },
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

  failAssistant: (id, error) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id
          ? { ...m, content: `⚠ ${error}`, loading: false }
          : m,
      ),
    })),

  setStreaming: (v) => set({ streaming: v }),
  setAbort: (ctrl) => set({ abortController: ctrl }),
  clearMessages: () => set({ messages: [] }),
}))
