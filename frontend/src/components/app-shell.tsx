'use client'

import React from 'react'
import { usePathname } from 'next/navigation'
import { AppSidebar } from './app-sidebar'

const FULL_SCREEN_ROUTES = ['/chat']

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isFullScreen = FULL_SCREEN_ROUTES.some((r) => pathname.startsWith(r))

  if (isFullScreen) {
    return (
      <div className="flex min-h-screen">
        <AppSidebar />
        <div className="flex-1 ml-[68px] min-h-screen">
          {children}
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex-1 ml-[68px] min-h-screen">
        {children}
      </main>
    </div>
  )
}
