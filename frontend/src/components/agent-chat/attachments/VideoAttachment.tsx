'use client'
import { useState } from 'react'
import { Play } from 'lucide-react'

interface Props { url: string; poster?: string }
export function VideoAttachment({ url, poster }: Props) {
  const [playing, setPlaying] = useState(false)

  if (!playing) {
    return (
      <button
        onClick={() => setPlaying(true)}
        className="relative max-w-[320px] rounded-lg border border-gray-200 overflow-hidden group"
      >
        {poster ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={poster} alt="video thumbnail" className="w-full h-auto" loading="lazy" />
        ) : (
          <div className="w-[320px] h-[180px] bg-gray-200 flex items-center justify-center">
            <Play className="w-12 h-12 text-gray-400" />
          </div>
        )}
        <div className="absolute inset-0 flex items-center justify-center bg-black/30 group-hover:bg-black/40 transition-colors">
          <div className="w-14 h-14 rounded-full bg-white/90 flex items-center justify-center">
            <Play className="w-6 h-6 text-violet-600 ml-1" />
          </div>
        </div>
      </button>
    )
  }
  return (
    <video
      autoPlay
      controls
      src={url}
      className="max-w-[320px] rounded-lg border border-gray-200"
      preload="metadata"
    />
  )
}
