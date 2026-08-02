import {
  approvalServiceHeaders,
  fetchJson,
  requireApprovalActor,
  requireSameOrigin,
  ServiceFetchError,
  serviceBase,
  type ApprovalActor,
} from '../_shared'

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

const MODEL_HINTS: Record<string, string[]> = {
  openai: [
    'gpt-5.5',
    'gpt-5.4-mini',
    'gpt-5.4-nano',
    'gpt-5.2-chat-latest',
    'gpt-image-2',
    'gpt-image-1.5',
    'gpt-image-1',
    'gpt-image-1-mini',
  ],
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

async function readProvidersSnapshot(
  base: ReturnType<typeof serviceBase>,
  actor: ApprovalActor,
): Promise<ProviderItem[]> {
  const providersUrl = `${base.aiHub}/api/v1/ai/providers`
  const modelsUrl = `${base.aiHub}/api/v1/ai/models?quick=true`
  const [providersResp, modelsResp] = await Promise.all([
    fetchJson<ProvidersResp>(providersUrl, {
      headers: approvalServiceHeaders('GET', providersUrl, actor),
    }),
    fetchJson<ModelsResp>(modelsUrl, {
      headers: approvalServiceHeaders('GET', modelsUrl, actor),
    }),
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
    models: Array.from(new Set([...(modelMap.get(name) || []), ...(MODEL_HINTS[name] || [])])),
    apiKeySet: info.api_key_set,
  }))
}

function developerBoundaryError(error: unknown, fallback: string): Response {
  const status = error instanceof ServiceFetchError ? error.status : 502
  const code = error instanceof ServiceFetchError ? error.code : fallback
  return Response.json({ success: false, error: code }, { status })
}

export async function GET(request: Request) {
  try {
    const actor = await requireApprovalActor(request)
    const base = serviceBase()
    const providers = await readProvidersSnapshot(base, actor)

    return Response.json({ success: true, data: { providers } })
  } catch (error) {
    return developerBoundaryError(error, 'model_status_unavailable')
  }
}

export async function POST(request: Request) {
  try {
    requireSameOrigin(request)
    const actor = await requireApprovalActor(request)
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
      const url = `${base.aiHub}/api/v1/ai/config`
      const upstreamBody = JSON.stringify({
        provider: body.providerId,
        api_key: body.apiKey,
        default_chat_model: body.defaultChatModel,
        default_embedding_model: body.defaultEmbeddingModel,
      })
      const updateResp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...approvalServiceHeaders('POST', url, actor, upstreamBody),
        },
        body: upstreamBody,
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
      const url = `${base.aiHub}/api/v1/ai/test-connection`
      const upstreamBody = JSON.stringify({
        provider: body.providerId,
        api_key: body.apiKey,
        default_chat_model: body.defaultChatModel,
        smoke_image: true,
      })
      const testResp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...approvalServiceHeaders('POST', url, actor, upstreamBody),
        },
        body: upstreamBody,
        cache: 'no-store',
      })
      const testJson = (await testResp.json()) as {
        success: boolean
        provider: string
        message: string
        models?: string[]
        smoke_test?: {
          success: boolean
          type: string
          message: string
          image_url?: string
          model?: string
        } | null
      }
      let providers = await readProvidersSnapshot(base, actor)
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
      let providers = await readProvidersSnapshot(base, actor)
      if (body.providerId) {
        const url = `${base.aiHub}/api/v1/ai/test-connection`
        const upstreamBody = JSON.stringify({
          provider: body.providerId,
          api_key: body.apiKey,
        })
        const testResp = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...approvalServiceHeaders('POST', url, actor, upstreamBody),
          },
          body: upstreamBody,
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
    const providers = await readProvidersSnapshot(base, actor)
    return Response.json({ success: true, data: { providers } })
  } catch (error) {
    return developerBoundaryError(error, 'model_operation_unavailable')
  }
}
