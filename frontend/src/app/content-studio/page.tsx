'use client'

import React, { useCallback, useEffect, useState } from 'react'
import {
  ArrowLeft, Check, Download, Film, Image as ImageIcon,
  Loader2, Pen, Plus, RefreshCw, Sparkles, Video, Wand2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  useContentStudioStore,
  type Pipeline,
  type Scene,
  type StoryboardItem,
  type VideoItem,
} from '@/stores/contentStudioStore'

const STEPS = [
  { key: 'copy', label: '文案生成', icon: Pen },
  { key: 'script', label: '脚本生成', icon: Wand2 },
  { key: 'storyboard', label: '分镜图', icon: ImageIcon },
  { key: 'video', label: '视频片段', icon: Video },
  { key: 'compose', label: '合成下载', icon: Film },
] as const

const STEP_ORDER = STEPS.map(s => s.key)

const STATUS_LABELS: Record<string, string> = {
  pending: '待开始', running: '生成中', paused: '待确认', completed: '已完成', failed: '失败',
}

export default function ContentStudioPage() {
  const {
    pipelines, currentPipeline, presets, loading, stepLoading, error,
    fetchPipelines, fetchPipeline, createPipeline,
    generateCopy, generateScript, generateStoryboard, regenerateStoryboardScene,
    generateVideos, composeFinal, fetchPresets,
  } = useContentStudioStore()

  const [view, setView] = useState<'list' | 'editor'>('list')
  const [newTitle, setNewTitle] = useState('')
  const [newSource, setNewSource] = useState('')
  const [selectedPreset, setSelectedPreset] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [editCopy, setEditCopy] = useState('')
  const [editingCopy, setEditingCopy] = useState(false)

  useEffect(() => { fetchPipelines(); fetchPresets() }, [fetchPipelines, fetchPresets])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const text = params.get('source_text')
    if (text) {
      setNewSource(decodeURIComponent(text))
      setShowCreate(true)
    }
  }, [])

  const pipe = currentPipeline
  const currentStepIdx = pipe ? STEP_ORDER.indexOf(pipe.current_step as typeof STEP_ORDER[number]) : -1

  const handleCreate = useCallback(async () => {
    if (!newTitle.trim() || !newSource.trim()) return
    const presetConfig = presets.find(p => p.id === selectedPreset)?.config || {}
    const p = await createPipeline(newTitle, newSource, presetConfig)
    if (p) {
      setView('editor')
      setShowCreate(false)
      setNewTitle('')
      setNewSource('')
    }
  }, [newTitle, newSource, selectedPreset, presets, createPipeline])

  const openPipeline = useCallback(async (id: string) => {
    await fetchPipeline(id)
    setView('editor')
  }, [fetchPipeline])

  const handleStepAction = useCallback(async () => {
    if (!pipe) return
    const step = pipe.current_step
    if (step === 'copy') await generateCopy(pipe.id)
    else if (step === 'script') await generateScript(pipe.id)
    else if (step === 'storyboard') await generateStoryboard(pipe.id)
    else if (step === 'video') await generateVideos(pipe.id)
    else if (step === 'compose') await composeFinal(pipe.id)
  }, [pipe, generateCopy, generateScript, generateStoryboard, generateVideos, composeFinal])

  const handleConfirmCopy = useCallback(async () => {
    if (!pipe) return
    const { updatePipeline } = useContentStudioStore.getState()
    await updatePipeline(pipe.id, { copy_result: editCopy || pipe.copy_result } as Partial<Pipeline>)
    setEditingCopy(false)
    await generateScript(pipe.id)
  }, [pipe, editCopy, generateScript])

  // ──── List View ────
  if (view === 'list') {
    return (
      <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white p-6">
        <div className="mx-auto max-w-6xl">
          <div className="mb-8 flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">内容工坊</h1>
              <p className="mt-1 text-sm text-gray-500">从运营方案一键生成短视频内容</p>
            </div>
            <Button onClick={() => setShowCreate(true)} className="gap-2">
              <Plus className="h-4 w-4" /> 新建任务
            </Button>
          </div>

          {/* Create Dialog */}
          {showCreate && (
            <Card className="mb-6 border-blue-200 bg-blue-50/30">
              <CardContent className="p-6">
                <h3 className="mb-4 text-lg font-semibold">新建内容任务</h3>
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
            <div className="rounded-lg border border-dashed py-20 text-center text-gray-400">
              还没有任何内容任务，点击「新建任务」开始
            </div>
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

  // ──── Editor View ────
  if (!pipe) return null

  const scenes: Scene[] = (typeof pipe.script_result === 'object' && pipe.script_result)
    ? (pipe.script_result as ScriptResult).scenes || []
    : []
  const storyboard: StoryboardItem[] = Array.isArray(pipe.storyboard_results) ? pipe.storyboard_results : []
  const videos: VideoItem[] = Array.isArray(pipe.video_results) ? pipe.video_results : []

  type ScriptResult = { title: string; duration_seconds: number; scenes: Scene[] }

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white">
      {/* Header */}
      <div className="border-b bg-white px-6 py-3">
        <div className="mx-auto flex max-w-6xl items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => { setView('list'); fetchPipelines() }}>
            <ArrowLeft className="mr-1 h-4 w-4" /> 返回
          </Button>
          <h2 className="text-lg font-semibold text-gray-900">{pipe.title}</h2>
          <Badge variant="outline">{STATUS_LABELS[pipe.status] || pipe.status}</Badge>
          {error && <span className="ml-auto text-sm text-red-500">{error}</span>}
        </div>
      </div>

      {/* Stepper */}
      <div className="border-b bg-white px-6 py-4">
        <div className="mx-auto flex max-w-4xl items-center justify-between">
          {STEPS.map((s, i) => {
            const Icon = s.icon
            const done = i < currentStepIdx || pipe.status === 'completed'
            const active = i === currentStepIdx
            return (
              <React.Fragment key={s.key}>
                {i > 0 && <div className={`mx-2 h-0.5 flex-1 ${done ? 'bg-green-400' : 'bg-gray-200'}`} />}
                <div className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium
                  ${done ? 'bg-green-50 text-green-700' : active ? 'bg-blue-50 text-blue-700' : 'text-gray-400'}`}>
                  {done ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
                  {s.label}
                </div>
              </React.Fragment>
            )
          })}
        </div>
      </div>

      {/* Content area */}
      <div className="mx-auto max-w-6xl p-6">
        {/* Step 1: Copy */}
        {pipe.current_step === 'copy' && !pipe.copy_result && (
          <Card>
            <CardContent className="p-6 text-center">
              <Sparkles className="mx-auto mb-4 h-10 w-10 text-blue-400" />
              <h3 className="mb-2 text-lg font-semibold">生成营销文案</h3>
              <p className="mb-4 text-sm text-gray-500">AI 将根据您的运营方案生成营销文案</p>
              <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                {stepLoading === 'copy' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                开始生成文案
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Copy result */}
        {pipe.copy_result && (
          <Card className="mb-6">
            <CardContent className="p-6">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="font-semibold text-gray-900">营销文案</h3>
                <div className="flex gap-2">
                  {!editingCopy && pipe.current_step === 'script' && (
                    <Button variant="ghost" size="sm" onClick={() => { setEditCopy(pipe.copy_result || ''); setEditingCopy(true) }}>
                      <Pen className="mr-1 h-3 w-3" /> 编辑
                    </Button>
                  )}
                </div>
              </div>
              {editingCopy ? (
                <div>
                  <Textarea value={editCopy} onChange={e => setEditCopy(e.target.value)} rows={8} className="mb-3" />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={handleConfirmCopy}>确认并生成脚本</Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditingCopy(false)}>取消</Button>
                  </div>
                </div>
              ) : (
                <div className="whitespace-pre-wrap text-sm text-gray-700 leading-relaxed">{pipe.copy_result}</div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Step 2: Script generation trigger */}
        {pipe.current_step === 'script' && !pipe.script_result && !editingCopy && (
          <Card className="mb-6">
            <CardContent className="p-6 text-center">
              <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                {stepLoading === 'script' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                生成分镜脚本
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Script result */}
        {pipe.script_result && scenes.length > 0 && (
          <Card className="mb-6">
            <CardContent className="p-6">
              <h3 className="mb-4 font-semibold text-gray-900">
                分镜脚本 — {(pipe.script_result as ScriptResult).title} ({scenes.length} 个场景)
              </h3>
              <div className="space-y-3">
                {scenes.map(scene => (
                  <div key={scene.scene_id} className="flex gap-4 rounded-lg border p-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-50 text-sm font-bold text-blue-600">
                      {scene.scene_id}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex items-center gap-2 text-xs text-gray-400">
                        <span>{scene.duration}</span>
                        <span>·</span>
                        <span>{scene.camera_movement}</span>
                        {scene.transition && <><span>·</span><span>→ {scene.transition}</span></>}
                      </div>
                      <p className="text-sm text-gray-600">{scene.visual_description_zh || scene.visual_description}</p>
                      {scene.narration && (
                        <p className="mt-1 text-sm italic text-gray-500">🎙️ {scene.narration}</p>
                      )}
                      {scene.text_overlay && (
                        <p className="mt-1 text-xs text-blue-500">📝 {scene.text_overlay}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 3: Storyboard trigger */}
        {pipe.current_step === 'storyboard' && storyboard.length === 0 && scenes.length > 0 && (
          <Card className="mb-6">
            <CardContent className="p-6 text-center">
              <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                {stepLoading === 'storyboard' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImageIcon className="h-4 w-4" />}
                生成分镜图 ({scenes.length} 张)
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Storyboard grid */}
        {storyboard.length > 0 && (
          <Card className="mb-6">
            <CardContent className="p-6">
              <h3 className="mb-4 font-semibold text-gray-900">分镜看板</h3>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {storyboard.map(sb => {
                  const scene = scenes.find(s => s.scene_id === sb.scene_id)
                  const vid = videos.find(v => v.scene_id === sb.scene_id)
                  return (
                    <div key={sb.scene_id} className="overflow-hidden rounded-lg border">
                      <div className="aspect-video bg-gray-100">
                        {sb.image_url ? (
                          <img src={sb.image_url} alt={`Scene ${sb.scene_id}`}
                            className="h-full w-full object-cover" />
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
                        <div className="flex gap-1">
                          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs"
                            disabled={stepLoading === `storyboard-${sb.scene_id}`}
                            onClick={() => regenerateStoryboardScene(pipe.id, sb.scene_id)}>
                            {stepLoading === `storyboard-${sb.scene_id}`
                              ? <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                              : <RefreshCw className="mr-1 h-3 w-3" />}
                            重生成
                          </Button>
                          {sb.image_url && (
                            <a href={sb.image_url} download className="inline-flex h-7 items-center rounded px-2 text-xs text-gray-500 hover:bg-gray-100">
                              <Download className="mr-1 h-3 w-3" /> 下载
                            </a>
                          )}
                        </div>
                        {vid && vid.video_url && (
                          <video src={vid.video_url} controls className="mt-2 w-full rounded" />
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Step 4: Video trigger */}
        {pipe.current_step === 'video' && videos.length === 0 && storyboard.length > 0 && (
          <Card className="mb-6">
            <CardContent className="p-6 text-center">
              <Button onClick={handleStepAction} disabled={!!stepLoading} className="gap-2">
                {stepLoading === 'video' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
                生成视频片段 ({storyboard.length} 段)
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Step 5: Compose trigger */}
        {(pipe.current_step === 'compose' || (pipe.current_step === 'video' && videos.length > 0)) && !pipe.final_video_url && (
          <Card className="mb-6">
            <CardContent className="p-6 text-center">
              <Button onClick={() => composeFinal(pipe.id)} disabled={!!stepLoading} className="gap-2">
                {stepLoading === 'compose' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Film className="h-4 w-4" />}
                合成最终视频
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Final video + download */}
        {(pipe.final_video_url || pipe.status === 'completed') && (
          <Card className="mb-6">
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
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}
