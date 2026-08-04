import { expect, test } from '@playwright/test'

const snapshot = {
  snapshot_id: `sha256:${'a'.repeat(64)}`,
  generated_at_utc: '2026-08-01T00:00:00Z',
  content: {
    nodes: [
      { id: 'ui_route:/workspace', kind: 'page', key: '/workspace', label: '工作台事实节点', state: { existence: 'observed', health: 'healthy', lifecycle: 'active', evidence: 'static' }, evidence: [{ path: 'frontend/src/app/workspace/page.tsx', line: 1, blob: 'abcdef0' }] },
      { id: 'service:unknown', kind: 'service', key: 'unknown', label: '运行来源未知', state: { existence: 'unknown', health: 'unknown', lifecycle: 'active', evidence: 'none' } },
    ],
    edges: [],
    source_results: [{ collector_id: 'frontend.static', version: '1', status: 'success' }, { collector_id: 'runtime', version: '1', status: 'unknown' }],
  },
}

const graphPage = {
  snapshot_id: snapshot.snapshot_id,
  generated_at_utc: snapshot.generated_at_utc,
  nodes: snapshot.content.nodes,
  edges: snapshot.content.edges,
  source_results: snapshot.content.source_results,
  partial: true,
  issues: [],
  orphan_node_ids: [],
  page_info: { next_cursor: null, has_more: false },
}

test('development mode renders partial facts and accessible fallback tree', async ({ page }) => {
  await page.route('**/api/omni/system-graph/snapshot', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(snapshot) }))
  await page.route('**/api/omni/system-graph/snapshots/**/graph?limit=500', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(graphPage) }))
  await page.route('**/api/omni/scout/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }))
  await page.goto('/workspace?mode=development')
  await expect(page.getByTestId('system-graph-success')).toBeVisible()
  await expect(page.getByText(/当前是部分快照/)).toBeVisible()
  await expect(page.getByTestId('system-graph-node-ui_route:/workspace')).toBeVisible()
  await page.getByText('无图形依赖树').click()
  await expect(page.getByRole('tree')).toBeVisible()
  await expect(page.getByText(/frontend\/src\/app\/workspace\/page.tsx:1/)).toBeVisible()
})

test('top-level graph route remains the canonical Development surface', async ({ page }) => {
  await page.goto('/system-graph')
  await expect(page).toHaveURL(/\/system-graph$/)
})
