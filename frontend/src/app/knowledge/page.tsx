'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'
import { Database, Plus, Search, FileText, Upload, MoreHorizontal } from 'lucide-react'

interface KnowledgeBaseItem {
  id: string
  name: string
  description: string
  embedding_model: string
  dimension: number
  created_at: string
}

export default function KnowledgeBaseConfig() {
  const [bases, setBases] = useState<KnowledgeBaseItem[]>([])
  const [search, setSearch] = useState('')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [selectedKb, setSelectedKb] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

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

  const createBase = useCallback(async () => {
    const name = window.prompt('请输入知识库名称')
    if (!name) return
    const res = await fetch('/api/omni/knowledge/bases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description: '' }),
    })
    const json = (await res.json()) as { success: boolean; error?: string }
    if (!json.success) {
      throw new Error(json.error || '创建失败')
    }
    await loadBases()
  }, [loadBases])

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
            <p className="text-gray-500">创建与管理向量检索空间、上传私有文档并构建知识图谱。</p>
          </div>
          <Button className="bg-green-600 hover:bg-green-700 shadow-md" onClick={() => void createBase()} disabled={loading}>
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
                    <th className="px-6 py-4 font-medium">向量模型</th>
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
                      <td className="px-6 py-4 text-gray-600 font-medium">{kb.embedding_model}</td>
                      <td className="px-6 py-4 text-gray-500">{kb.dimension}</td>
                      <td className="px-6 py-4 text-gray-500 text-xs">{new Date(kb.created_at).toLocaleString('zh-CN')}</td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <Button variant="ghost" size="sm" className="h-8 px-2 text-gray-500 hover:text-green-600" onClick={() => setSelectedKb(kb.id)}>
                            <Upload className="w-4 h-4 mr-1.5" /> 选择
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

        <div className="mt-8">
          <Card className="apple-card border-none shadow-sm bg-gradient-to-br from-white to-green-50/30">
            <CardHeader>
              <CardTitle className="text-lg flex items-center gap-2">
                <FileText className="w-5 h-5 text-green-600" />
                快速测试入库 (Debug Ingestion)
              </CardTitle>
              <CardDescription>直接粘贴文本内容验证 Embedding 与检索管道 (生成 202 异步任务)</CardDescription>
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
      </main>
    </div>
  )
}
