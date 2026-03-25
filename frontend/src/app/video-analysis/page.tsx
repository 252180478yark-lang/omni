'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const VIDEO_API_BASE = '/api/v1/video-analysis'

interface ProviderItem {
  id: string
  name: string
  models: string[]
  apiKeySet?: boolean
  defaultChatModel?: string | null
}

interface KnowledgeBaseItem {
  id: string
  name: string
}

interface VideoItem {
  id: string
  original_name: string
  status: string
  created_at: string
}

interface ScoreDim {
  score: number
  weight: number
  brief: string
}

interface Scores {
  overall: number
  dimensions: Record<string, ScoreDim>
  replicability?: { score: number; difficulty: string; key_barriers: string[] }
}

interface PriorityAction {
  category: string
  urgency: string
  current_issue: string
  suggestion: string
  expected_impact: string
}

interface ImprovementSuggestions {
  priority_actions: PriorityAction[]
  copy_rewrite?: {
    original_title: string
    suggested_titles: string[]
    title_optimization_notes: string
  }
  editing_suggestions?: { timestamp_sec: number; suggestion: string }[]
  algorithm_optimization?: string[]
  a_b_test_suggestions?: { variable: string; version_a: string; version_b: string }[]
}

interface VideoDetailResp {
  video: VideoItem & {
    retry_count?: number
    next_run_at?: string | null
    last_error?: string | null
    pipeline?: { current_stage?: string }
  }
  report?: Record<string, unknown>
  report_markdown_url?: string
  report_json_url?: string
  bundle_url?: string
  original_video_url?: string
}

function joinUrl(path?: string): string {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  if (path.startsWith('/')) return path
  return `${VIDEO_API_BASE}/${path}`
}

const DIM_LABELS: Record<string, string> = {
  hook_power: '钩子力',
  content_value: '内容价值',
  visual_quality: '画面质量',
  editing_rhythm: '剪辑节奏',
  audio_bgm: '音频/BGM',
  copy_script: '文案脚本',
  interaction_design: '互动设计',
  algorithm_friendliness: '算法友好',
  commercial_potential: '商业潜力',
}

function scoreColor(s: number): string {
  if (s >= 8) return '#22c55e'
  if (s >= 5) return '#f59e0b'
  return '#ef4444'
}

function RadarChart({ dimensions }: { dimensions: Record<string, ScoreDim> }) {
  const keys = Object.keys(DIM_LABELS).filter((k) => dimensions[k])
  const n = keys.length
  if (n < 3) return null
  const cx = 150, cy = 150, r = 110
  const angleStep = (2 * Math.PI) / n

  const pointAt = (i: number, val: number) => {
    const angle = -Math.PI / 2 + i * angleStep
    const dist = (val / 10) * r
    return { x: cx + dist * Math.cos(angle), y: cy + dist * Math.sin(angle) }
  }

  const gridLevels = [2, 4, 6, 8, 10]
  const dataPoints = keys.map((k, i) => pointAt(i, dimensions[k].score))
  const polygon = dataPoints.map((p) => `${p.x},${p.y}`).join(' ')

  return (
    <svg viewBox="0 0 300 300" className="w-full max-w-[320px] mx-auto">
      {gridLevels.map((lv) => (
        <polygon
          key={lv}
          points={keys.map((_, i) => { const p = pointAt(i, lv); return `${p.x},${p.y}` }).join(' ')}
          fill="none" stroke="#e5e7eb" strokeWidth={lv === 10 ? 1.5 : 0.5}
        />
      ))}
      {keys.map((_, i) => {
        const p = pointAt(i, 10)
        return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="#e5e7eb" strokeWidth={0.5} />
      })}
      <polygon points={polygon} fill="rgba(59,130,246,0.15)" stroke="#3b82f6" strokeWidth={2} />
      {keys.map((k, i) => {
        const p = pointAt(i, dimensions[k].score)
        return <circle key={k} cx={p.x} cy={p.y} r={4} fill={scoreColor(dimensions[k].score)} />
      })}
      {keys.map((k, i) => {
        const lp = pointAt(i, 11.8)
        const label = DIM_LABELS[k] || k
        return (
          <text key={k} x={lp.x} y={lp.y} textAnchor="middle" dominantBaseline="middle"
            className="text-[10px] fill-gray-600">{label}</text>
        )
      })}
    </svg>
  )
}

function ScoreBar({ label, score, brief }: { label: string; score: number; brief: string }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-gray-600">{label}</span>
        <span className="font-semibold" style={{ color: scoreColor(score) }}>{score}/10</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${score * 10}%`, backgroundColor: scoreColor(score) }} />
      </div>
      {brief ? <p className="text-xs text-gray-400">{brief}</p> : null}
    </div>
  )
}

export default function VideoAnalysisPage() {
  const [providers, setProviders] = useState<ProviderItem[]>([])
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseItem[]>([])
  const [selectedProvider, setSelectedProvider] = useState('gemini')
  const [selectedModel, setSelectedModel] = useState('')
  const [videos, setVideos] = useState<VideoItem[]>([])
  const [selectedVideoId, setSelectedVideoId] = useState('')
  const [videoDetail, setVideoDetail] = useState<VideoDetailResp | null>(null)
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([])
  const [includeOriginal, setIncludeOriginal] = useState(true)
  const [includeBundle, setIncludeBundle] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [message, setMessage] = useState('')
  const [metricsText, setMetricsText] = useState('')
  const [activeTab, setActiveTab] = useState<'scores' | 'suggestions' | 'douyin' | 'detail'>('scores')

  const currentProvider = useMemo(
    () => providers.find((p) => p.id === selectedProvider),
    [providers, selectedProvider],
  )
  const availableProviders = useMemo(() => {
    const geminiOnly = providers.filter((p) => p.id === 'gemini')
    return geminiOnly.length > 0 ? geminiOnly : providers
  }, [providers])

  const report = videoDetail?.report as Record<string, unknown> | undefined
  const scores = report?.scores as Scores | undefined
  const improvement = report?.improvement_suggestions as ImprovementSuggestions | undefined
  const douyinSpecific = report?.douyin_specific as Record<string, unknown> | undefined

  const refreshVideos = useCallback(async () => {
    const res = await fetch(`${VIDEO_API_BASE}/videos`, { cache: 'no-store' })
    if (!res.ok) throw new Error('短视频服务不可用，请先启动短视频分析后端')
    const data = (await res.json()) as VideoItem[]
    setVideos(data)
    if (data.length === 0) {
      setSelectedVideoId('')
      setVideoDetail(null)
      return
    }
    if (!selectedVideoId || !data.some((x) => x.id === selectedVideoId)) {
      setSelectedVideoId(data[0].id)
    }
  }, [selectedVideoId])

  const loadVideoDetail = async (videoId: string) => {
    const res = await fetch(`${VIDEO_API_BASE}/videos/${videoId}`, { cache: 'no-store' })
    if (!res.ok) throw new Error('读取分析详情失败')
    const data = (await res.json()) as VideoDetailResp
    setVideoDetail(data)
  }

  useEffect(() => {
    const run = async () => {
      const [providerRes, kbRes] = await Promise.all([
        fetch('/api/omni/models', { cache: 'no-store' }),
        fetch('/api/omni/knowledge/bases', { cache: 'no-store' }),
      ])
      const pJson = (await providerRes.json()) as { success: boolean; data?: { providers: ProviderItem[] } }
      const kbJson = (await kbRes.json()) as { success: boolean; data?: KnowledgeBaseItem[] }
      if (pJson.success && pJson.data) {
        setProviders(pJson.data.providers)
        const gemini = pJson.data.providers.find((x) => x.id === 'gemini') || pJson.data.providers[0]
        if (gemini) {
          setSelectedProvider(gemini.id)
          setSelectedModel(gemini.defaultChatModel || gemini.models[0] || '')
        }
      }
      if (kbJson.success && kbJson.data) {
        setKnowledgeBases(kbJson.data)
      }
      await refreshVideos()
    }
    void run().catch((err) => setMessage(String(err)))
  }, [refreshVideos])

  useEffect(() => {
    if (!selectedVideoId) return
    void loadVideoDetail(selectedVideoId).catch((err) => setMessage(String(err)))
  }, [selectedVideoId])

  useEffect(() => {
    const status = videoDetail?.video?.status
    if (!selectedVideoId || !status || !['queued', 'running', 'retrying', 'processing'].includes(status)) return
    const timer = window.setInterval(() => {
      void Promise.all([refreshVideos(), loadVideoDetail(selectedVideoId)]).catch((err) => setMessage(String(err)))
    }, 3000)
    return () => window.clearInterval(timer)
  }, [videoDetail?.video?.status, selectedVideoId, refreshVideos])

  const syncProviderKey = async () => {
    setSyncing(true)
    setMessage('')
    try {
      const res = await fetch('/api/omni/video-analysis/sync-provider', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: selectedProvider, model: selectedModel }),
      })
      const json = (await res.json()) as { success: boolean; error?: string }
      if (!json.success) throw new Error(json.error || '同步失败')
      setMessage('已同步系统 API Key 到短视频分析服务')
    } catch (err) {
      setMessage(String(err))
    } finally {
      setSyncing(false)
    }
  }

  const uploadVideo = async (file?: File) => {
    if (!file) return
    setUploading(true)
    setMessage('')
    try {
      const form = new FormData()
      form.append('file', file)
      if (metricsText.trim()) {
        JSON.parse(metricsText)
        form.append('metrics', metricsText.trim())
      }
      const res = await fetch(`${VIDEO_API_BASE}/videos`, { method: 'POST', body: form })
      if (!res.ok) throw new Error(await res.text())
      await refreshVideos()
      setMessage('上传成功，分析任务已进入队列')
    } catch (err) {
      setMessage(String(err))
    } finally {
      setUploading(false)
    }
  }

  const saveToKnowledge = async () => {
    if (!videoDetail?.report || selectedKbIds.length === 0) {
      setMessage('请先勾选至少一个知识库，并确保分析结果已生成')
      return
    }
    setSaving(true)
    setMessage('')
    try {
      const summary = String(videoDetail.report.summary || '')
      const reportText = JSON.stringify(videoDetail.report, null, 2)
      const sourceParts: string[] = []
      if (includeOriginal && videoDetail.original_video_url) sourceParts.push(`原视频: ${joinUrl(videoDetail.original_video_url)}`)
      if (includeBundle && videoDetail.bundle_url) sourceParts.push(`打包文件: ${joinUrl(videoDetail.bundle_url)}`)
      const sourceUrl = sourceParts.join(' | ')

      for (const kbId of selectedKbIds) {
        const resp = await fetch('/api/omni/knowledge/ingest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            kb_id: kbId,
            title: `短视频分析-${videoDetail.video.original_name}`,
            text: `# 分析摘要\n${summary}\n\n# 结构化结果\n${reportText}\n\n# 资产\n${sourceParts.join('\n')}`,
            source_url: sourceUrl || undefined,
          }),
        })
        const json = (await resp.json()) as { success: boolean; error?: string }
        if (!json.success) throw new Error(json.error || `入库失败: ${kbId}`)
      }
      setMessage(`已保存到 ${selectedKbIds.length} 个知识库，后续可在任务页查看入库进度`)
    } catch (err) {
      setMessage(String(err))
    } finally {
      setSaving(false)
    }
  }

  const openOriginalVideo = () => {
    const url = videoDetail?.original_video_url ? joinUrl(videoDetail.original_video_url) : ''
    if (!url) { setMessage('当前视频暂无原视频链接'); return }
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  const deleteSelectedVideo = async () => {
    if (!selectedVideoId) { setMessage('请先选择要删除的视频'); return }
    if (!window.confirm('确认删除该视频及其分析产物吗？此操作不可撤销。')) return
    setDeleting(true)
    setMessage('')
    try {
      const res = await fetch(`${VIDEO_API_BASE}/videos/${selectedVideoId}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await res.text())
      setVideoDetail(null)
      await refreshVideos()
      setMessage('视频已删除')
    } catch (err) {
      setMessage(String(err))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link href="/" className="text-gray-500 hover:text-gray-900">← 返回控制台</Link>
          <div className="font-semibold text-gray-900">短视频分析（抖音特化）</div>
          <Badge variant="outline">{selectedProvider}</Badge>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 space-y-6">
        {/* Config row */}
        <Card className="apple-card border-none shadow-sm">
          <CardHeader>
            <CardTitle>分析来源配置</CardTitle>
            <CardDescription>模型来源走系统已保存 API Key（当前短视频多模态分析接入 Gemini）；向量库可多选保存。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid md:grid-cols-4 gap-3">
              <select value={selectedProvider} onChange={(e) => setSelectedProvider(e.target.value)} className="h-10 rounded-md border px-3">
                {availableProviders.map((p) => <option key={p.id} value={p.id}>{p.name} {p.apiKeySet ? '' : '(未配置Key)'}</option>)}
              </select>
              <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="h-10 rounded-md border px-3">
                {(currentProvider?.models || []).map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              <Button onClick={() => void syncProviderKey()} disabled={syncing}>{syncing ? '同步中...' : '同步系统 Key 到分析服务'}</Button>
              <input type="file" accept="video/*" onChange={(e) => void uploadVideo(e.target.files?.[0])} disabled={uploading} className="h-10 text-sm" />
            </div>
            <details className="text-sm">
              <summary className="cursor-pointer text-gray-500 hover:text-gray-700">附加抖音数据（可选，用于归因分析）</summary>
              <textarea
                value={metricsText}
                onChange={(e) => setMetricsText(e.target.value)}
                placeholder={'{\n  "play_count": 50000,\n  "like_count": 2300,\n  "comment_count": 156,\n  "share_count": 89,\n  "collect_count": 340,\n  "completion_rate": 0.45,\n  "avg_watch_duration_sec": 12.5\n}'}
                className="w-full mt-2 h-32 rounded-md border px-3 py-2 font-mono text-xs"
              />
            </details>
          </CardContent>
        </Card>

        {/* KB checkboxes */}
        <Card className="apple-card border-none shadow-sm">
          <CardHeader><CardTitle>向量库勾选</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-4">
            {knowledgeBases.map((kb) => (
              <label key={kb.id} className="text-sm flex items-center gap-2">
                <input type="checkbox" checked={selectedKbIds.includes(kb.id)} onChange={(e) => {
                  setSelectedKbIds((prev) => (e.target.checked ? [...prev, kb.id] : prev.filter((x) => x !== kb.id)))
                }} />
                {kb.name}
              </label>
            ))}
            <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={includeOriginal} onChange={(e) => setIncludeOriginal(e.target.checked)} /> 附带原视频链接</label>
            <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={includeBundle} onChange={(e) => setIncludeBundle(e.target.checked)} /> 附带打包文件链接</label>
            <Button onClick={() => void saveToKnowledge()} disabled={saving}>{saving ? '保存中...' : '保存分析结果到知识库'}</Button>
          </CardContent>
        </Card>

        {/* Video selector + actions */}
        <Card className="apple-card border-none shadow-sm">
          <CardHeader><CardTitle>分析结果</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <select value={selectedVideoId} onChange={(e) => setSelectedVideoId(e.target.value)} className="h-10 rounded-md border px-3 w-full md:w-[420px]">
                <option value="">请选择视频</option>
                {videos.map((v) => <option key={v.id} value={v.id}>{v.original_name} ({v.status})</option>)}
              </select>
              <Button variant="outline" onClick={openOriginalVideo} disabled={!videoDetail?.original_video_url}>打开原视频</Button>
              <Button variant="destructive" onClick={() => void deleteSelectedVideo()} disabled={deleting || !selectedVideoId}>
                {deleting ? '删除中...' : '删除视频'}
              </Button>
            </div>
            <div className="text-sm text-gray-600">{report?.summary ? String(report.summary) : '暂无摘要'}</div>
            {videoDetail?.video?.status && !['done'].includes(videoDetail.video.status) ? (
              <div className="text-xs text-gray-500">
                状态：{videoDetail.video.status}
                {videoDetail.video.pipeline?.current_stage ? `，阶段：${videoDetail.video.pipeline.current_stage}` : ''}
                {typeof videoDetail.video.retry_count === 'number' ? `，重试次数：${videoDetail.video.retry_count}` : ''}
                {videoDetail.video.last_error ? `，最近错误：${videoDetail.video.last_error}` : ''}
              </div>
            ) : null}
            <div className="flex flex-wrap gap-3 text-sm">
              {videoDetail?.original_video_url ? <a className="text-blue-600 hover:underline" href={joinUrl(videoDetail.original_video_url)} target="_blank">下载原视频</a> : null}
              {videoDetail?.bundle_url ? <a className="text-blue-600 hover:underline" href={joinUrl(videoDetail.bundle_url)} target="_blank">下载打包文件</a> : null}
              {videoDetail?.report_markdown_url ? <a className="text-blue-600 hover:underline" href={joinUrl(videoDetail.report_markdown_url)} target="_blank">下载Markdown</a> : null}
              {videoDetail?.report_json_url ? <a className="text-blue-600 hover:underline" href={joinUrl(videoDetail.report_json_url)} target="_blank">下载JSON</a> : null}
            </div>
          </CardContent>
        </Card>

        {/* Tabbed analysis display */}
        {report ? (
          <>
            <div className="flex gap-2 border-b border-gray-200">
              {(['scores', 'suggestions', 'douyin', 'detail'] as const).map((tab) => {
                const labels = { scores: '多维评分', suggestions: '改进建议', douyin: '抖音分析', detail: '详细报告' }
                return (
                  <button key={tab} onClick={() => setActiveTab(tab)}
                    className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === tab ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
                    {labels[tab]}
                  </button>
                )
              })}
            </div>

            {/* Scores tab */}
            {activeTab === 'scores' && scores ? (
              <div className="grid md:grid-cols-2 gap-6">
                <Card className="apple-card border-none shadow-sm">
                  <CardHeader>
                    <CardTitle className="flex items-baseline gap-3">
                      综合评分
                      <span className="text-3xl font-bold" style={{ color: scoreColor(scores.overall) }}>{scores.overall}</span>
                      <span className="text-lg text-gray-400">/10</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <RadarChart dimensions={scores.dimensions} />
                    {scores.replicability ? (
                      <div className="mt-4 p-3 bg-gray-50 rounded-lg text-sm">
                        <span className="font-medium">复刻可行性：</span>{scores.replicability.score}
                        <span className="mx-2">|</span>难度：{scores.replicability.difficulty}
                        {scores.replicability.key_barriers?.length ? (
                          <span className="mx-2">| 壁垒：{scores.replicability.key_barriers.join('、')}</span>
                        ) : null}
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
                <Card className="apple-card border-none shadow-sm">
                  <CardHeader><CardTitle>分项评分</CardTitle></CardHeader>
                  <CardContent className="space-y-4">
                    {Object.entries(DIM_LABELS).map(([key, label]) => {
                      const d = scores.dimensions[key]
                      return d ? <ScoreBar key={key} label={label} score={d.score} brief={d.brief} /> : null
                    })}
                  </CardContent>
                </Card>
              </div>
            ) : null}

            {/* Suggestions tab */}
            {activeTab === 'suggestions' && improvement ? (
              <div className="space-y-4">
                {improvement.priority_actions?.length ? (
                  <Card className="apple-card border-none shadow-sm">
                    <CardHeader><CardTitle>优先改进项</CardTitle></CardHeader>
                    <CardContent className="space-y-4">
                      {improvement.priority_actions.map((act, i) => (
                        <div key={i} className="p-4 rounded-lg bg-gray-50 space-y-2">
                          <div className="flex items-center gap-2">
                            <Badge variant={act.urgency === 'high' ? 'destructive' : act.urgency === 'medium' ? 'default' : 'secondary'}>
                              {act.urgency === 'high' ? '紧急' : act.urgency === 'medium' ? '中等' : '低'}
                            </Badge>
                            <span className="text-xs text-gray-400">{act.category}</span>
                          </div>
                          <p className="text-sm"><span className="font-medium text-red-600">问题：</span>{act.current_issue}</p>
                          <p className="text-sm"><span className="font-medium text-green-600">建议：</span>{act.suggestion}</p>
                          <p className="text-sm"><span className="font-medium text-blue-600">预期效果：</span>{act.expected_impact}</p>
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                ) : null}

                {improvement.copy_rewrite?.suggested_titles?.length ? (
                  <Card className="apple-card border-none shadow-sm">
                    <CardHeader><CardTitle>标题优化建议</CardTitle></CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      <p><span className="font-medium">原标题：</span>{improvement.copy_rewrite.original_title}</p>
                      {improvement.copy_rewrite.suggested_titles.map((t, i) => (
                        <p key={i} className="pl-4 border-l-2 border-blue-300">方案 {i + 1}：{t}</p>
                      ))}
                      <p className="text-gray-500">{improvement.copy_rewrite.title_optimization_notes}</p>
                    </CardContent>
                  </Card>
                ) : null}

                <div className="grid md:grid-cols-2 gap-4">
                  {improvement.algorithm_optimization?.length ? (
                    <Card className="apple-card border-none shadow-sm">
                      <CardHeader><CardTitle>算法优化建议</CardTitle></CardHeader>
                      <CardContent>
                        <ul className="space-y-1 text-sm list-disc pl-4">
                          {improvement.algorithm_optimization.map((tip, i) => <li key={i}>{tip}</li>)}
                        </ul>
                      </CardContent>
                    </Card>
                  ) : null}

                  {improvement.editing_suggestions?.length ? (
                    <Card className="apple-card border-none shadow-sm">
                      <CardHeader><CardTitle>剪辑改进建议</CardTitle></CardHeader>
                      <CardContent>
                        <ul className="space-y-1 text-sm">
                          {improvement.editing_suggestions.map((es, i) => (
                            <li key={i}><span className="font-mono font-medium text-blue-600">{es.timestamp_sec}s</span> — {es.suggestion}</li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  ) : null}
                </div>

                {improvement.a_b_test_suggestions?.length ? (
                  <Card className="apple-card border-none shadow-sm">
                    <CardHeader><CardTitle>A/B 测试方案</CardTitle></CardHeader>
                    <CardContent className="space-y-3">
                      {improvement.a_b_test_suggestions.map((t, i) => (
                        <div key={i} className="grid grid-cols-3 gap-2 text-sm p-3 bg-gray-50 rounded-lg">
                          <div className="font-medium">{t.variable}</div>
                          <div><span className="text-gray-400">A：</span>{t.version_a}</div>
                          <div><span className="text-gray-400">B：</span>{t.version_b}</div>
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                ) : null}
              </div>
            ) : null}

            {/* Douyin tab */}
            {activeTab === 'douyin' && douyinSpecific ? (
              <div className="grid md:grid-cols-2 gap-4">
                <Card className="apple-card border-none shadow-sm">
                  <CardHeader><CardTitle>内容识别</CardTitle></CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    <p><span className="font-medium">内容类型：</span>{String(douyinSpecific.content_type || '')}</p>
                    <p><span className="font-medium">视频格式：</span>{String(douyinSpecific.video_format || '')}</p>
                    {(() => {
                      const ds = douyinSpecific.duration_strategy as Record<string, string> | undefined
                      if (!ds) return null
                      return (<>
                        <p><span className="font-medium">时长评估：</span>{ds.actual_duration_assessment}</p>
                        <p><span className="font-medium">建议时长：</span>{ds.optimal_duration_suggestion}</p>
                      </>)
                    })()}
                  </CardContent>
                </Card>

                <Card className="apple-card border-none shadow-sm">
                  <CardHeader><CardTitle>流量池预测</CardTitle></CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    {(() => {
                      const tp = douyinSpecific.traffic_pool_prediction as Record<string, unknown> | undefined
                      if (!tp) return <p className="text-gray-400">暂无数据</p>
                      const bf = (tp.breakthrough_factors || []) as string[]
                      const rf = (tp.risk_factors || []) as string[]
                      return (<>
                        <p className="text-lg font-semibold">{String(tp.estimated_level || '')}</p>
                        {bf.length ? <div><span className="font-medium text-green-600">有利因素：</span>{bf.join('、')}</div> : null}
                        {rf.length ? <div><span className="font-medium text-red-600">风险因素：</span>{rf.join('、')}</div> : null}
                      </>)
                    })()}
                  </CardContent>
                </Card>

                <Card className="apple-card border-none shadow-sm">
                  <CardHeader><CardTitle>话题策略</CardTitle></CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    {(() => {
                      const hs = douyinSpecific.hashtag_strategy as Record<string, unknown> | undefined
                      if (!hs) return <p className="text-gray-400">暂无数据</p>
                      const detected = (hs.detected_topics || []) as string[]
                      const recommended = (hs.recommended_topics || []) as string[]
                      return (<>
                        {detected.length ? <p><span className="font-medium">检测话题：</span>{detected.join(' ')}</p> : null}
                        {recommended.length ? <p><span className="font-medium text-blue-600">推荐话题：</span>{recommended.join(' ')}</p> : null}
                        <p><span className="font-medium">热度评估：</span>{String(hs.topic_heat_assessment || '')}</p>
                      </>)
                    })()}
                  </CardContent>
                </Card>

                <Card className="apple-card border-none shadow-sm">
                  <CardHeader><CardTitle>抖音原生元素</CardTitle></CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    {(() => {
                      const dne = douyinSpecific.douyin_native_elements as Record<string, string> | undefined
                      if (!dne) return <p className="text-gray-400">暂无数据</p>
                      return (<>
                        <p><span className="font-medium">贴纸/特效：</span>{dne.sticker_effects}</p>
                        <p><span className="font-medium">合拍潜力：</span>{dne.duet_potential}</p>
                        <p><span className="font-medium">挑战赛关联：</span>{dne.challenge_relevance}</p>
                        <p><span className="font-medium">定位/POI：</span>{dne.poi_usage}</p>
                        <p><span className="font-medium">小黄车：</span>{dne.shopping_cart}</p>
                      </>)
                    })()}
                  </CardContent>
                </Card>
              </div>
            ) : null}

            {/* Detail tab - original 7 modules */}
            {activeTab === 'detail' ? (
              <div className="space-y-4">
                {[
                  { key: 'visual', title: '画面视觉' },
                  { key: 'bgm_audio', title: 'BGM 与音效' },
                  { key: 'editing_rhythm', title: '剪辑节奏' },
                  { key: 'copy_logic', title: '文案与逻辑' },
                  { key: 'interaction_algo', title: '互动与算法' },
                  { key: 'business_strategy', title: '商业与战略' },
                  { key: 'ai_insights', title: 'AI 深度洞察' },
                ].map(({ key, title }) => {
                  const section = report?.[key]
                  if (!section || typeof section !== 'object') return null
                  return (
                    <Card key={key} className="apple-card border-none shadow-sm">
                      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
                      <CardContent>
                        <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2 text-sm">
                          {Object.entries(section as Record<string, unknown>).map(([k, v]) => {
                            if (k === 'emotion_curve') return null
                            const display = typeof v === 'object' && v !== null ? JSON.stringify(v, null, 2) : String(v ?? '')
                            return (
                              <div key={k}>
                                <dt className="font-medium text-gray-500">{k}</dt>
                                <dd className="text-gray-900 whitespace-pre-wrap break-words">{display}</dd>
                              </div>
                            )
                          })}
                        </dl>
                      </CardContent>
                    </Card>
                  )
                })}
              </div>
            ) : null}
          </>
        ) : null}

        {message ? <div className="text-sm rounded-md border bg-white px-4 py-3">{message}</div> : null}
      </main>
    </div>
  )
}
