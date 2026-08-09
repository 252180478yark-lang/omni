'use client'

import { useSearchParams } from 'next/navigation'

import { ContentWorkspace } from '@/components/content-workspace'
import { SystemCommandCenter } from '@/components/system-command-center/SystemCommandCenter'
import { useWorkbenchStore } from '@/stores/workbenchStore'

export default function WorkspacePage() {
  const mode = useWorkbenchStore((state) => state.mode)
  const searchParams = useSearchParams()
  const initialView = searchParams.get('mode') === 'execution' ? 'runtime' : 'graph'

  return mode === 'development'
    ? <SystemCommandCenter initialView={initialView} />
    : <ContentWorkspace />
}
