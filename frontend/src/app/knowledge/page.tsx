'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'
import { Database, Plus, Search, FileText, Upload, MoreHorizontal, Trash2, File, X, CheckCircle, Loader2, Globe, ChevronDown, ChevronRight, Eye } from 'lucide-react'

interface KnowledgeBaseItem {
  id: string
  name: string
  description: string
  embedding_provider?: string
  embedding_model: string
  dimension: number
  created_at: string
}

interface DocumentItem {
  id: string
  kb_id: string
  title: string
  source_url: string | null
  created_at: string
  chunk_count: number
}

interface ChunkItem {
  id: string
  chunk_index: number
  content: string
  metadata: Record<string, unknown> | null
}

export default function KnowledgeBaseConfig() {
  const [bases, setBases] = useState<KnowledgeBaseItem[]>([])
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [search, setSearch] = useState('')
  const [docSearch, setDocSearch] = useState('')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [selectedKb, setSelectedKb] = useState('')
  const [loading, setLoading] = useState(false)
  const [docLoading, setDocLoading] = useState(false)
  const [error, setError] = useState('')
  const [docError, setDocError] = useState('')
  const [uploadFiles, setUploadFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadResults, setUploadResults] = useState<{ name: string; ok: boolean; msg: string }[]>([])
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [newKbName, setNewKbName] = useState('')
  const [newKbDesc, setNewKbDesc] = useState('')
  const [creating, setCreating] = useState(false)
  const [expandedDocId, setExpandedDocId] = useState('')
  const [docChunks, setDocChunks] = useState<ChunkItem[]>([])
  const [chunksLoading, setChunksLoading] = useState(false)

  const loadBases = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/omni/knowledge/bases', { cache: 'no-store' })
      const json = (await res.json()) as { success: boolean; data?: KnowledgeBaseItem[]; error?: string }
      if (!json.success || !json.data) {
        throw new Error(json.error || '知识库加载失败')
      }
      setBases(json.data)
      if (!selectedKb && json.data.length > 0) {
        setSelectedKb(json.data[0].id)
      }
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }, [selectedKb])

  useEffect(() => {
    void loadBases()
  }, [loadBases])

  const loadDocuments = useCallback(async () => {
    if (!selectedKb) {
      setDocuments([])
      return
    }
    setDocLoading(true)
    setDocError('')
    try {
      const params = new URLSearchParams({ kb_id: selectedKb, limit: '100' })
      if (docSearch.trim()) {
        params.set('search', docSearch.trim())
      }
      const res = await fetch(`/api/omni/knowledge/documents?${params.toString()}`, { cache: 'no-store' })
      const json = (await res.json()) as { success: boolean; data?: DocumentItem[]; error?: string }
      if (!json.success || !json.data) {
        throw new Error(json.error || '文档加载失败')
      }
      setDocuments(json.data)
    } catch (err) {
      setDocError(String(err))
    } finally {
      setDocLoading(false)
    }
  }, [docSearch, selectedKb])

  useEffect(() => {
    void loadDocuments()
  }, [loadDocuments])

  const createBase = useCallback(async () => {
    if (!newKbName.trim()) return
    setCreating(true)
    setError('')
    try {
      const res = await fetch('/api/omni/knowledge/bases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newKbName.trim(),
          description: newKbDesc.trim(),
          dimension: 1536,
        }),
      })
      const json = (await res.json()) as { success: boolean; data?: KnowledgeBaseItem; error?: string }
      if (!json.success) throw new Error(json.error || '创建失败')
      setShowCreateModal(false)
      setNewKbName('')
      setNewKbDesc('')
      await loadBases()
      if (json.data?.id) setSelectedKb(json.data.id)
    } catch (err) {
      setError(String(err))
    } finally {
      setCreating(false)
    }
  }, [newKbName, newKbDesc, loadBases])

  const submitIngest = useCallback(async () => {
    if (!selectedKb || !title.trim() || !text.trim()) {
      throw new Error('请先填写知识库、标题和正文')
    }
    const res = await fetch('/api/omni/knowledge/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kb_id: selectedKb,
        title: title.trim(),
        text: text.trim(),
      }),
    })
    const json = (await res.json()) as { success: boolean; data?: { task_id: string }; error?: string }
    if (!json.success) {
      throw new Error(json.error || '提交入库失败')
    }
    window.alert(`已提交异步任务: ${json.data?.task_id || ''}`)
    setTitle('')
    setText('')
  }, [selectedKb, title, text])

  const removeBase = useCallback(async (kbId: string) => {
    const target = bases.find((item) => item.id === kbId)
    const ok = window.confirm(`确认删除知识库「${target?.name || kbId}」？该库下文档与任务会一并清理。`)
    if (!ok) return
    const res = await fetch(`/api/omni/knowledge/bases/${kbId}`, { method: 'DELETE' })
    const json = (await res.json()) as { success: boolean; error?: string }
    if (!json.success) {
      throw new Error(json.error || '删除知识库失败')
    }
    if (selectedKb === kbId) {
      setSelectedKb('')
      setDocuments([])
    }
    await loadBases()
  }, [bases, loadBases, selectedKb])

  const ACCEPTED_TYPES = ['.pdf', '.txt', '.md', '.docx', '.html', '.htm', '.srt']

  const handleFileDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const files = Array.from(e.dataTransfer.files).filter((f) => {
      const ext = '.' + f.name.split('.').pop()?.toLowerCase()
      return ACCEPTED_TYPES.includes(ext)
    })
    setUploadFiles((prev) => [...prev, ...files])
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    setUploadFiles((prev) => [...prev, ...files])
    e.target.value = ''
  }, [])

  const removeUploadFile = useCallback((index: number) => {
    setUploadFiles((prev) => prev.filter((_, i) => i !== index))
  }, [])

  const submitFileUpload = useCallback(async () => {
    if (!selectedKb || uploadFiles.length === 0) return
    setUploading(true)
    setUploadResults([])
    const results: { name: string; ok: boolean; msg: string }[] = []

    for (const file of uploadFiles) {
      try {
        const form = new FormData()
        form.append('file', file)
        form.append('kb_id', selectedKb)
        form.append('title', file.name.replace(/\.[^.]+$/, ''))
        form.append('source_type', 'doc')

        const res = await fetch('/api/omni/knowledge/upload', { method: 'POST', body: form })
        const json = (await res.json()) as { success: boolean; data?: { task_id: string; text_length?: number }; error?: string }
        if (json.success) {
          results.push({ name: file.name, ok: true, msg: `任务 ${json.data?.task_id?.slice(0, 8)}...` })
        } else {
          results.push({ name: file.name, ok: false, msg: json.error || '上传失败' })
        }
      } catch (err) {
        results.push({ name: file.name, ok: false, msg: String(err) })
      }
    }

    setUploadResults(results)
    setUploadFiles([])
    setUploading(false)
    setTimeout(() => void loadDocuments(), 2000)
  }, [selectedKb, uploadFiles, loadDocuments])

  const removeDocument = useCallback(async (docId: string) => {
    const ok = window.confirm('确认删除该文档？删除后不可恢复。')
    if (!ok) return
    const res = await fetch(`/api/omni/knowledge/documents/${docId}`, { method: 'DELETE' })
    const json = (await res.json()) as { success: boolean; error?: string }
    if (!json.success) {
      throw new Error(json.error || '删除文档失败')
    }
    await loadDocuments()
  }, [loadDocuments])

  const toggleDocChunks = useCallback(async (docId: string) => {
    if (expandedDocId === docId) {
      setExpandedDocId('')
      setDocChunks([])
      return
    }
    setExpandedDocId(docId)
    setChunksLoading(true)
    try {
      const res = await fetch(`/api/omni/knowledge/documents/${docId}/chunks?limit=50`, { cache: 'no-store' })
      const json = (await res.json()) as { success: boolean; data?: ChunkItem[] }
      if (json.success && json.data) setDocChunks(json.data)
      else setDocChunks([])
    } catch {
      setDocChunks([])
    } finally {
      setChunksLoading(false)
    }
  }, [expandedDocId])

  const filteredBases = useMemo(() => {
    const key = search.trim().toLowerCase()
    if (!key) return bases
    return bases.filter((item) => item.name.toLowerCase().includes(key) || item.id.toLowerCase().includes(key))
  }, [bases, search])

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-4">
              <Link href="/" className="font-semibold text-lg text-gray-500 hover:text-gray-900 transition-colors">
                ← 返回控制台
              </Link>
            </div>
            <div className="font-semibold text-lg text-gray-900 flex items-center gap-2">
              <Database className="w-5 h-5 text-green-600" />
              知识检索引擎 (Knowledge Engine)
            </div>
            <div className="flex items-center gap-3">
              <Link href="/knowledge/harvester">
                <Button variant="outline" size="sm" className="hidden md:flex rounded-full text-xs text-blue-600 border-blue-200 hover:bg-blue-50">
                  <Globe className="w-3.5 h-3.5 mr-1" /> 知识采集
                </Button>
              </Link>
              <Link href="/tasks">
                <Button variant="outline" size="sm" className="hidden md:flex rounded-full text-xs text-gray-600 border-gray-200 hover:bg-gray-50">
                  查看入库任务队列 →
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-10">
        <div className="mb-8 flex justify-between items-end">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-gray-900 mb-2">知识库管理</h1>
            <p className="text-gray-500">创建与管理向量检索空间、上传私有文档并构建知识图谱（默认复用已保存的模型 API 配置）。</p>
          </div>
          <Button className="bg-green-600 hover:bg-green-700 shadow-md" onClick={() => setShowCreateModal(true)} disabled={loading}>
            <Plus className="w-4 h-4 mr-2" />
            新建知识库
          </Button>
        </div>

        {error ? (
          <div className="mb-6 rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">{error}</div>
        ) : null}

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Card className="apple-card border-none shadow-sm">
            <CardContent className="p-6">
              <p className="text-sm font-medium text-gray-500 mb-1">知识库总数</p>
              <h3 className="text-2xl font-bold text-gray-900">{bases.length}</h3>
            </CardContent>
          </Card>
          <Card className="apple-card border-none shadow-sm">
            <CardContent className="p-6">
              <p className="text-sm font-medium text-gray-500 mb-1">默认向量维度</p>
              <h3 className="text-2xl font-bold text-gray-900">1536</h3>
            </CardContent>
          </Card>
          <Card className="apple-card border-none shadow-sm">
            <CardContent className="p-6">
              <p className="text-sm font-medium text-gray-500 mb-1">状态</p>
              <h3 className="text-2xl font-bold text-gray-900">在线</h3>
            </CardContent>
          </Card>
        </div>

        <div className="mb-6 rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-700 flex flex-wrap items-center gap-3">
          <span className="text-gray-500">当前知识库</span>
          <Badge variant="outline" className="font-mono">
            {selectedKb || '未选择'}
          </Badge>
          <span className="text-gray-400">|</span>
          <span>文档数：{documents.length}</span>
        </div>

        <Card className="apple-card border-none shadow-sm">
          <CardHeader className="border-b border-gray-100 flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-xl">我的知识库列表</CardTitle>
              <CardDescription>管理已创建的 GraphRAG 集合与混合检索引擎</CardDescription>
            </div>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="搜索库名或 ID..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-9 pl-9 pr-4 text-sm rounded-full border border-gray-200 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-green-500 w-[200px] md:w-[300px]"
              />
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="text-xs text-gray-500 bg-gray-50 border-b border-gray-100 uppercase">
                  <tr>
                    <th className="px-6 py-4 font-medium">知识库名称 & ID</th>
                    <th className="px-6 py-4 font-medium">状态</th>
                    <th className="px-6 py-4 font-medium">向量配置</th>
                    <th className="px-6 py-4 font-medium">维度</th>
                    <th className="px-6 py-4 font-medium">创建时间</th>
                    <th className="px-6 py-4 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredBases.map((kb) => (
                    <tr key={kb.id} className="bg-white border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded bg-green-50 text-green-600 flex items-center justify-center shrink-0">
                            <Database className="w-4 h-4" />
                          </div>
                          <div>
                            <p className="font-semibold text-gray-900">{kb.name}</p>
                            <p className="text-xs text-gray-400 font-mono mt-0.5">{kb.id}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <Badge variant="outline" className="text-green-600 border-green-200 bg-green-50/50">已就绪</Badge>
                      </td>
                      <td className="px-6 py-4 text-gray-600 font-medium">
                        {(kb.embedding_provider || 'auto') + ' / ' + kb.embedding_model}
                      </td>
                      <td className="px-6 py-4 text-gray-500">{kb.dimension}</td>
                      <td className="px-6 py-4 text-gray-500 text-xs">{new Date(kb.created_at).toLocaleString('zh-CN')}</td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button variant="ghost" size="sm" className="h-8 px-2 text-gray-500 hover:text-green-600" onClick={() => setSelectedKb(kb.id)}>
                            <Upload className="w-4 h-4 mr-1.5" /> 选择
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 px-2 text-gray-400 hover:text-red-600"
                            onClick={() => void removeBase(kb.id)}
                          >
                            <Trash2 className="w-4 h-4 mr-1.5" /> 删除
                          </Button>
                          <Button variant="ghost" size="icon" className="h-8 w-8 text-gray-400">
                            <MoreHorizontal className="w-4 h-4" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* ═══ File Upload Section ═══ */}
        <div className="mt-8">
          <Card className="apple-card border-none shadow-sm bg-gradient-to-br from-white to-blue-50/30">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <Upload className="w-5 h-5 text-blue-600" />
                文档上传入库
              </CardTitle>
              <CardDescription>拖拽或选择文件上传到知识库，支持 PDF、TXT、MD、DOCX、HTML、SRT 格式</CardDescription>
            </CardHeader>
            <CardContent>
              {!selectedKb ? (
                <div className="text-sm text-gray-500">请先在上方列表选择一个知识库。</div>
              ) : (
                <div className="space-y-4">
                  {/* Drop Zone */}
                  <div
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={handleFileDrop}
                    onClick={() => fileInputRef.current?.click()}
                    className="border-2 border-dashed border-gray-200 hover:border-blue-400 rounded-xl p-8 text-center cursor-pointer transition-colors bg-gray-50/50 hover:bg-blue-50/30"
                  >
                    <Upload className="w-8 h-8 text-gray-400 mx-auto mb-3" />
                    <p className="text-sm text-gray-600 font-medium">点击选择文件或拖拽到此处</p>
                    <p className="text-xs text-gray-400 mt-1">支持 PDF、TXT、MD、DOCX、HTML、SRT（单文件最大 50MB）</p>
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      accept=".pdf,.txt,.md,.docx,.html,.htm,.srt"
                      onChange={handleFileSelect}
                      className="hidden"
                    />
                  </div>

                  {/* File List */}
                  {uploadFiles.length > 0 && (
                    <div className="space-y-2">
                      <div className="text-xs font-medium text-gray-500">待上传文件 ({uploadFiles.length})</div>
                      {uploadFiles.map((f, i) => (
                        <div key={i} className="flex items-center justify-between bg-white rounded-lg border border-gray-100 px-3 py-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <File className="w-4 h-4 text-blue-500 shrink-0" />
                            <span className="text-sm text-gray-700 truncate">{f.name}</span>
                            <span className="text-xs text-gray-400 shrink-0">({(f.size / 1024).toFixed(0)} KB)</span>
                          </div>
                          <button onClick={() => removeUploadFile(i)} className="text-gray-400 hover:text-red-500 transition-colors shrink-0 ml-2">
                            <X className="w-4 h-4" />
                          </button>
                        </div>
                      ))}
                      <div className="flex justify-end">
                        <Button
                          className="bg-blue-600 hover:bg-blue-700 text-white shadow-md"
                          onClick={() => void submitFileUpload()}
                          disabled={uploading}
                        >
                          {uploading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Upload className="w-4 h-4 mr-2" />}
                          {uploading ? '上传中...' : `上传 ${uploadFiles.length} 个文件`}
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* Upload Results */}
                  {uploadResults.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-gray-500">上传结果</div>
                      {uploadResults.map((r, i) => (
                        <div key={i} className={`flex items-center gap-2 text-sm px-3 py-2 rounded-lg ${r.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                          {r.ok ? <CheckCircle className="w-4 h-4 shrink-0" /> : <X className="w-4 h-4 shrink-0" />}
                          <span className="font-medium truncate">{r.name}</span>
                          <span className="text-xs opacity-70 shrink-0">{r.msg}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="mt-8">
          <Card className="apple-card border-none shadow-sm bg-gradient-to-br from-white to-green-50/30">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <FileText className="w-5 h-5 text-green-600" />
                快速测试入库 (Debug Ingestion)
              </CardTitle>
              <CardDescription>直接粘贴文本内容验证 Embedding 与检索管道（自动使用当前知识库保存的向量配置）</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-gray-600">目标知识库</label>
                    <select
                      value={selectedKb}
                      onChange={(e) => setSelectedKb(e.target.value)}
                      className="w-full h-10 px-3 rounded-md border border-gray-200 bg-white text-sm focus:ring-2 focus:ring-green-500 outline-none"
                    >
                      {bases.map((kb) => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
                    </select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-gray-600">文档标题</label>
                    <input
                      type="text"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="例如: Omni-Vibe 架构设计.md"
                      className="w-full h-10 px-3 rounded-md border border-gray-200 bg-white text-sm focus:ring-2 focus:ring-green-500 outline-none"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-medium text-gray-600">纯文本内容 (Raw Text)</label>
                  <textarea
                    rows={4}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="粘贴测试文本进行自动切分 (Chunking) 和向量化 (Embedding)..."
                    className="w-full p-3 rounded-md border border-gray-200 bg-white text-sm focus:ring-2 focus:ring-green-500 outline-none resize-none"
                  />
                </div>
                <div className="flex justify-end">
                  <Button className="bg-gray-900 hover:bg-gray-800 text-white" onClick={() => void submitIngest()}>
                    提交异步处理 (Ingest)
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="mt-8">
          <Card className="apple-card border-none shadow-sm">
            <CardHeader className="border-b border-gray-100 flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-lg">文档管理</CardTitle>
                <CardDescription>按知识库查看已入库文档，可执行删除清理。</CardDescription>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  placeholder="搜索文档标题..."
                  value={docSearch}
                  onChange={(e) => setDocSearch(e.target.value)}
                  className="h-9 pl-9 pr-4 text-sm rounded-full border border-gray-200 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-green-500 w-[200px] md:w-[280px]"
                />
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {docError ? <div className="p-4 text-sm text-red-600">{docError}</div> : null}
              {!selectedKb ? (
                <div className="p-6 text-sm text-gray-500">请先在上方列表选择一个知识库。</div>
              ) : docLoading ? (
                <div className="p-6 text-sm text-gray-500">正在加载文档...</div>
              ) : documents.length === 0 ? (
                <div className="p-6 text-sm text-gray-500">该知识库暂无文档。</div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left">
                    <thead className="text-xs text-gray-500 bg-gray-50 border-b border-gray-100 uppercase">
                      <tr>
                        <th className="px-6 py-4 font-medium">标题</th>
                        <th className="px-6 py-4 font-medium">Chunk 数</th>
                        <th className="px-6 py-4 font-medium">来源</th>
                        <th className="px-6 py-4 font-medium">入库时间</th>
                        <th className="px-6 py-4 font-medium text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {documents.map((doc) => (
                        <React.Fragment key={doc.id}>
                          <tr className="bg-white border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
                            <td className="px-6 py-4">
                              <div className="flex items-center gap-2">
                                <button
                                  onClick={() => void toggleDocChunks(doc.id)}
                                  className="text-gray-400 hover:text-blue-500 transition-colors shrink-0"
                                  title="查看内容"
                                >
                                  {expandedDocId === doc.id ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                                </button>
                                <div className="min-w-0">
                                  <p className="font-medium text-gray-900">{doc.title}</p>
                                  <p className="text-xs text-gray-400 font-mono mt-0.5">{doc.id}</p>
                                </div>
                              </div>
                            </td>
                            <td className="px-6 py-4 text-gray-600">{doc.chunk_count}</td>
                            <td className="px-6 py-4 text-gray-500 truncate max-w-[240px]">{doc.source_url || '-'}</td>
                            <td className="px-6 py-4 text-gray-500 text-xs">{new Date(doc.created_at).toLocaleString('zh-CN')}</td>
                            <td className="px-6 py-4 text-right">
                              <div className="flex items-center justify-end gap-1">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 px-2 text-gray-400 hover:text-blue-600"
                                  onClick={() => void toggleDocChunks(doc.id)}
                                  title="查看内容"
                                >
                                  <Eye className="w-4 h-4 mr-1" /> 查看
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-8 px-2 text-gray-400 hover:text-red-600"
                                  onClick={() => void removeDocument(doc.id)}
                                >
                                  <Trash2 className="w-4 h-4 mr-1" /> 删除
                                </Button>
                              </div>
                            </td>
                          </tr>
                          {expandedDocId === doc.id && (
                            <tr className="bg-blue-50/30">
                              <td colSpan={5} className="px-6 py-4">
                                {chunksLoading ? (
                                  <div className="flex items-center gap-2 text-sm text-gray-400 py-4 justify-center">
                                    <Loader2 className="w-4 h-4 animate-spin" /> 加载文档内容...
                                  </div>
                                ) : docChunks.length === 0 ? (
                                  <div className="text-sm text-gray-400 text-center py-4">暂无 chunk 数据</div>
                                ) : (
                                  <div className="space-y-3 max-h-[500px] overflow-y-auto pr-2">
                                    <div className="text-xs font-medium text-gray-500 mb-2">
                                      共 {doc.chunk_count} 个文本块（显示前 {docChunks.length} 个）
                                    </div>
                                    {docChunks.map((chunk) => (
                                      <div key={chunk.id} className="bg-white rounded-lg border border-gray-100 p-3 shadow-sm">
                                        <div className="flex items-center gap-2 mb-2">
                                          <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-blue-50 text-blue-600 border-blue-200">
                                            #{chunk.chunk_index}
                                          </Badge>
                                          <span className="text-[10px] text-gray-400 font-mono">{chunk.id.slice(0, 8)}</span>
                                        </div>
                                        <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{chunk.content}</p>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </main>

      {/* ═══ Create KB Modal ═══ */}
      {showCreateModal && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowCreateModal(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 pt-6 pb-4">
              <h3 className="text-lg font-semibold text-gray-900">新建知识库</h3>
              <p className="text-sm text-gray-500 mt-1">创建一个新的向量检索空间，默认使用系统配置的 Embedding 模型，1536 维度</p>
            </div>
            <div className="px-6 space-y-4">
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-gray-700">知识库名称 <span className="text-red-500">*</span></label>
                <input
                  type="text"
                  value={newKbName}
                  onChange={(e) => setNewKbName(e.target.value)}
                  placeholder="例如：直播切片知识库"
                  className="w-full h-10 px-3 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-300"
                  autoFocus
                  onKeyDown={(e) => { if (e.key === 'Enter' && newKbName.trim()) void createBase() }}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium text-gray-700">描述 <span className="text-gray-400">(可选)</span></label>
                <textarea
                  value={newKbDesc}
                  onChange={(e) => setNewKbDesc(e.target.value)}
                  placeholder="用于存储直播切片分析报告，包含逐字稿、背景元素、贴片元素等结构化数据"
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-300 resize-none"
                />
              </div>
              <div className="bg-gray-50 rounded-lg p-3 space-y-1.5">
                <div className="text-xs font-medium text-gray-500">向量配置（自动）</div>
                <div className="flex items-center gap-4 text-sm">
                  <span className="text-gray-600">Embedding 模型：<span className="font-medium text-gray-800">系统默认</span></span>
                  <span className="text-gray-600">维度：<span className="font-medium text-gray-800">1536</span></span>
                </div>
                <p className="text-[11px] text-gray-400">自动使用模型配置中心已配置的 Embedding 模型（支持 OpenAI / Gemini）</p>
              </div>
            </div>
            <div className="px-6 py-4 mt-2 flex justify-end gap-3 border-t border-gray-100">
              <Button variant="outline" onClick={() => { setShowCreateModal(false); setNewKbName(''); setNewKbDesc('') }} className="rounded-lg">
                取消
              </Button>
              <Button
                className="bg-green-600 hover:bg-green-700 rounded-lg"
                onClick={() => void createBase()}
                disabled={creating || !newKbName.trim()}
              >
                {creating ? '创建中...' : '创建知识库'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
