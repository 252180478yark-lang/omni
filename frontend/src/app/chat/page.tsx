'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
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
  Upload,
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
  type ChatMessage,
} from '@/stores/chatStore'

interface KBItem {
  id: string
  name: string
  description: string
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
) {
  try {
    const res = await fetch('/api/omni/knowledge/rag', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kb_id: kbId, query, stream: true, top_k: 5, session_id: sessionId }),
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

  const [bases, setBases] = useState<KBItem[]>([])
  const [input, setInput] = useState('')
  const [kbOpen, setKbOpen] = useState(false)
  const [modeOpen, setModeOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    ;(async () => {
      try {
        const res = await fetch('/api/omni/knowledge/bases', { cache: 'no-store' })
        const json = await res.json()
        if (json.success && json.data) {
          setBases(json.data)
          if (!kbId && json.data.length > 0) {
            setKbId(json.data[0].id)
          }
        }
      } catch { /* ignore */ }
    })()
  }, [kbId, setKbId])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

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
      await streamRAG(kbId, q, sessionId, aId, appendToken, finishAssistant, failAssistant, ctrl.signal)
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
    input, kbId, sessionId, outputMode, streaming,
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

  const selectedKb = bases.find((b) => b.id === kbId)
  const selectedMode = OUTPUT_MODES.find((m) => m.id === outputMode) || OUTPUT_MODES[0]

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
            {/* KB Selector */}
            <div className="relative">
              <button
                onClick={() => setKbOpen((v) => !v)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-full border border-gray-200 bg-white/80 hover:bg-white transition-colors shadow-sm"
              >
                <Database className="w-3.5 h-3.5 text-gray-500" />
                <span className="max-w-[120px] truncate">{selectedKb?.name || '选择知识库'}</span>
                <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
              </button>
              {kbOpen && (
                <div className="absolute right-0 top-full mt-1 w-64 bg-white rounded-xl shadow-xl border border-gray-100 py-1 z-50 max-h-64 overflow-auto">
                  {bases.map((kb) => (
                    <button
                      key={kb.id}
                      onClick={() => { setKbId(kb.id); setKbOpen(false) }}
                      className={`w-full text-left px-3 py-2 text-sm hover:bg-blue-50 transition-colors ${
                        kb.id === kbId ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-700'
                      }`}
                    >
                      <div className="font-medium truncate">{kb.name}</div>
                      {kb.description && <div className="text-xs text-gray-400 truncate">{kb.description}</div>}
                    </button>
                  ))}
                  {bases.length === 0 && (
                    <div className="px-3 py-4 text-sm text-gray-400 text-center">暂无知识库</div>
                  )}
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
                {/* Mode badge */}
                {msg.role === 'user' && msg.outputMode && msg.outputMode !== 'text' && (
                  <div className="mb-1.5">
                    <Badge variant="secondary" className="text-[10px] bg-white/20 text-white border-0">
                      {OUTPUT_MODES.find((m) => m.id === msg.outputMode)?.label}
                    </Badge>
                  </div>
                )}

                {/* Loading indicator */}
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

                {/* Text content */}
                <div className={`markdown-body text-sm whitespace-pre-wrap ${msg.role === 'user' ? '!text-white' : ''}`}>
                  {msg.content}
                  {msg.role === 'assistant' && msg.loading && msg.content && (
                    <span className="cursor-blink">▊</span>
                  )}
                </div>

                {/* Images */}
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

                {/* Video */}
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

                {/* Sources */}
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
          {/* Output Mode Selector */}
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
            <span className="text-[10px] text-gray-400">{(source.score * 100).toFixed(0)}%</span>
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
