'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft, BookOpen, Download, Edit3, Eye, Loader2, RefreshCw, Save, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { getReview, listKnowledgeBases, saveReview, streamGenerateReview, syncKb, type SsePayload } from '@/lib/ad-review-api'

/* ── Inline toast ────────────────────────────────────────────────── */
function useToast() {
  const [msg, setMsg] = useState<{ text: string; type: 'ok' | 'err' } | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const show = (text: string, type: 'ok' | 'err' = 'ok') => {
    clearTimeout(timer.current)
    setMsg({ text, type })
    timer.current = setTimeout(() => setMsg(null), 3500)
  }
  const Toast = msg ? (
    <div
      className={`fixed top-4 right-4 z-50 px-4 py-2.5 rounded-lg shadow-lg text-sm font-medium transition-all animate-in fade-in slide-in-from-top-2 ${
        msg.type === 'ok'
          ? 'bg-green-600 text-white'
          : 'bg-red-600 text-white'
      }`}
    >
      {msg.text}
    </div>
  ) : null
  return { show, Toast }
}

export default function AdReviewLogPage() {
  const params = useParams()
  const id = String(params.id || '')

  const [content, setContent] = useState('')
  const [tags, setTags] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [loading, setLoading] = useState(true)
  const [edit, setEdit] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [kbs, setKbs] = useState<{ id: string; name: string }[]>([])
  const [selectedKbs, setSelectedKbs] = useState<Set<string>>(new Set())
  const toast = useToast()

  /* ── Load existing review ──────────────────────────────────────── */
  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      const r = await getReview(id)
      const log = r.review_log
      if (log) {
        setContent(String(log.content_md || ''))
        const t = log.experience_tags
        setTags(Array.isArray(t) ? t.join(', ') : '')
      } else {
        setContent('')
        setTags('')
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    listKnowledgeBases().then(setKbs).catch(() => {})
  }, [])

  /* ── Generate / regenerate ─────────────────────────────────────── */
  const onGenerate = async (replace: boolean) => {
    if (replace && content) {
      if (!confirm('将覆盖当前复盘内容，确定继续？')) return
    }
    setError('')
    setStreaming(true)
    setContent('')
    try {
      await streamGenerateReview(id, replace, (e: SsePayload) => {
        if (e.type === 'chunk' && e.content) {
          setContent((c) => c + e.content)
        }
        if (e.type === 'error') {
          setError(e.content || '生成失败')
        }
      }, Array.from(selectedKbs))
      toast.show('复盘报告生成完成')
      void load()
    } catch (e) {
      setError(String(e))
    } finally {
      setStreaming(false)
    }
  }

  /* ── Save ───────────────────────────────────────────────────────── */
  const onSave = async () => {
    setSaving(true)
    setError('')
    try {
      const tagList = tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      await saveReview(id, content, tagList)
      setEdit(false)
      toast.show('已保存')
      void load()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  /* ── Sync to KB ─────────────────────────────────────────────────── */
  const onSync = async () => {
    setError('')
    try {
      await syncKb(id)
      toast.show('已提交同步，知识库入库可能需数秒')
    } catch (e) {
      toast.show(String(e), 'err')
    }
  }

  /* ── Export markdown as .md file download ────────────────────────── */
  const onExport = () => {
    if (!content) return
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `复盘报告_${id}.md`
    a.click()
    URL.revokeObjectURL(url)
    toast.show('已下载')
  }

  const hasContent = !!content.trim()

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-16">
      {toast.Toast}

      {/* ── Header ─────────────────────────────────────────────────── */}
      <header className="border-b border-gray-200/80 bg-white/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
          <Link
            href={`/ad-review/${id}`}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 shrink-0"
          >
            <ArrowLeft className="w-4 h-4" /> 批次详情
          </Link>

          <div className="flex items-center gap-2 flex-wrap justify-end">
            {/* Secondary actions */}
            {hasContent && !streaming && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  className="gap-1 text-gray-600"
                  onClick={() => setEdit((e) => !e)}
                >
                  {edit ? <Eye className="w-3.5 h-3.5" /> : <Edit3 className="w-3.5 h-3.5" />}
                  {edit ? '预览' : '编辑'}
                </Button>
                {edit && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1"
                    onClick={() => void onSave()}
                    disabled={saving}
                  >
                    <Save className="w-3.5 h-3.5" />
                    {saving ? '保存中…' : '保存'}
                  </Button>
                )}
                <Button size="sm" variant="ghost" className="gap-1 text-gray-600" onClick={onExport}>
                  <Download className="w-3.5 h-3.5" /> 导出
                </Button>
                <Button size="sm" variant="ghost" className="gap-1 text-gray-600" onClick={() => void onSync()}>
                  <BookOpen className="w-3.5 h-3.5" /> 同步知识库
                </Button>
                <div className="w-px h-5 bg-gray-200 mx-0.5" />
                <Button size="sm" variant="outline" className="gap-1" disabled={streaming} onClick={() => void onGenerate(true)}>
                  <RefreshCw className="w-3.5 h-3.5" /> 重新生成
                </Button>
              </>
            )}

            {/* Primary CTA */}
            {!hasContent && !streaming && (
              <Button size="sm" className="gap-1.5" onClick={() => void onGenerate(false)}>
                <Sparkles className="w-4 h-4" /> 生成复盘报告
              </Button>
            )}
          </div>
        </div>
      </header>

      {/* ── Streaming indicator ────────────────────────────────────── */}
      {streaming && (
        <div className="max-w-4xl mx-auto px-4 pt-4">
          <div className="flex items-center gap-2 text-sm text-indigo-600 bg-indigo-50 rounded-lg px-3 py-2">
            <Loader2 className="w-4 h-4 animate-spin" /> AI 正在生成复盘报告…
          </div>
        </div>
      )}

      {/* ── KB selector ──────────────────────────────────────────── */}
      {!streaming && (
        <div className="max-w-4xl mx-auto px-4 pt-3">
          <details className="border rounded-lg bg-white">
            <summary className="px-3 py-2 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-50">
              选择知识库参考 ({selectedKbs.size}/{kbs.length})
            </summary>
            <div className="px-3 pb-3 flex flex-wrap gap-2">
              {kbs.map((kb) => (
                <button
                  key={kb.id}
                  type="button"
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                    selectedKbs.has(kb.id) ? 'bg-indigo-100 border-indigo-300 text-indigo-700' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                  }`}
                  onClick={() => setSelectedKbs((prev) => {
                    const next = new Set(prev)
                    if (next.has(kb.id)) next.delete(kb.id); else next.add(kb.id)
                    return next
                  })}
                >
                  {selectedKbs.has(kb.id) ? '✓ ' : ''}{kb.name}
                </button>
              ))}
              {kbs.length === 0 && <span className="text-xs text-gray-400">暂无知识库</span>}
            </div>
          </details>
        </div>
      )}

      {/* ── Main content ───────────────────────────────────────────── */}
      <main className="max-w-4xl mx-auto px-4 py-6 space-y-4">
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm">{error}</div>
        )}

        {loading ? (
          <div className="py-16 text-center text-gray-400 text-sm">加载中…</div>
        ) : edit ? (
          /* ── Edit mode: side-by-side ─────────────────────────────── */
          <div className="space-y-4">
            <div className="grid md:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <span className="text-xs text-gray-500 font-medium">Markdown 编辑</span>
                <Textarea
                  className="min-h-[520px] font-mono text-sm bg-white"
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="在此编辑 Markdown…"
                />
              </div>
              <div className="space-y-1.5">
                <span className="text-xs text-gray-500 font-medium">实时预览</span>
                <div className="min-h-[520px] rounded-lg border bg-white p-5 overflow-auto prose prose-sm max-w-none">
                  {content ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
                  ) : (
                    <p className="text-gray-400 text-sm">预览区</p>
                  )}
                </div>
              </div>
            </div>
            <div>
              <span className="text-xs text-gray-500 font-medium block mb-1">经验标签（逗号分隔）</span>
              <Textarea
                rows={2}
                className="bg-white"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="如：高转化素材、新客投放、千川、短视频"
              />
            </div>
          </div>
        ) : (
          /* ── Read mode ───────────────────────────────────────────── */
          <div className="rounded-xl border bg-white p-6 shadow-sm">
            {hasContent ? (
              <div className="prose prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
              </div>
            ) : (
              <div className="py-20 text-center">
                <Sparkles className="w-10 h-10 mx-auto mb-3 text-gray-300" />
                <p className="text-gray-500 text-sm mb-4">暂无复盘内容</p>
                <Button size="sm" className="gap-1.5" onClick={() => void onGenerate(false)}>
                  <Sparkles className="w-4 h-4" /> 生成复盘报告
                </Button>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
