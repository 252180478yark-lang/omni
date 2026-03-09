const DEFAULTS = {
  identity: 'http://localhost:8000',
  aiHub: 'http://localhost:8001',
  knowledge: 'http://localhost:8002',
}

function trimSlash(value: string): string {
  return value.endsWith('/') ? value.slice(0, -1) : value
}

export function serviceBase() {
  return {
    identity: trimSlash(process.env.IDENTITY_SERVICE_URL || DEFAULTS.identity),
    aiHub: trimSlash(process.env.AI_PROVIDER_HUB_URL || DEFAULTS.aiHub),
    knowledge: trimSlash(process.env.KNOWLEDGE_ENGINE_URL || DEFAULTS.knowledge),
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
