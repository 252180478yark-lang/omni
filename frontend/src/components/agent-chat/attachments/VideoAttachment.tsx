'use client'
interface Props { url: string }
export function VideoAttachment({ url }: Props) {
  return (
    <video
      controls
      src={url}
      className="max-w-[320px] rounded-lg border border-gray-200"
      preload="metadata"
    />
  )
}
