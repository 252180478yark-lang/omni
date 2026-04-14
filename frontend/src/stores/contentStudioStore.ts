import { create } from 'zustand'

const API_BASE = '/api/omni/content-studio'

export interface Scene {
  scene_id: number
  duration: string
  visual_description: string
  visual_description_zh: string
  narration: string
  camera_movement: string
  text_overlay: string
  transition: string
}

export interface ScriptResult {
  title: string
  duration_seconds: number
  scenes: Scene[]
}

export interface StoryboardItem {
  scene_id: number
  image_url: string
  status: string
  error?: string
}

export interface VideoItem {
  scene_id: number
  task_id: string
  video_url: string
  status: string
  error?: string
}

export interface Pipeline {
  id: string
  title: string
  status: string
  current_step: string
  source_text?: string
  copy_result?: string
  script_result?: ScriptResult | null
  storyboard_results?: StoryboardItem[]
  video_results?: VideoItem[]
  final_video_url?: string
  download_url?: string
  config?: Record<string, unknown>
  cost_estimate?: Record<string, number>
  actual_cost?: Record<string, number>
  error_message?: string
  created_at?: string
  updated_at?: string
}

export interface StylePreset {
  id: string
  name: string
  description: string
  is_builtin: boolean
  config: Record<string, string>
}

interface ContentStudioState {
  pipelines: Pipeline[]
  currentPipeline: Pipeline | null
  presets: StylePreset[]
  loading: boolean
  stepLoading: string | null
  error: string | null

  fetchPipelines: () => Promise<void>
  fetchPipeline: (id: string) => Promise<void>
  createPipeline: (title: string, sourceText: string, config?: Record<string, unknown>) => Promise<Pipeline>
  updatePipeline: (id: string, fields: Partial<Pipeline>) => Promise<void>
  deletePipeline: (id: string) => Promise<void>

  generateCopy: (id: string) => Promise<void>
  generateScript: (id: string) => Promise<void>
  generateStoryboard: (id: string) => Promise<void>
  regenerateStoryboardScene: (id: string, sceneId: number) => Promise<void>
  generateVideos: (id: string) => Promise<void>
  regenerateVideoScene: (id: string, sceneId: number) => Promise<void>
  composeFinal: (id: string) => Promise<void>

  fetchPresets: () => Promise<void>
  createPreset: (name: string, description: string, config: Record<string, string>) => Promise<void>
  estimateCost: (sceneCount: number, avgDuration?: number) => Promise<Record<string, number>>
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!res.ok) {
    let msg = `${res.status}`
    try {
      const body = await res.json()
      msg = body?.detail || body?.message || msg
    } catch { /* empty */ }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const useContentStudioStore = create<ContentStudioState>((set, get) => ({
  pipelines: [],
  currentPipeline: null,
  presets: [],
  loading: false,
  stepLoading: null,
  error: null,

  fetchPipelines: async () => {
    set({ loading: true, error: null })
    try {
      const data = await api<{ pipelines: Pipeline[] }>('/pipelines')
      set({ pipelines: data.pipelines, loading: false })
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false })
    }
  },

  fetchPipeline: async (id) => {
    set({ loading: true, error: null })
    try {
      const pipe = await api<Pipeline>(`/pipeline/${id}`)
      set({ currentPipeline: pipe, loading: false })
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false })
    }
  },

  createPipeline: async (title, sourceText, config = {}) => {
    set({ loading: true, error: null })
    try {
      const pipe = await api<Pipeline>('/pipelines', {
        method: 'POST',
        body: JSON.stringify({ title, source_text: sourceText, config }),
      })
      set(s => ({ pipelines: [pipe, ...s.pipelines], currentPipeline: pipe, loading: false }))
      return pipe
    } catch (e: unknown) {
      set({ error: (e as Error).message, loading: false })
      throw e
    }
  },

  updatePipeline: async (id, fields) => {
    try {
      const pipe = await api<Pipeline>(`/pipeline/${id}`, {
        method: 'PUT',
        body: JSON.stringify(fields),
      })
      set({ currentPipeline: pipe })
    } catch (e: unknown) {
      set({ error: (e as Error).message })
    }
  },

  deletePipeline: async (id) => {
    try {
      await api(`/pipeline/${id}`, { method: 'DELETE' })
      set(s => ({
        pipelines: s.pipelines.filter(p => p.id !== id),
        currentPipeline: s.currentPipeline?.id === id ? null : s.currentPipeline,
      }))
    } catch (e: unknown) {
      set({ error: (e as Error).message })
    }
  },

  generateCopy: async (id) => {
    set({ stepLoading: 'copy', error: null })
    try {
      const pipe = await api<Pipeline>(`/copy?pipeline_id=${id}`, { method: 'POST' })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  generateScript: async (id) => {
    set({ stepLoading: 'script', error: null })
    try {
      const pipe = await api<Pipeline>(`/script?pipeline_id=${id}`, { method: 'POST' })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  generateStoryboard: async (id) => {
    set({ stepLoading: 'storyboard', error: null })
    try {
      const pipe = await api<Pipeline>(`/storyboard?pipeline_id=${id}`, { method: 'POST' })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  regenerateStoryboardScene: async (id, sceneId) => {
    set({ stepLoading: `storyboard-${sceneId}`, error: null })
    try {
      const pipe = await api<Pipeline>(`/storyboard/regenerate?pipeline_id=${id}`, {
        method: 'POST',
        body: JSON.stringify({ scene_id: sceneId }),
      })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  generateVideos: async (id) => {
    set({ stepLoading: 'video', error: null })
    try {
      const pipe = await api<Pipeline>(`/video?pipeline_id=${id}`, { method: 'POST' })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  regenerateVideoScene: async (id, sceneId) => {
    set({ stepLoading: `video-${sceneId}`, error: null })
    try {
      const pipe = await api<Pipeline>(`/video/regenerate?pipeline_id=${id}`, {
        method: 'POST',
        body: JSON.stringify({ scene_id: sceneId }),
      })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  composeFinal: async (id) => {
    set({ stepLoading: 'compose', error: null })
    try {
      const pipe = await api<Pipeline>(`/compose?pipeline_id=${id}`, { method: 'POST' })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  fetchPresets: async () => {
    try {
      const data = await api<{ presets: StylePreset[] }>('/presets')
      set({ presets: data.presets })
    } catch { /* silent */ }
  },

  createPreset: async (name, description, config) => {
    const preset = await api<StylePreset>('/presets', {
      method: 'POST',
      body: JSON.stringify({ name, description, config }),
    })
    set(s => ({ presets: [...s.presets, preset] }))
  },

  estimateCost: async (sceneCount, avgDuration = 5) => {
    return api<Record<string, number>>('/estimate', {
      method: 'POST',
      body: JSON.stringify({ scene_count: sceneCount, avg_duration: avgDuration }),
    })
  },
}))
