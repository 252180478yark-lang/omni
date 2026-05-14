'use client'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Props { markdown: string }
export function MarkdownAttachment({ markdown }: Props) {
  return (
    <div className="max-w-2xl prose prose-sm prose-violet bg-white rounded-lg border border-gray-200 p-3">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  )
}
