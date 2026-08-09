'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { Activity, Bot, Boxes, Loader2, ShieldCheck, X } from 'lucide-react'

import { RuntimeOverlay } from '@/components/system-command-center/RuntimeOverlay'
import { SystemGraphView } from '@/components/system-command-center/SystemGraphView'
import { buildWorkbenchActionCard, type WorkbenchActionCard } from '@/lib/workbench-runtime'
import { cn } from '@/lib/utils'
import { useWorkbenchStore } from '@/stores/workbenchStore'

type DockPanel = 'assistant' | 'blueprint' | 'runs'

const PANEL_LABEL: Record<DockPanel, string> = {
  assistant: '证据助手',
  blueprint: '智能蓝图',
  runs: '运行中心',
}

function AssistantPanel() {
  const [question, setQuestion] = useState('')
  const [phase, setPhase] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [card, setCard] = useState<WorkbenchActionCard | null>(null)
  const contextLabel = useWorkbenchStore((state) => state.contextLabel)
  const contextRevision = useWorkbenchStore((state) => state.contextRevision)

  const generate = async () => {
    setPhase('loading')
    try {
      const response = await fetch('/api/omni/workbench/suggestions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ question }),
      })
      const suggestion = await response.json().catch(() => null) as WorkbenchActionCard | null
      setCard(suggestion?.evidenceState ? suggestion : buildWorkbenchActionCard(null, question))
      setPhase(response.ok ? 'ready' : 'error')
    } catch {
      setCard(buildWorkbenchActionCard(null, question))
      setPhase('error')
    }
  }

  return (
    <section className="space-y-4" aria-label="上下文证据助手">
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
        <p className="font-semibold text-slate-900">当前上下文</p>
        <p className="mt-1">{contextLabel || '尚未选择经营对象'} · {contextRevision || 'revision unknown'}</p>
      </div>
      <label className="block text-sm font-medium text-slate-800">
        想判断什么？
        <textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：现在最值得先处理哪个问题？"
          className="workbench-focusable mt-2 min-h-24 w-full resize-y rounded-xl border border-slate-200 bg-white p-3 text-sm"
        />
      </label>
      <button
        type="button"
        onClick={() => void generate()}
        disabled={phase === 'loading'}
        className="workbench-focusable inline-flex items-center gap-2 rounded-lg bg-violet-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
      >
        {phase === 'loading' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Bot className="h-4 w-4" aria-hidden="true" />}
        基于证据生成建议
      </button>

      {card ? (
        <article className="space-y-4 rounded-xl border border-slate-200 bg-white p-4" data-testid="workbench-action-card">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">观察</h3>
            {card.observations.length ? (
              <ul className="mt-2 space-y-1 text-sm text-slate-700">{card.observations.map((item) => <li key={item}>• {item}</li>)}</ul>
            ) : <p className="mt-2 text-sm text-amber-800">没有可引用的事实证据。</p>}
          </div>
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-violet-700">推断</h3>
            <p className="mt-2 text-sm leading-6 text-slate-700">{card.inference}</p>
          </div>
          <div className="rounded-lg border border-violet-200 bg-violet-50 p-3">
            <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-violet-800">建议动作</h3>
            <p className="mt-2 text-sm font-medium text-slate-900">{card.action}</p>
            <dl className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
              <div><dt>风险</dt><dd className="font-semibold text-slate-900">{card.riskLevel}</dd></div>
              <div><dt>审批</dt><dd className="font-semibold text-slate-900">{card.approvalRequired ? '需要 Human Gate' : '不需要'}</dd></div>
              <div className="sm:col-span-2"><dt>拟用工具</dt><dd className="font-mono text-slate-800">{card.toolPlan.join(' → ')}</dd></div>
              <div className="sm:col-span-2"><dt>预期影响</dt><dd className="text-slate-800">{card.expectedImpact}</dd></div>
            </dl>
          </div>
          {card.evidenceRefs.length ? (
            <details className="rounded-lg border border-blue-200 bg-blue-50 p-3">
              <summary className="cursor-pointer text-sm font-semibold text-blue-900">证据 {card.evidenceRefs.length} 条</summary>
              <ul className="mt-2 space-y-2 text-xs text-blue-950">{card.evidenceRefs.map((item) => <li key={item.id}><span className="font-semibold">{item.label}</span><br />{item.source} · {item.observedAt || '时间未知'}</li>)}</ul>
            </details>
          ) : null}
          {card.nextEvidenceStep ? <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">补证方式：{card.nextEvidenceStep}</p> : null}
        </article>
      ) : (
        <p className="rounded-xl border border-dashed border-slate-300 p-5 text-center text-sm text-slate-500">建议不会凭空生成；先读取当前事实快照。</p>
      )}
    </section>
  )
}

export function WorkbenchDock() {
  const [panel, setPanel] = useState<DockPanel | null>(null)
  const titleId = useId()
  const closeButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!panel) return
    closeButton.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPanel(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [panel])

  return (
    <>
      <nav className="fixed bottom-4 right-4 z-[80] flex items-center gap-2 rounded-2xl border border-slate-200 bg-white/95 p-2 shadow-xl backdrop-blur" aria-label="AI 工作台工具">
        <span hidden data-workbench-slot="approval" />
        {([
          ['assistant', Bot, '证据助手'],
          ['blueprint', Boxes, '查看运行链'],
          ['runs', Activity, '运行中心'],
        ] as const).map(([id, Icon, label]) => (
          <button
            key={id}
            type="button"
            aria-expanded={panel === id}
            aria-controls="workbench-progressive-panel"
            data-workbench-slot={id === 'runs' ? 'run-center' : id}
            onClick={() => setPanel((current) => current === id ? null : id)}
            className={cn('workbench-focusable flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold', panel === id ? 'bg-slate-950 text-white' : 'text-slate-700 hover:bg-slate-100')}
          >
            <Icon className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
      </nav>

      {panel ? (
        <aside
          id="workbench-progressive-panel"
          role="dialog"
          aria-modal="false"
          aria-labelledby={titleId}
          className="fixed inset-y-0 right-0 z-[90] w-full overflow-y-auto border-l border-slate-200 bg-slate-50 shadow-2xl sm:w-[min(760px,calc(100vw-72px))]"
          data-testid={`workbench-${panel}-panel`}
        >
          <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white/95 px-5 py-4 backdrop-blur">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-violet-700">Omni AI Blueprint</p>
              <h2 id={titleId} className="mt-1 text-lg font-semibold text-slate-950">{PANEL_LABEL[panel]}</h2>
            </div>
            <button ref={closeButton} type="button" onClick={() => setPanel(null)} className="workbench-focusable rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-100" aria-label={`关闭${PANEL_LABEL[panel]}`}><X className="h-4 w-4" /></button>
          </header>
          <div className="p-4 sm:p-5">
            {panel === 'assistant' ? <AssistantPanel /> : null}
            {panel === 'blueprint' ? <SystemGraphView /> : null}
            {panel === 'runs' ? <RuntimeOverlay /> : null}
          </div>
          <footer data-workbench-slot="approval" className="border-t border-slate-200 bg-white px-5 py-3 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1"><ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />R3 仍需显式批准；unknown 不会显示为成功。</span>
          </footer>
        </aside>
      ) : null}
    </>
  )
}
