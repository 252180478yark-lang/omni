'use client'
import { Loader2, CheckCircle2, XCircle, Wrench } from 'lucide-react'
import { useState } from 'react'
import { JsonAttachment } from './attachments/JsonAttachment'

interface Props {
  toolName: string
  args: Record<string, unknown> | undefined
  status: 'pending' | 'completed' | 'error'
}

export function ToolCallChip({ toolName, args, status }: Props) {
  const [open, setOpen] = useState(false)
  const Icon = status === 'pending' ? Loader2 : status === 'error' ? XCircle : CheckCircle2
  const color = status === 'pending' ? 'text-blue-500' : status === 'error' ? 'text-red-500' : 'text-emerald-500'
  return (
    <div className="inline-flex flex-col items-start gap-1 max-w-2xl">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-violet-50 border border-violet-200 text-xs text-gray-700 hover:bg-violet-100"
      >
        <Wrench className="w-3 h-3 text-violet-600" />
        <span className="font-medium">{toolName}</span>
        <Icon className={`w-3 h-3 ${color} ${status === 'pending' ? 'animate-spin' : ''}`} />
      </button>
      {open && args && <JsonAttachment data={args} />}
    </div>
  )
}
