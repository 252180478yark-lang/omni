import { describe, it, expect } from 'vitest'
import { Readable } from 'node:stream'
import { parseStreamChunks, buildSpawnArgs } from '@/lib/agent-chat/claude-runner'

describe('claude-runner', () => {
  describe('buildSpawnArgs', () => {
    it('builds basic prompt args', () => {
      const args = buildSpawnArgs({
        prompt: 'hello',
        mcpConfigPath: '/tmp/mcp.json',
      })
      expect(args).toContain('-p')
      expect(args).toContain('hello')
      expect(args).toContain('--output-format')
      expect(args).toContain('stream-json')
      expect(args).toContain('--mcp-config')
      expect(args).toContain('/tmp/mcp.json')
      expect(args).toContain('--verbose')
    })

    it('adds --resume when resuming session', () => {
      const args = buildSpawnArgs({
        prompt: 'continue',
        mcpConfigPath: '/tmp/mcp.json',
        resumeSessionId: 'abc-123',
      })
      expect(args).toContain('--resume')
      expect(args).toContain('abc-123')
    })

    it('passes through allowed/disallowed tools', () => {
      const args = buildSpawnArgs({
        prompt: 'hello',
        mcpConfigPath: '/tmp/mcp.json',
        allowedTools: ['Bash(ls)', 'mcp__omni__list_skus'],
      })
      const idx = args.indexOf('--allowedTools')
      expect(idx).toBeGreaterThan(-1)
      expect(args[idx + 1]).toBe('Bash(ls),mcp__omni__list_skus')
    })
  })

  describe('parseStreamChunks', () => {
    it('parses 4 chunk types from stream-json output', async () => {
      const input = [
        '{"type":"system","subtype":"init","session_id":"sess-1"}',
        '{"type":"assistant","message":{"id":"m1","role":"assistant","content":[{"type":"text","text":"hi"}]},"session_id":"sess-1"}',
        '{"type":"assistant","message":{"id":"m2","role":"assistant","content":[{"type":"tool_use","id":"tu1","name":"list_skus","input":{}}]},"session_id":"sess-1"}',
        '{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu1","content":"ok"}]},"session_id":"sess-1"}',
        '{"type":"result","result":"done","duration_ms":1000,"total_cost_usd":0.01,"session_id":"sess-1"}',
      ].join('\n')

      const stream = Readable.from([input])
      const chunks: unknown[] = []
      for await (const c of parseStreamChunks(stream)) {
        chunks.push(c)
      }
      expect(chunks).toHaveLength(5)
      expect((chunks[0] as { type: string }).type).toBe('system')
      expect((chunks[4] as { type: string }).type).toBe('result')
    })

    it('handles partial line at buffer boundary', async () => {
      const stream = new Readable({ read() {} })
      stream.push('{"type":"system","sess')
      stream.push('ion_id":"sess-1"}\n')
      stream.push(null)
      const chunks: unknown[] = []
      for await (const c of parseStreamChunks(stream)) {
        chunks.push(c)
      }
      expect(chunks).toHaveLength(1)
    })
  })
})
