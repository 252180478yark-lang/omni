const DEFAULTS = {
  gateway: '',
  aiHub: 'http://localhost:8001',
  knowledge: 'http://localhost:8002',
  videoAnalysis: 'http://localhost:8006',
}

function trimSlash(value: string): string {
  return value.endsWith('/') ? value.slice(0, -1) : value
}

export function serviceBase() {
  const gateway = trimSlash(process.env.OMNI_API_BASE_URL || DEFAULTS.gateway)
  const fallback = gateway || ''
  return {
    // In local dev (without OMNI_API_BASE_URL), prefer direct service ports.
    aiHub: trimSlash(process.env.AI_PROVIDER_HUB_URL || fallback || DEFAULTS.aiHub),
    knowledge: trimSlash(process.env.KNOWLEDGE_ENGINE_URL || fallback || DEFAULTS.knowledge),
    videoAnalysis: trimSlash(process.env.VIDEO_ANALYSIS_SERVICE_URL || fallback || DEFAULTS.videoAnalysis),
  }
}

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}
