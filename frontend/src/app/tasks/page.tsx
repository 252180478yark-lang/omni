'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import Link from 'next/link'
import { ListTodo, CheckCircle2, Clock, RotateCw, AlertCircle, PlayCircle, Loader2 } from 'lucide-react'

interface TaskItem {
  id: string
  kb_id: string
  title: string | null
  source_url: string | null
  status: string
  error: string | null
  document_id: string | null
  created_at: string
  updated_at: string
  progress: number
}

export default function TaskProgress() {
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const loadTasks = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/omni/knowledge/tasks?limit=100', { cache: 'no-store' })
      const json = (await res.json()) as { success: boolean; data?: TaskItem[]; error?: string }
      if (!json.success || !json.data) {
        throw new Error(json.error || '任务加载失败')
      }
      setTasks(json.data)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadTasks()
    const timer = window.setInterval(() => void loadTasks(), 5000)
    return () => window.clearInterval(timer)
  }, [loadTasks])

  const retryTask = useCallback(async (taskId: string) => {
    const res = await fetch(`/api/omni/knowledge/tasks/${taskId}/retry`, { method: 'POST' })
    const json = (await res.json()) as { success: boolean; error?: string }
    if (!json.success) {
      throw new Error(json.error || '重试失败')
    }
    await loadTasks()
  }, [loadTasks])

  const counts = useMemo(() => {
    const by = { queued: 0, running: 0, succeeded: 0, failed: 0 }
    for (const task of tasks) {
      if (task.status === 'queued') by.queued += 1
      else if (task.status === 'running') by.running += 1
      else if (task.status === 'succeeded') by.succeeded += 1
      else if (task.status === 'failed') by.failed += 1
    }
    return by
  }, [tasks])

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'succeeded': return <CheckCircle2 className="w-5 h-5 text-green-500" />
      case 'running': return <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />
      case 'queued': return <Clock className="w-5 h-5 text-gray-400" />
      case 'failed': return <AlertCircle className="w-5 h-5 text-red-500" />
      default: return <PlayCircle className="w-5 h-5 text-gray-500" />
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'succeeded': return <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200">已完成</Badge>
      case 'running': return <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200">处理中</Badge>
      case 'queued': return <Badge variant="outline" className="bg-gray-100 text-gray-600 border-gray-200">排队中</Badge>
      case 'failed': return <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200">失败</Badge>
      default: return null
    }
  }

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-4">
              <Link href="/knowledge" className="font-semibold text-lg text-gray-500 hover:text-gray-900 transition-colors">
                ← 返回知识库管理
              </Link>
            </div>
            <div className="font-semibold text-lg text-gray-900 flex items-center gap-2">
              <ListTodo className="w-5 h-5 text-blue-600" />
              异步任务队列监控
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 pt-10">
        <div className="mb-8 flex justify-between items-end">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-gray-900 mb-2">任务进度中心</h1>
            <p className="text-gray-500">监控文档切片、向量化与 GraphRAG 抽取的异步执行进度。</p>
          </div>
          <Button variant="outline" className="bg-white hover:bg-gray-50 border-gray-200 shadow-sm text-gray-700" onClick={() => void loadTasks()} disabled={loading}>
            <RotateCw className="w-4 h-4 mr-2" />
            刷新队列状态
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
          <Card className="apple-card border-none shadow-sm md:col-span-1 bg-white">
            <CardContent className="p-6 space-y-2 text-sm text-gray-700">
              <div className="flex justify-between"><span>排队中</span><span>{counts.queued}</span></div>
              <div className="flex justify-between"><span>运行中</span><span>{counts.running}</span></div>
              <div className="flex justify-between"><span>已成功</span><span>{counts.succeeded}</span></div>
              <div className="flex justify-between"><span>失败</span><span>{counts.failed}</span></div>
            </CardContent>
          </Card>

          <Card className="apple-card border-none shadow-sm md:col-span-3">
            <CardHeader className="border-b border-gray-100">
              <CardTitle className="text-lg">最近任务</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {error ? <div className="p-4 text-sm text-red-600">{error}</div> : null}
              <div className="divide-y divide-gray-100">
                {tasks.map((task) => (
                  <div key={task.id} className="p-4 md:p-6 hover:bg-gray-50/50 transition-colors">
                    <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                      <div className="flex items-start gap-4 flex-1">
                        <div className="mt-1 flex-shrink-0">{getStatusIcon(task.status)}</div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 mb-1">
                            <span className="text-sm font-semibold text-gray-900 truncate">{task.title || '(未命名文档)'}</span>
                            {getStatusBadge(task.status)}
                          </div>
                          <div className="flex items-center gap-3 text-xs text-gray-500">
                            <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded">{task.id}</span>
                            <span>•</span>
                            <span>知识库: {task.kb_id}</span>
                            <span>•</span>
                            <span>{new Date(task.updated_at).toLocaleString('zh-CN')}</span>
                          </div>
                          {task.error ? <div className="text-xs text-red-600 mt-2">{task.error}</div> : null}
                        </div>
                      </div>

                      <div className="w-full md:w-64 flex-shrink-0 flex flex-col gap-2">
                        <div className="flex justify-between items-center text-xs">
                          <span className={`truncate pr-2 ${task.status === 'failed' ? 'text-red-500' : 'text-gray-600'}`}>
                            {task.status}
                          </span>
                          <span className="font-mono font-medium text-gray-900">{task.progress}%</span>
                        </div>
                        <div className="w-full bg-gray-100 rounded-full h-2">
                          <div
                            className={`h-2 rounded-full transition-all duration-500 ${
                              task.status === 'failed' ? 'bg-red-500' :
                              task.status === 'succeeded' ? 'bg-green-500' :
                              task.status === 'running' ? 'bg-blue-500' : 'bg-gray-300'
                            }`}
                            style={{ width: `${task.progress}%` }}
                          />
                        </div>
                        {task.status === 'failed' ? (
                          <div className="flex justify-end mt-1">
                            <button
                              className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1"
                              onClick={() => void retryTask(task.id)}
                            >
                              <RotateCw className="w-3 h-3" /> 重试任务
                            </button>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  )
}
