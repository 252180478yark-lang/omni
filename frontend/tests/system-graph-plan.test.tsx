/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

const routerMock = { replace: vi.fn() }
const legacySearchParams = new URLSearchParams('legacy_plan=1')

vi.mock('next/navigation', () => ({
  useRouter: () => routerMock,
  useSearchParams: () => legacySearchParams,
}))

import SystemGraphPlanPage from '@/app/system-graph/page'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function response(body: object, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('system graph owner co-design page', () => {
  it('shows loading then the empty state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ plans: [], summaries: {} })))
    render(<SystemGraphPlanPage />)
    expect(screen.getByLabelText('正在加载候选计划')).toBeTruthy()
    expect(await screen.findByText(/暂无候选计划/)).toBeTruthy()
  })

  it('shows upstream errors instead of an empty state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ message: '事实快照不可用' }, 503)))
    render(<SystemGraphPlanPage />)
    expect((await screen.findByRole('alert')).textContent).toContain('事实快照不可用')
    expect(screen.queryByText(/暂无候选计划/)).toBeNull()
  })

  it('renders partial evidence and prevents freezing critical unknowns', async () => {
    const plan = {
      plan_id: 'plan-aaaaaaaaaaaaaaaa', feature_id: 'candidate-a', base_snapshot_id: `sha256:${'a'.repeat(64)}`,
      revision: 2, state: 'reviewing', snapshot_status: 'partial', missing_sources: ['catalog.openapi'],
      updated_at_utc: '2026-08-01T00:00:00Z', archived_reason: '',
      items: [{
        item_id: 'api', layer: 'api', target_ref: 'candidate:candidate-a:api', decision: 'unknown',
        evidence_class: 'hypothesis', evidence_refs: [], recommendation: '', rationale: '',
        missing_evidence: 'OpenAPI collector unavailable', verification: 'rescan OpenAPI', risk: 'R2', critical: true,
        review_status: 'pending', review_note: '',
      }],
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      plans: [plan], summaries: { [plan.plan_id]: { facts: 0, recommendations: 0, hypotheses: 1, pending_reviews: 1, critical_unknowns: 1, snapshot_status: 'partial', missing_sources: ['catalog.openapi'] } },
    })))
    render(<SystemGraphPlanPage />)
    expect(await screen.findByText('快照部分可用')).toBeTruthy()
    expect(screen.getByText(/缺失来源：catalog.openapi/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '确认并冻结接入合同' }).hasAttribute('disabled')).toBe(true)
  })

  it('creates a candidate through the owner BFF', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ plans: [], summaries: {} }))
      .mockResolvedValueOnce(response({
        plan: { plan_id: 'plan-bbbbbbbbbbbbbbbb', feature_id: 'feature-b', base_snapshot_id: `sha256:${'b'.repeat(64)}`, revision: 1, state: 'draft', items: [], snapshot_status: 'complete', missing_sources: [], updated_at_utc: '2026-08-01T00:00:00Z', archived_reason: '' },
        summary: { facts: 0, recommendations: 0, hypotheses: 0, pending_reviews: 0, critical_unknowns: 0, snapshot_status: 'complete', missing_sources: [] },
      }))
    vi.stubGlobal('fetch', fetchMock)
    render(<SystemGraphPlanPage />)
    await screen.findByText(/暂无候选计划/)
    fireEvent.change(screen.getByLabelText('功能 ID'), { target: { value: 'feature-b' } })
    fireEvent.change(screen.getByLabelText('事实快照 ID'), { target: { value: `sha256:${'b'.repeat(64)}` } })
    fireEvent.change(screen.getByLabelText('需求意图'), { target: { value: '新增共创入口' } })
    fireEvent.click(screen.getByRole('button', { name: '创建候选节点' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][0]).toBe('/api/omni/system-graph/integration-plans')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ feature_id: 'feature-b', items: [] })
  })

  it('rebases a stale candidate onto an explicit immutable snapshot', async () => {
    const stale = {
      plan_id: 'plan-cccccccccccccccc', feature_id: 'feature-c', base_snapshot_id: `sha256:${'c'.repeat(64)}`,
      revision: 3, state: 'stale', items: [], snapshot_status: 'complete', missing_sources: [],
      updated_at_utc: '2026-08-01T00:00:00Z', archived_reason: '',
    }
    const rebased = { ...stale, revision: 4, state: 'draft', base_snapshot_id: `sha256:${'d'.repeat(64)}` }
    const summary = { facts: 0, recommendations: 0, hypotheses: 0, pending_reviews: 0, critical_unknowns: 0, snapshot_status: 'complete', missing_sources: [] }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ plans: [stale], summaries: { [stale.plan_id]: summary } }))
      .mockResolvedValueOnce(response({ plan: rebased, summary }))
    vi.stubGlobal('fetch', fetchMock)
    render(<SystemGraphPlanPage />)
    await screen.findByLabelText('新快照 ID')
    fireEvent.change(screen.getByLabelText('新快照 ID'), { target: { value: rebased.base_snapshot_id } })
    fireEvent.click(screen.getByRole('button', { name: '重基线并重新确认' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls[1][0]).toBe(`/api/omni/system-graph/integration-plans/${stale.plan_id}/rebase`)
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({
      expected_revision: 3,
      base_snapshot_id: rebased.base_snapshot_id,
    })
  })
})
