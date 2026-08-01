// @vitest-environment happy-dom

import React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { RuntimeRadar } from '@/components/system-command-center/RuntimeRadar'
import { factualExplanation, reduceRuntimeEvents } from '@/lib/system-command-center/runtime-reducer'
import type { RuntimeEvent } from '@/lib/system-command-center/runtime-model'

const event = (overrides: Partial<RuntimeEvent> = {}): RuntimeEvent => ({
  cursor: 1, source: 'mcp.audit', event_id: 'event:one', trace_id: 'trace:one', execution_id: 'run:one', span_id: 'span:one', parent_span_id: null,
  correlation_id: null, session_id: null, gate_id: null, sequence: 2, event_type: 'completed', status: 'completed', span_kind: 'tool', node_id: 'mcp_tool:list_skus', read_write: 'read',
  payload_schema: ['tool_name'], payload_summary: { tool_name: 'list_skus' }, observed_at: '2026-08-01T00:00:00Z', received_at: '2026-08-01T00:00:00Z', retention_until: '2026-09-01T00:00:00Z', ordering: 'known', ...overrides,
})

afterEach(cleanup)

describe('runtime execution overlay facts', () => {
  it('deduplicates reconnect events and marks unordered gaps without drawing a continuation', () => {
    const first = reduceRuntimeEvents({ mode: 'disconnected', cursor: 0, events: [], gaps: 0 }, [event(), event()])
    expect(first.events).toHaveLength(1)
    const gap = reduceRuntimeEvents(first, [event({ cursor: 2, event_id: 'event:two', sequence: null, event_type: 'gap', node_id: null, status: 'partial' })])
    expect(gap.mode).toBe('partial')
    expect(gap.gaps).toBeGreaterThan(0)
    expect(factualExplanation(gap.events.at(-1)!)).toContain('没有足够证据')
  })

  it('visibly separates deterministic facts from AI suggestions', () => {
    render(<RuntimeRadar findings={[
      { fingerprint: 'sha256:' + 'a'.repeat(64), detector_version: 'v1', code: 'runtime_event_unmapped', severity: 'warning', classification: 'observed_fact', state: 'open', layers: ['fact', 'runtime'], trace_id: 'trace:one', message_zh: '真实缺口', evidence: [], repair_hint: '补埋点', verification: '重放' },
      { fingerprint: 'sha256:' + 'b'.repeat(64), detector_version: 'v1', code: 'idea', severity: 'info', classification: 'hypothesis', state: 'open', layers: ['planned'], trace_id: 'trace:one', message_zh: '建议', evidence: [], repair_hint: '确认', verification: '验证' },
    ]} />)
    expect(screen.getByText('确定性事实')).toBeTruthy()
    expect(screen.getByText('AI 建议')).toBeTruthy()
  })
})
