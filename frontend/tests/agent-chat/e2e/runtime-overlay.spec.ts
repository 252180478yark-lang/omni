import { expect, test } from '@playwright/test'

const runtimeEvent = {
  cursor: 1, source: 'mcp.audit', event_id: 'event:one', trace_id: 'trace:browser', execution_id: 'execution:browser',
  span_id: 'tool:one', parent_span_id: null, correlation_id: 'correlation:browser', session_id: 'session:browser', gate_id: null,
  sequence: 1, event_type: 'completed', status: 'completed', span_kind: 'tool', node_id: 'mcp_tool:list_skus', read_write: 'read',
  payload_schema: ['tool_name', 'duration_ms'], payload_summary: { tool_name: 'list_skus', duration_ms: 12 },
  observed_at: '2026-08-01T00:00:00Z', received_at: '2026-08-01T00:00:00Z', retention_until: '2026-09-01T00:00:00Z', ordering: 'known',
}

test('execution mode renders factual graph, playback, plan draft and host degradation', async ({ page }) => {
  await page.route('**/api/omni/runtime-traces/**', async (route) => {
    if (route.request().url().endsWith('/active')) return route.fulfill({ json: { runs: [] } })
    return route.fulfill({ json: {
      trace_id: 'trace:browser', events: [runtimeEvent], next_cursor: 1, replay_hash: `sha256:${'a'.repeat(64)}`,
      partial: false, has_more: false, dropped_count: 0, redacted_count: 0,
    } })
  })
  await page.route('**/api/omni/system-graph/snapshot', async (route) => route.fulfill({ json: {
    snapshot_id: `sha256:${'b'.repeat(64)}`, content: {
      nodes: [{ id: 'mcp_tool:list_skus', kind: 'mcp_tool', key: 'list_skus', label: 'MCP list_skus', state: { existence: 'observed', health: 'healthy', lifecycle: 'active', evidence: 'both' } }],
      edges: [],
    },
  } }))
  await page.route('**/api/omni/host-bridge/health', async (route) => route.fulfill({ status: 503, json: { state: 'unavailable' } }))
  await page.route('**/api/omni/runtime-findings**', async (route) => route.fulfill({ json: {
    trace_id: 'trace:browser', source_status: 'success', findings: [{
      fingerprint: `sha256:${'c'.repeat(64)}`, detector_version: 'v1', code: 'delivery_not_attested', severity: 'warning',
      classification: 'observed_fact', state: 'open', layers: ['delivery'], trace_id: 'trace:browser',
      message_zh: '候选尚未交付', evidence: ['delivery_state:verified_not_delivered'], repair_hint: '等待外部回执', verification: '检查 DeliveryReceipt',
    }],
  } }))
  await page.route('**/api/omni/runtime-plan-drafts', async (route) => route.fulfill({ json: {
    draft_id: `plan:${'d'.repeat(32)}`, finding_fingerprint: `sha256:${'c'.repeat(64)}`, trace_id: 'trace:browser',
    base_snapshot_id: `sha256:${'b'.repeat(64)}`, title: '修复候选', status: 'active', version: 1, reused: false,
  } }))

  await page.goto('/workspace/execution?trace_id=trace:browser')
  const execution = page.getByRole('region', { name: '执行模式' })
  await expect(execution).toBeVisible()
  await expect(execution.getByRole('img', { name: '实际执行路径图' })).toBeVisible()
  await expect(execution.getByText(/经过模块：mcp_tool:list_skus/)).toBeVisible()
  await expect(execution.getByText(/Host Bridge：unavailable/)).toBeVisible()
  await execution.getByRole('button', { name: /回放/ }).click()
  await expect(execution.getByLabel('回放控制')).toBeVisible()
  await expect(execution.getByLabel('回放跳转')).toBeVisible()
  await execution.getByRole('button', { name: /单步/ }).click()
  await execution.getByRole('button', { name: '加入候选计划（仅草稿）' }).click()
  await expect(execution.getByRole('status')).toContainText('尚未确认，也未执行任何修复')
})

test('execution mode does not turn empty evidence into success', async ({ page }) => {
  await page.goto('/workspace/execution')
  const execution = page.getByRole('region', { name: '执行模式' })
  await expect(execution.getByText('空结果不是成功。')).toBeVisible()
  await expect(execution.getByText(/Host Bridge：(unknown|unavailable)/)).toBeVisible()
})
