const DEFAULTS = {
  gateway: '',
  aiHub: 'http://localhost:8001',
  knowledge: 'http://localhost:8002',
  newsAggregator: 'http://localhost:8005',
  videoAnalysis: 'http://localhost:8006',
  livestreamAnalysis: 'http://localhost:8007',
  adReview: 'http://localhost:8008',
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
    newsAggregator: trimSlash(process.env.NEWS_AGGREGATOR_URL || fallback || DEFAULTS.newsAggregator),
    videoAnalysis: trimSlash(process.env.VIDEO_ANALYSIS_SERVICE_URL || fallback || DEFAULTS.videoAnalysis),
    livestreamAnalysis: trimSlash(process.env.LIVESTREAM_ANALYSIS_SERVICE_URL || fallback || DEFAULTS.livestreamAnalysis),
    adReview: trimSlash(process.env.AD_REVIEW_SERVICE_URL || fallback || DEFAULTS.adReview),
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
    let detail = ''
    try {
      const body = await response.json()
      detail = body?.detail || body?.error || body?.message || ''
    } catch {
      try { detail = await response.text() } catch { /* noop */ }
    }
    throw new Error(detail || `${response.status} ${response.statusText}`)
  }
  return (await response.json()) as T
}
