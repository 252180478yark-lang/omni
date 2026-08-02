'use client'

import { useEffect, useMemo } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { AlertTriangle, ArrowLeft, RouteOff } from 'lucide-react'

import { resolveWorkbenchLocation } from '@/lib/workbench-ia'

const REPORT_DEDUPE_MS = 10_000
const MAX_RECENT_REPORTS = 64
const recentReports = new Map<string, number>()

function reserveGapReport(key: string): boolean {
  const now = Date.now()
  recentReports.forEach((observedAt, candidate) => {
    if (now - observedAt > REPORT_DEDUPE_MS) recentReports.delete(candidate)
  })
  const previous = recentReports.get(key)
  if (previous !== undefined && now - previous <= REPORT_DEDUPE_MS) return false
  recentReports.set(key, now)
  while (recentReports.size > MAX_RECENT_REPORTS) {
    const oldest = recentReports.keys().next().value
    if (typeof oldest !== 'string') break
    recentReports.delete(oldest)
  }
  return true
}

export default function NotFound() {
  const pathname = usePathname() || '/'
  const location = useMemo(() => resolveWorkbenchLocation(pathname), [pathname])
  const gapKind = location.kind === 'ambiguous' || location.kind === 'unregistered'
    ? location.kind
    : null

  useEffect(() => {
    if (!gapKind) return
    const key = `${gapKind}:${location.requestedHref}`
    if (!reserveGapReport(key)) return
    void fetch('/api/omni/workbench/navigation-events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      keepalive: true,
      body: JSON.stringify({
        event_type: 'route_gap',
        requested_href: location.requestedHref,
        result: gapKind,
      }),
    }).catch(() => undefined)
  }, [gapKind, location.requestedHref])

  const ambiguous = gapKind === 'ambiguous'
  const title = ambiguous
    ? '入口归属冲突'
    : gapKind === 'unregistered'
      ? '此入口尚未登记'
      : '页面暂不可用'
  const description = ambiguous
    ? '该入口存在多个能力归属，系统已停止自动跳转，避免打开错误页面。'
    : gapKind === 'unregistered'
      ? '该地址尚未登记到统一工作台；原有页面与数据不会因此被删除。'
      : '当前页面无法呈现，请返回工作台后重试。'
  const Icon = ambiguous ? AlertTriangle : RouteOff

  return (
    <section
      aria-labelledby="workbench-not-found-title"
      className="mx-auto flex min-h-[60vh] w-full max-w-3xl items-center px-6 py-12"
      data-gap-kind={gapKind || 'unavailable'}
      data-testid="workbench-route-gap"
      role="alert"
    >
      <div className="w-full rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-amber-50 text-amber-700">
          <Icon aria-hidden="true" className="h-6 w-6" />
        </div>
        <p className="mb-2 text-sm font-semibold text-amber-700">兼容入口</p>
        <h1 id="workbench-not-found-title" className="text-2xl font-bold text-slate-950">
          {title}
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600">{description}</p>
        <p className="mt-4 text-sm text-slate-500">
          请求路径：{' '}
          <code className="break-all rounded bg-slate-100 px-2 py-1 text-slate-800">
            {location.requestedHref}
          </code>
        </p>
        <Link
          className="workbench-focusable mt-7 inline-flex items-center gap-2 rounded-lg bg-violet-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-800"
          href="/workspace"
        >
          <ArrowLeft aria-hidden="true" className="h-4 w-4" />
          返回工作台
        </Link>
      </div>
    </section>
  )
}
