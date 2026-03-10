import { NextRequest } from 'next/server'
import { adapterManager } from '@/server/tri-mind/adapters'
import type { ModelProvider } from '@/server/tri-mind/types'
import { serviceBase } from '@/app/api/omni/_shared'

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

    if (provider === 'openai' || provider === 'gemini' || provider === 'ollama') {
      const base = serviceBase()
      const testResp = await fetch(`${base.aiHub}/api/v1/ai/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider,
          api_key: provider === 'ollama' ? undefined : apiKey,
        }),
        cache: 'no-store',
      })

      if (!testResp.ok) {
        const text = await testResp.text()
        return Response.json(
          { success: false, error: text || `test failed: ${testResp.status}` },
          { status: testResp.status }
        )
      }

      const result = (await testResp.json()) as { success: boolean; message: string }
      return Response.json({
        success: true,
        data: { ok: result.success, error: result.success ? undefined : result.message },
      })
    }

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
