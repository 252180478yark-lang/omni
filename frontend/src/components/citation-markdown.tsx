'use client'

import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ExternalLink } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { SourceRef } from '@/stores/chatStore'

/* ───── Citation Badge ───── */

export function CitationBadge({
  index,
  source,
  msgId,
}: {
  index: number
  source: SourceRef
  msgId: string
}) {
  const onClick = () => {
    const el = document.getElementById(`cite-${msgId}-${index}`)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('ring-2', 'ring-violet-400')
    window.setTimeout(() => {
      el.classList.remove('ring-2', 'ring-violet-400')
    }, 1500)
  }
  const tip =
    (source.title ? `${source.title}\n\n` : '') + (source.content ?? '').slice(0, 200)
  return (
    <button
      type="button"
      onClick={onClick}
      title={tip}
      className="inline-flex items-center justify-center align-super text-[10px] leading-none font-medium px-1.5 h-4 rounded bg-violet-50 text-violet-600 border border-violet-200 hover:bg-violet-100 hover:text-violet-700 cursor-pointer mx-0.5 transition-colors"
    >
      {index}
    </button>
  )
}

/* ───── Walk children & replace [N] with badges ───── */

export function renderWithCitations(
  children: React.ReactNode,
  sources: SourceRef[] | undefined,
  msgId: string,
): React.ReactNode {
  if (!sources || sources.length === 0) return children
  const walk = (node: React.ReactNode): React.ReactNode => {
    if (typeof node === 'string') {
      const parts = node.split(/(\[\d+\])/g)
      if (parts.length === 1) return node
      return parts.map((part, i) => {
        const m = part.match(/^\[(\d+)\]$/)
        if (!m) return part
        const idx = parseInt(m[1], 10)
        const src = sources.find((s) => s.index === idx)
        if (!src) return part
        return (
          <CitationBadge key={`cb-${i}-${idx}`} index={idx} source={src} msgId={msgId} />
        )
      })
    }
    if (Array.isArray(node)) {
      return node.map((c, i) => <React.Fragment key={i}>{walk(c)}</React.Fragment>)
    }
    return node
  }
  return React.Children.map(children, walk)
}

/* ───── Markdown wrapper with citation support ───── */

export function CitationMarkdown({
  content,
  sources,
  msgId,
}: {
  content: string
  sources?: SourceRef[]
  msgId: string
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p>{renderWithCitations(children, sources, msgId)}</p>,
        li: ({ children }) => <li>{renderWithCitations(children, sources, msgId)}</li>,
        td: ({ children }) => <td>{renderWithCitations(children, sources, msgId)}</td>,
        th: ({ children }) => <th>{renderWithCitations(children, sources, msgId)}</th>,
      }}
    >
      {content}
    </ReactMarkdown>
  )
}

/* ───── Source Card (anchor target) ───── */

export function SourceCard({ source, msgId }: { source: SourceRef; msgId: string }) {
  return (
    <Card
      id={`cite-${msgId}-${source.index}`}
      className="p-2 bg-gray-50/80 border-gray-100 hover:bg-gray-100/80 transition-all scroll-mt-20"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <Badge
              variant="outline"
              className="text-[10px] px-1.5 py-0 bg-violet-50 text-violet-600 border-violet-200"
            >
              #{source.index}
            </Badge>
            {source.title && (
              <span className="text-xs font-medium text-gray-700 truncate">{source.title}</span>
            )}
            <span className="text-[10px] text-gray-400">
              相关度 {(source.score * 100).toFixed(0)}%
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5 line-clamp-6">{source.content}</p>
        </div>
        {source.source_url && (
          <a
            href={source.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 text-gray-400 hover:text-violet-500 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        )}
      </div>
    </Card>
  )
}

/* ───── Source list panel ───── */

export function SourceList({
  sources,
  msgId,
  label = '📚 引用来源',
}: {
  sources: SourceRef[] | undefined
  msgId: string
  label?: string
}) {
  if (!sources || sources.length === 0) return null
  return (
    <div className="mt-3 pt-2 border-t border-gray-100">
      <div className="text-xs font-medium text-gray-400 mb-1.5">{label}</div>
      <div className="space-y-1.5">
        {sources.map((src) => (
          <SourceCard key={src.chunk_id} source={src} msgId={msgId} />
        ))}
      </div>
    </div>
  )
}
