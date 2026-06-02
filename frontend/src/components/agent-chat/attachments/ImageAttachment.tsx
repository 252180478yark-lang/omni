'use client'
import { useState } from 'react'

interface Props { url: string; alt?: string }

export function ImageAttachment({ url, alt }: Props) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="block max-w-[320px] rounded-lg overflow-hidden border border-gray-200 hover:border-violet-400 transition-colors"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt={alt || 'image'} className="w-full h-auto" loading="lazy" />
      </button>
      {open && (
        <div
          className="fixed inset-0 bg-black/80 z-[100] flex items-center justify-center p-4"
          onClick={() => setOpen(false)}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={url} alt={alt || 'image'} className="max-w-full max-h-full object-contain" />
        </div>
      )}
    </>
  )
}
