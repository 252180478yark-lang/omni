'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  BrainCircuit,
  Send,
  StopCircle,
  Trash2,
  Database,
  ExternalLink,
  ChevronDown,
  Sparkles,
  ArrowLeft,
  Image as ImageIcon,
  Video,
  FileSearch,
  MessageSquare,
  Search,
  Loader2,
  Eye,
  X,
  Check,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  useChatStore,
  type OutputMode,
  type SourceRef,
  type ImageResult,
  type VideoResult,
} from '@/stores/chatStore'

interface KBItem {
  id: string
  name: string
  description: string
  embedding_provider?: string
  embedding_model?: string
  dimension?: number
}

interface ProviderItem {
  id: string
  name: string
  models: string[]
  defaultChatModel: string | null
  apiKeySet?: boolean
}

interface ChunkPreview {
  id: string
  chunk_index: number
  content: string
}

const OUTPUT_MODES: { id: OutputMode; label: string; icon: React.ReactNode; desc: string }[] = [
  { id: 'text', label: '文本回答', icon: <MessageSquare className="w-3.5 h-3.5" />, desc: 'RAG 知识问答' },
  { id: 'image', label: '生成图片', icon: <ImageIcon className="w-3.5 h-3.5" />, desc: 'DALL·E / SD' },
  { id: 'video', label: '生成视频', icon: <Video className="w-3.5 h-3.5" />, desc: 'Runway / 可灵' },
  { id: 'analyze', label: '综合分析', icon: <FileSearch className="w-3.5 h-3.5" />, desc: '多模态分析' },
]

/* ───── SSE streaming helper ───── */

async function streamRAG(
  kbId: string,
  query: string,
  sessionId: string,
  assistantId: string,
  appendToken: (id: string, token: string) => void,
  finishAssistant: (id: string, sources: SourceRef[]) => void,
  failAssistant: (id: string, error: string) => void,
  signal: AbortSignal,
  model?: string,
  provider?: string,
) {
  try {
    const payload: Record<string, unknown> = { kb_id: kbId, query, stream: true, top_k: 15, session_id: sessionId }
    if (model) payload.model = model
    if (provider) payload.provider = provider
    const res = await fetch('/api/omni/knowledge/rag', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
    if (!res.ok) {
      failAssistant(assistantId, `服务器错误: ${res.status}`)
      return
    }
    if (!res.body) {
      failAssistant(assistantId, '响应流为空')
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let sources: SourceRef[] = []

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data:')) continue
        const payload = trimmed.slice(5).trim()
        if (payload === '[DONE]') continue

        try {
          const obj = JSON.parse(payload)
          if (obj.type === 'text' && obj.content) {
            appendToken(assistantId, obj.content)
          } else if (obj.type === 'done') {
            sources = obj.sources || []
          }
        } catch {
          // skip
        }
      }
    }

    finishAssistant(assistantId, sources)
  } catch (err) {
    if ((err as Error).name === 'AbortError') {
      finishAssistant(assistantId, [])
    } else {
      failAssistant(assistantId, String(err))
    }
  }
}

async function generateImage(
  prompt: string,
  assistantId: string,
  finishImage: (id: string, images: ImageResult[]) => void,
  failAssistant: (id: string, error: string) => void,
) {
  try {
    const res = await fetch('/api/omni/ai/images', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, model: 'dall-e-3', size: '1024x1024', quality: 'standard', n: 1 }),
    })
    const json = await res.json()
    if (!json.success) {
      failAssistant(assistantId, json.error || '图片生成失败')
      return
    }
    finishImage(assistantId, json.data?.images || [])
  } catch (err) {
    failAssistant(assistantId, String(err))
  }
}

async function generateVideo(
  prompt: string,
  assistantId: string,
  finishVideo: (id: string, video: VideoResult) => void,
  failAssistant: (id: string, error: string) => void,
) {
  try {
    const res = await fetch('/api/omni/ai/videos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, duration: 4, aspect_ratio: '16:9' }),
    })
    const json = await res.json()
    if (!json.success) {
      failAssistant(assistantId, json.error || '视频生成失败')
      return
    }
    finishVideo(assistantId, json.data)
  } catch (err) {
    failAssistant(assistantId, String(err))
  }
}

async function analyzeContent(
  prompt: string,
  assistantId: string,
  appendToken: (id: string, token: string) => void,
  finishAssistant: (id: string, sources: SourceRef[]) => void,
  failAssistant: (id: string, error: string) => void,
) {
  try {
    const res = await fetch('/api/omni/ai/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'document', content: prompt, prompt: `请对以下内容进行深度分析：\n${prompt}` }),
    })
    const json = await res.json()
    if (!json.success) {
      failAssistant(assistantId, json.error || '分析失败')
      return
    }
    appendToken(assistantId, json.data?.analysis || '无分析结果')
    finishAssistant(assistantId, [])
  } catch (err) {
    failAssistant(assistantId, String(err))
  }
}

/* ───── Page Component ───── */

export default function ChatPage() {
  const {
    kbId, sessionId, outputMode, messages, streaming,
    setKbId, setOutputMode,
    addUserMessage, startAssistant, appendToken,
    finishAssistant, finishAssistantImage, finishAssistantVideo,
    failAssistant, setStreaming, setAbort, abortController, clearMessages,
  } = useChatStore()

  const [allBases, setAllBases] = useState<KBItem[]>([])
  const [providers, setProviders] = useState<ProviderItem[]>([])
  const [selectedProvider, setSelectedProvider] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const [input, setInput] = useState('')
  const [kbOpen, setKbOpen] = useState(false)
  const [modelOpen, setModelOpen] = useState(false)
  const [kbSearch, setKbSearch] = useState('')
  const [loadingData, setLoadingData] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const kbSearchRef = useRef<HTMLInputElement>(null)

  const [previewKbId, setPreviewKbId] = useState('')
  const [previewChunks, setPreviewChunks] = useState<ChunkPreview[]>([])
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewDocCount, setPreviewDocCount] = useState(0)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoadingData(true)
      try {
        const [kbRes, pRes] = await Promise.all([
          fetch('/api/omni/knowledge/bases', { cache: 'no-store' }),
          fetch('/api/omni/models', { cache: 'no-store' }),
        ])
        const kbJson = await kbRes.json()
        if (!cancelled && kbJson.success && kbJson.data) {
          setAllBases(kbJson.data)
          if (!kbId && kbJson.data.length > 0) setKbId(kbJson.data[0].id)
        }
        const pJson = await pRes.json()
        if (!cancelled && pJson.success && pJson.data?.providers) {
          const chatProviders = (pJson.data.providers as ProviderItem[]).filter(
            (p) => p.apiKeySet && p.models.length > 0,
          )
          setProviders(chatProviders)
          if (chatProviders.length > 0 && !selectedProvider) {
            setSelectedProvider(chatProviders[0].id)
            setSelectedModel(chatProviders[0].defaultChatModel || chatProviders[0].models[0] || '')
          }
        }
      } catch { /* ignore */ }
      finally { if (!cancelled) setLoadingData(false) }
    })()
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  useEffect(() => {
    if (kbOpen) kbSearchRef.current?.focus()
  }, [kbOpen])

  const loadKbPreview = useCallback(async (id: string) => {
    if (previewKbId === id) { setPreviewKbId(''); return }
    setPreviewKbId(id)
    setPreviewLoading(true)
    setPreviewChunks([])
    setPreviewDocCount(0)
    try {
      const docRes = await fetch(`/api/omni/knowledge/documents?kb_id=${id}&limit=5`, { cache: 'no-store' })
      const docJson = await docRes.json()
      const docs = (docJson.success && docJson.data) ? docJson.data : []
      setPreviewDocCount(docs.length)
      if (docs.length > 0) {
        const firstDoc = docs[0]
        const chunkRes = await fetch(`/api/omni/knowledge/documents/${firstDoc.id}/chunks?limit=3`, { cache: 'no-store' })
        const chunkJson = await chunkRes.json()
        if (chunkJson.success && chunkJson.data) setPreviewChunks(chunkJson.data)
      }
    } catch { /* ignore */ }
    finally { setPreviewLoading(false) }
  }, [previewKbId])

  const filteredBases = allBases.filter((kb) => {
    if (!kbSearch.trim()) return true
    const q = kbSearch.toLowerCase()
    return kb.name.toLowerCase().includes(q) || kb.id.toLowerCase().includes(q) || (kb.description || '').toLowerCase().includes(q)
  })

  const handleSend = useCallback(async () => {
    const q = input.trim()
    if (!q || streaming) return
    if (outputMode === 'text' && !kbId) return

    setInput('')
    const currentMode = outputMode
    addUserMessage(q, currentMode)
    const aId = `ast-${Date.now()}`
    startAssistant(aId, currentMode)
    setStreaming(true)

    if (currentMode === 'text') {
      const ctrl = new AbortController()
      setAbort(ctrl)
      await streamRAG(kbId, q, sessionId, aId, appendToken, finishAssistant, failAssistant, ctrl.signal, selectedModel || undefined, selectedProvider || undefined)
    } else if (currentMode === 'image') {
      await generateImage(q, aId, finishAssistantImage, failAssistant)
    } else if (currentMode === 'video') {
      await generateVideo(q, aId, finishAssistantVideo, failAssistant)
    } else if (currentMode === 'analyze') {
      await analyzeContent(q, aId, appendToken, finishAssistant, failAssistant)
    }

    setStreaming(false)
    setAbort(null)
    inputRef.current?.focus()
  }, [
    input, kbId, sessionId, outputMode, streaming, selectedModel, selectedProvider,
    addUserMessage, startAssistant, appendToken,
    finishAssistant, finishAssistantImage, finishAssistantVideo,
    failAssistant, setStreaming, setAbort,
  ])

  const handleStop = useCallback(() => {
    abortController?.abort()
    setStreaming(false)
    setAbort(null)
  }, [abortController, setStreaming, setAbort])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSend()
    }
  }

  const selectedKb = allBases.find((b) => b.id === kbId)
  const modelLabel = selectedModel || '选择模型'

  return (
    <div className="min-h-screen bg-[#F5F5F7] flex flex-col">
      {/* Header */}
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="text-gray-500 hover:text-gray-900 transition-colors">
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-blue-600 to-purple-500 flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-white" />
              </div>
              <span className="font-semibold tracking-tight">智能问答</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Model Selector */}
            <div className="relative">
              <button
                onClick={() => { setModelOpen((v) => !v); setKbOpen(false) }}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-full border border-gray-200 bg-white/80 hover:bg-white transition-colors shadow-sm"
              >
                <BrainCircuit className="w-3.5 h-3.5 text-purple-500" />
                <span className="max-w-[140px] truncate">{loadingData ? '加载中...' : modelLabel}</span>
                <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
              </button>
              {modelOpen && (
                <div className="absolute right-0 top-full mt-1 w-80 bg-white rounded-xl shadow-xl border border-gray-100 py-1 z-50 max-h-96 overflow-auto">
                  {loadingData && (
                    <div className="px-3 py-6 text-sm text-gray-400 text-center flex items-center justify-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin" /> 正在加载模型列表...
                    </div>
                  )}
                  {!loadingData && providers.length === 0 && (
                    <div className="px-3 py-4 text-sm text-gray-400 text-center">
                      暂无可用模型，请先在<Link href="/models" className="text-blue-500 underline ml-1">模型配置</Link>中设置 API Key
                    </div>
                  )}
                  {providers.map((prov) => (
                    <div key={prov.id}>
                      <div className="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wider text-gray-400 font-semibold flex items-center gap-2">
                        {prov.name}
                        <Badge variant="outline" className="text-[9px] px-1 py-0">{prov.models.length} 个</Badge>
                      </div>
                      {prov.models.filter((m) => !m.includes('embedding')).map((m) => (
                        <button
                          key={`${prov.id}/${m}`}
                          onClick={() => { setSelectedProvider(prov.id); setSelectedModel(m); setModelOpen(false) }}
                          className={`w-full text-left px-3 py-1.5 text-sm hover:bg-purple-50 transition-colors flex items-center justify-between ${
                            selectedProvider === prov.id && selectedModel === m
                              ? 'bg-purple-50 text-purple-700 font-medium' : 'text-gray-700'
                          }`}
                        >
                          <span className="truncate">{m}</span>
                          {selectedProvider === prov.id && selectedModel === m && <Check className="w-3.5 h-3.5 text-purple-600 shrink-0" />}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>
            {/* KB Selector */}
            <div className="relative">
              <button
                onClick={() => { setKbOpen((v) => !v); setModelOpen(false); setPreviewKbId('') }}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-full border border-gray-200 bg-white/80 hover:bg-white transition-colors shadow-sm"
              >
                <Database className="w-3.5 h-3.5 text-gray-500" />
                <span className="max-w-[120px] truncate">{loadingData ? '加载中...' : (selectedKb?.name || '选择知识库')}</span>
                <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
              </button>
              {kbOpen && (
                <div className="absolute right-0 top-full mt-1 w-80 bg-white rounded-xl shadow-xl border border-gray-100 z-50 overflow-hidden">
                  {/* Search */}
                  <div className="p-2 border-b border-gray-100">
                    <div className="relative">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                      <input
                        ref={kbSearchRef}
                        type="text"
                        value={kbSearch}
                        onChange={(e) => setKbSearch(e.target.value)}
                        placeholder="搜索知识库名称..."
                        className="w-full h-8 pl-8 pr-8 text-sm rounded-lg border border-gray-200 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                      />
                      {kbSearch && (
                        <button onClick={() => setKbSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                          <X className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                  {/* KB List */}
                  <div className="max-h-72 overflow-auto">
                    {loadingData && (
                      <div className="px-3 py-6 text-sm text-gray-400 text-center flex items-center justify-center gap-2">
                        <Loader2 className="w-4 h-4 animate-spin" /> 加载知识库列表...
                      </div>
                    )}
                    {!loadingData && filteredBases.length === 0 && (
                      <div className="px-3 py-4 text-sm text-gray-400 text-center">
                        {kbSearch ? '无匹配结果' : '暂无知识库'}
                      </div>
                    )}
                    {filteredBases.map((kb) => (
                      <div key={kb.id} className="border-b border-gray-50 last:border-0">
                        <div className={`flex items-center gap-2 px-3 py-2 hover:bg-blue-50 transition-colors ${kb.id === kbId ? 'bg-blue-50' : ''}`}>
                          <button
                            onClick={() => { setKbId(kb.id); setKbOpen(false); setKbSearch('') }}
                            className="flex-1 text-left min-w-0"
                          >
                            <div className="flex items-center gap-2">
                              <div className="font-medium text-sm truncate text-gray-900">{kb.name}</div>
                              {kb.id === kbId && <Check className="w-3.5 h-3.5 text-blue-600 shrink-0" />}
                            </div>
                            {kb.description && <div className="text-xs text-gray-400 truncate mt-0.5">{kb.description}</div>}
                            <div className="text-[10px] text-gray-400 mt-0.5">
                              {kb.embedding_provider}/{kb.embedding_model} · {kb.dimension}维
                            </div>
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); void loadKbPreview(kb.id) }}
                            className={`shrink-0 p-1.5 rounded-md transition-colors ${previewKbId === kb.id ? 'bg-blue-100 text-blue-600' : 'text-gray-400 hover:text-blue-500 hover:bg-blue-50'}`}
                            title="预览知识库内容"
                          >
                            <Eye className="w-3.5 h-3.5" />
                          </button>
                        </div>
                        {/* KB Preview */}
                        {previewKbId === kb.id && (
                          <div className="px-3 pb-3 bg-gray-50/80">
                            {previewLoading ? (
                              <div className="text-xs text-gray-400 py-3 text-center flex items-center justify-center gap-1">
                                <Loader2 className="w-3 h-3 animate-spin" /> 加载预览...
                              </div>
                            ) : previewDocCount === 0 ? (
                              <div className="text-xs text-gray-400 py-2 text-center">该知识库暂无文档</div>
                            ) : (
                              <div className="space-y-2">
                                <div className="text-[10px] text-gray-500 font-medium">文档数: {previewDocCount} · 内容预览:</div>
                                {previewChunks.map((c) => (
                                  <div key={c.id} className="bg-white rounded-md border border-gray-100 p-2 text-xs text-gray-600 line-clamp-3">
                                    <Badge variant="outline" className="text-[9px] px-1 py-0 mb-1 bg-blue-50 text-blue-500 border-blue-200">#{c.chunk_index}</Badge>
                                    <p className="leading-relaxed">{c.content.slice(0, 200)}{c.content.length > 200 ? '...' : ''}</p>
                                  </div>
                                ))}
                                {previewChunks.length === 0 && previewDocCount > 0 && (
                                  <div className="text-[10px] text-gray-400">文档处理中，暂无 chunk 数据</div>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                  {/* Footer */}
                  <div className="p-2 border-t border-gray-100 bg-gray-50/50">
                    <Link href="/knowledge" className="text-xs text-blue-500 hover:text-blue-700 flex items-center gap-1">
                      <Database className="w-3 h-3" /> 管理知识库
                      <ExternalLink className="w-3 h-3 ml-auto" />
                    </Link>
                  </div>
                </div>
              )}
            </div>
            <Button variant="ghost" size="sm" onClick={() => { clearMessages(); inputRef.current?.focus() }} className="rounded-full" title="清空对话">
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </nav>

      {/* Messages Area */}
      <div ref={scrollRef} className="flex-1 overflow-auto chat-scroll px-4 py-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-blue-500 to-purple-500 flex items-center justify-center shadow-lg mb-6">
                <BrainCircuit className="w-8 h-8 text-white" />
              </div>
              <h2 className="text-xl font-semibold text-gray-800 mb-2">智能问答</h2>
              <p className="text-gray-500 text-sm max-w-md">
                基于 RAG 技术，从知识库中检索相关内容并生成精准回答。
                <br />支持文本、图片、视频多模态输出。选择知识库后输入问题即可开始。
              </p>
              <div className="flex gap-3 mt-6">
                {OUTPUT_MODES.map((m) => (
                  <div key={m.id} className="flex flex-col items-center gap-1 px-4 py-3 rounded-xl bg-white/80 border border-gray-100 shadow-sm">
                    <div className="text-gray-500">{m.icon}</div>
                    <span className="text-xs font-medium text-gray-700">{m.label}</span>
                    <span className="text-[10px] text-gray-400">{m.desc}</span>
                  </div>
                ))}
              </div>
              {loadingData && (
                <div className="flex items-center gap-2 mt-8 text-sm text-gray-400">
                  <Loader2 className="w-4 h-4 animate-spin" /> 正在加载模型与知识库...
                </div>
              )}
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                  msg.role === 'user'
                    ? 'bg-gradient-to-r from-blue-600 to-purple-500 text-white shadow-md'
                    : 'bg-white shadow-sm border border-gray-100'
                }`}
              >
                {msg.role === 'user' && msg.outputMode && msg.outputMode !== 'text' && (
                  <div className="mb-1.5">
                    <Badge variant="secondary" className="text-[10px] bg-white/20 text-white border-0">
                      {OUTPUT_MODES.find((m) => m.id === msg.outputMode)?.label}
                    </Badge>
                  </div>
                )}

                {msg.role === 'assistant' && msg.loading && !msg.content && !msg.images && !msg.video && (
                  <div className="flex items-center gap-2 text-gray-400 text-sm">
                    <div className="flex gap-0.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:0ms]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:150ms]" />
                      <span className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:300ms]" />
                    </div>
                    {msg.outputMode === 'image' ? '正在生成图片...' :
                     msg.outputMode === 'video' ? '正在生成视频...' :
                     msg.outputMode === 'analyze' ? '正在分析...' : '正在思考...'}
                  </div>
                )}

                {msg.role === 'user' ? (
                  <div className="markdown-body text-sm whitespace-pre-wrap !text-white">
                    {msg.content}
                  </div>
                ) : (
                  <div className="markdown-body text-sm prose prose-sm max-w-none prose-table:text-sm prose-th:bg-gray-100 prose-th:px-3 prose-th:py-1.5 prose-td:px-3 prose-td:py-1.5 prose-table:border prose-th:border prose-td:border">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {msg.content}
                    </ReactMarkdown>
                    {msg.loading && msg.content && (
                      <span className="cursor-blink">▊</span>
                    )}
                  </div>
                )}

                {msg.images && msg.images.length > 0 && (
                  <div className="mt-3 grid gap-2">
                    {msg.images.map((img, i) => (
                      <div key={i} className="rounded-lg overflow-hidden border border-gray-100">
                        <a href={img.url} target="_blank" rel="noopener noreferrer">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={img.url} alt={img.revised_prompt || 'Generated'} className="w-full max-w-md rounded-lg" />
                        </a>
                        {img.revised_prompt && (
                          <p className="text-xs text-gray-400 mt-1 px-2 pb-2 line-clamp-2">{img.revised_prompt}</p>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {msg.video && (
                  <div className="mt-3 rounded-lg border border-gray-100 p-3 bg-gray-50/50">
                    <div className="flex items-center gap-2 mb-2">
                      <Video className="w-4 h-4 text-purple-500" />
                      <span className="text-sm font-medium text-gray-700">视频任务</span>
                      <Badge variant="outline" className={
                        msg.video.status === 'completed' ? 'text-green-600 border-green-200 bg-green-50' :
                        msg.video.status === 'processing' ? 'text-yellow-600 border-yellow-200 bg-yellow-50' :
                        'text-gray-500'
                      }>
                        {msg.video.status}
                      </Badge>
                    </div>
                    {msg.video.video_url && (
                      <video src={msg.video.video_url} controls className="w-full max-w-md rounded-lg" />
                    )}
                    <p className="text-xs text-gray-400 mt-1">Task ID: {msg.video.task_id}</p>
                  </div>
                )}

                {msg.sources && msg.sources.length > 0 && (
                  <div className="mt-3 pt-2 border-t border-gray-100">
                    <div className="text-xs font-medium text-gray-400 mb-1.5">📚 引用来源</div>
                    <div className="space-y-1.5">
                      {msg.sources.map((src) => (
                        <SourceCard key={src.chunk_id} source={src} />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Input Area */}
      <div className="sticky bottom-0 glass border-t border-gray-200/50">
        <div className="max-w-3xl mx-auto px-4 py-3">
          <div className="flex items-center gap-1.5 mb-2">
            {OUTPUT_MODES.map((m) => (
              <button
                key={m.id}
                onClick={() => setOutputMode(m.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full transition-all ${
                  outputMode === m.id
                    ? 'bg-gradient-to-r from-blue-600 to-purple-500 text-white shadow-md'
                    : 'bg-white/80 text-gray-500 border border-gray-200 hover:bg-gray-50'
                }`}
              >
                {m.icon}
                <span className="hidden sm:inline">{m.label}</span>
              </button>
            ))}
          </div>

          <div className="flex items-end gap-2">
            <div className="flex-1 relative">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  outputMode === 'text' ? (kbId ? '输入问题，Enter 发送...' : '请先选择知识库') :
                  outputMode === 'image' ? '描述你想生成的图片...' :
                  outputMode === 'video' ? '描述你想生成的视频...' :
                  '输入要分析的内容...'
                }
                disabled={outputMode === 'text' && !kbId}
                rows={1}
                className="w-full resize-none rounded-xl border border-gray-200 bg-white/90 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-300 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ maxHeight: 120 }}
                onInput={(e) => {
                  const el = e.target as HTMLTextAreaElement
                  el.style.height = 'auto'
                  el.style.height = `${Math.min(el.scrollHeight, 120)}px`
                }}
              />
            </div>
            {streaming ? (
              <Button onClick={handleStop} className="rounded-xl bg-red-500 hover:bg-red-600 text-white shadow-md h-11 w-11 p-0">
                <StopCircle className="w-5 h-5" />
              </Button>
            ) : (
              <Button
                onClick={() => void handleSend()}
                disabled={!input.trim() || (outputMode === 'text' && !kbId)}
                className="rounded-xl bg-gradient-to-r from-blue-600 to-purple-500 hover:from-blue-700 hover:to-purple-600 text-white shadow-md h-11 w-11 p-0 disabled:opacity-50"
              >
                <Send className="w-5 h-5" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ───── Source Card ───── */

function SourceCard({ source }: { source: SourceRef }) {
  return (
    <Card className="p-2 bg-gray-50/80 border-gray-100 hover:bg-gray-100/80 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 bg-blue-50 text-blue-600 border-blue-200">
              #{source.index}
            </Badge>
            {source.title && (
              <span className="text-xs font-medium text-gray-700 truncate">{source.title}</span>
            )}
            <span className="text-[10px] text-gray-400">相关度 {(source.score * 100).toFixed(0)}%</span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{source.content}</p>
        </div>
        {source.source_url && (
          <a href={source.source_url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-gray-400 hover:text-blue-500 transition-colors">
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        )}
      </div>
    </Card>
  )
}
