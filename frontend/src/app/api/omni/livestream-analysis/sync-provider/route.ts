import { fetchJson, serviceBase } from '../../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface SyncBody {
  provider: string
  model?: string
}

interface ProviderSecretResp {
  provider: string
  api_key: string
  default_chat_model?: string | null
}

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as SyncBody
    if (!payload.provider) {
      return Response.json({ success: false, error: 'provider is required' }, { status: 400 })
    }
    if (payload.provider !== 'gemini') {
      return Response.json(
        { success: false, error: '直播切片分析仅支持 Gemini 多模态分析，请选择 gemini' },
        { status: 400 },
      )
    }
    const base = serviceBase()
    const secret = await fetchJson<ProviderSecretResp>(
      `${base.aiHub}/api/v1/ai/provider-secrets/${payload.provider}`,
    )
    if (!secret.api_key) {
      return Response.json(
        { success: false, error: `provider ${payload.provider} has no api key in system` },
        { status: 400 },
      )
    }

    const resp = await fetch(
      `${base.livestreamAnalysis}/api/v1/livestream-analysis/settings/gemini/test`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          api_key: secret.api_key,
          model: payload.model || secret.default_chat_model || undefined,
        }),
        cache: 'no-store',
      },
    )
    const text = await resp.text()
    if (!resp.ok) {
      throw new Error(text || `sync failed: ${resp.status}`)
    }
    return Response.json({ success: true, data: { provider: payload.provider, synced: true, detail: text } })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
