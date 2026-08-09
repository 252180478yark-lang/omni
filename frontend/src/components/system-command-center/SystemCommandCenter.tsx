'use client'

import { useEffect, useState } from 'react'
import { Activity, Boxes } from 'lucide-react'

import { RuntimeOverlay } from './RuntimeOverlay'
import { SystemGraphView } from './SystemGraphView'
import { cn } from '@/lib/utils'

export type SystemCommandCenterView = 'graph' | 'runtime'

export function SystemCommandCenter({ initialView = 'graph' }: { initialView?: SystemCommandCenterView }) {
  const [view, setView] = useState<SystemCommandCenterView>(initialView)

  useEffect(() => setView(initialView), [initialView])

  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8" data-testid="system-command-center">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-5 border-b border-slate-200 pb-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-700">Development Control Plane</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.03em] text-slate-950">系统中台</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            静态事实图与运行证据共用一个入口；未知保持未知，计划不冒充事实。
          </p>
        </div>
        <div className="grid grid-cols-2 gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1" role="tablist" aria-label="系统中台视图">
          <button
            type="button"
            role="tab"
            aria-selected={view === 'graph'}
            className={cn('workbench-focusable flex items-center gap-2 rounded-md px-3 py-2 text-xs font-semibold transition-colors', view === 'graph' ? 'bg-slate-950 text-white' : 'text-slate-500 hover:bg-white hover:text-slate-900')}
            onClick={() => setView('graph')}
          >
            <Boxes className="h-3.5 w-3.5" aria-hidden="true" />
            系统图谱
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === 'runtime'}
            className={cn('workbench-focusable flex items-center gap-2 rounded-md px-3 py-2 text-xs font-semibold transition-colors', view === 'runtime' ? 'bg-slate-950 text-white' : 'text-slate-500 hover:bg-white hover:text-slate-900')}
            onClick={() => setView('runtime')}
          >
            <Activity className="h-3.5 w-3.5" aria-hidden="true" />
            运行证据
          </button>
        </div>
      </header>

      <div role="tabpanel" aria-label={view === 'graph' ? '系统图谱' : '运行证据'}>
        {view === 'graph' ? <SystemGraphView /> : <RuntimeOverlay />}
      </div>
    </div>
  )
}
