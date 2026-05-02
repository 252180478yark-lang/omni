'use client'

import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'

interface BriefSummary {
  id: string
  title: string
  usp: string
  scenarios?: Array<Record<string, unknown>>
  audience_profile?: Record<string, unknown>
  tone_style?: Record<string, unknown>
  dmp_sop?: string | null
}

interface Props {
  /** 取最近一条 assistant 消息内容用于"应用为 DMP SOP" */
  getLatestAssistantContent?: () => string
}

export function BriefContextPanel({ getLatestAssistantContent }: Props) {
  const searchParams = useSearchParams()
  const briefId = searchParams.get('brief_id') || ''

  const [brief, setBrief] = useState<BriefSummary | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!briefId) {
      setBrief(null)
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(`/api/omni/content-studio/briefs/${briefId}`, { cache: 'no-store' })
        if (!res.ok) {
          throw new Error(`${res.status}`)
        }
        const data = (await res.json()) as BriefSummary
        if (!cancelled) setBrief(data)
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [briefId])

  if (!briefId) return null
  if (error) {
    return (
      <div className="mx-auto my-2 max-w-3xl rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
        无法加载 Brief（{error}）
      </div>
    )
  }
  if (!brief) {
    return (
      <div className="mx-auto my-2 max-w-3xl rounded border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500">
        加载 Brief 中…
      </div>
    )
  }

  const onSaveDmp = async () => {
    const content = getLatestAssistantContent?.()
    if (!content) return
    setSaving(true)
    try {
      const res = await fetch(`/api/omni/content-studio/briefs/${brief.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dmp_sop: content }),
      })
      if (!res.ok) throw new Error(`${res.status}`)
      setSavedAt(new Date().toLocaleTimeString())
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto my-3 max-w-3xl rounded-lg border border-violet-200 bg-violet-50/60 p-3 text-xs">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="font-medium text-violet-800">
          🧠 当前会话已挂载 Brief：{brief.title}
        </div>
        <button
          type="button"
          disabled={saving}
          onClick={onSaveDmp}
          className="rounded border border-violet-300 bg-white px-2 py-0.5 text-[11px] text-violet-700 hover:bg-violet-100 disabled:opacity-60"
        >
          {saving ? '保存中…' : '将本轮回复应用为 DMP SOP'}
        </button>
      </div>
      <div className="text-violet-900">USP：{brief.usp}</div>
      {Array.isArray(brief.scenarios) && brief.scenarios.length > 0 && (
        <div className="mt-1 text-violet-700">
          场景数：{brief.scenarios.length}
        </div>
      )}
      {savedAt && (
        <div className="mt-1 text-emerald-700">已保存 DMP SOP（{savedAt}）</div>
      )}
    </div>
  )
}
