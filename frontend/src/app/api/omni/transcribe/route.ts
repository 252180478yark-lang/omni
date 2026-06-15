import { serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

/**
 * 语音转文字代理 — 把浏览器录的音频转给 KE 本地 faster-whisper。
 * web 表单（如产物点评 OutputFeedback）录音 → 本路由 → KE POST /api/v1/transcribe
 * （离线 CPU 转写，不走云）→ 返 {ok, text, language, duration}。
 *
 * 复用桌面口述用的同一个 KE 端点；language 走 query（KE 侧是 query 参数，默认 zh）。
 */
export async function POST(request: Request) {
  const base = serviceBase()
  try {
    const inForm = await request.formData()
    const audio = inForm.get('audio') as File | null
    if (!audio) {
      return Response.json({ ok: false, error: 'no_audio' }, { status: 400 })
    }
    const language = (inForm.get('language') as string) || 'zh'

    const out = new FormData()
    out.append('audio', audio, audio.name || 'note.webm')

    const resp = await fetch(
      `${base.knowledge}/api/v1/transcribe?language=${encodeURIComponent(language)}`,
      { method: 'POST', body: out, cache: 'no-store' },
    )
    const data = await resp.json().catch(() => null)
    if (!resp.ok || !data?.ok) {
      return Response.json(
        { ok: false, error: data?.error || `${resp.status} ${resp.statusText}` },
        { status: resp.ok ? 400 : resp.status },
      )
    }
    return Response.json(data) // {ok, text, language, duration}
  } catch (err: unknown) {
    return Response.json(
      { ok: false, error: err instanceof Error ? err.message : String(err) },
      { status: 502 },
    )
  }
}
