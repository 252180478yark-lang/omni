/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import InboxPage from '@/app/inbox/page'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('inbox authentication UI', () => {
  it('opens directly as the local owner without rendering a product login form', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true, data: [], total: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    render(<InboxPage />)
    expect(await screen.findByRole('heading', { name: '待批' })).toBeTruthy()
    expect(await screen.findByText('暂无待批')).toBeTruthy()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())
    expect(fetchMock.mock.calls[0][0]).toBe('/api/omni/inbox')
    expect(screen.queryByLabelText('邮箱')).toBeNull()
    expect(screen.queryByLabelText('密码')).toBeNull()
    expect(screen.queryByRole('button', { name: '登录并进入待审批' })).toBeNull()
  })
})
