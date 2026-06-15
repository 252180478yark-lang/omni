'use client'

import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Loader2, Mic, Square } from 'lucide-react'

/**
 * 语音输入按钮 — 浏览器录音 → KE 本地 faster-whisper 转写 → 回填文字。
 *
 * 点一下开始录、再点停止 → 转写完成把文字交给 onTranscript（调用方自行决定
 * 追加还是覆盖）。复用桌面口述用的同一个 KE 端点（/api/omni/transcribe 代理）。
 *
 * 注意：getUserMedia 需要安全上下文——localhost 或 https 才能录音；
 * 经纯 http 的 Tailscale IP 访问时浏览器会拒绝（届时退回手打）。
 */
interface Props {
  /** 转写出的文字（中文）；调用方决定 append/replace */
  onTranscript: (text: string) => void
  disabled?: boolean
  title?: string
}

type State = 'idle' | 'recording' | 'transcribing'

export default function VoiceInputButton({ onTranscript, disabled, title }: Props) {
  const [state, setState] = useState<State>('idle')
  const [err, setErr] = useState<string | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)

  const releaseMic = () => {
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
  }

  const start = async () => {
    setErr(null)
    if (!navigator.mediaDevices?.getUserMedia) {
      setErr('当前环境不支持录音（需 localhost/https）')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mr = new MediaRecorder(stream)
      chunksRef.current = []
      mr.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      mr.onstop = async () => {
        releaseMic()
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' })
        if (!blob.size) { setState('idle'); return }
        setState('transcribing')
        try {
          const fd = new FormData()
          fd.append('audio', blob, 'note.webm')
          fd.append('language', 'zh')
          const res = await fetch('/api/omni/transcribe', { method: 'POST', body: fd })
          const json = await res.json()
          if (json.ok && (json.text || '').trim()) onTranscript(json.text.trim())
          else setErr(json.error || '没听清，再说一次')
        } catch (e) {
          setErr(e instanceof Error ? e.message : String(e))
        } finally {
          setState('idle')
        }
      }
      mr.start()
      recorderRef.current = mr
      setState('recording')
    } catch (e) {
      releaseMic()
      setErr('麦克风不可用：' + (e instanceof Error ? e.message : String(e)))
      setState('idle')
    }
  }

  const stop = () => {
    try { recorderRef.current?.stop() } catch { /* noop */ }
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <Button
        type="button"
        size="sm"
        variant={state === 'recording' ? 'default' : 'outline'}
        className="text-xs h-7 px-2"
        disabled={disabled || state === 'transcribing'}
        onClick={state === 'recording' ? stop : start}
        title={title || '语音输入（本地转写，离线不走云）'}
      >
        {state === 'transcribing'
          ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
          : state === 'recording'
            ? <Square className="w-3.5 h-3.5 fill-current" />
            : <Mic className="w-3.5 h-3.5" />}
      </Button>
      {state === 'recording' && (
        <span className="text-[10px] text-red-500 animate-pulse">录音中·点■停</span>
      )}
      {state === 'transcribing' && (
        <span className="text-[10px] text-muted-foreground">转写中…</span>
      )}
      {err && <span className="text-[10px] text-red-500">{err}</span>}
    </span>
  )
}
