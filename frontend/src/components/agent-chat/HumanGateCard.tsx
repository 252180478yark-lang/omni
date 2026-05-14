'use client'
import { CheckCircle2, XCircle, Shield } from 'lucide-react'
import { useState } from 'react'

interface Props {
  shortId: string
  summary: string
  decision: 'pending' | 'approved' | 'rejected'
  onDecide: (decision: 'approved' | 'rejected', note?: string) => void
}

export function HumanGateCard({ shortId, summary, decision, onDecide }: Props) {
  const [note, setNote] = useState('')
  return (
    <div className="max-w-2xl rounded-xl border-2 border-amber-300 bg-amber-50 p-4 self-start">
      <div className="flex items-center gap-2 mb-2">
        <Shield className="w-4 h-4 text-amber-600" />
        <span className="text-sm font-semibold text-amber-900">需要你点头</span>
        <span className="text-[10px] text-amber-700 font-mono">{shortId}</span>
      </div>
      <p className="text-sm text-gray-700 mb-3 whitespace-pre-wrap">{summary}</p>
      {decision === 'pending' ? (
        <>
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="备注（可选）"
            className="w-full px-2.5 py-1.5 text-xs rounded-md border border-amber-200 mb-2 focus:outline-none focus:border-amber-400"
          />
          <div className="flex gap-2">
            <button
              onClick={() => onDecide('approved', note)}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-600 text-white text-xs hover:bg-emerald-700"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              通过
            </button>
            <button
              onClick={() => onDecide('rejected', note)}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md bg-red-600 text-white text-xs hover:bg-red-700"
            >
              <XCircle className="w-3.5 h-3.5" />
              驳回
            </button>
          </div>
        </>
      ) : (
        <div className="text-xs">
          {decision === 'approved' ? (
            <span className="text-emerald-700">✓ 已通过</span>
          ) : (
            <span className="text-red-700">✗ 已驳回</span>
          )}
        </div>
      )}
    </div>
  )
}
