'use client'

import React, { useCallback, useEffect, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'
import {
  Globe,
  Search,
  FileText,
  CheckCircle,
  Loader2,
  Database,
  ArrowLeft,
  Eye,
  ChevronDown,
  ChevronUp,
  Save,
  RefreshCw,
} from 'lucide-react'

interface Chapter {
  index: number
  title: string
  graph_path: string
  markdown: string
  text?: string
  word_count: number
  block_count: number
  source_url?: string
  error?: string
}

interface CrawlJob {
  status: string
  progress: number
  total?: number
  chapters: Chapter[]
  graph_name?: string
  total_articles?: number
  error?: string | null
}

interface KBItem {
  id: string
  name: string
  description: string
}

type Step = 'input' | 'crawling' | 'review' | 'saving' | 'done'

export default function HarvesterPage() {
  const [step, setStep] = useState<Step>('input')
  const [url, setUrl] = useState('')
  const [maxPages, setMaxPages] = useState<string>('')
  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<CrawlJob | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [bases, setBases] = useState<KBItem[]>([])
  const [selectedKb, setSelectedKb] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedTasks, setSavedTasks] = useState<string[]>([])

  useEffect(() => {
    fetch('/api/omni/knowledge/bases', { cache: 'no-store' })
      .then(r => r.json())
      .then(json => {
        if (json.success && json.data) {
          setBases(json.data)
          if (json.data.length > 0) setSelectedKb(json.data[0].id)
        }
      })
      .catch(() => {})
  }, [])

  const startCrawl = useCallback(async () => {
    if (!url.trim()) return
    setError('')
    setStep('crawling')
    setJob(null)
    try {
      const body: Record<string, unknown> = { url: url.trim() }
      if (maxPages) body.max_pages = parseInt(maxPages, 10)
      const res = await fetch('/api/omni/knowledge/harvester?action=crawl', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '启动爬取失败')
      setJobId(json.data.job_id)
    } catch (e) {
      setError(String(e))
      setStep('input')
    }
  }, [url, maxPages])

  useEffect(() => {
    if (step !== 'crawling' || !jobId) return
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/omni/knowledge/harvester?job_id=${jobId}`)
        const json = await res.json()
        if (json.success && json.data) {
          const j = json.data as CrawlJob
          setJob(j)
          if (j.status === 'done') {
            setStep('review')
            const allIdx = new Set(j.chapters.filter(c => c.word_count > 0).map(c => c.index))
            setSelected(allIdx)
            clearInterval(interval)
          } else if (j.status === 'failed') {
            setError(j.error || '爬取失败')
            setStep('input')
            clearInterval(interval)
          }
        }
      } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(interval)
  }, [step, jobId])

  const toggleSelect = (idx: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const toggleExpand = (idx: number) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const selectAll = () => {
    if (job) setSelected(new Set(job.chapters.filter(c => c.word_count > 0).map(c => c.index)))
  }

  const selectNone = () => setSelected(new Set())

  const saveSelected = useCallback(async () => {
    if (!selectedKb || selected.size === 0 || !job) return
    setSaving(true)
    setError('')
    try {
      const chapters = job.chapters
        .filter(c => selected.has(c.index) && c.markdown)
        .map(c => ({
          title: c.title,
          markdown: c.markdown,
          source_url: c.source_url || null,
        }))

      const res = await fetch('/api/omni/knowledge/harvester?action=save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kb_id: selectedKb, chapters }),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '保存失败')
      setSavedTasks(json.data.task_ids)
      setStep('done')
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }, [selectedKb, selected, job])

  const reset = () => {
    setStep('input')
    setUrl('')
    setMaxPages('')
    setJobId('')
    setJob(null)
    setError('')
    setSelected(new Set())
    setExpanded(new Set())
    setSavedTasks([])
  }

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-3">
              <Link href="/" className="text-xl font-bold bg-gradient-to-r from-gray-900 to-gray-600 bg-clip-text text-transparent">
                Omni-Vibe OS
              </Link>
              <span className="text-gray-300">/</span>
              <Link href="/knowledge" className="text-sm text-gray-500 hover:text-gray-900 flex items-center gap-1">
                <Database className="w-4 h-4" /> 知识库
              </Link>
              <span className="text-gray-300">/</span>
              <span className="text-sm font-medium text-gray-900 flex items-center gap-1">
                <Globe className="w-4 h-4" /> 知识采集
              </span>
            </div>
            <div className="flex items-center gap-4">
              <Link href="/knowledge">
                <Button variant="ghost" size="sm"><ArrowLeft className="w-4 h-4 mr-1" /> 返回知识库</Button>
              </Link>
              <Link href="/tasks">
                <Button variant="outline" size="sm">任务进度</Button>
              </Link>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">{error}</div>
        )}

        {/* Step 1: Input */}
        {step === 'input' && (
          <Card className="apple-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Globe className="w-5 h-5 text-blue-500" /> 知识采集器</CardTitle>
              <CardDescription>输入帮助中心 URL，系统将自动爬取内容并分章节呈现，供你审核后保存到知识库</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">帮助中心 URL</label>
                <input
                  type="url"
                  value={url}
                  onChange={e => setUrl(e.target.value)}
                  placeholder="https://yuntu.oceanengine.com/support/content/root?graphId=..."
                  className="w-full px-4 py-3 rounded-xl border border-gray-200 bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition"
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-700 mb-1 block">最大页数（可选）</label>
                <input
                  type="number"
                  value={maxPages}
                  onChange={e => setMaxPages(e.target.value)}
                  placeholder="留空则爬取全部"
                  min={1}
                  max={200}
                  className="w-48 px-4 py-3 rounded-xl border border-gray-200 bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition"
                />
              </div>
              <Button onClick={startCrawl} disabled={!url.trim()} size="lg" className="mt-2">
                <Search className="w-4 h-4 mr-2" /> 开始爬取
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Step 2: Crawling */}
        {step === 'crawling' && (
          <Card className="apple-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Loader2 className="w-5 h-5 animate-spin text-blue-500" /> 正在爬取...</CardTitle>
              <CardDescription>
                {job ? `${job.status} — ${job.progress}/${job.total || '?'} 页` : '正在启动浏览器...'}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {job && job.total && (
                <div className="w-full bg-gray-100 rounded-full h-3 overflow-hidden">
                  <div
                    className="bg-blue-500 h-full rounded-full transition-all duration-500"
                    style={{ width: `${Math.round((job.progress / job.total) * 100)}%` }}
                  />
                </div>
              )}
              {job?.chapters && job.chapters.length > 0 && (
                <div className="mt-4 space-y-1">
                  {job.chapters.map(ch => (
                    <div key={ch.index} className="flex items-center gap-2 text-sm text-gray-600">
                      <CheckCircle className="w-4 h-4 text-green-500" />
                      <span>{ch.title}</span>
                      <Badge variant="secondary">{ch.word_count}字</Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Step 3: Review */}
        {step === 'review' && job && (
          <>
            <Card className="apple-card mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><Eye className="w-5 h-5 text-green-500" /> 审核爬取结果</CardTitle>
                <CardDescription>
                  {job.graph_name && <Badge variant="outline" className="mr-2">{job.graph_name}</Badge>}
                  共 {job.chapters.length} 篇文章，
                  {job.chapters.reduce((s, c) => s + c.word_count, 0).toLocaleString()} 字
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-3 mb-4">
                  <Button variant="outline" size="sm" onClick={selectAll}>全选</Button>
                  <Button variant="outline" size="sm" onClick={selectNone}>取消全选</Button>
                  <span className="text-sm text-gray-500">已选 {selected.size}/{job.chapters.length}</span>
                  <div className="ml-auto flex items-center gap-2">
                    <select
                      value={selectedKb}
                      onChange={e => setSelectedKb(e.target.value)}
                      className="px-3 py-2 rounded-lg border border-gray-200 bg-white text-sm"
                    >
                      {bases.map(kb => (
                        <option key={kb.id} value={kb.id}>{kb.name}</option>
                      ))}
                    </select>
                    <Button onClick={saveSelected} disabled={saving || selected.size === 0 || !selectedKb}>
                      {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Save className="w-4 h-4 mr-1" />}
                      保存到知识库 ({selected.size})
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="space-y-3">
              {job.chapters.map(ch => (
                <Card key={ch.index} className={`apple-card transition-all ${selected.has(ch.index) ? 'ring-2 ring-blue-400' : ''}`}>
                  <div
                    className="flex items-center gap-3 px-6 py-4 cursor-pointer"
                    onClick={() => toggleSelect(ch.index)}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(ch.index)}
                      onChange={() => toggleSelect(ch.index)}
                      className="w-5 h-5 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
                      onClick={e => e.stopPropagation()}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-gray-900 truncate">{ch.title}</div>
                      <div className="text-xs text-gray-500 mt-0.5">{ch.graph_path}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {ch.error ? (
                        <Badge variant="destructive">失败</Badge>
                      ) : (
                        <>
                          <Badge variant="secondary">{ch.word_count.toLocaleString()}字</Badge>
                          <Badge variant="outline">{ch.block_count}块</Badge>
                        </>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={e => { e.stopPropagation(); toggleExpand(ch.index) }}
                      >
                        {expanded.has(ch.index) ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </Button>
                    </div>
                  </div>
                  {expanded.has(ch.index) && (
                    <CardContent className="pt-0 border-t border-gray-100">
                      <div className="bg-gray-50 rounded-lg p-4 max-h-96 overflow-y-auto">
                        <pre className="whitespace-pre-wrap text-sm text-gray-700 font-mono leading-relaxed">
                          {ch.markdown || ch.text || '(无内容)'}
                        </pre>
                      </div>
                    </CardContent>
                  )}
                </Card>
              ))}
            </div>
          </>
        )}

        {/* Step 4: Done */}
        {step === 'done' && (
          <Card className="apple-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><CheckCircle className="w-5 h-5 text-green-500" /> 保存完成</CardTitle>
              <CardDescription>
                已提交 {savedTasks.length} 篇文章到知识库，正在后台向量化处理中
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {savedTasks.length > 0 && (
                <div className="text-sm text-gray-500">
                  任务ID: {savedTasks.map(t => t.slice(0, 8)).join(', ')}
                </div>
              )}
              <div className="flex gap-3 mt-4">
                <Link href="/tasks">
                  <Button variant="default"><FileText className="w-4 h-4 mr-1" /> 查看入库进度</Button>
                </Link>
                <Button variant="outline" onClick={reset}><RefreshCw className="w-4 h-4 mr-1" /> 继续采集</Button>
                <Link href="/knowledge">
                  <Button variant="ghost"><Database className="w-4 h-4 mr-1" /> 返回知识库</Button>
                </Link>
              </div>
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  )
}
