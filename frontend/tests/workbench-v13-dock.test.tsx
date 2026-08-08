// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { WorkbenchDock } from '@/components/workbench/WorkbenchDock'

vi.mock('@/components/system-command-center/SystemGraphView', () => ({
  SystemGraphView: () => <div>canonical blueprint</div>,
}))
vi.mock('@/components/system-command-center/RuntimeOverlay', () => ({
  RuntimeOverlay: () => <div>recoverable runs</div>,
}))

afterEach(cleanup)

describe('workbench progressive dock', () => {
  it('opens the canonical blueprint and closes it with Escape', () => {
    render(<WorkbenchDock />)
    fireEvent.click(screen.getByRole('button', { name: '查看运行链' }))

    expect(screen.getByRole('dialog', { name: '智能蓝图' })).toBeTruthy()
    expect(screen.getByText('canonical blueprint')).toBeTruthy()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('exposes the recoverable run center and explicit R3 footer', () => {
    render(<WorkbenchDock />)
    fireEvent.click(screen.getByRole('button', { name: '运行中心' }))

    expect(screen.getByText('recoverable runs')).toBeTruthy()
    expect(screen.getByText(/R3 仍需显式批准/)).toBeTruthy()
  })
})
