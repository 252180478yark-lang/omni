import { describe, it, expect } from 'vitest'
import path from 'node:path'
import { readSessionHistory, encodeProjectDir } from '@/lib/agent-chat/history-reader'

const SAMPLE = path.join(__dirname, '../fixtures/sample-session.jsonl')

describe('history-reader', () => {
  it('encodes project dir to claude code format', () => {
    expect(encodeProjectDir('E:\\agent\\omni')).toBe('E--agent-omni')
    expect(encodeProjectDir('/home/user/project')).toBe('-home-user-project')
  })

  it('parses sample jsonl into ChatMessage[]', async () => {
    const messages = await readSessionHistory(SAMPLE)
    expect(messages).toHaveLength(5)
    expect(messages[0]).toMatchObject({ role: 'user', text: '列一下我的 SKU' })
    expect(messages[1]).toMatchObject({ role: 'assistant', text: '我帮你查' })
    expect(messages[2]).toMatchObject({
      role: 'tool_call',
      tool_name: 'list_skus',
      tool_args: { status: 'active' },
      tool_use_id: 'toolu-1',
    })
    expect(messages[3]).toMatchObject({ role: 'tool_result', tool_use_id: 'toolu-1' })
    expect(messages[4]).toMatchObject({ role: 'assistant', text: '你有 1 个 SKU' })
  })

  it('returns empty array if file missing', async () => {
    const messages = await readSessionHistory('/tmp/does-not-exist.jsonl')
    expect(messages).toEqual([])
  })
})
