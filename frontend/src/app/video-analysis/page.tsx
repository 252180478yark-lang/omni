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

interface VideoDetailResp {
  video: VideoItem & {
    retry_count?: number
    next_run_at?: string | null
    last_error?: string | null
    pipeline?: {
      current_stage?: string
    }
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

  const currentProvider = useMemo(
    () => providers.find((p) => p.id === selectedProvider),
    [providers, selectedProvider],
  )
  const availableProviders = useMemo(() => {
    const geminiOnly = providers.filter((p) => p.id === 'gemini')
    return geminiOnly.length > 0 ? geminiOnly : providers
  }, [providers])

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
    if (!selectedVideoId || !status || !['queued', 'running', 'retrying'].includes(status)) {
      return
    }
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
    if (!url) {
      setMessage('当前视频暂无原视频链接')
      return
    }
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  const deleteSelectedVideo = async () => {
    if (!selectedVideoId) {
      setMessage('请先选择要删除的视频')
      return
    }
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
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link href="/" className="text-gray-500 hover:text-gray-900">← 返回控制台</Link>
          <div className="font-semibold text-gray-900">短视频分析接入</div>
          <Badge variant="outline">{selectedProvider}</Badge>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 space-y-6">
        <Card className="apple-card border-none shadow-sm">
          <CardHeader>
            <CardTitle>分析来源配置</CardTitle>
            <CardDescription>模型来源走系统已保存 API Key（当前短视频多模态分析接入 Gemini）；向量库可多选保存。</CardDescription>
          </CardHeader>
          <CardContent className="grid md:grid-cols-4 gap-3">
            <select value={selectedProvider} onChange={(e) => setSelectedProvider(e.target.value)} className="h-10 rounded-md border px-3">
              {availableProviders.map((p) => <option key={p.id} value={p.id}>{p.name} {p.apiKeySet ? '' : '(未配置Key)'}</option>)}
            </select>
            <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="h-10 rounded-md border px-3">
              {(currentProvider?.models || []).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <Button onClick={() => void syncProviderKey()} disabled={syncing}>{syncing ? '同步中...' : '同步系统 Key 到分析服务'}</Button>
            <input type="file" accept="video/*" onChange={(e) => void uploadVideo(e.target.files?.[0])} disabled={uploading} className="h-10 text-sm" />
          </CardContent>
        </Card>

        <Card className="apple-card border-none shadow-sm">
          <CardHeader>
            <CardTitle>向量库勾选</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-4">
            {knowledgeBases.map((kb) => (
              <label key={kb.id} className="text-sm flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selectedKbIds.includes(kb.id)}
                  onChange={(e) => {
                    setSelectedKbIds((prev) => (e.target.checked ? [...prev, kb.id] : prev.filter((x) => x !== kb.id)))
                  }}
                />
                {kb.name}
              </label>
            ))}
            <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={includeOriginal} onChange={(e) => setIncludeOriginal(e.target.checked)} /> 附带原视频链接</label>
            <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={includeBundle} onChange={(e) => setIncludeBundle(e.target.checked)} /> 附带打包文件链接</label>
            <Button onClick={() => void saveToKnowledge()} disabled={saving}>{saving ? '保存中...' : '保存分析结果到知识库'}</Button>
          </CardContent>
        </Card>

        <Card className="apple-card border-none shadow-sm">
          <CardHeader>
            <CardTitle>分析结果</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <select value={selectedVideoId} onChange={(e) => setSelectedVideoId(e.target.value)} className="h-10 rounded-md border px-3 w-full md:w-[420px]">
              <option value="">请选择视频</option>
              {videos.map((v) => (
                <option key={v.id} value={v.id}>{v.original_name} ({v.status})</option>
              ))}
            </select>
            <div className="text-sm text-gray-600">{videoDetail?.report?.summary ? String(videoDetail.report.summary) : '暂无摘要'}</div>
            {videoDetail?.video?.status !== 'done' ? (
              <div className="text-xs text-gray-500">
                状态：{videoDetail?.video?.status}
                {videoDetail?.video?.pipeline?.current_stage ? `，阶段：${videoDetail.video.pipeline.current_stage}` : ''}
                {typeof videoDetail?.video?.retry_count === 'number' ? `，重试次数：${videoDetail.video.retry_count}` : ''}
                {videoDetail?.video?.last_error ? `，最近错误：${videoDetail.video.last_error}` : ''}
              </div>
            ) : null}
            <div className="flex gap-3 text-sm">
              <Button variant="outline" onClick={openOriginalVideo} disabled={!videoDetail?.original_video_url}>打开原视频</Button>
              <Button variant="destructive" onClick={() => void deleteSelectedVideo()} disabled={deleting || !selectedVideoId}>
                {deleting ? '删除中...' : '删除视频'}
              </Button>
              {videoDetail?.original_video_url ? <a className="text-blue-600" href={joinUrl(videoDetail.original_video_url)} target="_blank">下载原视频</a> : null}
              {videoDetail?.bundle_url ? <a className="text-blue-600" href={joinUrl(videoDetail.bundle_url)} target="_blank">下载打包文件</a> : null}
              {videoDetail?.report_markdown_url ? <a className="text-blue-600" href={joinUrl(videoDetail.report_markdown_url)} target="_blank">下载Markdown</a> : null}
              {videoDetail?.report_json_url ? <a className="text-blue-600" href={joinUrl(videoDetail.report_json_url)} target="_blank">下载JSON</a> : null}
            </div>
          </CardContent>
        </Card>

        {message ? <div className="text-sm rounded-md border bg-white px-4 py-3">{message}</div> : null}
      </main>
    </div>
  )
}
