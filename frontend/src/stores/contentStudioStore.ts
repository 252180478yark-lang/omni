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
  characters?: string[]
  has_product?: boolean
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
  prompt_used?: string
  error?: string
}

export interface VideoItem {
  scene_id: number
  task_id: string
  video_url: string
  status: string
  prompt_used?: string
  error?: string
}

export interface CharacterProfile {
  id: string
  name: string
  gender: string
  age_range: string
  appearance: string
  scene_ids: number[]
  face_url: string
  is_virtual_avatar?: boolean
}

export interface PipelineStageModel {
  provider: string | null
  model: string | null
}

export type PipelineStageKey = 'copy' | 'script' | 'face' | 'storyboard' | 'video'

export interface PipelineConfig {
  copy_style?: string
  tone?: string
  pace?: string
  image_style?: string
  video_ratio?: string
  generate_audio?: boolean
  product_description?: string
  avatar_generation_guidance?: string
  /** Per-step model override. Missing keys or {provider: null, model: null} = hub default. */
  models?: Partial<Record<PipelineStageKey, PipelineStageModel>>
}

export interface Pipeline {
  id: string
  title: string
  status: string
  current_step: string
  product_id?: string | null
  brief_id?: string | null
  digital_human_id?: string | null
  source_text?: string
  copy_result?: string
  script_result?: ScriptResult | null
  storyboard_results?: StoryboardItem[]
  video_results?: VideoItem[]
  final_video_url?: string
  download_url?: string
  config?: PipelineConfig
  product_images?: string[]
  extra_reference_images?: Array<{ url: string; type: 'character' | 'product' | 'scene' | 'style' | 'reference'; weight?: number }>
  character_profiles?: CharacterProfile[]
  character_avatar_map?: Record<string, string>
  audience_package?: Record<string, unknown>
  cost_estimate?: Record<string, number>
  actual_cost?: Record<string, number>
  error_message?: string
  skip_final_concat?: boolean
  sku_id?: string | null
  created_at?: string
  updated_at?: string
}

export interface Brief {
  id: string
  title: string
  usp: string
  product_id?: string | null
  product_name?: string | null
  parent_brief_id?: string | null
  version?: number
  scenarios?: Array<Record<string, unknown>>
  audience_profile?: Record<string, unknown>
  tone_style?: Record<string, unknown>
  source_notes?: string | null
  dmp_sop?: string | null
  status?: string
  kb_doc_id?: string | null
  quality_score?: number
  extra?: Record<string, unknown>
  created_at?: string
}

export interface DigitalHuman {
  id: string
  name: string
  seed_face_url: string
  face_urls: string[]
  gender?: string | null
  age_range?: string | null
  style_tags?: string[]
  identity_anchor?: string | null
  status?: string
  ctr_avg?: number
  cvr_avg?: number
  quality_score?: number
  usage_count?: number
  extra?: Record<string, unknown>
  created_at?: string
}

export interface StylePreset {
  id: string
  name: string
  description: string
  is_builtin: boolean
  config: Record<string, string>
}

export interface PromptPreview {
  scene_id: number
  original_description: string
  prompt_will_use: string
  characters_in_scene?: string[]
  has_product?: boolean
  first_frame?: string
  reference_images?: string[]
}

interface ContentStudioState {
  pipelines: Pipeline[]
  currentPipeline: Pipeline | null
  presets: StylePreset[]
  loading: boolean
  stepLoading: string | null
  error: string | null
  storyboardPromptPreviews: PromptPreview[]
  videoPromptPreviews: PromptPreview[]
  briefs: Brief[]
  digitalHumans: DigitalHuman[]

  fetchPipelines: () => Promise<void>
  fetchPipeline: (id: string) => Promise<void>
  createPipeline: (
    title: string,
    sourceText: string,
    config?: PipelineConfig,
    opts?: { productId?: string; briefId?: string; digitalHumanId?: string }
  ) => Promise<Pipeline>
  updatePipeline: (id: string, fields: Partial<Pipeline>) => Promise<void>
  updateConfig: (id: string, config: PipelineConfig) => Promise<void>
  deletePipeline: (id: string) => Promise<void>

  generateCopy: (id: string) => Promise<void>
  generateScript: (id: string) => Promise<void>
  analyzeScript: (id: string) => Promise<void>
  generateCharacterFaces: (id: string) => Promise<void>
  generateStoryboard: (id: string) => Promise<void>
  regenerateStoryboardScene: (id: string, sceneId: number, promptOverride?: string) => Promise<void>
  regenerateStoryboardScenes: (id: string, sceneIds: number[], promptOverride?: string) => Promise<void>
  generateVideos: (id: string) => Promise<void>
  regenerateVideoScene: (id: string, sceneId: number, promptOverride?: string, userHint?: string) => Promise<void>
  regenerateVideoScenes: (
    id: string,
    sceneIds: number[],
    opts?: { promptOverride?: string; useNextSceneAsLastFrame?: boolean; userHint?: string },
  ) => Promise<void>
  composeFinal: (id: string) => Promise<void>

  previewStoryboardPrompts: (id: string) => Promise<void>
  previewVideoPrompts: (id: string) => Promise<void>

  fetchPresets: () => Promise<void>
  createPreset: (name: string, description: string, config: Record<string, string>) => Promise<void>
  estimateCost: (sceneCount: number, avgDuration?: number) => Promise<Record<string, number>>
  fetchBriefs: () => Promise<void>
  createBrief: (payload: Partial<Brief> & { title: string; usp: string }) => Promise<Brief>
  generateBrief: (payload: { product_id?: string; title?: string; hints?: Record<string, unknown> }) => Promise<Brief>
  deriveBrief: (briefId: string, overrides?: Partial<Brief>) => Promise<Brief>
  updateBrief: (briefId: string, fields: Partial<Brief>) => Promise<Brief>
  applyDmpSop: (briefId: string, sopText: string) => Promise<Brief>
  deleteBrief: (briefId: string) => Promise<void>
  fetchBriefPipelines: (briefId: string) => Promise<Pipeline[]>
  fetchBriefVersionTree: (briefId: string) => Promise<{ root: Brief | null; tree: Brief[] }>
  fetchAvatarPipelines: (avatarId: string) => Promise<Pipeline[]>
  fetchDigitalHumans: () => Promise<void>
  createDigitalHuman: (payload: Partial<DigitalHuman> & { name: string; seed_face_url: string }) => Promise<DigitalHuman>
  generateDigitalHuman: (payload: {
    name: string
    appearance_desc?: string
    reference_images?: string[]
    angles?: string[]
    gender?: string
    age_range?: string
    style_tags?: string[]
    identity_anchor?: string
  }) => Promise<DigitalHuman>
  promoteDigitalHuman: (id: string, toStatus?: string) => Promise<DigitalHuman>
  archiveDigitalHuman: (id: string) => Promise<DigitalHuman>
  setExtraReferenceImages: (
    pipelineId: string,
    refs: Array<{ url: string; type: 'character' | 'product'; weight?: number }>,
  ) => Promise<void>
}

const JSON_FIELD_KEYS = new Set([
  'scenarios',
  'audience_profile',
  'tone_style',
  'extra',
  'face_urls',
  'style_tags',
  'config',
  'script_result',
  'storyboard_results',
  'video_results',
  'product_images',
  'character_profiles',
  'cost_estimate',
  'actual_cost',
  'extra_reference_images',
  'audience_package',
  'character_avatar_map',
])

function normalizeJsonFields(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(normalizeJsonFields)
  }
  if (!value || typeof value !== 'object') {
    return value
  }

  const out: Record<string, unknown> = {}
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (JSON_FIELD_KEYS.has(key) && typeof raw === 'string') {
      try {
        out[key] = normalizeJsonFields(JSON.parse(raw))
        continue
      } catch {
        out[key] = raw
        continue
      }
    }
    out[key] = normalizeJsonFields(raw)
  }
  return out
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
  const data = await res.json()
  return normalizeJsonFields(data) as T
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const useContentStudioStore = create<ContentStudioState>((set, get) => ({
  pipelines: [],
  currentPipeline: null,
  presets: [],
  loading: false,
  stepLoading: null,
  error: null,
  storyboardPromptPreviews: [],
  videoPromptPreviews: [],
  briefs: [],
  digitalHumans: [],

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

  createPipeline: async (title, sourceText, config = {}, opts = {}) => {
    set({ loading: true, error: null })
    try {
      const pipe = await api<Pipeline>('/pipelines', {
        method: 'POST',
        body: JSON.stringify({
          title,
          source_text: sourceText,
          config,
          product_id: opts.productId,
          brief_id: opts.briefId,
          digital_human_id: opts.digitalHumanId,
        }),
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

  updateConfig: async (id, config) => {
    try {
      const pipe = await api<Pipeline>(`/pipeline/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ config }),
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

  analyzeScript: async (id) => {
    set({ stepLoading: 'analyze', error: null })
    try {
      const pipe = await api<Pipeline>(`/analyze?pipeline_id=${id}`, { method: 'POST' })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  generateCharacterFaces: async (id) => {
    set({ stepLoading: 'characters', error: null })
    try {
      const pipe = await api<Pipeline>(`/characters/generate?pipeline_id=${id}`, { method: 'POST' })
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

  regenerateStoryboardScene: async (id, sceneId, promptOverride) => {
    set({ stepLoading: `storyboard-${sceneId}`, error: null })
    try {
      const pipe = await api<Pipeline>(`/storyboard/regenerate?pipeline_id=${id}`, {
        method: 'POST',
        body: JSON.stringify({ scene_id: sceneId, prompt_override: promptOverride || null }),
      })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  regenerateStoryboardScenes: async (id, sceneIds, promptOverride) => {
    set({ stepLoading: 'storyboard-batch', error: null })
    try {
      const pipe = await api<Pipeline>(`/storyboard/batch-regenerate?pipeline_id=${id}`, {
        method: 'POST',
        body: JSON.stringify({ scene_ids: sceneIds, prompt_override: promptOverride || null }),
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

  regenerateVideoScene: async (id, sceneId, promptOverride, userHint) => {
    set({ stepLoading: `video-${sceneId}`, error: null })
    try {
      const pipe = await api<Pipeline>(`/video/regenerate?pipeline_id=${id}`, {
        method: 'POST',
        body: JSON.stringify({
          scene_id: sceneId,
          prompt_override: promptOverride || null,
          user_hint: userHint || null,
        }),
      })
      set({ currentPipeline: pipe, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  regenerateVideoScenes: async (id, sceneIds, opts = {}) => {
    set({ stepLoading: 'video-batch', error: null })
    try {
      const pipe = await api<Pipeline>(`/video/batch-regenerate?pipeline_id=${id}`, {
        method: 'POST',
        body: JSON.stringify({
          scene_ids: sceneIds,
          prompt_override: opts.promptOverride || null,
          use_next_scene_as_last_frame: !!opts.useNextSceneAsLastFrame,
          user_hint: opts.userHint || null,
        }),
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

  previewStoryboardPrompts: async (id) => {
    set({ stepLoading: 'preview-storyboard', error: null })
    try {
      const data = await api<{ previews: PromptPreview[] }>(`/storyboard/preview-prompts?pipeline_id=${id}`, { method: 'POST' })
      set({ storyboardPromptPreviews: data.previews, stepLoading: null })
    } catch (e: unknown) {
      set({ error: (e as Error).message, stepLoading: null })
    }
  },

  previewVideoPrompts: async (id) => {
    set({ stepLoading: 'preview-video', error: null })
    try {
      const data = await api<{ previews: PromptPreview[] }>(`/video/preview-prompts?pipeline_id=${id}`, { method: 'POST' })
      set({ videoPromptPreviews: data.previews, stepLoading: null })
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

  fetchBriefs: async () => {
    try {
      const data = await api<{ items: Brief[] }>('/briefs')
      set({ briefs: data.items })
    } catch (e: unknown) {
      set({ error: (e as Error).message })
    }
  },

  createBrief: async (payload) => {
    const brief = await api<Brief>('/briefs', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    set(s => ({ briefs: [brief, ...s.briefs] }))
    return brief
  },

  fetchDigitalHumans: async () => {
    try {
      const data = await api<{ items: DigitalHuman[] }>('/digital-humans')
      set({ digitalHumans: data.items })
    } catch (e: unknown) {
      set({ error: (e as Error).message })
    }
  },

  createDigitalHuman: async (payload) => {
    const dh = await api<DigitalHuman>('/digital-humans', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    set(s => ({ digitalHumans: [dh, ...s.digitalHumans] }))
    return dh
  },

  generateBrief: async (payload) => {
    const brief = await api<Brief>('/briefs/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    set(s => ({ briefs: [brief, ...s.briefs] }))
    return brief
  },

  deriveBrief: async (briefId, overrides = {}) => {
    const brief = await api<Brief>(`/briefs/${briefId}/derive`, {
      method: 'POST',
      body: JSON.stringify(overrides),
    })
    set(s => ({ briefs: [brief, ...s.briefs] }))
    return brief
  },

  updateBrief: async (briefId, fields) => {
    const brief = await api<Brief>(`/briefs/${briefId}`, {
      method: 'PUT',
      body: JSON.stringify(fields),
    })
    set(s => ({ briefs: s.briefs.map(b => (b.id === briefId ? brief : b)) }))
    return brief
  },

  applyDmpSop: async (briefId, sopText) => {
    const brief = await api<Brief>(`/briefs/${briefId}/dmp-sop`, {
      method: 'POST',
      body: JSON.stringify({ sop_text: sopText }),
    })
    set(s => ({ briefs: s.briefs.map(b => (b.id === briefId ? brief : b)) }))
    return brief
  },

  deleteBrief: async (briefId) => {
    await api(`/briefs/${briefId}`, { method: 'DELETE' })
    set(s => ({ briefs: s.briefs.filter(b => b.id !== briefId) }))
  },

  generateDigitalHuman: async (payload) => {
    const dh = await api<DigitalHuman>('/digital-humans/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    set(s => ({ digitalHumans: [dh, ...s.digitalHumans] }))
    return dh
  },

  promoteDigitalHuman: async (id, toStatus) => {
    const dh = await api<DigitalHuman>(`/digital-humans/${id}/promote`, {
      method: 'POST',
      body: JSON.stringify({ to_status: toStatus }),
    })
    set(s => ({ digitalHumans: s.digitalHumans.map(d => (d.id === id ? dh : d)) }))
    return dh
  },

  archiveDigitalHuman: async (id) => {
    const dh = await api<DigitalHuman>(`/digital-humans/${id}/archive`, {
      method: 'POST',
    })
    set(s => ({ digitalHumans: s.digitalHumans.map(d => (d.id === id ? dh : d)) }))
    return dh
  },

  setExtraReferenceImages: async (pipelineId, refs) => {
    await api(`/pipeline/${pipelineId}/extra-refs`, {
      method: 'PUT',
      body: JSON.stringify({ reference_images: refs }),
    })
  },

  fetchBriefPipelines: async (briefId) => {
    const data = await api<{ items: Pipeline[] }>(`/briefs/${briefId}/pipelines`)
    return data.items
  },

  fetchBriefVersionTree: async (briefId) => {
    return api<{ root: Brief | null; tree: Brief[] }>(`/briefs/${briefId}/version-tree`)
  },

  fetchAvatarPipelines: async (avatarId) => {
    const data = await api<{ items: Pipeline[] }>(`/digital-humans/${avatarId}/pipelines`)
    return data.items
  },
}))
