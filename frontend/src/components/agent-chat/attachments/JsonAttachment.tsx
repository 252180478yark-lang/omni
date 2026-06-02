'use client'
import { useState } from 'react'
import { ChevronDown, ChevronRight, FileJson } from 'lucide-react'

interface Props { data: unknown }
export function JsonAttachment({ data }: Props) {
  const [open, setOpen] = useState(false)
  const text = JSON.stringify(data, null, 2)
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 overflow-hidden max-w-2xl">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-100 transition-colors"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <FileJson className="w-3.5 h-3.5 text-gray-500" />
        <span className="text-xs text-gray-600">JSON · {text.length} chars</span>
      </button>
      {open && (
        <pre className="px-3 py-2 text-[11px] font-mono text-gray-800 overflow-x-auto max-h-96">
          {text}
        </pre>
      )}
    </div>
  )
}
