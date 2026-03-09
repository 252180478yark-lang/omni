import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface ProvidersResp {
  providers: Record<
    string,
    {
      capabilities: string[]
      default_chat_model: string | null
      default_embedding_model: string | null
    }
  >
}

interface ModelsResp {
  models: Array<{
    provider: string
    models: string[]
  }>
}

export async function GET() {
  try {
    const base = serviceBase()
    const [providersResp, modelsResp] = await Promise.all([
      fetchJson<ProvidersResp>(`${base.aiHub}/api/v1/ai/providers`),
      fetchJson<ModelsResp>(`${base.aiHub}/api/v1/ai/models`),
    ])

    const modelMap = new Map<string, string[]>()
    for (const item of modelsResp.models) {
      modelMap.set(item.provider, item.models)
    }

    const providers = Object.entries(providersResp.providers).map(([name, info]) => ({
      id: name,
      name: name.toUpperCase(),
      status: 'connected',
      capabilities: info.capabilities,
      defaultChatModel: info.default_chat_model,
      defaultEmbeddingModel: info.default_embedding_model,
      models: modelMap.get(name) || [],
    }))

    return Response.json({ success: true, data: { providers } })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
