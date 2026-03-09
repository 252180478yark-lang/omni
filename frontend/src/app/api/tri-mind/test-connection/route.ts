import { NextRequest } from 'next/server'
import { adapterManager } from '@/server/tri-mind/adapters'
import type { ModelProvider } from '@/server/tri-mind/types'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface Body {
  provider: ModelProvider
  apiKey: string
  baseUrl?: string
  model: string
}

export async function POST(request: NextRequest) {
  try {
    const body: Body = await request.json()
    const { provider, apiKey, baseUrl, model } = body
    const adapter = adapterManager.get(provider)
    if (!adapter) {
      return Response.json({ success: false, error: 'Unknown provider' }, { status: 400 })
    }
    const result = await adapter.testConnection({
      apiKey: provider === 'ollama' ? 'ollama' : apiKey,
      baseUrl,
      model,
    })
    return Response.json({ success: true, data: result })
  } catch (error) {
    console.error('Test connection error:', error)
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
