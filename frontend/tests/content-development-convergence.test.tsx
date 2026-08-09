// @vitest-environment happy-dom

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WorkspacePage from '@/app/workspace/page'
import WorkspaceDevelopmentPage from '@/app/workspace/development/page'
import { ContentWorkspace } from '@/components/content-workspace'
import { SystemCommandCenter } from '@/components/system-command-center/SystemCommandCenter'
import { useWorkbenchStore } from '@/stores/workbenchStore'

let workspaceQuery = ''

vi.mock('next/navigation', async () => {
  const actual = await vi.importActual<typeof import('next/navigation')>('next/navigation')
  return {
    ...actual,
    useSearchParams: () => new URLSearchParams(workspaceQuery),
  }
})

vi.mock('@/components/system-command-center/SystemGraphView', () => ({
  SystemGraphView: () => <div data-testid="graph-view">graph evidence</div>,
}))

vi.mock('@/components/system-command-center/RuntimeOverlay', () => ({
  RuntimeOverlay: () => <div data-testid="runtime-view">runtime evidence</div>,
}))

beforeEach(() => {
  workspaceQuery = ''
  useWorkbenchStore.getState().reset()
  useWorkbenchStore.getState().hydrateMode('work', null)
})

afterEach(() => cleanup())

describe('content and development surface convergence', () => {
  it('projects exactly three content groups from FeatureDefinition', () => {
    render(<ContentWorkspace />)

    expect(document.querySelectorAll('[data-content-group]')).toHaveLength(3)
    expect(screen.getByRole('heading', { name: '内容生产' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '拆解分析' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '资产资料' })).toBeTruthy()
    expect(screen.getByRole('link', { name: /SKU 圈包链路/ }).getAttribute('href')).toBe('/sku-pipeline')
    expect(screen.getByRole('link', { name: /知识库与 RAG/ }).getAttribute('href')).toBe('/knowledge')
  })

  it('reuses one command center for graph and runtime evidence', () => {
    render(<SystemCommandCenter initialView="runtime" />)

    expect(screen.getByTestId('runtime-view')).toBeTruthy()
    expect(screen.queryByTestId('graph-view')).toBeNull()
    fireEvent.click(screen.getByRole('tab', { name: '系统图谱' }))
    expect(screen.getByTestId('graph-view')).toBeTruthy()
    expect(screen.queryByTestId('runtime-view')).toBeNull()
  })

  it('renders the canonical development route through the shared command center', () => {
    render(<WorkspaceDevelopmentPage />)

    expect(screen.getByTestId('system-command-center')).toBeTruthy()
    expect(screen.getByTestId('graph-view')).toBeTruthy()
  })

  it('switches the shared workspace renderer without changing route identity', () => {
    const view = render(<WorkspacePage />)
    expect(screen.getByTestId('content-workspace')).toBeTruthy()

    act(() => useWorkbenchStore.getState().setMode('development', null))
    expect(screen.getByTestId('system-command-center')).toBeTruthy()
    expect(screen.getByTestId('graph-view')).toBeTruthy()

    workspaceQuery = 'mode=execution'
    view.rerender(<WorkspacePage />)
    expect(screen.getByTestId('runtime-view')).toBeTruthy()
  })
})
