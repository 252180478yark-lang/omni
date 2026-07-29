/**
 * @vitest-environment happy-dom
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import InboxPage from '@/app/inbox/page'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('inbox authentication UI', () => {
  it('shows a repair login on 401 and reloads through an HttpOnly BFF session', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: false, error: 'authentication_required' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true, actor: { id: 'admin@example.com', role: 'admin' } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true, data: [], total: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    render(<InboxPage />)
    expect(await screen.findByRole('heading', { name: '审批登录' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'admin@example.com' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByRole('button', { name: '登录并进入待审批' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    const loginCall = fetchMock.mock.calls[1]
    expect(loginCall[0]).toBe('/api/omni/auth/session')
    expect(loginCall[1]).toMatchObject({ method: 'POST', credentials: 'same-origin' })
    expect(JSON.parse(loginCall[1].body)).toEqual({
      email: 'admin@example.com',
      password: 'password123',
    })
    expect(document.body.textContent).not.toContain('header.payload.signature')
  })
})
