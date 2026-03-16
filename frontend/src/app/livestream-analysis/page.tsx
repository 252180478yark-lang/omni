'use client'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

const API = '/api/v1/livestream-analysis'
const UPLOAD_API = 'http://127.0.0.1:8007/api/v1/livestream-analysis'

interface ProviderItem { id: string; name: string; models: string[]; apiKeySet?: boolean; defaultChatModel?: string | null }
interface KnowledgeBaseItem { id: string; name: string }
interface TaskItem { id: string; original_name: string; display_name?: string; status: string; created_at: string }
interface TaskDetail {
  task_id: string
  original_name: string
  display_name?: string
  status: string
  phase: string
  message: string
  progress: { current: number; total: number }
  excel_url: string | null
  json_url: string | null
  error: string | null
  summary: {
    total_duration?: string
    total_segments?: number
    overall_style?: string
    highlights?: string[]
    improvements?: string[]
    person_summary?: { role: string; description: string }[]
    phase_distribution?: Record<string, number>
  } | null
  created_at: string
}

interface FullSegment {
  time_start: string
  time_end: string
  duration_seconds: number
  phase: string
  visual_description: string
  background_elements?: string[]
  overlay_elements?: string[]
  person_count: number
  person_roles?: string[]
  scripts?: Record<string, { role: string; content: string }>
  speech_pace?: string
  rhythm_notes?: string
  style_tags?: string[]
  notes?: string
}

interface FullReport {
  segments: FullSegment[]
  summary: TaskDetail['summary']
}

function formatReportForKB(filename: string, report: FullReport): string {
  const lines: string[] = [`# 直播切片分析报告: ${filename}\n`]

  if (report.summary) {
    const s = report.summary
    lines.push('## 总览')
    if (s.total_duration) lines.push(`- 总时长: ${s.total_duration}`)
    if (s.total_segments) lines.push(`- 总片段数: ${s.total_segments}`)
    if (s.overall_style) lines.push(`- 整体风格: ${s.overall_style}`)
    if (s.person_summary?.length) {
      lines.push('- 人物:')
      for (const p of s.person_summary) lines.push(`  - ${p.role}: ${p.description}`)
    }
    if (s.phase_distribution) {
      lines.push('- 阶段分布:')
      for (const [k, v] of Object.entries(s.phase_distribution)) lines.push(`  - ${k}: ${v}段`)
    }
    if (s.highlights?.length) lines.push(`- 亮点: ${s.highlights.join('；')}`)
    if (s.improvements?.length) lines.push(`- 改进建议: ${s.improvements.join('；')}`)
    lines.push('')
  }

  if (report.segments?.length) {
    lines.push('## 逐段分析\n')
    for (const seg of report.segments) {
      lines.push(`### ${seg.time_start} ~ ${seg.time_end} (${seg.duration_seconds}s) — ${seg.phase}`)
      lines.push(`画面描述: ${seg.visual_description}`)
      if (seg.background_elements?.length)
        lines.push(`背景元素: ${seg.background_elements.join('、')}`)
      if (seg.overlay_elements?.length)
        lines.push(`贴片元素: ${seg.overlay_elements.join('、')}`)
      if (seg.person_count) lines.push(`出镜人数: ${seg.person_count}`)
      if (seg.speech_pace) lines.push(`语速: ${seg.speech_pace}`)
      if (seg.style_tags?.length) lines.push(`风格标签: ${seg.style_tags.join('、')}`)
      if (seg.scripts && Object.keys(seg.scripts).length > 0) {
        lines.push('话术逐字稿:')
        for (const [, ps] of Object.entries(seg.scripts)) {
          lines.push(`  [${ps.role}] ${ps.content}`)
        }
      }
      if (seg.notes) lines.push(`备注: ${seg.notes}`)
      lines.push('')
    }
  }

  return lines.join('\n')
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  } catch { return iso }
}

const STEP_LABELS = ['读取视频', '上传', 'AI 分析', '生成报告']

const statusMap: Record<string, { label: string; color: string }> = {
  queued: { label: '排队中', color: 'bg-gray-400' },
  running: { label: '分析中', color: 'bg-blue-500 animate-pulse' },
  done: { label: '已完成', color: 'bg-green-500' },
  failed: { label: '失败', color: 'bg-red-500' },
}

const PHASE_COLORS: Record<string, string> = {
  '开场': 'bg-blue-100 text-blue-700',
  '产品介绍': 'bg-purple-100 text-purple-700',
  '互动': 'bg-green-100 text-green-700',
  '促单': 'bg-orange-100 text-orange-700',
  '福利': 'bg-pink-100 text-pink-700',
  '过渡': 'bg-gray-100 text-gray-600',
}

export default function LivestreamAnalysisPage() {
  const [providers, setProviders] = useState<ProviderItem[]>([])
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseItem[]>([])
  const [selectedProvider, setSelectedProvider] = useState('gemini')
  const [selectedModel, setSelectedModel] = useState('')
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [activeTaskId, setActiveTaskId] = useState('')
  const [taskDetail, setTaskDetail] = useState<TaskDetail | null>(null)
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([])
  const [syncing, setSyncing] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [message, setMessage] = useState('')
  const [dragover, setDragover] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [elapsed, setElapsed] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [taskTab, setTaskTab] = useState<'active' | 'done'>('active')
  const [fullReport, setFullReport] = useState<FullReport | null>(null)
  const [loadingReport, setLoadingReport] = useState(false)
  const [expandedSegIdx, setExpandedSegIdx] = useState<number | null>(null)
  const [showNewKbInput, setShowNewKbInput] = useState(false)
  const [newKbName, setNewKbName] = useState('')
  const [creatingKb, setCreatingKb] = useState(false)
  const [batchSelectedIds, setBatchSelectedIds] = useState<Set<string>>(new Set())
  const [batchSaving, setBatchSaving] = useState(false)
  const [batchProgress, setBatchProgress] = useState({ done: 0, total: 0 })

  const currentProvider = useMemo(() => providers.find((p) => p.id === selectedProvider), [providers, selectedProvider])
  const availableProviders = useMemo(() => {
    const g = providers.filter((p) => p.id === 'gemini')
    return g.length ? g : providers
  }, [providers])

  const activeTasks = useMemo(() => tasks.filter((t) => t.status !== 'done'), [tasks])
  const doneTasks = useMemo(() => tasks.filter((t) => t.status === 'done'), [tasks])

  const refreshTasks = useCallback(async () => {
    try {
      const res = await fetch(`${API}/videos`, { cache: 'no-store' })
      if (!res.ok) return
      const data = (await res.json()) as TaskItem[]
      setTasks(data)
    } catch { /* service may be offline */ }
  }, [])

  const loadDetail = useCallback(async (id: string) => {
    try {
      const res = await fetch(`${API}/tasks/${id}`, { cache: 'no-store' })
      if (!res.ok) return
      setTaskDetail((await res.json()) as TaskDetail)
    } catch { /* */ }
  }, [])

  const loadFullReport = useCallback(async (id: string) => {
    setLoadingReport(true)
    setFullReport(null)
    setExpandedSegIdx(null)
    try {
      const res = await fetch(`${API}/videos/${id}`, { cache: 'no-store' })
      if (!res.ok) return
      const data = (await res.json()) as { report?: FullReport | null }
      if (data.report) setFullReport(data.report)
    } catch { /* */ }
    finally { setLoadingReport(false) }
  }, [])

  const saveLocal = useCallback(async (taskId: string) => {
    try {
      const res = await fetch(`${API}/tasks/${taskId}/save-local`, { method: 'POST' })
      if (!res.ok) { setMessage('保存失败'); return }
      const data = (await res.json()) as { success: boolean; files: string[]; folder: string }
      if (data.success) {
        setMessage(`已保存到 ${data.folder}\n${data.files.map((f) => '  → ' + f.split('\\').pop()).join('\n')}`)
      }
    } catch {
      setMessage('保存失败，请重试')
    }
  }, [])

  useEffect(() => {
    const run = async () => {
      const [pRes, kbRes] = await Promise.all([
        fetch('/api/omni/models', { cache: 'no-store' }).catch(() => null),
        fetch('/api/omni/knowledge/bases', { cache: 'no-store' }).catch(() => null),
      ])
      if (pRes?.ok) {
        const pj = (await pRes.json()) as { success: boolean; data?: { providers: ProviderItem[] } }
        if (pj.success && pj.data) {
          setProviders(pj.data.providers)
          const g = pj.data.providers.find((x) => x.id === 'gemini') || pj.data.providers[0]
          if (g) { setSelectedProvider(g.id); setSelectedModel(g.defaultChatModel || g.models[0] || '') }
        }
      }
      if (kbRes?.ok) {
        const kj = (await kbRes.json()) as { success: boolean; data?: KnowledgeBaseItem[] }
        if (kj.success && kj.data) setKnowledgeBases(kj.data)
      }
      await refreshTasks()
    }
    void run().catch(() => {})
  }, [refreshTasks])

  useEffect(() => {
    if (!activeTaskId) return
    void loadDetail(activeTaskId)
  }, [activeTaskId, loadDetail])

  useEffect(() => {
    if (activeTaskId && taskDetail?.status === 'done') {
      void loadFullReport(activeTaskId)
    }
  }, [activeTaskId, taskDetail?.status, loadFullReport])

  useEffect(() => {
    const st = taskDetail?.status
    if (!activeTaskId || !st || !['queued', 'running'].includes(st)) {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
      return
    }
    const poll = window.setInterval(() => {
      void Promise.all([refreshTasks(), loadDetail(activeTaskId)])
    }, 2000)
    return () => window.clearInterval(poll)
  }, [taskDetail?.status, activeTaskId, refreshTasks, loadDetail])

  useEffect(() => {
    const st = taskDetail?.status
    if (st === 'running' || st === 'queued') {
      if (!timerRef.current) {
        setElapsed(0)
        timerRef.current = setInterval(() => setElapsed((p) => p + 1), 1000)
      }
    } else {
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [taskDetail?.status])

  const syncKey = async () => {
    setSyncing(true); setMessage('')
    try {
      const res = await fetch('/api/omni/livestream-analysis/sync-provider', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: selectedProvider, model: selectedModel }),
      })
      const j = (await res.json()) as { success: boolean; error?: string }
      if (!j.success) throw new Error(j.error || '同步失败')
      setMessage('已同步系统 API Key 到直播切片分析服务')
    } catch (e) { setMessage(String(e)) }
    finally { setSyncing(false) }
  }

  const uploadOne = (file: File, onProgress?: (pct: number) => void): Promise<string> => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${UPLOAD_API}/videos`)
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try { resolve(JSON.parse(xhr.responseText).task_id) }
          catch { reject(new Error(`${file.name}: 解析响应失败`)) }
        } else {
          reject(new Error(`${file.name}: ${xhr.statusText || '上传失败'}`))
        }
      }
      xhr.onerror = () => reject(new Error(`${file.name}: 网络错误`))
      const form = new FormData(); form.append('file', file)
      xhr.send(form)
    })
  }

  const upload = async (files?: FileList | File[] | null) => {
    if (!files || files.length === 0) return
    const fileList = Array.from(files)
    const valid = fileList.filter((f) => {
      const ext = f.name.split('.').pop()?.toLowerCase()
      return ['mp4', 'mov'].includes(ext || '') && f.size <= 2 * 1024 * 1024 * 1024
    })
    if (valid.length === 0) { setMessage('没有有效的 MP4/MOV 文件'); return }
    if (valid.length < fileList.length) setMessage(`已过滤 ${fileList.length - valid.length} 个无效文件`)

    setUploading(true); setUploadProgress('')
    const PARALLEL = 3
    let lastTaskId = ''
    let doneCount = 0
    const errors: string[] = []
    for (let i = 0; i < valid.length; i += PARALLEL) {
      const batch = valid.slice(i, i + PARALLEL)
      const progressMap: Record<number, number> = {}
      const updateMsg = () => {
        const currentPcts = batch.map((_, bi) => progressMap[bi] ?? 0)
        const avgPct = Math.round(currentPcts.reduce((a, b) => a + b, 0) / batch.length)
        setUploadProgress(`上传 ${doneCount + 1}-${Math.min(doneCount + batch.length, valid.length)}/${valid.length} (${avgPct}%)`)
      }
      updateMsg()
      const results = await Promise.allSettled(
        batch.map((f, bi) => uploadOne(f, (pct) => { progressMap[bi] = pct; updateMsg() }))
      )
      for (const r of results) {
        if (r.status === 'fulfilled') lastTaskId = r.value
        else errors.push(r.reason?.message || '上传失败')
      }
      doneCount += batch.length
      await refreshTasks()
    }
    if (lastTaskId) { setActiveTaskId(lastTaskId); setTaskTab('active') }
    setUploadProgress('')
    setMessage(errors.length > 0
      ? `已上传 ${doneCount - errors.length}/${valid.length}，失败: ${errors.join('; ')}`
      : `已上传 ${doneCount} 个文件，分析任务已启动`)
    setUploading(false)
  }

  const saveToKb = async () => {
    if (!taskDetail?.summary || selectedKbIds.length === 0) {
      setMessage('请勾选知识库并确保分析已完成'); return
    }
    setSaving(true); setMessage('')
    try {
      const report = fullReport
      const text = report ? formatReportForKB(taskDetail.original_name, report) : JSON.stringify(taskDetail.summary, null, 2)

      for (const kbId of selectedKbIds) {
        const resp = await fetch('/api/omni/knowledge/ingest', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            kb_id: kbId,
            title: `直播切片分析-${taskDetail.original_name}`,
            text,
            source_type: 'livestream-analysis',
          }),
        })
        const j = (await resp.json()) as { success: boolean; error?: string }
        if (!j.success) throw new Error(j.error || `入库失败: ${kbId}`)
      }
      setMessage(`已保存到 ${selectedKbIds.length} 个知识库（含完整逐字稿和元素分析）`)
    } catch (e) { setMessage(String(e)) }
    finally { setSaving(false) }
  }

  const deleteTask = async (id: string) => {
    if (!window.confirm('确认删除该任务及分析产物？')) return
    setDeleting(true); setMessage('')
    try {
      const res = await fetch(`${API}/videos/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await res.text())
      if (activeTaskId === id) { setActiveTaskId(''); setTaskDetail(null); setFullReport(null) }
      await refreshTasks()
      setMessage('已删除')
    } catch (e) { setMessage(String(e)) }
    finally { setDeleting(false) }
  }

  const createKb = async () => {
    if (!newKbName.trim()) return
    setCreatingKb(true)
    try {
      const res = await fetch('/api/omni/knowledge/bases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newKbName.trim(), description: '直播切片分析报告', dimension: 1536 }),
      })
      const json = (await res.json()) as { success: boolean; data?: { id: string; name: string }; error?: string }
      if (!json.success) throw new Error(json.error || '创建失败')
      const kbRes = await fetch('/api/omni/knowledge/bases', { cache: 'no-store' })
      const kbJson = (await kbRes.json()) as { success: boolean; data?: KnowledgeBaseItem[] }
      if (kbJson.success && kbJson.data) {
        setKnowledgeBases(kbJson.data)
        if (json.data?.id) setSelectedKbIds((prev) => [...prev, json.data!.id])
      }
      setNewKbName('')
      setShowNewKbInput(false)
      setMessage(`知识库「${newKbName.trim()}」创建成功`)
    } catch (e) { setMessage(String(e)) }
    finally { setCreatingKb(false) }
  }

  const toggleBatchId = (id: string) => {
    setBatchSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const selectAllDone = () => {
    const allIds = new Set(doneTasks.map((t) => t.id))
    setBatchSelectedIds((prev) => prev.size === allIds.size ? new Set() : allIds)
  }

  const batchSaveToKb = async () => {
    if (batchSelectedIds.size === 0 || selectedKbIds.length === 0) {
      setMessage('请勾选任务和知识库'); return
    }
    setBatchSaving(true); setMessage('')
    const ids = Array.from(batchSelectedIds)
    setBatchProgress({ done: 0, total: ids.length })
    let successCount = 0
    for (const tid of ids) {
      try {
        const res = await fetch(`${API}/videos/${tid}`, { cache: 'no-store' })
        if (!res.ok) continue
        const data = (await res.json()) as { report?: FullReport | null; video?: { original_name?: string; display_name?: string } }
        if (!data.report) continue
        const taskItem = tasks.find((t) => t.id === tid)
        const name = taskItem?.display_name || taskItem?.original_name || tid
        const text = formatReportForKB(name, data.report as FullReport)
        for (const kbId of selectedKbIds) {
          const resp = await fetch('/api/omni/knowledge/ingest', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ kb_id: kbId, title: `直播切片分析-${name}`, text, source_type: 'livestream-analysis' }),
          })
          const j = (await resp.json()) as { success: boolean }
          if (!j.success) throw new Error('入库失败')
        }
        successCount++
      } catch { /* skip */ }
      setBatchProgress((p) => ({ ...p, done: p.done + 1 }))
    }
    setBatchSaving(false)
    setBatchSelectedIds(new Set())
    setMessage(`批量入库完成：${successCount}/${ids.length} 个任务已保存到 ${selectedKbIds.length} 个知识库`)
  }

  const pct = taskDetail?.progress ? Math.round((taskDetail.progress.current / (taskDetail.progress.total || 4)) * 100) : 0
  const isDone = taskDetail?.status === 'done'
  const isRunning = taskDetail?.status === 'running' || taskDetail?.status === 'queued'

  const visibleTasks = taskTab === 'active' ? activeTasks : doneTasks

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link href="/" className="text-gray-500 hover:text-gray-900 transition-colors">&larr; 返回控制台</Link>
          <div className="font-semibold text-gray-900">直播切片分析</div>
          <Badge variant="outline">Gemini</Badge>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 space-y-6">
        {/* 配置区 */}
        <Card className="apple-card border-none shadow-sm">
          <CardHeader>
            <CardTitle>模型配置</CardTitle>
            <CardDescription>使用 Gemini 多模态能力分析电商直播切片，自动生成话术逐字稿和结构化报告</CardDescription>
          </CardHeader>
          <CardContent className="grid md:grid-cols-4 gap-3">
            <select value={selectedProvider} onChange={(e) => setSelectedProvider(e.target.value)} className="h-10 rounded-md border px-3 text-sm">
              {availableProviders.map((p) => <option key={p.id} value={p.id}>{p.name}{p.apiKeySet ? '' : ' (未配置Key)'}</option>)}
            </select>
            <select value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)} className="h-10 rounded-md border px-3 text-sm">
              {(currentProvider?.models || []).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <Button onClick={() => void syncKey()} disabled={syncing} className="text-sm">
              {syncing ? '同步中...' : '同步 API Key'}
            </Button>
            <div />
          </CardContent>
        </Card>

        {/* 上传区 */}
        <Card className="apple-card border-none shadow-sm">
          <CardHeader><CardTitle>上传直播切片</CardTitle></CardHeader>
          <CardContent>
            <div
              className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all ${dragover ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}`}
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragover(true) }}
              onDragLeave={() => setDragover(false)}
              onDrop={(e) => { e.preventDefault(); setDragover(false); void upload(e.dataTransfer?.files) }}
            >
              <input ref={fileRef} type="file" accept=".mp4,.mov" multiple className="hidden" onChange={(e) => void upload(e.target.files)} />
              <div className="text-4xl mb-3 opacity-60">🎬</div>
              <div className="font-medium text-gray-700">{uploading ? (uploadProgress || '上传中...') : '点击或拖拽视频到此处'}</div>
              <div className="text-sm text-gray-400 mt-1">支持 MP4、MOV，≤ 2GB，≤ 60 分钟</div>
            </div>
          </CardContent>
        </Card>

        {/* 任务区域 */}
        <div className="grid md:grid-cols-3 gap-6">
          {/* 左：任务列表 */}
          <Card className="apple-card border-none shadow-sm md:col-span-1 flex flex-col" style={{ maxHeight: 600 }}>
            <CardHeader className="pb-2">
              <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-0.5">
                <button
                  onClick={() => setTaskTab('active')}
                  className={`flex-1 text-xs font-medium py-1.5 rounded-md transition-all ${taskTab === 'active' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}
                >
                  进行中 {activeTasks.length > 0 && <span className="ml-1 text-blue-500">({activeTasks.length})</span>}
                </button>
                <button
                  onClick={() => setTaskTab('done')}
                  className={`flex-1 text-xs font-medium py-1.5 rounded-md transition-all ${taskTab === 'done' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}
                >
                  已完成 {doneTasks.length > 0 && <span className="ml-1 text-green-500">({doneTasks.length})</span>}
                </button>
              </div>
            </CardHeader>
            <CardContent className="flex-1 overflow-y-auto space-y-1.5 min-h-0">
              {visibleTasks.length === 0 && (
                <div className="text-sm text-gray-400 text-center py-8">
                  {taskTab === 'active' ? '暂无进行中的任务' : '暂无已完成的报告'}
                </div>
              )}
              {taskTab === 'done' && doneTasks.length > 1 && (
                <div className="flex items-center justify-between pb-1 border-b border-gray-100 mb-1">
                  <label className="text-[11px] text-gray-500 flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" className="accent-blue-600" checked={batchSelectedIds.size === doneTasks.length && doneTasks.length > 0} onChange={selectAllDone} />
                    全选 ({batchSelectedIds.size}/{doneTasks.length})
                  </label>
                </div>
              )}
              {visibleTasks.map((t) => {
                const st = statusMap[t.status] || statusMap.queued
                const isSelected = activeTaskId === t.id
                const isBatchChecked = batchSelectedIds.has(t.id)
                return (
                  <div
                    key={t.id}
                    className={`p-3 rounded-lg cursor-pointer transition-all ${isSelected ? 'bg-blue-50 ring-1 ring-blue-200 shadow-sm' : 'hover:bg-gray-50'}`}
                    onClick={() => { setActiveTaskId(t.id); setFullReport(null) }}
                  >
                    <div className="flex items-center gap-2">
                      {taskTab === 'done' && (
                        <input
                          type="checkbox"
                          className="accent-blue-600 flex-shrink-0"
                          checked={isBatchChecked}
                          onClick={(e) => e.stopPropagation()}
                          onChange={() => toggleBatchId(t.id)}
                        />
                      )}
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${st.color}`} />
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate" title={t.display_name || t.original_name}>{t.display_name || t.original_name}</div>
                      </div>
                      <button
                        className="text-xs text-gray-300 hover:text-red-500 transition-colors flex-shrink-0"
                        onClick={(e) => { e.stopPropagation(); void deleteTask(t.id) }}
                        disabled={deleting}
                        title="删除"
                      >✕</button>
                    </div>
                    <div className="flex items-center justify-between mt-1 pl-4">
                      <span className="text-[11px] text-gray-400">{st.label}</span>
                      <span className="text-[11px] text-gray-400">{formatDate(t.created_at)}</span>
                    </div>
                  </div>
                )
              })}
            </CardContent>
          </Card>

          {/* 右：详情 */}
          <Card className="apple-card border-none shadow-sm md:col-span-2 flex flex-col" style={{ maxHeight: 600 }}>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                {isDone ? '分析报告' : '分析详情'}
                {taskDetail && <span className="text-sm font-normal text-gray-400 ml-2 truncate">{taskDetail.display_name || taskDetail.original_name}</span>}
              </CardTitle>
            </CardHeader>
            <CardContent className="flex-1 overflow-y-auto space-y-4 min-h-0">
              {!activeTaskId && <div className="text-sm text-gray-400 text-center py-12">请从左侧选择一个任务，或上传新视频</div>}

              {/* ─── Running state ─── */}
              {activeTaskId && isRunning && (
                <div className="space-y-3">
                  <div className="flex gap-1">
                    {STEP_LABELS.map((label, i) => (
                      <div key={label} className="flex-1 space-y-1">
                        <div className={`h-1.5 rounded-full transition-all ${i < (taskDetail?.progress?.current || 0) ? 'bg-green-500' : i === (taskDetail?.progress?.current || 0) ? 'bg-blue-500 animate-pulse' : 'bg-gray-200'}`} />
                        <div className="text-[10px] text-gray-400 text-center">{label}</div>
                      </div>
                    ))}
                  </div>
                  <div className="relative h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div className="absolute inset-y-0 left-0 bg-gradient-to-r from-blue-500 to-purple-500 rounded-full transition-all" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="flex justify-between text-xs text-gray-500">
                    <span>{taskDetail?.message}</span>
                    <span>已用时 {elapsed}s</span>
                  </div>
                </div>
              )}

              {/* ─── Failed state ─── */}
              {activeTaskId && taskDetail?.status === 'failed' && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-600">
                  {taskDetail.error || '分析失败'}
                </div>
              )}

              {/* ─── Done: Summary + Full Report ─── */}
              {activeTaskId && isDone && taskDetail?.summary && (
                <div className="space-y-5">
                  {/* Summary banner */}
                  <div className="bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-xl p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="w-2 h-2 rounded-full bg-green-500" />
                      <span className="text-sm font-semibold text-green-800">分析完成</span>
                    </div>
                    <div className="grid grid-cols-3 gap-3 text-sm">
                      <div className="bg-white/60 rounded-lg p-2 text-center">
                        <div className="text-lg font-bold text-gray-800">{taskDetail.summary.total_duration || '-'}</div>
                        <div className="text-[11px] text-gray-500">总时长</div>
                      </div>
                      <div className="bg-white/60 rounded-lg p-2 text-center">
                        <div className="text-lg font-bold text-gray-800">{taskDetail.summary.total_segments ?? '-'}</div>
                        <div className="text-[11px] text-gray-500">分析段数</div>
                      </div>
                      <div className="bg-white/60 rounded-lg p-2 text-center">
                        <div className="text-sm font-medium text-gray-800 truncate">{taskDetail.summary.overall_style?.slice(0, 10) || '-'}</div>
                        <div className="text-[11px] text-gray-500">整体风格</div>
                      </div>
                    </div>
                  </div>

                  {/* Person summary */}
                  {taskDetail.summary.person_summary && taskDetail.summary.person_summary.length > 0 && (
                    <div>
                      <div className="text-sm font-semibold text-gray-700 mb-2">出场人物</div>
                      <div className="flex flex-wrap gap-2">
                        {taskDetail.summary.person_summary.map((p) => (
                          <div key={p.role} className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-1.5 text-sm">
                            <span className="font-medium text-blue-700">{p.role}</span>
                            <span className="text-gray-600 ml-1.5">{p.description}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Phase distribution */}
                  {taskDetail.summary.phase_distribution && Object.keys(taskDetail.summary.phase_distribution).length > 0 && (
                    <div>
                      <div className="text-sm font-semibold text-gray-700 mb-2">流程分布</div>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(taskDetail.summary.phase_distribution).map(([phase, cnt]) => (
                          <Badge key={phase} className={`text-xs ${PHASE_COLORS[phase] || 'bg-gray-100 text-gray-600'}`}>
                            {phase} ({cnt}段)
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Highlights & improvements */}
                  <div className="grid md:grid-cols-2 gap-4">
                    {taskDetail.summary.highlights && taskDetail.summary.highlights.length > 0 && (
                      <div className="bg-amber-50/50 border border-amber-100 rounded-lg p-3">
                        <div className="text-sm font-semibold text-amber-800 mb-1.5">话术亮点</div>
                        <ul className="text-sm text-gray-600 space-y-1 list-disc list-inside">
                          {taskDetail.summary.highlights.slice(0, 5).map((h, i) => <li key={i}>{h}</li>)}
                        </ul>
                      </div>
                    )}
                    {taskDetail.summary.improvements && taskDetail.summary.improvements.length > 0 && (
                      <div className="bg-sky-50/50 border border-sky-100 rounded-lg p-3">
                        <div className="text-sm font-semibold text-sky-800 mb-1.5">改进建议</div>
                        <ul className="text-sm text-gray-600 space-y-1 list-disc list-inside">
                          {taskDetail.summary.improvements.slice(0, 5).map((imp, i) => <li key={i}>{imp}</li>)}
                        </ul>
                      </div>
                    )}
                  </div>

                  {/* Save to local folder */}
                  <div className="flex items-center gap-3">
                    <Button variant="default" className="text-sm" onClick={() => void saveLocal(taskDetail.task_id)}>
                      保存报告到本地
                    </Button>
                    <span className="text-xs text-gray-400">保存到 E:\agent\omni\downloads\reports\</span>
                  </div>

                  {/* ─── Full Segment Report ─── */}
                  {loadingReport && (
                    <div className="text-sm text-gray-400 text-center py-6">加载逐段分析报告...</div>
                  )}
                  {fullReport && fullReport.segments && fullReport.segments.length > 0 && (
                    <div>
                      <div className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                        逐段详细分析
                        <Badge variant="outline" className="text-[10px]">{fullReport.segments.length} 段</Badge>
                      </div>
                      <div className="space-y-2">
                        {fullReport.segments.map((seg, idx) => {
                          const isOpen = expandedSegIdx === idx
                          const phaseClass = PHASE_COLORS[seg.phase] || 'bg-gray-100 text-gray-600'
                          return (
                            <div key={idx} className="border border-gray-100 rounded-lg bg-white transition-all hover:shadow-sm">
                              {/* Segment header — always visible */}
                              <button
                                className="w-full flex items-center gap-3 p-3 text-left"
                                onClick={() => setExpandedSegIdx(isOpen ? null : idx)}
                              >
                                <span className="text-xs font-mono text-gray-500 w-24 flex-shrink-0">
                                  {seg.time_start} ~ {seg.time_end}
                                </span>
                                <Badge className={`text-[10px] flex-shrink-0 ${phaseClass}`}>{seg.phase}</Badge>
                                <span className="text-sm text-gray-600 truncate flex-1">{seg.visual_description}</span>
                                <span className={`text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}>▾</span>
                              </button>

                              {/* Segment detail — expanded */}
                              {isOpen && (
                                <div className="px-4 pb-4 space-y-3 border-t border-gray-50">
                                  {/* Meta row */}
                                  <div className="flex flex-wrap gap-2 pt-3">
                                    <span className="text-xs bg-gray-50 px-2 py-0.5 rounded text-gray-500">{seg.duration_seconds}s</span>
                                    {seg.person_count > 0 && <span className="text-xs bg-gray-50 px-2 py-0.5 rounded text-gray-500">{seg.person_count}人出镜</span>}
                                    {seg.speech_pace && <span className="text-xs bg-gray-50 px-2 py-0.5 rounded text-gray-500">语速: {seg.speech_pace}</span>}
                                    {seg.style_tags?.map((tag) => (
                                      <span key={tag} className="text-xs bg-purple-50 text-purple-600 px-2 py-0.5 rounded">{tag}</span>
                                    ))}
                                  </div>

                                  {/* Visual description */}
                                  <div>
                                    <div className="text-xs font-semibold text-gray-500 mb-1">画面描述</div>
                                    <p className="text-sm text-gray-700">{seg.visual_description}</p>
                                  </div>

                                  {/* Background & Overlay elements */}
                                  {seg.background_elements && seg.background_elements.length > 0 && (
                                    <div>
                                      <div className="text-xs font-semibold text-gray-500 mb-1">背景元素</div>
                                      <div className="flex flex-wrap gap-1.5">
                                        {seg.background_elements.map((el) => (
                                          <span key={el} className="text-xs bg-teal-50 text-teal-700 border border-teal-200 px-2 py-0.5 rounded-full">{el}</span>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                  {seg.overlay_elements && seg.overlay_elements.length > 0 && (
                                    <div>
                                      <div className="text-xs font-semibold text-gray-500 mb-1">贴片元素</div>
                                      <div className="flex flex-wrap gap-1.5">
                                        {seg.overlay_elements.map((el) => (
                                          <span key={el} className="text-xs bg-orange-50 text-orange-700 border border-orange-200 px-2 py-0.5 rounded-full">{el}</span>
                                        ))}
                                      </div>
                                    </div>
                                  )}

                                  {/* Scripts */}
                                  {seg.scripts && Object.keys(seg.scripts).length > 0 && (
                                    <div>
                                      <div className="text-xs font-semibold text-gray-500 mb-1">话术逐字稿</div>
                                      <div className="space-y-2">
                                        {Object.entries(seg.scripts).map(([key, ps]) => (
                                          <div key={key} className="bg-gray-50 rounded-lg p-3">
                                            <div className="text-xs font-medium text-blue-600 mb-1">{ps.role}</div>
                                            <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{ps.content}</p>
                                          </div>
                                        ))}
                                      </div>
                                    </div>
                                  )}

                                  {seg.notes && (
                                    <div className="text-xs text-gray-400 italic">备注: {seg.notes}</div>
                                  )}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* 知识库入库 */}
        <Card className="apple-card border-none shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center justify-between">
              <span>保存到知识库</span>
              <button
                onClick={() => setShowNewKbInput((v) => !v)}
                className="text-xs font-normal text-blue-600 hover:text-blue-700 transition-colors"
              >
                + 新建知识库
              </button>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {showNewKbInput && (
              <div className="flex items-center gap-2 bg-blue-50 border border-blue-100 rounded-lg p-3">
                <input
                  type="text"
                  value={newKbName}
                  onChange={(e) => setNewKbName(e.target.value)}
                  placeholder="输入知识库名称，例如：切片知识库"
                  className="flex-1 h-8 px-3 text-sm rounded-md border border-blue-200 focus:outline-none focus:ring-2 focus:ring-blue-400"
                  autoFocus
                  onKeyDown={(e) => { if (e.key === 'Enter' && newKbName.trim()) void createKb() }}
                />
                <Button size="sm" onClick={() => void createKb()} disabled={creatingKb || !newKbName.trim()} className="text-xs bg-blue-600 hover:bg-blue-700 h-8">
                  {creatingKb ? '创建中...' : '创建'}
                </Button>
                <button onClick={() => { setShowNewKbInput(false); setNewKbName('') }} className="text-gray-400 hover:text-gray-600 text-xs">取消</button>
              </div>
            )}
            <div className="flex flex-wrap gap-3 items-center">
              {knowledgeBases.length === 0 && !showNewKbInput && (
                <span className="text-sm text-gray-400">暂无知识库，请先新建</span>
              )}
              {knowledgeBases.map((kb) => (
                <label key={kb.id} className="text-sm flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-200 hover:border-blue-300 cursor-pointer transition-colors has-[:checked]:border-blue-400 has-[:checked]:bg-blue-50">
                  <input type="checkbox" checked={selectedKbIds.includes(kb.id)} className="accent-blue-600"
                    onChange={(e) => setSelectedKbIds((prev) => e.target.checked ? [...prev, kb.id] : prev.filter((x) => x !== kb.id))} />
                  {kb.name}
                </label>
              ))}
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <Button onClick={() => void saveToKb()} disabled={saving || !isDone || selectedKbIds.length === 0} className="text-sm">
                {saving ? '保存中...' : '保存当前报告到知识库'}
              </Button>
              {batchSelectedIds.size > 0 && (
                <Button
                  onClick={() => void batchSaveToKb()}
                  disabled={batchSaving || selectedKbIds.length === 0}
                  variant="outline"
                  className="text-sm border-blue-300 text-blue-700 hover:bg-blue-50"
                >
                  {batchSaving ? `批量入库中 (${batchProgress.done}/${batchProgress.total})...` : `批量入库 (${batchSelectedIds.size} 个)`}
                </Button>
              )}
              {selectedKbIds.length === 0 && (
                <span className="text-xs text-gray-400">请勾选至少一个知识库</span>
              )}
            </div>
          </CardContent>
        </Card>

        {message && <div className="text-sm rounded-lg border bg-white px-4 py-3 shadow-sm">{message}</div>}
      </main>
    </div>
  )
}
