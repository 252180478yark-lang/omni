'use client'
import type { ChatAttachment } from '@/lib/agent-chat/types'
import { ImageAttachment } from './attachments/ImageAttachment'
import { VideoAttachment } from './attachments/VideoAttachment'
import { MarkdownAttachment } from './attachments/MarkdownAttachment'
import { JsonAttachment } from './attachments/JsonAttachment'

interface Props {
  attachments: ChatAttachment[]
  rawResult: unknown
}

export function ToolResultCard({ attachments, rawResult }: Props) {
  if (attachments.length === 0) {
    return <JsonAttachment data={rawResult} />
  }
  return (
    <div className="flex flex-wrap gap-3 max-w-3xl">
      {attachments.map((att, idx) => {
        if (att.type === 'image' && att.url) return <ImageAttachment key={idx} url={att.url} alt={att.alt} />
        if (att.type === 'video' && att.url) return <VideoAttachment key={idx} url={att.url} poster={att.thumbnail_url} />
        if (att.type === 'markdown' && att.markdown) return <MarkdownAttachment key={idx} markdown={att.markdown} />
        if (att.type === 'json') return <JsonAttachment key={idx} data={att.data} />
        return null
      })}
    </div>
  )
}
