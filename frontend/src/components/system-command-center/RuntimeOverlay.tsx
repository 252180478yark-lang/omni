'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertTriangle, Clipboard, Clock3, Pause, Play, Radio, RotateCcw, StepForward } from 'lucide-react'

import { ExecutionGraph } from './ExecutionGraph'
import { RuntimeRadar } from './RuntimeRadar'
import type {
  RuntimeEventPage,
  RuntimeExecutionSummary,
  RuntimeFinding,
  RuntimeFindingPage,
  RuntimePlanDraft,
  SystemGraphSnapshot,
} from '@/lib/system-command-center/runtime-model'
import { factualExplanation, reduceRuntimeEvents, type RuntimeTimeline } from '@/lib/system-command-center/runtime-reducer'

const initialTimeline: RuntimeTimeline = { mode: 'disconnected', cursor: 0, events: [], gaps: 0 }

function traceFromLocation(): string {
  if (typeof window === 'undefined') return ''
  return new URLSearchParams(window.location.search).get('trace_id') || ''
}

export function RuntimeOverlay() {
  const [traceId, setTraceId] = useState(traceFromLocation)
  const [timeline, setTimeline] = useState(initialTimeline)
  const cursor = useRef(0)
  const [findings, setFindings] = useState<RuntimeFindingPage | null>(null)
  const [snapshot, setSnapshot] = useState<SystemGraphSnapshot | null>(null)
  const [hostState, setHostState] = useState('unknown')
  const [error, setError] = useState('')
  const [replaying, setReplaying] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [playbackIndex, setPlaybackIndex] = useState(-1)
  const [speed, setSpeed] = useState(1)
  const [droppedCount, setDroppedCount] = useState(0)
  const [redactedCount, setRedactedCount] = useState(0)
  const [creatingFingerprint, setCreatingFingerprint] = useState('')
  const [draftNotice, setDraftNotice] = useState('')
  const [activeRuns, setActiveRuns] = useState<RuntimeExecutionSummary[]>([])
  const reducedMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  useEffect(() => {
    let cancelled = false
    const read = async () => {
      const [response, host] = await Promise.all([
        fetch('/api/omni/runtime-traces/active', { cache: 'no-store' }).catch(() => null),
        fetch('/api/omni/host-bridge/health', { cache: 'no-store' }).catch(() => null),
      ])
      if (response?.ok && !cancelled) {
        const page = await response.json() as { runs: RuntimeExecutionSummary[] }
        setActiveRuns(page.runs)
      }
      if (host && !cancelled) {
        const health = await host.json().catch(() => ({})) as { state?: string }
        setHostState(health.state || (host.ok ? 'unknown' : 'unavailable'))
      }
    }
    void read()
    const id = window.setInterval(() => void read(), 5_000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [])

  useEffect(() => {
    if (!traceId || replaying) return
    let cancelled = false
    cursor.current = 0
    setTimeline(initialTimeline)
    setDroppedCount(0)
    setRedactedCount(0)
    setFindings(null)
    const read = async () => {
      try {
        const [response, graph] = await Promise.all([
          fetch(`/api/omni/runtime-traces/${encodeURIComponent(traceId)}/events?cursor=${cursor.current}`, { cache: 'no-store' }),
          fetch('/api/omni/system-graph/snapshot', { cache: 'no-store' }),
        ])
        if (!response.ok) throw new Error('运行事件暂不可读取')
        const page = await response.json() as RuntimeEventPage
        if (cancelled) return
        if (graph.ok) setSnapshot(await graph.json() as SystemGraphSnapshot)
        else setSnapshot(null)
        setTimeline((previous) => {
          const next = reduceRuntimeEvents(previous, page.events)
          cursor.current = next.cursor
          return next
        })
        setDroppedCount((value) => value + page.dropped_count)
        setRedactedCount((value) => value + page.redacted_count)
        const radar = await fetch(`/api/omni/runtime-findings?trace_id=${encodeURIComponent(traceId)}`, { cache: 'no-store' })
        if (radar.ok && !cancelled) setFindings(await radar.json() as RuntimeFindingPage)
        setError('')
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : '运行事件暂不可读取')
          setTimeline((previous) => ({ ...previous, mode: 'disconnected' }))
        }
      }
    }
    void read()
    const id = window.setInterval(() => void read(), 2_000)
    return () => { cancelled = true; window.clearInterval(id) }
  }, [traceId, replaying])

  useEffect(() => {
    if (!replaying || !playing || reducedMotion || timeline.events.length === 0) return
    const id = window.setInterval(() => {
      setPlaybackIndex((value) => {
        if (value >= timeline.events.length - 1) {
          setPlaying(false)
          return value
        }
        return value + 1
      })
    }, Math.max(150, 900 / speed))
    return () => window.clearInterval(id)
  }, [playing, reducedMotion, replaying, speed, timeline.events.length])

  const startReplay = async () => {
    if (!traceId) return
    setError('')
    try {
      const events: RuntimeEventPage['events'] = []
      let replayCursor = 0
      let dropped = 0
      let redacted = 0
      while (true) {
        const response = await fetch(`/api/omni/runtime-traces/${encodeURIComponent(traceId)}/replay?cursor=${replayCursor}`, { cache: 'no-store' })
        if (!response.ok) throw new Error('历史回放暂不可读取')
        const page = await response.json() as RuntimeEventPage
        events.push(...page.events)
        dropped += page.dropped_count
        redacted += page.redacted_count
        if (!page.has_more) break
        if (page.next_cursor === null || page.next_cursor <= replayCursor) throw new Error('历史回放游标未前进，已停止以避免重复。')
        replayCursor = page.next_cursor
      }
      const next = reduceRuntimeEvents(initialTimeline, events)
      setTimeline({ ...next, mode: 'replaying' })
      setDroppedCount(dropped)
      setRedactedCount(redacted)
      setPlaybackIndex(events.length ? 0 : -1)
      setReplaying(true)
      setPlaying(!reducedMotion && events.length > 1)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '历史回放暂不可读取')
    }
  }

  const returnLive = () => {
    setPlaying(false)
    setReplaying(false)
    setPlaybackIndex(-1)
    cursor.current = 0
    setDroppedCount(0)
    setRedactedCount(0)
    setTimeline(initialTimeline)
  }

  const createDraft = async (finding: RuntimeFinding) => {
    if (!snapshot?.snapshot_id) return setDraftNotice('事实快照不可用，不能创建修复草稿。')
    setCreatingFingerprint(finding.fingerprint)
    setDraftNotice('')
    try {
      const response = await fetch('/api/omni/runtime-plan-drafts', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ finding_fingerprint: finding.fingerprint, trace_id: traceId, base_snapshot_id: snapshot.snapshot_id }),
      })
      if (!response.ok) throw new Error('候选计划草稿创建失败')
      const draft = await response.json() as RuntimePlanDraft
      setDraftNotice(`${draft.reused ? '已复用' : '已创建'}草稿 ${draft.draft_id}；尚未确认，也未执行任何修复。`)
    } catch (reason) {
      setDraftNotice(reason instanceof Error ? reason.message : '候选计划草稿创建失败')
    } finally {
      setCreatingFingerprint('')
    }
  }

  const activeIndex = replaying ? playbackIndex : timeline.events.length - 1
  const currentEvent = activeIndex >= 0 ? timeline.events[activeIndex] : undefined
  const nextEvent = activeIndex >= 0 ? timeline.events[activeIndex + 1] : undefined
  const explanation = useMemo(() => currentEvent ? factualExplanation(currentEvent) : '尚无受信任运行事件。', [currentEvent])
  const stateLabel = replaying ? (playing ? '回放中' : '回放已暂停') : timeline.mode === 'live' ? '实时' : timeline.mode === 'delayed' ? '延迟' : timeline.mode
  const copyIds = () => void navigator.clipboard?.writeText([traceId, currentEvent?.correlation_id].filter(Boolean).join('\n'))

  return <section className="space-y-4 rounded-xl border border-violet-200 bg-violet-50/30 p-5" aria-label="执行模式">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="flex items-center gap-2 font-semibold text-slate-900"><Activity className="h-5 w-5 text-violet-700" />执行模式</h2>
        <p className="text-sm text-slate-600">只高亮真实 span/event；缺段会标为 gap，不补画。</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <input aria-label="Trace ID" value={traceId} onChange={(event) => setTraceId(event.target.value)} placeholder="输入 trace_id" className="rounded border px-2 py-1 text-sm" />
        <button type="button" onClick={copyIds} className="rounded border bg-white px-3 py-1 text-sm" aria-label="复制 Trace 与 Correlation ID"><Clipboard className="mr-1 inline h-3 w-3" />复制 ID</button>
        <button type="button" onClick={() => void startReplay()} className="rounded border bg-white px-3 py-1 text-sm"><Play className="mr-1 inline h-3 w-3" />回放</button>
        <button type="button" onClick={returnLive} className="rounded border bg-white px-3 py-1 text-sm"><Radio className="mr-1 inline h-3 w-3" />实时</button>
      </div>
    </div>
    {replaying ? <div className="flex flex-wrap items-center gap-2 rounded bg-white p-2 text-sm" aria-label="回放控制">
      <button type="button" onClick={() => setPlaying((value) => !value)} disabled={reducedMotion} className="rounded border px-2 py-1 disabled:opacity-50">{playing ? <Pause className="inline h-4 w-4" /> : <Play className="inline h-4 w-4" />} {playing ? '暂停' : '继续'}</button>
      <button type="button" onClick={() => setPlaybackIndex((value) => Math.min(timeline.events.length - 1, value + 1))} className="rounded border px-2 py-1"><StepForward className="inline h-4 w-4" /> 单步</button>
      <label>倍速 <select aria-label="回放倍速" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} className="rounded border p-1"><option value={0.5}>0.5x</option><option value={1}>1x</option><option value={2}>2x</option><option value={4}>4x</option></select></label>
      <label className="flex min-w-56 flex-1 items-center gap-2">跳转 <input aria-label="回放跳转" type="range" min={0} max={Math.max(0, timeline.events.length - 1)} value={Math.max(0, playbackIndex)} onChange={(event) => { setPlaying(false); setPlaybackIndex(Number(event.target.value)) }} className="flex-1" /></label>
      <span>{Math.max(0, playbackIndex + 1)} / {timeline.events.length}</span>
    </div> : null}
    {error ? <p role="alert" className="text-sm text-rose-700">{error}</p> : null}
    <div className="flex flex-wrap items-center gap-2 text-sm" aria-live="polite">
      {timeline.mode === 'delayed' ? <Clock3 className="h-4 w-4 text-amber-600" /> : timeline.gaps ? <AlertTriangle className="h-4 w-4 text-amber-600" /> : <RotateCcw className="h-4 w-4 text-violet-700" />}
      <span>状态：{stateLabel}；事件 {timeline.events.length}；gap / 排序未知 {timeline.gaps}；dropped {droppedCount}；redacted {redactedCount}</span>
    </div>
    <p className="text-xs text-slate-500">事实图：{snapshot?.snapshot_id || '当前快照不可读，运行事件将保留为 gap / unknown'}</p>
    <p className={hostState === 'healthy' ? 'text-xs text-emerald-700' : 'text-xs text-amber-700'}>Host Bridge：{hostState}；离线或版本不匹配时宿主能力不可用，Electron 仍是回退。</p>
    {activeRuns.length ? <div className="flex flex-wrap gap-2" aria-label="最近运行">
      {activeRuns.slice(0, 8).map((run) => <button type="button" key={run.trace_id} onClick={() => { setTraceId(run.trace_id); setReplaying(false) }} className="rounded-full border bg-white px-3 py-1 text-xs">
        {run.status === 'running' ? '运行中' : run.status} · {run.trace_id}
      </button>)}
    </div> : <p className="text-xs text-slate-500">当前没有可确认的最近运行。</p>}
    {reducedMotion ? <p className="text-xs text-slate-500">已按“减少动态效果”偏好关闭自动播放，保留单步和静态节点高亮。</p> : null}
    <ExecutionGraph snapshot={snapshot} events={timeline.events} activeIndex={activeIndex} />
    <ol className="max-h-80 space-y-2 overflow-y-auto" aria-label="运行事件序列">
      {timeline.events.map((event, index) => <li key={`${event.source}:${event.event_id}`} className={`rounded bg-white p-3 text-sm shadow-sm ${index === activeIndex ? 'ring-2 ring-violet-400' : ''}`}>
        <button type="button" className="w-full text-left" onClick={() => { setReplaying(true); setPlaying(false); setPlaybackIndex(index) }}>
          <span className="font-medium text-slate-800">{event.node_id || 'gap / unmapped'} · {event.status}</span>
          <span className="mt-1 block text-slate-600">{factualExplanation(event)}</span>
        </button>
      </li>)}
      {!timeline.events.length && !error ? <li className="rounded border border-dashed bg-white p-3 text-sm text-slate-500">输入可访问的 trace_id 后显示真实事件；空结果不是成功。</li> : null}
    </ol>
    <aside className="grid gap-2 rounded bg-white p-3 text-sm text-slate-700 md:grid-cols-2" aria-label="中文事实解释">
      <p className="md:col-span-2">{explanation}</p>
      <p><span className="font-medium">经过模块：</span>{currentEvent?.node_id || '不知道 / 未埋点'}</p>
      <p><span className="font-medium">下一跳：</span>{nextEvent?.node_id || (currentEvent ? '未观察到下一跳' : '不知道 / 未埋点')}</p>
      <p><span className="font-medium">输入/输出 schema：</span>{currentEvent?.payload_schema.length ? currentEvent.payload_schema.join('、') : '未埋点'}</p>
      <p><span className="font-medium">读写：</span>{currentEvent?.read_write || '不知道'}</p>
      <p><span className="font-medium">耗时/重试：</span>{String(currentEvent?.payload_summary.duration_ms ?? '未埋点')} ms / {currentEvent?.event_type === 'retry' ? '是' : '否'}</p>
      <p><span className="font-medium">证据：</span>{currentEvent ? `${currentEvent.source}:${currentEvent.event_id} · cursor ${currentEvent.cursor}` : '无'}</p>
    </aside>
    <div><h3 className="mb-2 font-medium text-slate-900">planned / fact / runtime / delivery 雷达</h3><RuntimeRadar findings={findings?.findings || []} onCreateDraft={(finding) => void createDraft(finding)} creatingFingerprint={creatingFingerprint} /></div>
    {draftNotice ? <p role="status" className="rounded bg-violet-100 p-2 text-sm text-violet-900">{draftNotice}</p> : null}
  </section>
}
