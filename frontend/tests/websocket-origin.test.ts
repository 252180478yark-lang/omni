import type { IncomingMessage } from 'node:http'
import { describe, expect, it } from 'vitest'

import { isSameOriginWebSocketUpgrade } from '@/lib/agent-chat/ws-origin'

type UpgradeFixture = Pick<IncomingMessage, 'headers' | 'socket'>

function request(
  origin: string | undefined,
  options: {
    host?: string
    encrypted?: boolean
    forwardedHost?: string | string[]
    forwardedProto?: string | string[]
  } = {},
): UpgradeFixture {
  const headers: UpgradeFixture['headers'] = {
    host: options.host ?? '127.0.0.1:3000',
  }
  if (origin !== undefined) headers.origin = origin
  if (options.forwardedHost !== undefined) headers['x-forwarded-host'] = options.forwardedHost
  if (options.forwardedProto !== undefined) headers['x-forwarded-proto'] = options.forwardedProto

  return {
    headers,
    socket: { encrypted: options.encrypted === true } as unknown as UpgradeFixture['socket'],
  }
}

describe('WebSocket effective same-origin classification', () => {
  it('accepts exact direct HTTP and HTTPS origins', () => {
    expect(isSameOriginWebSocketUpgrade(request('http://127.0.0.1:3000'))).toBe(true)
    expect(isSameOriginWebSocketUpgrade(request('https://app.local', {
      host: 'app.local',
      encrypted: true,
    }))).toBe(true)
  })

  it('rejects direct cross-scheme and cross-host origins', () => {
    expect(isSameOriginWebSocketUpgrade(request('https://127.0.0.1:3000'))).toBe(false)
    expect(isSameOriginWebSocketUpgrade(request('http://app.local', {
      host: 'app.local',
      encrypted: true,
    }))).toBe(false)
    expect(isSameOriginWebSocketUpgrade(request('http://localhost:3000'))).toBe(false)
  })

  it('uses the first forwarded scheme and host behind a local TLS proxy', () => {
    expect(isSameOriginWebSocketUpgrade(request('https://owner.local', {
      host: 'frontend:3000',
      forwardedHost: ' owner.local, ignored.local ',
      forwardedProto: ' https, http ',
    }))).toBe(true)
    expect(isSameOriginWebSocketUpgrade(request('https://owner.local', {
      host: 'frontend:3000',
      forwardedHost: ['owner.local', 'ignored.local'],
      forwardedProto: ['https', 'http'],
    }))).toBe(true)
  })

  it('rejects invalid or mismatched forwarded values instead of falling back', () => {
    expect(isSameOriginWebSocketUpgrade(request('http://127.0.0.1:3000', {
      forwardedProto: '',
    }))).toBe(false)
    expect(isSameOriginWebSocketUpgrade(request('https://owner.local', {
      forwardedHost: '',
      forwardedProto: 'https',
    }))).toBe(false)
    expect(isSameOriginWebSocketUpgrade(request('http://owner.local', {
      forwardedHost: 'owner.local',
      forwardedProto: 'https',
    }))).toBe(false)
  })

  it('rejects missing, malformed, non-HTTP and non-origin URL values', () => {
    expect(isSameOriginWebSocketUpgrade(request(undefined))).toBe(false)
    expect(isSameOriginWebSocketUpgrade(request('null'))).toBe(false)
    expect(isSameOriginWebSocketUpgrade(request('ws://127.0.0.1:3000'))).toBe(false)
    expect(isSameOriginWebSocketUpgrade(request('wss://127.0.0.1:3000'))).toBe(false)
    expect(isSameOriginWebSocketUpgrade(request('http://127.0.0.1:3000/path'))).toBe(false)
    expect(isSameOriginWebSocketUpgrade(request('http://user@127.0.0.1:3000'))).toBe(false)
  })
})
