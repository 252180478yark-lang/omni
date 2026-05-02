'use client'

import React, { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft, ArrowRight, Check, ChevronDown, ChevronUp, Download, Eye, FileText, Film,
  Image as ImageIcon, Loader2, Pen, RefreshCw, Search, Settings2,
  Sparkles, User, UserCircle2, Users, Video, Wand2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ContentStudioHubNav } from '@/components/content-studio-hub-nav'
import {
  useContentStudioStore,
  type Pipeline,
  type PipelineConfig,
  type PipelineStageKey,
  type PipelineStageModel,
  type Scene,
  type ScriptResult,
  type StoryboardItem,
  type VideoItem,
  type CharacterProfile,
} from '@/stores/contentStudioStore'
import { ModelSelector, type ModelCapability } from '@/components/model-selector'
import { PromptFeedback } from '@/components/prompt-feedback'
import { PromptNodeDrawer } from '@/components/prompt-node-drawer'

/* ── Step definitions (7 steps, matching backend flow) ── */

const STEPS = [
  { key: 'copy', label: '文案', icon: Pen },
  { key: 'script', label: '脚本', icon: Wand2 },
  { key: 'analyze', label: '角色分析', icon: Search },
  { key: 'characters', label: '角色生成', icon: Users },
  { key: 'storyboard', label: '分镜图', icon: ImageIcon },
  { key: 'video', label: '视频片段', icon: Video },
  { key: 'compose', label: '合成', icon: Film },
] as const

const STEP_ORDER = STEPS.map(s => s.key)

const STATUS_LABELS: Record<string, string> = {
  pending: '待开始', running: '生成中', paused: '待确认', completed: '已完成', failed: '失败',
}

/* ── Config options (matching backend prompt_templates.py) ── */

const RATIO_OPTIONS = [
  { value: '16:9', label: '16:9 横屏' },
  { value: '9:16', label: '9:16 竖屏' },
  { value: '1:1', label: '1:1 方形' },
]

/* ── Select component ── */

function LabeledSelect({ label, value, onChange, options }: {
  label: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <div>
      <label className="text-xs text-gray-500 block mb-1">{label}</label>
      <select
        className="w-full h-9 rounded-md border border-input bg-white px-3 text-sm"
        value={value}
        onChange={e => onChange(e.target.value)}
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

function ClosureGuide({
  pipe,
  scenes,
  storyboard,
  videos,
}: {
  pipe: Pipeline
  scenes: Scene[]
  storyboard: StoryboardItem[]
  videos: VideoItem[]
}) {
  const productRefCount = (pipe.product_images?.length ?? 0)
    + (pipe.extra_reference_images?.filter((r) => r.type === 'product').length ?? 0)
  const characterRefCount = (pipe.extra_reference_images?.filter((r) => r.type === 'character').length ?? 0)
    + (pipe.character_profiles?.filter((c) => c.face_url).length ?? 0)
  const scriptOk = scenes.length === 10
  const storyboardOk = storyboard.length === 10 && storyboard.every((s) => !!s.image_url)
  const videosOk = videos.length === 10 && videos.every((v) => !!v.video_url)
  const finalOk = !!pipe.final_video_url
  const missing = [
    !pipe.brief_id && '绑定 Brief，否则复盘 CTR/CVR 不会回灌到 Brief',
    !pipe.digital_human_id && '绑定 Avatar，否则数字人样本数无法累计',
    characterRefCount === 0 && '人脸参考图',
    productRefCount === 0 && '产品参考图',
    scenes.length > 0 && !scriptOk && `10 scene 脚本（当前 ${scenes.length}/10）`,
    scenes.length === 0 && '10 scene 分镜脚本',
    !storyboardOk && 'Seedream 分镜图',
    !videosOk && 'Seedance 视频片段',
    !finalOk && '最终视频下载包',
  ].filter(Boolean)
  const steps = [
    { label: '建 Brief', done: !!pipe.brief_id },
    { label: '建 Avatar', done: !!pipe.digital_human_id },
    { label: '新建 Pipeline', done: true },
    { label: '生成', done: scriptOk && storyboardOk && videosOk },
    { label: '下载', done: finalOk },
    { label: '投放', done: false },
    { label: '复盘', done: false },
  ]

  return (
    <Card className="border-violet-200 bg-violet-50/40">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-violet-950">闭环进度</h3>
            <p className="mt-1 text-xs text-violet-800">
              Avatar + 产品图 → 10 scene → Seedream 分镜图 → Seedance 视频 → 下载 → 投放 → ad-review 复盘回灌。
            </p>
          </div>
          <Link href={`/ad-review`} className="text-xs text-violet-700 underline shrink-0">
            去投放复盘
          </Link>
        </div>
        <div className="flex flex-wrap gap-2">
          {steps.map((s, idx) => (
            <span
              key={s.label}
              className={`rounded-full px-2.5 py-1 text-xs ${
                s.done ? 'bg-emerald-100 text-emerald-700' : 'bg-white text-gray-500 border border-violet-100'
              }`}
            >
              {idx + 1}. {s.label}{s.done ? ' ✓' : ''}
            </span>
          ))}
        </div>
        {missing.length > 0 ? (
          <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            当前还缺：{missing.join('、')}。
          </div>
        ) : (
          <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            生成侧已闭环。投放后请在 ad-review 素材上绑定当前 Pipeline，复盘完成后会回灌 Brief / Avatar 指标。
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* ── Config Panel ── */

const STAGE_LABELS: { key: PipelineStageKey; label: string; capability: ModelCapability }[] = [
  { key: 'copy', label: '文案', capability: 'chat' },
  { key: 'script', label: '脚本 / 场景优化', capability: 'chat' },
  { key: 'face', label: '角色人脸图', capability: 'image_generation' },
  { key: 'storyboard', label: '分镜图', capability: 'image_generation' },
  { key: 'video', label: '分镜视频', capability: 'video_generation' },
]

function getStageModel(config: PipelineConfig | undefined, stage: PipelineStageKey): PipelineStageModel {
  return config?.models?.[stage] ?? { provider: null, model: null }
}

function describeStageModel(m: PipelineStageModel | undefined): string {
  if (!m || !m.provider || !m.model) return '使用系统默认'
  return `${m.provider} · ${m.model}`
}

function parseImportedScript(copyText: string, scenesText: string): ScriptResult {
  const raw = scenesText.trim()
  if (!raw) {
    throw new Error('请填写场景描述，或只导入文案后点击“继续生成脚本”')
  }

  try {
    const parsed = JSON.parse(raw) as unknown
    const script = Array.isArray(parsed)
      ? { title: '导入脚本', duration_seconds: parsed.length * 4, scenes: parsed }
      : parsed
    if (
      script
      && typeof script === 'object'
      && Array.isArray((script as { scenes?: unknown }).scenes)
    ) {
      const obj = script as ScriptResult
      return {
        title: obj.title || '导入脚本',
        duration_seconds: obj.duration_seconds || obj.scenes.length * 4,
        scenes: obj.scenes.map((scene, idx) => ({
          scene_id: idx + 1,
          duration: scene.duration || '4s',
          visual_description: scene.visual_description || scene.visual_description_zh || '',
          visual_description_zh: scene.visual_description_zh || scene.visual_description || '',
          narration: scene.narration || '',
          camera_movement: scene.camera_movement || 'static',
          text_overlay: scene.text_overlay || '',
          transition: scene.transition || 'cut',
          characters: scene.characters || [],
          has_product: scene.has_product ?? true,
        })),
      }
    }
  } catch {
    // fall through to line-based parsing
  }

  const lines = raw
    .split(/\n+/)
    .map((line) => line.replace(/^\s*(?:[-*]|\d+[.)、]|场景\s*\d+[:：]?)\s*/i, '').trim())
    .filter(Boolean)

  if (lines.length === 0) {
    throw new Error('没有识别到有效场景描述')
  }

  const copyLines = copyText.split(/\n+/).map((line) => line.trim()).filter(Boolean)
  return {
    title: '导入脚本',
    duration_seconds: lines.length * 4,
    scenes: lines.map((line, idx) => ({
      scene_id: idx + 1,
      duration: '4s',
      visual_description: line,
      visual_description_zh: line,
      narration: copyLines[idx] || '',
      camera_movement: 'static',
      text_overlay: '',
      transition: idx === 0 ? 'cut' : 'fade',
      characters: [],
      has_product: true,
    })),
  }
}

function ConfigPanel({ config, onChange, disabled }: {
  config: PipelineConfig
  onChange: (c: PipelineConfig) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)

  const update = (key: keyof PipelineConfig, val: string | boolean) => {
    onChange({ ...config, [key]: val })
  }

  const setStageModel = (stage: PipelineStageKey, m: PipelineStageModel) => {
    const nextModels = { ...(config.models || {}) }
    if (!m.provider || !m.model) {
      delete nextModels[stage]
    } else {
      nextModels[stage] = m
    }
    onChange({ ...config, models: nextModels })
  }

  return (
    <div className="border rounded-lg bg-gray-50/50">
      <button
        className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-100/50 rounded-lg transition"
        onClick={() => setOpen(!open)}
      >
        <span className="flex items-center gap-2">
          <Settings2 className="h-4 w-4" />
          生成参数配置
        </span>
        {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1 space-y-4 border-t">
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            文案风格、语气、节奏、画面风格不再作为手动参数。系统会结合 Brief、知识库、产品图和分镜描述自动推断。
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <LabeledSelect label="视频比例" value={config.video_ratio || '16:9'}
              onChange={v => update('video_ratio', v)} options={RATIO_OPTIONS} />
            <div>
              <label className="text-xs text-gray-500 block mb-1">生成音频</label>
              <label className="flex items-center gap-2 h-9 px-3 rounded-md border bg-white cursor-pointer">
                <input type="checkbox" checked={!!config.generate_audio}
                  onChange={e => update('generate_audio', e.target.checked)} disabled={disabled} />
                <span className="text-sm">{config.generate_audio ? '开启' : '关闭'}</span>
              </label>
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">产品描述（可选，帮助 AI 更准确描绘产品）</label>
            <Input
              value={config.product_description || ''}
              onChange={e => update('product_description', e.target.value)}
              placeholder="如：红色瓶身、金色瓶盖的酱油瓶"
              disabled={disabled}
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">人脸生成基础指引（可选）</label>
            <Textarea
              value={config.avatar_generation_guidance || ''}
              onChange={e => update('avatar_generation_guidance', e.target.value)}
              placeholder="如：25-30 岁女性，亲和自然，黑色中长发，淡妆，白色上衣；避免夸张网红脸、浓妆、过度磨皮。"
              disabled={disabled}
              rows={3}
              className="text-xs"
            />
            <p className="mt-1 text-[11px] text-gray-500">
              会用于角色分析和人脸参考图生成，帮助同一人物在分镜和视频中更稳定。
            </p>
          </div>
          <div className="pt-3 border-t">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="h-4 w-4 text-gray-500" />
              <span className="text-sm font-medium text-gray-700">分步模型选择</span>
              <span className="text-[11px] text-gray-500">（不选则使用系统默认 / 全局配置）</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {STAGE_LABELS.map(({ key, label, capability }) => (
                <ModelSelector
                  key={key}
                  capability={capability}
                  label={label}
                  value={getStageModel(config, key)}
                  onChange={(m) => setStageModel(key, m)}
                  disabled={disabled}
                />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Main Page ── */

export default function ContentStudioPage() {
  const {
    pipelines, currentPipeline, presets, loading, stepLoading, error,
    storyboardPromptPreviews, videoPromptPreviews,
    fetchPipelines, fetchPipeline, createPipeline, updatePipeline, updateConfig,
    generateCopy, generateScript, analyzeScript, generateCharacterFaces,
    generateStoryboard, regenerateStoryboardScene, regenerateStoryboardScenes,
    generateVideos, regenerateVideoScene, regenerateVideoScenes, composeFinal,
    previewStoryboardPrompts, previewVideoPrompts, fetchPresets,
  } = useContentStudioStore()

  const [view, setView] = useState<'list' | 'editor'>('list')
  const [drawerNode, setDrawerNode] = useState<string | null>(null)
  const [newTitle, setNewTitle] = useState('')
  const [newSource, setNewSource] = useState('')
  const [selectedPreset, setSelectedPreset] = useState('')
  const [newConfig, setNewConfig] = useState<PipelineConfig>({})
  const [showCreate, setShowCreate] = useState(false)

  // Editor state
  const [editCopy, setEditCopy] = useState('')
  const [editingCopy, setEditingCopy] = useState(false)
  const [editingScript, setEditingScript] = useState(false)
  const [editScriptJson, setEditScriptJson] = useState('')
  const [scriptJsonError, setScriptJsonError] = useState('')
  const [showPromptPreview, setShowPromptPreview] = useState(false)
  const [copyInputMode, setCopyInputMode] = useState<'auto' | 'import'>('auto')
  const [importCopyText, setImportCopyText] = useState('')
  const [importScenesText, setImportScenesText] = useState('')
  const [importError, setImportError] = useState('')
  const [selectedScenes, setSelectedScenes] = useState<number[]>([])
  const [useNextSceneAsLastFrame, setUseNextSceneAsLastFrame] = useState(true)
  const [videoHints, setVideoHints] = useState<Record<number, string>>({})
  const [skipFinalConcat, setSkipFinalConcat] = useState(false)

  useEffect(() => { fetchPipelines(); fetchPresets() }, [fetchPipelines, fetchPresets])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const id = params.get('id')
    if (id) {
      void (async () => {
        await fetchPipeline(id)
        setView('editor')
      })()
      return
    }
    const text = params.get('source_text')
    if (text) {
      const safeText = (() => {
        try { return decodeURIComponent(text) } catch { return text }
      })()
      setNewSource(safeText)
      setShowCreate(true)
    }
  }, [fetchPipeline])

  // Apply preset config when selecting
  useEffect(() => {
    if (selectedPreset) {
      const p = presets.find(p => p.id === selectedPreset)
      if (p?.config) setNewConfig(prev => ({ ...prev, ...p.config }))
    }
  }, [selectedPreset, presets])

  const pipe = currentPipeline
  const currentStepIdx = pipe ? STEP_ORDER.indexOf(pipe.current_step as typeof STEP_ORDER[number]) : -1
  const pipeConfig: PipelineConfig = (pipe?.config && typeof pipe.config === 'object') ? pipe.config : {}

  // Parsed data from pipeline
  const scriptResult: ScriptResult | null = pipe?.script_result
    ? (typeof pipe.script_result === 'object' ? pipe.script_result as ScriptResult : null)
    : null
  const scenes: Scene[] = scriptResult?.scenes || []
  const storyboard: StoryboardItem[] = Array.isArray(pipe?.storyboard_results) ? pipe.storyboard_results : []
  const videos: VideoItem[] = Array.isArray(pipe?.video_results) ? pipe.video_results : []
  const characters: CharacterProfile[] = Array.isArray(pipe?.character_profiles) ? pipe.character_profiles : []

  useEffect(() => {
    setSelectedScenes([])
  }, [pipe?.id])

  /* ── Handlers ── */

  const handleCreate = useCallback(async () => {
    if (!newTitle.trim() || !newSource.trim()) return
    const p = await createPipeline(newTitle, newSource, newConfig)
    if (p) {
      setView('editor')
      setShowCreate(false)
      setNewTitle('')
      setNewSource('')
      setNewConfig({})
    }
  }, [newTitle, newSource, newConfig, createPipeline])

  const openPipeline = useCallback(async (id: string) => {
    await fetchPipeline(id)
    setView('editor')
    setEditingCopy(false)
    setEditingScript(false)
    setShowPromptPreview(false)
  }, [fetchPipeline])

  const handleStepAction = useCallback(async () => {
    if (!pipe) return
    const step = pipe.current_step
    if (step === 'copy') await generateCopy(pipe.id)
    else if (step === 'script') await generateScript(pipe.id)
    else if (step === 'analyze') await analyzeScript(pipe.id)
    else if (step === 'characters') await generateCharacterFaces(pipe.id)
    else if (step === 'storyboard') await generateStoryboard(pipe.id)
    else if (step === 'video') await generateVideos(pipe.id)
    else if (step === 'compose') await composeFinal(pipe.id)
  }, [pipe, generateCopy, generateScript, analyzeScript, generateCharacterFaces, generateStoryboard, generateVideos, composeFinal])

  const handleConfirmCopy = useCallback(async () => {
    if (!pipe) return
    await updatePipeline(pipe.id, { copy_result: editCopy || pipe.copy_result } as Partial<Pipeline>)
    setEditingCopy(false)
    await generateScript(pipe.id)
  }, [pipe, editCopy, updatePipeline, generateScript])

  const handleSaveScript = useCallback(async () => {
    if (!pipe) return
    try {
      const parsed = JSON.parse(editScriptJson)
      if (!parsed.scenes || !Array.isArray(parsed.scenes)) {
        setScriptJsonError('JSON 必须包含 scenes 数组')
        return
      }
      setScriptJsonError('')
      await updatePipeline(pipe.id, { script_result: parsed } as Partial<Pipeline>)
      setEditingScript(false)
    } catch {
      setScriptJsonError('JSON 格式不合法')
    }
  }, [pipe, editScriptJson, updatePipeline])

  const handleConfigChange = useCallback(async (cfg: PipelineConfig) => {
    if (!pipe) return
    await updateConfig(pipe.id, cfg)
  }, [pipe, updateConfig])

  const handleSkipAnalyze = useCallback(async () => {
    if (!pipe) return
    // Skip analyze & characters, go directly to storyboard
    await updatePipeline(pipe.id, { current_step: 'storyboard', status: 'paused' } as Partial<Pipeline>)
    await fetchPipeline(pipe.id)
  }, [pipe, updatePipeline, fetchPipeline])

  const handleSkipCharacters = useCallback(async () => {
    if (!pipe) return
    await updatePipeline(pipe.id, { current_step: 'storyboard', status: 'paused' } as Partial<Pipeline>)
    await fetchPipeline(pipe.id)
  }, [pipe, updatePipeline, fetchPipeline])

  const toggleSceneSelection = useCallback((sceneId: number) => {
    setSelectedScenes((prev) =>
      prev.includes(sceneId) ? prev.filter((id) => id !== sceneId) : [...prev, sceneId].sort((a, b) => a - b),
    )
  }, [])

  const selectAllStoryboardScenes = useCallback(() => {
    setSelectedScenes(storyboard.map((s) => s.scene_id).sort((a, b) => a - b))
  }, [storyboard])

  const clearSceneSelection = useCallback(() => {
    setSelectedScenes([])
  }, [])

  const handleBatchStoryboard = useCallback(async () => {
    if (!pipe || selectedScenes.length === 0) return
    await regenerateStoryboardScenes(pipe.id, selectedScenes)
    setSelectedScenes([])
  }, [pipe, selectedScenes, regenerateStoryboardScenes])

  const handleBatchVideo = useCallback(async () => {
    if (!pipe || selectedScenes.length === 0) return
    await regenerateVideoScenes(pipe.id, selectedScenes, { useNextSceneAsLastFrame })
  }, [pipe, selectedScenes, regenerateVideoScenes, useNextSceneAsLastFrame])

  const handleImportCopyOnly = useCallback(async () => {
    if (!pipe) return
    const copy = importCopyText.trim()
    if (!copy) {
      setImportError('请先粘贴或上传已有文案')
      return
    }
    setImportError('')
    await updatePipeline(pipe.id, { copy_result: copy } as Partial<Pipeline>)
    await generateScript(pipe.id)
  }, [pipe, importCopyText, updatePipeline, generateScript])

  const handleImportCopyAndScenes = useCallback(async () => {
    if (!pipe) return
    const copy = importCopyText.trim()
    if (!copy) {
      setImportError('请先粘贴或上传已有文案')
      return
    }
    try {
      const script = parseImportedScript(copy, importScenesText)
      setImportError('')
      const res = await fetch(`/api/omni/content-studio/script/import?pipeline_id=${pipe.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ copy_result: copy, script }),
      })
      if (!res.ok) {
        throw new Error(await res.text())
      }
      await fetchPipeline(pipe.id)
    } catch (err) {
      setImportError((err as Error).message)
    }
  }, [pipe, importCopyText, importScenesText, fetchPipeline])

  const handleImportFile = useCallback(async (file: File | undefined, target: 'copy' | 'scenes') => {
    if (!file) return
    const text = await file.text()
    if (target === 'copy') {
      setImportCopyText(text)
    } else {
      setImportScenesText(text)
    }
  }, [])

  /* ── List View ── */

  if (view === 'list') {
    return (
      <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white">
        <div className="mx-auto max-w-6xl px-6 pt-4">
          <ContentStudioHubNav />

          <div className="mb-6 flex items-end justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">生成流水线</h1>
              <p className="mt-1 text-sm text-gray-500">
                推荐使用「向导」从 Brief + 数字人脸开始；高级模式（自由文本）保留作为兜底。
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Link href="/content-studio/new">
                <Button className="gap-2 bg-violet-600 hover:bg-violet-700">
                  <Sparkles className="h-4 w-4" /> 使用向导创建
                </Button>
              </Link>
              <Button
                variant="outline"
                onClick={() => setShowCreate(!showCreate)}
                className="gap-2"
              >
                <Settings2 className="h-4 w-4" /> {showCreate ? '收起' : '高级模式'}
              </Button>
            </div>
          </div>

          {/* Create Card — 高级模式（向后兼容 v1 source_text 入口） */}
          {showCreate && (
            <Card className="mb-6 border-amber-200 bg-amber-50/30">
              <CardContent className="p-6">
                <div className="mb-3 flex items-start justify-between">
                  <div>
                    <h3 className="text-lg font-semibold">高级模式 · 自由文本</h3>
                    <p className="text-xs text-gray-500 mt-0.5">
                      不挂 Brief / 数字人，直接粘文案；旧入口保留用于回归。
                    </p>
                  </div>
                  <Link href="/content-studio/new" className="text-xs text-violet-600 hover:underline shrink-0">
                    用向导创建 →
                  </Link>
                </div>
                <div className="space-y-4">
                  <Input placeholder="任务标题" value={newTitle}
                    onChange={e => setNewTitle(e.target.value)} />
                  <Textarea placeholder="粘贴运营方案或文案素材..." rows={6} value={newSource}
                    onChange={e => setNewSource(e.target.value)} className="resize-none" />
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-gray-600">风格预设：</span>
                    <select className="rounded border px-3 py-1.5 text-sm"
                      value={selectedPreset} onChange={e => setSelectedPreset(e.target.value)}>
                      <option value="">默认</option>
                      {presets.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                  </div>
                  <ConfigPanel config={newConfig} onChange={setNewConfig} />
                  <div className="flex gap-2">
                    <Button onClick={handleCreate} disabled={!newTitle.trim() || !newSource.trim()}>
                      创建并开始
                    </Button>
                    <Button variant="ghost" onClick={() => setShowCreate(false)}>取消</Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Pipeline List */}
          {loading && !pipelines.length ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
            </div>
          ) : pipelines.length === 0 ? (
            <EmptyStateGuide />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {pipelines.map(p => (
                <Card key={p.id} className="cursor-pointer transition hover:shadow-md"
                  onClick={() => openPipeline(p.id)}>
                  <CardContent className="p-4">
                    <div className="mb-2 flex items-start justify-between">
                      <h3 className="font-medium text-gray-900 line-clamp-1">{p.title}</h3>
                      <Badge variant="secondary" className="ml-2 shrink-0 text-xs">
                        {STATUS_LABELS[p.status] || p.status}
                      </Badge>
                    </div>
                    <p className="mb-3 text-xs text-gray-400">
                      {p.created_at ? new Date(p.created_at).toLocaleString('zh-CN') : ''}
                    </p>
                    <div className="flex gap-1">
                      {STEPS.map((s, i) => {
                        const stepIdx = STEP_ORDER.indexOf(p.current_step as typeof STEP_ORDER[number])
                        const done = i < stepIdx || p.status === 'completed'
                        const active = i === stepIdx
                        return (
                          <div key={s.key}
                            className={`h-1.5 flex-1 rounded-full ${done ? 'bg-green-400' : active ? 'bg-blue-400' : 'bg-gray-200'}`} />
                        )
                      })}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  /* ── Editor View ── */

  if (!pipe) return null

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white">
      {/* Header */}
      <div className="border-b bg-white px-6 py-3">
        <div className="mx-auto flex max-w-6xl items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => { setView('list'); fetchPipelines() }}>
            <ArrowLeft className="mr-1 h-4 w-4" /> 返回
          </Button>
          <h2 className="text-lg font-semibold text-gray-900 truncate">{pipe.title}</h2>
          <Badge variant="outline">{STATUS_LABELS[pipe.status] || pipe.status}</Badge>
          {pipe.error_message && (
            <span className="ml-auto text-sm text-red-500 truncate max-w-xs" title={pipe.error_message}>
              {pipe.error_message}
            </span>
          )}
          {error && <span className="ml-auto text-sm text-red-500">{error}</span>}
        </div>
      </div>

      {/* Stepper — 7 steps */}
      <div className="border-b bg-white px-6 py-3">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          {STEPS.map((s, i) => {
            const Icon = s.icon
            const done = i < currentStepIdx || pipe.status === 'completed'
            const active = i === currentStepIdx
            return (
              <React.Fragment key={s.key}>
                {i > 0 && <div className={`mx-1 h-0.5 flex-1 ${done ? 'bg-green-400' : 'bg-gray-200'}`} />}
                <div className={`flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs font-medium whitespace-nowrap
                  ${done ? 'bg-green-50 text-green-700' : active ? 'bg-blue-50 text-blue-700' : 'text-gray-400'}`}>
                  {done ? <Check className="h-3.5 w-3.5" /> : <Icon className="h-3.5 w-3.5" />}
                  {s.label}
                </div>
              </React.Fragment>
            )
          })}
        </div>
      </div>

      {/* Content area */}
      <div className="mx-auto max-w-6xl p-6 space-y-6">

        <ClosureGuide pipe={pipe} scenes={scenes} storyboard={storyboard} videos={videos} />

        {/* ── Config Panel (always accessible in editor) ── */}
        <ConfigPanel config={pipeConfig} onChange={handleConfigChange} disabled={pipe.status === 'running'} />

        {/* ── Step 1: Copy ── */}
        {pipe.current_step === 'copy' && !pipe.copy_result && (
          <Card>
            <CardContent className="p-6">
              <div className="mb-5 text-center">
                <Sparkles className="mx-auto mb-4 h-10 w-10 text-blue-400" />
                <h3 className="mb-2 text-lg font-semibold">文案输入方式</h3>
                <p className="text-sm text-gray-500">可以结合知识库自动生成，也可以导入已经写好的文案和场景描述。</p>
              </div>

              <div className="mb-5 grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setCopyInputMode('auto')}
                  className={`rounded-xl border p-4 text-left transition ${copyInputMode === 'auto' ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'}`}
                >
                  <div className="font-medium text-gray-900">自动生成文案</div>
                  <div className="mt-1 text-xs text-gray-500">基于 Brief、知识库和产品信息生成营销文案。</div>
                </button>
                <button
                  type="button"
                  onClick={() => setCopyInputMode('import')}
                  className={`rounded-xl border p-4 text-left transition ${copyInputMode === 'import' ? 'border-violet-400 bg-violet-50' : 'border-gray-200 hover:bg-gray-50'}`}
                >
                  <div className="font-medium text-gray-900">导入已有文案 / 场景</div>
                  <div className="mt-1 text-xs text-gray-500">上传或粘贴已有文案，场景描述会转换为后续分镜/视频提示词。</div>
                </button>
              </div>

              {copyInputMode === 'auto' ? (
                <div className="text-center">
                  <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                    {stepLoading === 'copy' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                    结合知识库自动生成文案
                  </Button>
                </div>
              ) : (
                <div className="space-y-4">
                  {importError && (
                    <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{importError}</div>
                  )}
                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <label className="text-sm font-medium text-gray-700">已有文案</label>
                      <label className="cursor-pointer text-xs text-violet-700 underline">
                        上传文案文件
                        <input
                          type="file"
                          accept=".txt,.md,.json"
                          className="hidden"
                          onChange={(e) => void handleImportFile(e.target.files?.[0], 'copy')}
                        />
                      </label>
                    </div>
                    <Textarea
                      rows={7}
                      value={importCopyText}
                      onChange={(e) => setImportCopyText(e.target.value)}
                      placeholder="粘贴已经生成好的营销文案..."
                    />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between">
                      <label className="text-sm font-medium text-gray-700">场景描述（可选，但填写后可跳过脚本生成）</label>
                      <label className="cursor-pointer text-xs text-violet-700 underline">
                        上传场景文件
                        <input
                          type="file"
                          accept=".txt,.md,.json"
                          className="hidden"
                          onChange={(e) => void handleImportFile(e.target.files?.[0], 'scenes')}
                        />
                      </label>
                    </div>
                    <Textarea
                      rows={8}
                      value={importScenesText}
                      onChange={(e) => setImportScenesText(e.target.value)}
                      placeholder={'每行一个场景描述，或粘贴 JSON：{ "title": "...", "scenes": [...] }'}
                    />
                    <p className="mt-1 text-xs text-gray-500">
                      只导入文案：系统继续生成 10 scene 脚本；导入文案 + 场景：直接进入角色分析，后续会把场景转为分镜/视频 Prompt。
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="outline" onClick={() => void handleImportCopyOnly()} disabled={!!stepLoading}>
                      导入文案，继续生成脚本
                    </Button>
                    <Button onClick={() => void handleImportCopyAndScenes()} disabled={!!stepLoading}>
                      导入文案 + 场景，进入后续生成
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Copy result — editable */}
        {pipe.copy_result && (
          <Card>
            <CardContent className="p-6">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="font-semibold text-gray-900">营销文案</h3>
                <div className="flex gap-2">
                  {!editingCopy && (
                    <Button variant="ghost" size="sm" onClick={() => { setEditCopy(pipe.copy_result || ''); setEditingCopy(true) }}>
                      <Pen className="mr-1 h-3 w-3" /> 编辑
                    </Button>
                  )}
                  {pipe.current_step === 'copy' && pipe.copy_result && (
                    <Button variant="ghost" size="sm" onClick={() => generateCopy(pipe.id)} disabled={!!stepLoading}>
                      <RefreshCw className="mr-1 h-3 w-3" /> 重新生成
                    </Button>
                  )}
                </div>
              </div>
              {editingCopy ? (
                <div>
                  <Textarea value={editCopy} onChange={e => setEditCopy(e.target.value)} rows={8} className="mb-3" />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={handleConfirmCopy} disabled={!!stepLoading}>
                      {stepLoading === 'script' ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                      确认并生成脚本
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditingCopy(false)}>取消</Button>
                  </div>
                </div>
              ) : (
                <div className="whitespace-pre-wrap text-sm text-gray-700 leading-relaxed">{pipe.copy_result}</div>
              )}
              {!editingCopy && pipe.copy_result && (
                <div className="mt-3">
                  <PromptFeedback
                    nodeId="content.copy"
                    inputRef={{ pipeline_id: pipe.id, copy_style: pipe.config?.copy_style || 'grassplanting' }}
                    output={pipe.copy_result}
                    onOpenDrawer={setDrawerNode}
                  />
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ── Step 2: Script ── */}
        {pipe.current_step === 'script' && !pipe.script_result && !editingCopy && (
          <Card>
            <CardContent className="p-6 text-center">
              <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                {stepLoading === 'script' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                生成分镜脚本
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Script result — viewable and editable */}
        {scriptResult && scenes.length > 0 && (
          <Card>
            <CardContent className="p-6">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="font-semibold text-gray-900">
                  分镜脚本 — {scriptResult.title} ({scenes.length} 个场景, ~{scriptResult.duration_seconds}s)
                </h3>
                <div className="flex gap-2">
                  <Button variant="ghost" size="sm" onClick={() => {
                    setEditScriptJson(JSON.stringify(scriptResult, null, 2))
                    setEditingScript(!editingScript)
                    setScriptJsonError('')
                  }}>
                    <Pen className="mr-1 h-3 w-3" /> {editingScript ? '取消编辑' : '编辑脚本'}
                  </Button>
                  {(pipe.current_step === 'script' || pipe.current_step === 'analyze') && (
                    <Button variant="ghost" size="sm" onClick={() => generateScript(pipe.id)} disabled={!!stepLoading}>
                      <RefreshCw className="mr-1 h-3 w-3" /> 重新生成
                    </Button>
                  )}
                </div>
              </div>

              {editingScript ? (
                <div>
                  <Textarea
                    value={editScriptJson}
                    onChange={e => setEditScriptJson(e.target.value)}
                    rows={16}
                    className="mb-2 font-mono text-xs"
                  />
                  {scriptJsonError && (
                    <p className="mb-2 text-sm text-red-500">{scriptJsonError}</p>
                  )}
                  <div className="flex gap-2">
                    <Button size="sm" onClick={handleSaveScript}>保存脚本</Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditingScript(false)}>取消</Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  {scenes.map(scene => (
                    <div key={scene.scene_id} className="flex gap-4 rounded-lg border p-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-50 text-sm font-bold text-blue-600">
                        {scene.scene_id}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-gray-400">
                          <span>{scene.duration}</span>
                          <span>·</span>
                          <span>{scene.camera_movement}</span>
                          {scene.transition && <><span>·</span><span>{'→'} {scene.transition}</span></>}
                          {scene.has_product && <Badge variant="secondary" className="text-[10px] px-1.5 py-0">产品</Badge>}
                          {scene.characters && scene.characters.length > 0 && (
                            <span className="flex items-center gap-0.5">
                              <User className="h-3 w-3" /> {scene.characters.join(', ')}
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-gray-600">{scene.visual_description_zh || scene.visual_description}</p>
                        {scene.narration && (
                          <p className="mt-1 text-sm italic text-gray-500">旁白: {scene.narration}</p>
                        )}
                        {scene.text_overlay && (
                          <p className="mt-1 text-xs text-blue-500">花字: {scene.text_overlay}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {!editingScript && (
                <div className="mt-3">
                  <PromptFeedback
                    nodeId="content.script"
                    inputRef={{
                      pipeline_id: pipe.id,
                      pace: pipe.config?.pace || 'medium',
                      image_style: pipe.config?.image_style || 'lifestyle_photo',
                    }}
                    output={JSON.stringify(scriptResult).slice(0, 4000)}
                    onOpenDrawer={setDrawerNode}
                  />
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* ── Step 3: Analyze — extract characters ── */}
        {pipe.current_step === 'analyze' && (
          <Card>
            <CardContent className="p-6">
              <div className="text-center">
                <Search className="mx-auto mb-3 h-8 w-8 text-violet-400" />
                <h3 className="mb-2 text-lg font-semibold">角色与产品分析</h3>
                <p className="mb-4 text-sm text-gray-500">
                  AI 将分析脚本中出现的人物角色和产品，用于后续保持画面一致性
                </p>
                <div className="flex items-center justify-center gap-3">
                  <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                    {stepLoading === 'analyze' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                    开始分析
                  </Button>
                  <Button variant="outline" onClick={handleSkipAnalyze} disabled={!!stepLoading}>
                    跳过，直接生成分镜图
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Step 4: Characters — generate face references ── */}
        {pipe.current_step === 'characters' && (
          <Card>
            <CardContent className="p-6">
              {characters.length > 0 ? (
                <>
                  <h3 className="mb-4 font-semibold text-gray-900">
                    角色档案 ({characters.length} 位角色)
                  </h3>
                  {characters.length > 1 && (
                    <CharacterAvatarMapping
                      pipelineId={pipe.id}
                      characters={characters}
                      initialMap={(pipe as Pipeline & { character_avatar_map?: Record<string, string> }).character_avatar_map ?? {}}
                      onSaved={() => fetchPipeline(pipe.id)}
                    />
                  )}
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-6">
                    {characters.map(ch => (
                      <div key={ch.id} className="rounded-lg border p-4">
                        <div className="flex items-start gap-3">
                          {ch.face_url ? (
                            <img src={ch.face_url} alt={ch.name}
                              className="h-16 w-16 rounded-lg object-cover border" />
                          ) : (
                            <div className="h-16 w-16 rounded-lg bg-gray-100 flex items-center justify-center">
                              <User className="h-6 w-6 text-gray-300" />
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <h4 className="font-medium text-gray-900">{ch.name}</h4>
                            <p className="text-xs text-gray-500">
                              {ch.gender === 'female' ? '女' : ch.gender === 'male' ? '男' : ch.gender}
                              {ch.age_range && ` · ${ch.age_range}岁`}
                            </p>
                            <p className="mt-1 text-xs text-gray-400 line-clamp-2">{ch.appearance}</p>
                            <p className="mt-1 text-xs text-blue-500">
                              出现场景: {ch.scene_ids?.join(', ')}
                            </p>
                            {ch.face_url && pipe?.id && (
                              <button
                                type="button"
                                className="mt-2 text-[11px] px-2 py-0.5 rounded border border-violet-300 text-violet-700 hover:bg-violet-50"
                                onClick={async () => {
                                  const name = window.prompt(`把"${ch.name}"另存为 Avatar 的名字`, ch.name)
                                  if (!name) return
                                  try {
                                    const r = await fetch(
                                      '/api/omni/content-studio/digital-humans/promote-from-pipeline',
                                      {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({
                                          pipeline_id: pipe.id,
                                          character_name: ch.name,
                                          new_avatar_name: name,
                                        }),
                                      },
                                    )
                                    if (!r.ok) throw new Error(`${r.status}`)
                                    alert('已另存为 Avatar（draft 状态），可在数字人脸库中查看')
                                  } catch (e) {
                                    alert(`保存失败：${(e as Error).message}`)
                                  }
                                }}
                              >
                                另存为 Avatar
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center justify-center gap-3">
                    <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                      {stepLoading === 'characters' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Users className="h-4 w-4" />}
                      {characters.some(c => c.face_url) ? '重新生成角色人像' : '生成角色人像'}
                    </Button>
                    <Button variant="outline" onClick={handleSkipCharacters} disabled={!!stepLoading}>
                      跳过，直接生成分镜图
                    </Button>
                  </div>
                </>
              ) : (
                <div className="text-center">
                  <Users className="mx-auto mb-3 h-8 w-8 text-violet-400" />
                  <p className="mb-4 text-sm text-gray-500">未检测到角色信息</p>
                  <Button variant="outline" onClick={handleSkipCharacters}>
                    继续到分镜图生成
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Character profiles display (shown after character step is done) */}
        {characters.length > 0 && characters.some(c => c.face_url) && pipe.current_step !== 'characters' && (
          <Card>
            <CardContent className="p-4">
              <h3 className="mb-3 text-sm font-semibold text-gray-700">角色档案</h3>
              <div className="flex gap-4 overflow-x-auto pb-1">
                {characters.map(ch => (
                  <div key={ch.id} className="flex items-center gap-2 shrink-0">
                    {ch.face_url ? (
                      <img src={ch.face_url} alt={ch.name} className="h-10 w-10 rounded-lg object-cover border" />
                    ) : (
                      <div className="h-10 w-10 rounded-lg bg-gray-100 flex items-center justify-center">
                        <User className="h-4 w-4 text-gray-300" />
                      </div>
                    )}
                    <div>
                      <span className="text-sm font-medium">{ch.name}</span>
                      <p className="text-[10px] text-gray-400">{ch.appearance?.slice(0, 20)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Step 5: Storyboard ── */}
        {pipe.current_step === 'storyboard' && storyboard.length === 0 && scenes.length > 0 && (
          <Card>
            <CardContent className="p-6">
              <div className="text-center mb-4">
                <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                  {stepLoading === 'storyboard' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImageIcon className="h-4 w-4" />}
                  生成分镜图 ({scenes.length} 张)
                </Button>
              </div>
              {/* Prompt Preview Button */}
              <div className="text-center">
                <Button variant="outline" size="sm" className="gap-1"
                  onClick={() => { previewStoryboardPrompts(pipe.id); setShowPromptPreview(true) }}
                  disabled={stepLoading === 'preview-storyboard'}>
                  {stepLoading === 'preview-storyboard' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Eye className="h-3 w-3" />}
                  预览生成 Prompt
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Prompt Preview Panel */}
        {showPromptPreview && storyboardPromptPreviews.length > 0 && (
          <Card className="border-amber-200 bg-amber-50/30">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900">Prompt 预览（生成前检查）</h3>
                <Button variant="ghost" size="sm" onClick={() => setShowPromptPreview(false)}>关闭</Button>
              </div>
              <div className="space-y-3">
                {storyboardPromptPreviews.map(p => (
                  <div key={p.scene_id} className="rounded-lg border bg-white p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge variant="secondary" className="text-xs">场景 {p.scene_id}</Badge>
                      {p.has_product && <Badge variant="outline" className="text-[10px]">含产品</Badge>}
                      {p.characters_in_scene && p.characters_in_scene.length > 0 && (
                        <span className="text-xs text-gray-400">角色: {p.characters_in_scene.join(', ')}</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 mb-1">原始描述: {p.original_description}</p>
                    <p className="text-sm text-gray-800 font-mono bg-gray-50 p-2 rounded">{p.prompt_will_use}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Storyboard grid */}
        {storyboard.length > 0 && (
          <Card>
            <CardContent className="p-6">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-gray-900">分镜看板</h3>
                  <p className="mt-1 text-xs text-gray-500">
                    可勾选多个分镜，只重生成这些图，或只为选中分镜创建视频任务。
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="outline" size="sm" onClick={selectAllStoryboardScenes}>
                    全选
                  </Button>
                  <Button variant="ghost" size="sm" onClick={clearSceneSelection} disabled={selectedScenes.length === 0}>
                    清空
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1"
                    disabled={selectedScenes.length === 0 || stepLoading === 'storyboard-batch'}
                    onClick={() => void handleBatchStoryboard()}
                  >
                    {stepLoading === 'storyboard-batch' ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                    重生成选中图 ({selectedScenes.length})
                  </Button>
                  <label className="flex items-center gap-1.5 rounded border px-2 py-1 text-xs text-gray-600">
                    <input
                      type="checkbox"
                      checked={useNextSceneAsLastFrame}
                      onChange={(e) => setUseNextSceneAsLastFrame(e.target.checked)}
                    />
                    尾帧=下一分镜
                  </label>
                  <Button
                    size="sm"
                    className="gap-1"
                    disabled={selectedScenes.length === 0 || stepLoading === 'video-batch'}
                    onClick={() => void handleBatchVideo()}
                  >
                    {stepLoading === 'video-batch' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Video className="h-3 w-3" />}
                    生成选中视频 ({selectedScenes.length})
                  </Button>
                </div>
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {storyboard.map(sb => {
                  const scene = scenes.find(s => s.scene_id === sb.scene_id)
                  const vid = videos.find(v => v.scene_id === sb.scene_id)
                  const selected = selectedScenes.includes(sb.scene_id)
                  return (
                    <div key={sb.scene_id} className={`overflow-hidden rounded-lg border ${selected ? 'border-violet-400 ring-2 ring-violet-100' : ''}`}>
                      <div className="relative aspect-video bg-gray-100">
                        <label className="absolute left-2 top-2 z-10 flex items-center gap-1 rounded bg-white/90 px-2 py-1 text-[11px] shadow">
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => toggleSceneSelection(sb.scene_id)}
                          />
                          选中
                        </label>
                        {sb.image_url ? (
                          <img src={sb.image_url} alt={`Scene ${sb.scene_id}`}
                            className="h-full w-full object-cover" />
                        ) : sb.status === 'failed' ? (
                          <div className="flex h-full flex-col items-center justify-center text-red-400 px-2">
                            <ImageIcon className="h-6 w-6 mb-1" />
                            <span className="text-xs text-center">{sb.error || '生成失败'}</span>
                          </div>
                        ) : (
                          <div className="flex h-full items-center justify-center text-gray-300">
                            <ImageIcon className="h-8 w-8" />
                          </div>
                        )}
                      </div>
                      <div className="p-3">
                        <div className="mb-1 flex items-center justify-between">
                          <span className="text-sm font-medium">场景 {sb.scene_id}</span>
                          <span className="text-xs text-gray-400">{scene?.duration}</span>
                        </div>
                        {scene && (
                          <p className="mb-2 text-xs text-gray-500 line-clamp-2">
                            {scene.visual_description_zh || scene.visual_description}
                          </p>
                        )}
                        {sb.prompt_used && (
                          <details className="mb-2">
                            <summary className="text-[10px] text-gray-400 cursor-pointer">查看 Prompt</summary>
                            <p className="text-[10px] text-gray-500 mt-1 font-mono bg-gray-50 p-1 rounded">{sb.prompt_used}</p>
                          </details>
                        )}
                        <div className="flex gap-1">
                          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                            disabled={!!stepLoading && stepLoading.startsWith('storyboard')}
                            onClick={() => regenerateStoryboardScene(pipe.id, sb.scene_id)}>
                            {stepLoading === `storyboard-${sb.scene_id}`
                              ? <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                              : <RefreshCw className="mr-1 h-3 w-3" />}
                            重生成
                          </Button>
                          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                            disabled={!!stepLoading && stepLoading.startsWith('video')}
                            onClick={() => regenerateVideoScene(pipe.id, sb.scene_id)}>
                            {stepLoading === `video-${sb.scene_id}`
                              ? <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                              : <Video className="mr-1 h-3 w-3" />}
                            生成视频
                          </Button>
                          {sb.image_url && (
                            <a href={sb.image_url} download className="inline-flex h-7 items-center rounded px-2 text-xs text-gray-500 hover:bg-gray-100">
                              <Download className="mr-1 h-3 w-3" /> 下载
                            </a>
                          )}
                        </div>
                        {vid && (
                          <div className="mt-2 rounded bg-gray-50 px-2 py-1 text-[10px] text-gray-500">
                            视频：{vid.status || '—'}
                            {vid.task_id ? <span className="ml-1 font-mono">任务 {vid.task_id.slice(0, 18)}...</span> : null}
                            {(vid as VideoItem & { first_frame_used?: string; last_frame_used?: string }).last_frame_used ? (
                              <span className="ml-1 text-violet-600">已用尾帧</span>
                            ) : null}
                            {vid.error ? <div className="mt-0.5 text-rose-500 line-clamp-2">{vid.error}</div> : null}
                          </div>
                        )}
                        {vid && vid.video_url && (
                          <video src={vid.video_url} controls className="mt-2 w-full rounded" />
                        )}
                        {vid && vid.video_url && (
                          <details className="mt-2 group">
                            <summary className="cursor-pointer text-[10px] text-violet-600 hover:text-violet-700 select-none">
                              💬 提修改意见 + 重生成本段
                            </summary>
                            <div className="mt-1.5 space-y-1.5">
                              <textarea
                                className="w-full text-xs border rounded px-2 py-1.5 min-h-[60px] focus:border-violet-300 focus:outline-none"
                                placeholder="例：人物表情更自然一些；背景换到厨房；运镜慢推；产品要正面出现"
                                value={videoHints[sb.scene_id] || ''}
                                onChange={(e) => setVideoHints((prev) => ({ ...prev, [sb.scene_id]: e.target.value }))}
                              />
                              <Button
                                size="sm"
                                className="h-7 px-2 text-xs"
                                disabled={!videoHints[sb.scene_id]?.trim() || (!!stepLoading && stepLoading.startsWith('video'))}
                                onClick={() => regenerateVideoScene(pipe.id, sb.scene_id, undefined, videoHints[sb.scene_id])}
                              >
                                {stepLoading === `video-${sb.scene_id}`
                                  ? <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                  : <RefreshCw className="mr-1 h-3 w-3" />}
                                按修改意见重生成
                              </Button>
                            </div>
                          </details>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Step 6: Video trigger ── */}
        {pipe.current_step === 'video' && videos.length === 0 && storyboard.length > 0 && (
          <Card>
            <CardContent className="p-6 text-center space-y-3">
              <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                {stepLoading === 'video' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
                生成视频片段 ({storyboard.length} 段)
              </Button>
              <div>
                <Button variant="outline" size="sm" className="gap-1"
                  onClick={() => { previewVideoPrompts(pipe.id); setShowPromptPreview(true) }}
                  disabled={stepLoading === 'preview-video'}>
                  {stepLoading === 'preview-video' ? <Loader2 className="h-3 w-3 animate-spin" /> : <Eye className="h-3 w-3" />}
                  预览视频 Prompt
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Video Prompt Preview */}
        {showPromptPreview && videoPromptPreviews.length > 0 && (
          <Card className="border-amber-200 bg-amber-50/30">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900">视频 Prompt 预览</h3>
                <Button variant="ghost" size="sm" onClick={() => setShowPromptPreview(false)}>关闭</Button>
              </div>
              <div className="space-y-3">
                {videoPromptPreviews.map(p => (
                  <div key={p.scene_id} className="rounded-lg border bg-white p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge variant="secondary" className="text-xs">场景 {p.scene_id}</Badge>
                      {p.first_frame && <Badge variant="outline" className="text-[10px]">有首帧</Badge>}
                      {p.reference_images && p.reference_images.length > 0 && (
                        <Badge variant="outline" className="text-[10px]">{p.reference_images.length} 张参考图</Badge>
                      )}
                    </div>
                    <p className="text-sm text-gray-800 font-mono bg-gray-50 p-2 rounded">{p.prompt_will_use}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Step 7: Compose trigger ── */}
        {(pipe.current_step === 'compose' || (pipe.current_step === 'video' && videos.length > 0)) && !pipe.final_video_url && (
          <Card>
            <CardContent className="p-6 text-center space-y-3">
              <label className="inline-flex items-center gap-2 text-xs text-gray-700 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={skipFinalConcat}
                  onChange={(e) => setSkipFinalConcat(e.target.checked)}
                  className="rounded"
                />
                <span>跳过合成 — 只下载 10 段独立视频，自己拿去剪</span>
              </label>
              <div>
                <Button
                  onClick={async () => {
                    if (skipFinalConcat) {
                      await updatePipeline(pipe.id, { skip_final_concat: true } as Partial<Pipeline>)
                    }
                    await composeFinal(pipe.id)
                  }}
                  disabled={!!stepLoading}
                  className="gap-2"
                >
                  {stepLoading === 'compose'
                    ? <Loader2 className="h-4 w-4 animate-spin" />
                    : skipFinalConcat ? <Download className="h-4 w-4" /> : <Film className="h-4 w-4" />}
                  {skipFinalConcat ? '完成（不合成，下载 10 段）' : '合成最终视频'}
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Final video + download */}
        {(pipe.final_video_url || pipe.status === 'completed') && (
          <Card>
            <CardContent className="p-6">
              <h3 className="mb-4 font-semibold text-gray-900">最终视频</h3>
              {pipe.final_video_url && (
                <video src={pipe.final_video_url} controls className="mb-4 w-full max-w-2xl rounded-lg" />
              )}
              <div className="flex gap-3">
                <a href={`/api/omni/content-studio/download/${pipe.id}`}>
                  <Button className="gap-2">
                    <Download className="h-4 w-4" /> 下载全部 (ZIP)
                  </Button>
                </a>
                {pipe.final_video_url && (
                  <a href={pipe.final_video_url} download>
                    <Button variant="outline" className="gap-2">
                      <Download className="h-4 w-4" /> 仅下载视频
                    </Button>
                  </a>
                )}
                <Link href="/ad-review">
                  <Button variant="outline" className="gap-2">
                    <ArrowRight className="h-4 w-4" /> 去投放 / 复盘
                  </Button>
                </Link>
              </div>
              <p className="mt-3 text-xs text-gray-500">
                投放后在 ad-review 的素材行绑定当前 Pipeline（{pipe.id}），复盘完成后 CTR / CVR / 样本数会回灌到 Brief 和 Avatar。
              </p>
            </CardContent>
          </Card>
        )}

        {/* Failed state — allow retry */}
        {pipe.status === 'failed' && (
          <Card className="border-red-200">
            <CardContent className="p-6 text-center">
              <p className="mb-3 text-sm text-red-600">
                步骤「{STEPS.find(s => s.key === pipe.current_step)?.label || pipe.current_step}」执行失败
              </p>
              {pipe.error_message && (
                <p className="mb-4 text-xs text-gray-500 max-w-lg mx-auto break-all">{pipe.error_message}</p>
              )}
              <Button onClick={handleStepAction} disabled={!!stepLoading} variant="outline" className="gap-2">
                <RefreshCw className="h-4 w-4" /> 重试当前步骤
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
      <PromptNodeDrawer nodeId={drawerNode} onClose={() => setDrawerNode(null)} />
    </div>
  )
}


/* ── Empty State Guide：把新版三入口推到用户面前 ── */
function EmptyStateGuide() {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-violet-200 bg-gradient-to-br from-violet-50 to-purple-50 p-8 text-center">
        <Sparkles className="mx-auto mb-3 h-10 w-10 text-violet-500" />
        <h3 className="text-xl font-semibold text-gray-900">还没有任何流水线</h3>
        <p className="mx-auto mt-2 max-w-xl text-sm text-gray-600">
          推荐流程：先准备一个 <b>Brief</b>（结构化策略）和一个 <b>数字人脸</b>（可复用 AI 演员），
          然后在向导里选这两样 + 上传产品图，自动生成口播 → 分镜 → 视频。
        </p>
        <div className="mt-5">
          <Link href="/content-studio/new">
            <Button size="lg" className="gap-2 bg-violet-600 hover:bg-violet-700">
              <Sparkles className="h-4 w-4" /> 使用向导一键开工
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <GuideCard
          href="/content-studio/briefs"
          title="① Brief 库"
          desc="结构化的 USP + 场景 + 人群画像。可一键 LLM 生成、可派生 v2、可挂入 chat 当上下文。"
          icon={FileText}
          accent="indigo"
        />
        <GuideCard
          href="/content-studio/avatars"
          title="② 数字人脸库"
          desc="沉淀可复用的 AI 演员。投放后按 CTR 自动晋级 / 归档，跨流水线保持人脸一致。"
          icon={UserCircle2}
          accent="rose"
        />
        <GuideCard
          href="/content-studio/new"
          title="③ 新建流水线"
          desc="选 Brief + 数字人 + 双路参考图（人脸 + 产品），按步执行 copy → script → 分镜 → 视频。"
          icon={Sparkles}
          accent="violet"
        />
      </div>

      <div className="rounded-lg border border-dashed border-gray-200 bg-white p-4 text-center text-xs text-gray-500">
        如果你有现成文案，也可以点击右上角 <b>「高级模式」</b> 直接粘贴自由文本（兼容 v1 入口）。
      </div>
    </div>
  )
}

function GuideCard({
  href, title, desc, icon: Icon, accent,
}: {
  href: string
  title: string
  desc: string
  icon: React.ElementType
  accent: 'indigo' | 'rose' | 'violet'
}) {
  const colorMap = {
    indigo: 'bg-indigo-50 text-indigo-700 border-indigo-200',
    rose:   'bg-rose-50 text-rose-700 border-rose-200',
    violet: 'bg-violet-50 text-violet-700 border-violet-200',
  }
  return (
    <Link
      href={href}
      className={`block rounded-xl border bg-white p-5 transition hover:shadow-md hover:-translate-y-0.5 ${colorMap[accent].split(' ').filter((c) => c.startsWith('border-')).join(' ')}`}
    >
      <div className={`mb-3 inline-flex h-9 w-9 items-center justify-center rounded-lg ${colorMap[accent]}`}>
        <Icon className="h-5 w-5" />
      </div>
      <div className="text-sm font-semibold text-gray-900">{title}</div>
      <p className="mt-1.5 text-xs text-gray-600 leading-relaxed">{desc}</p>
      <div className="mt-3 flex items-center text-xs text-violet-600">
        进入 <ArrowRight className="ml-1 h-3 w-3" />
      </div>
    </Link>
  )
}


/* ── Multi-character → Avatar mapping (only shown if 2+ characters) ── */
function CharacterAvatarMapping({
  pipelineId,
  characters,
  initialMap,
  onSaved,
}: {
  pipelineId: string
  characters: CharacterProfile[]
  initialMap: Record<string, string>
  onSaved: () => void
}) {
  const { digitalHumans, fetchDigitalHumans } = useContentStudioStore()
  const [map, setMap] = useState<Record<string, string>>(initialMap || {})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (digitalHumans.length === 0) void fetchDigitalHumans()
  }, [digitalHumans.length, fetchDigitalHumans])

  const onSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const r = await fetch(
        `/api/omni/content-studio/pipeline/${pipelineId}/character-avatar-map`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mapping: map }),
        },
      )
      if (!r.ok) throw new Error(`${r.status}`)
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-violet-200 bg-violet-50/40 p-3 mb-4">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-medium text-violet-800">
          多角色场景 — 把每个角色映射到一个数字人
        </div>
        <Button size="sm" disabled={saving} onClick={() => void onSave()}>
          {saving ? '保存中…' : '保存映射'}
        </Button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {characters.map((ch) => (
          <div key={ch.id} className="flex items-center gap-2 bg-white rounded p-2 border">
            <span className="text-xs text-gray-700 w-20 truncate">{ch.name}</span>
            <select
              className="flex-1 border rounded px-2 py-1 text-xs"
              value={map[ch.name] || ''}
              onChange={(e) => setMap({ ...map, [ch.name]: e.target.value })}
            >
              <option value="">— 不映射（走 LLM 生成） —</option>
              {digitalHumans.filter((d) => d.status !== 'archived').map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                  {d.status ? ` (${d.status})` : ''}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>
      {error && <div className="text-xs text-rose-600 mt-2">{error}</div>}
      <div className="text-[11px] text-gray-500 mt-1">
        映射后，该角色的脸图直接复用 Avatar 的 face_urls[0]，不再走 LLM 生成。
      </div>
    </div>
  )
}
