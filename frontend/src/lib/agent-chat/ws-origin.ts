import type { IncomingMessage } from 'node:http'

function firstHeaderValue(value: string | string[] | undefined): string | undefined {
  const first = Array.isArray(value) ? value[0] : value?.split(',')[0]
  const normalized = first?.trim()
  return normalized || undefined
}

function effectiveProtocol(req: Pick<IncomingMessage, 'headers' | 'socket'>): 'http:' | 'https:' | null {
  const forwarded = req.headers['x-forwarded-proto']
  if (forwarded !== undefined) {
    const protocol = firstHeaderValue(forwarded)?.toLowerCase()
    if (protocol === 'http' || protocol === 'https') return `${protocol}:`
    return null
  }

  return 'encrypted' in req.socket && req.socket.encrypted === true ? 'https:' : 'http:'
}

export function isSameOriginWebSocketUpgrade(
  req: Pick<IncomingMessage, 'headers' | 'socket'>,
): boolean {
  const origin = req.headers.origin
  if (!origin || Array.isArray(origin)) return false

  const forwardedHost = req.headers['x-forwarded-host']
  const expectedHost = forwardedHost === undefined
    ? firstHeaderValue(req.headers.host)
    : firstHeaderValue(forwardedHost)
  const expectedProtocol = effectiveProtocol(req)
  if (!expectedHost || !expectedProtocol) return false

  try {
    const parsedOrigin = new URL(origin)
    const parsedExpected = new URL(`${expectedProtocol}//${expectedHost}`)
    const hasOriginSuffix = parsedOrigin.pathname !== '/'
      || parsedOrigin.search !== ''
      || parsedOrigin.hash !== ''
      || parsedOrigin.username !== ''
      || parsedOrigin.password !== ''
    const hasInvalidExpectedAuthority = parsedExpected.pathname !== '/'
      || parsedExpected.search !== ''
      || parsedExpected.hash !== ''
      || parsedExpected.username !== ''
      || parsedExpected.password !== ''

    return !hasOriginSuffix
      && !hasInvalidExpectedAuthority
      && (parsedOrigin.protocol === 'http:' || parsedOrigin.protocol === 'https:')
      && parsedOrigin.origin === parsedExpected.origin
  } catch {
    return false
  }
}
