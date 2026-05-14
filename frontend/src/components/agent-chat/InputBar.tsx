'use client'
import { useState, useRef } from 'react'
import { Send, Paperclip, X, Square } from 'lucide-react'

interface Props {
  sessionId: string
  running: boolean
  onSend: (prompt: string) => void
  onCancel: () => void
}

interface UploadedFile {
  url: string
  filename: string
}

export function InputBar({ sessionId, running, onSend, onCancel }: Props) {
  const [input, setInput] = useState('')
  const [files, setFiles] = useState<UploadedFile[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const handleSend = () => {
    if (!input.trim() && files.length === 0) return
    let prompt = input.trim()
    if (files.length > 0) {
      const fileList = files.map((f) => `- ${f.filename}: ${f.url}`).join('\n')
      prompt = `${prompt}\n\n附件：\n${fileList}`
    }
    onSend(prompt)
    setInput('')
    setFiles([])
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const list = e.target.files
    if (!list || list.length === 0) return
    setUploading(true)
    try {
      for (const f of Array.from(list)) {
        const form = new FormData()
        form.append('file', f)
        const resp = await fetch(`/api/agent-chat/upload?session_id=${sessionId}`, {
          method: 'POST',
          body: form,
        })
        const json = await resp.json()
        if (json.success) {
          setFiles((prev) => [...prev, { url: json.data.url, filename: json.data.filename }])
        }
      }
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <div className="border-t border-gray-100 bg-white px-4 py-3">
      {files.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {files.map((f, idx) => (
            <span
              key={idx}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-violet-50 border border-violet-200 text-xs"
            >
              <Paperclip className="w-3 h-3 text-violet-600" />
              {f.filename}
              <button onClick={() => setFiles(files.filter((_, i) => i !== idx))}>
                <X className="w-3 h-3 text-gray-400 hover:text-red-500" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2">
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="shrink-0 w-9 h-9 rounded-lg border border-gray-200 flex items-center justify-center text-gray-500 hover:bg-gray-50"
        >
          <Paperclip className="w-4 h-4" />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/*,video/*,.pdf,.md,.txt,.json"
          onChange={handleFileUpload}
          className="hidden"
        />
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder="输入指令，回车发送 (Shift+Enter 换行) / 支持 / 触发 skill"
          rows={1}
          className="flex-1 resize-none rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:border-violet-400 max-h-32"
        />
        {running ? (
          <button
            onClick={onCancel}
            className="shrink-0 w-9 h-9 rounded-lg bg-red-500 text-white flex items-center justify-center hover:bg-red-600"
            title="停止"
          >
            <Square className="w-4 h-4" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!input.trim() && files.length === 0}
            className="shrink-0 w-9 h-9 rounded-lg bg-violet-600 text-white flex items-center justify-center hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed"
            title="发送"
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  )
}
