'use client'

import { AppLayout } from '@/components/tri-mind/layout/AppLayout'
import { useAppShortcuts } from '@/hooks/tri-mind/useAppShortcuts'
import { useEffect } from 'react'
import { useConfigStore } from '@/stores/tri-mind/configStore'

export default function TriMindPage() {
  useAppShortcuts()
  const initConfig = useConfigStore((s) => s.initConfig)

  useEffect(() => {
    initConfig()
  }, [initConfig])

  return (
    <div className="h-screen w-screen overflow-hidden bg-[#F5F5F7] text-gray-900 antialiased">
      <AppLayout />
    </div>
  )
}
