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
      api_key_set?: boolean
    }
  >
}

interface ModelsResp {
  models: Array<{
    provider: string
    models: string[]
  }>
}

interface ProviderItem {
  id: string
  name: string
  status: string
  capabilities: string[]
  defaultChatModel: string | null
  defaultEmbeddingModel: string | null
  models: string[]
  apiKeySet?: boolean
}

function mergeProviderModels(
  providers: ProviderItem[],
  providerId?: string,
  models?: string[],
): ProviderItem[] {
  if (!providerId || !models || models.length === 0) return providers
  const deduped = Array.from(new Set(models.filter(Boolean)))
  return providers.map((p) => (p.id === providerId ? { ...p, models: deduped } : p))
}

async function readProvidersSnapshot(base: ReturnType<typeof serviceBase>): Promise<ProviderItem[]> {
  const [providersResp, modelsResp] = await Promise.all([
    fetchJson<ProvidersResp>(`${base.aiHub}/api/v1/ai/providers`),
    fetchJson<ModelsResp>(`${base.aiHub}/api/v1/ai/models`),
  ])

  const modelMap = new Map<string, string[]>()
  for (const item of modelsResp.models) {
    modelMap.set(item.provider, item.models)
  }

  return Object.entries(providersResp.providers).map(([name, info]) => ({
    id: name,
    name: name.toUpperCase(),
    status: 'connected',
    capabilities: info.capabilities,
    defaultChatModel: info.default_chat_model,
    defaultEmbeddingModel: info.default_embedding_model,
    models: modelMap.get(name) || [],
    apiKeySet: info.api_key_set,
  }))
}

export async function GET() {
  try {
    const base = serviceBase()
    const providers = await readProvidersSnapshot(base)

    return Response.json({ success: true, data: { providers } })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      action?: 'refresh' | 'update-provider' | 'test-connection'
      providerId?: string
      apiKey?: string
      defaultChatModel?: string
      defaultEmbeddingModel?: string
    }

    const base = serviceBase()

    if (body.action === 'update-provider') {
      if (!body.providerId) {
        return Response.json({ success: false, error: 'providerId is required' }, { status: 400 })
      }
      const updateResp = await fetch(`${base.aiHub}/api/v1/ai/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: body.providerId,
          api_key: body.apiKey,
          default_chat_model: body.defaultChatModel,
          default_embedding_model: body.defaultEmbeddingModel,
        }),
        cache: 'no-store',
      })
      if (!updateResp.ok) {
        const text = await updateResp.text()
        throw new Error(text || `update failed: ${updateResp.status}`)
      }
    }

    if (body.action === 'test-connection') {
      if (!body.providerId) {
        return Response.json({ success: false, error: 'providerId is required' }, { status: 400 })
      }
      const testResp = await fetch(`${base.aiHub}/api/v1/ai/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: body.providerId,
          api_key: body.apiKey,
        }),
        cache: 'no-store',
      })
      const testJson = (await testResp.json()) as { success: boolean; provider: string; message: string; models?: string[] }
      let providers = await readProvidersSnapshot(base)
      providers = mergeProviderModels(providers, body.providerId, testJson.models)
      return Response.json({
        success: true,
        data: {
          providers,
          connectionTest: testJson,
        },
      })
    }

    if (body.action === 'refresh') {
      let providers = await readProvidersSnapshot(base)
      if (body.providerId) {
        const testResp = await fetch(`${base.aiHub}/api/v1/ai/test-connection`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            provider: body.providerId,
            api_key: body.apiKey,
          }),
          cache: 'no-store',
        })
        const testJson = (await testResp.json()) as { success: boolean; provider: string; message: string; models?: string[] }
        providers = mergeProviderModels(providers, body.providerId, testJson.models)
        return Response.json({
          success: true,
          data: {
            providers,
            connectionTest: testJson,
          },
        })
      }
      return Response.json({ success: true, data: { providers } })
    }

    // refresh/default behavior: return latest snapshot
    const providers = await readProvidersSnapshot(base)
    return Response.json({ success: true, data: { providers } })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
