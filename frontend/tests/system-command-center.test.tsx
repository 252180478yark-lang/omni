// @vitest-environment happy-dom

import React from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SystemGraphView } from '@/components/system-command-center/SystemGraphView'

vi.mock('@/components/OutputFeedback', () => ({ default: () => <div>feedback-entry</div> }))

const snapshot = {
  snapshot_id: `sha256:${'a'.repeat(64)}`,
  generated_at_utc: '2026-08-01T00:00:00Z',
  content: {
    nodes: [
      { id: 'ui_route:/workspace', kind: 'page', key: '/workspace', label: '工作台', state: { existence: 'observed', health: 'healthy', lifecycle: 'active', evidence: 'static' }, evidence: [{ path: 'frontend/src/app/workspace/page.tsx', line: 1, blob: 'abcdef0' }] },
    ],
    edges: [],
    source_results: [{ collector_id: 'frontend', version: '1', status: 'success' }],
  },
}

function graphPage(source = snapshot) {
  return {
    snapshot_id: source.snapshot_id,
    generated_at_utc: source.generated_at_utc,
    nodes: source.content.nodes,
    edges: source.content.edges,
    source_results: source.content.source_results,
    partial: false,
    issues: [],
    orphan_node_ids: [],
    page_info: { next_cursor: null, has_more: false },
  }
}

function graphFetch(source = snapshot) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const body = url.includes('/snapshots/') ? graphPage(source) : source
    return new Response(JSON.stringify(body), { status: 200 })
  })
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('static system command center states', () => {
  it('renders the fact node, evidence drawer and accessible tree', async () => {
    vi.stubGlobal('fetch', graphFetch())
    render(<SystemGraphView />)
    expect(screen.getByTestId('system-graph-loading')).toBeTruthy()
    await waitFor(() => expect(screen.getByTestId('system-graph-success')).toBeTruthy())
    expect(screen.getAllByText('工作台').length).toBeGreaterThan(0)
    expect(screen.getByText(/frontend\/src\/app\/workspace\/page.tsx:1/)).toBeTruthy()
    expect(screen.getByRole('tree')).toBeTruthy()
    expect(screen.getByText('feedback-entry')).toBeTruthy()
  })

  it('does not represent an empty snapshot as success', async () => {
    const empty = { ...snapshot, content: { ...snapshot.content, nodes: [] } }
    vi.stubGlobal('fetch', graphFetch(empty))
    render(<SystemGraphView />)
    await waitFor(() => expect(screen.getByTestId('system-graph-empty')).toBeTruthy())
    expect(screen.getByText(/不会把空数据显示成健康/)).toBeTruthy()
  })

  it('shows a retryable typed error surface', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })))
    render(<SystemGraphView />)
    await waitFor(() => expect(screen.getByTestId('system-graph-error')).toBeTruthy())
    expect(screen.getByRole('alert').textContent).toContain('暂不可读')
  })
})
