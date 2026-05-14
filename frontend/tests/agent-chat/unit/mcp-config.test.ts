import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { buildMcpConfig, getOmniMcpUrl } from '@/lib/agent-chat/mcp-config'

describe('mcp-config', () => {
  let originalEnv: string | undefined

  beforeEach(() => {
    originalEnv = process.env.OMNI_KE_URL
  })

  afterEach(() => {
    process.env.OMNI_KE_URL = originalEnv
  })

  it('returns omni mcp http url with default 8002 port', () => {
    delete process.env.OMNI_KE_URL
    expect(getOmniMcpUrl()).toBe('http://localhost:8002/mcp')
  })

  it('respects OMNI_KE_URL env var', () => {
    process.env.OMNI_KE_URL = 'http://example.com:9000'
    expect(getOmniMcpUrl()).toBe('http://example.com:9000/mcp')
  })

  it('builds claude code mcp config with omni server entry', () => {
    delete process.env.OMNI_KE_URL
    const config = buildMcpConfig()
    expect(config.mcpServers).toBeDefined()
    expect(config.mcpServers.omni).toEqual({
      type: 'http',
      url: 'http://localhost:8002/mcp',
    })
  })
})
