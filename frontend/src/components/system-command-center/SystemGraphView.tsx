'use client'

import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Boxes, ChevronLeft, ChevronRight, Loader2, RefreshCw, Search } from 'lucide-react'

import OutputFeedback from '@/components/OutputFeedback'
import { buildGraphModel, GRAPH_STATUSES, graphDisplayStatus, pathToNode } from '@/lib/system-command-center/graph-model'
import { nodeTypeDefinition } from '@/lib/system-command-center/node-type-registry'
import type { SystemGraphNode, SystemGraphSnapshot } from '@/lib/system-command-center/runtime-model'

const PAGE_SIZE = 24
interface GraphPageResponse {
  snapshot_id: string
  generated_at_utc: string
  nodes: SystemGraphSnapshot['content']['nodes']
  edges: SystemGraphSnapshot['content']['edges']
  source_results: SystemGraphSnapshot['content']['source_results']
}
const STATUS_STYLE: Record<string, string> = {
  planned: 'border-dashed border-blue-400 bg-blue-50 text-blue-800',
  healthy: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  broken: 'border-rose-400 bg-rose-50 text-rose-800',
  unknown: 'border-amber-400 bg-amber-50 text-amber-800',
  deprecated: 'border-slate-300 bg-slate-100 text-slate-500',
  verified_not_delivered: 'border-violet-400 bg-violet-50 text-violet-800',
}

function NodeCard({ node, selected, onSelect }: { node: SystemGraphNode; selected: boolean; onSelect: () => void }) {
  const status = graphDisplayStatus(node)
  const definition = nodeTypeDefinition(node.kind)
  return <button
    type="button"
    onClick={onSelect}
    data-testid={`system-graph-node-${node.id}`}
    className={`min-h-24 w-full rounded-lg border p-3 text-left shadow-sm transition focus:outline-none focus:ring-2 focus:ring-violet-500 ${STATUS_STYLE[status]} ${selected ? 'ring-2 ring-violet-500' : ''}`}
  >
    <span className="block truncate text-sm font-semibold">{node.label}</span>
    <span className="mt-1 block truncate text-[11px] opacity-75">{definition.label} · {node.key}</span>
    <span className="mt-2 inline-block rounded-full border border-current/20 px-2 py-0.5 text-[10px]">{status}</span>
  </button>
}

export function SystemGraphView({ focusQuery = '' }: { focusQuery?: string }) {
  const [snapshot, setSnapshot] = useState<SystemGraphSnapshot | null>(null)
  const [phase, setPhase] = useState<'loading' | 'success' | 'empty' | 'error'>('loading')
  const [error, setError] = useState('')
  const [query, setQuery] = useState(focusQuery)
  const [status, setStatus] = useState('all')
  const [kind, setKind] = useState('all')
  const [page, setPage] = useState(0)
  const [selectedId, setSelectedId] = useState('')
  const [refreshState, setRefreshState] = useState('')

  const load = async () => {
    setPhase('loading')
    setError('')
    try {
      const response = await fetch('/api/omni/system-graph/snapshot', { cache: 'no-store' })
      if (!response.ok) throw new Error(response.status === 404 ? '还没有系统图快照，请先刷新。' : '系统图事实快照暂不可读。')
      const identity = await response.json() as SystemGraphSnapshot
      const graphResponse = await fetch(
        `/api/omni/system-graph/snapshots/${encodeURIComponent(identity.snapshot_id)}/graph?limit=500`,
        { cache: 'no-store' },
      )
      if (!graphResponse.ok) throw new Error('不可变系统图分页暂不可读。')
      const graph = await graphResponse.json() as GraphPageResponse
      const value: SystemGraphSnapshot = {
        ...identity,
        snapshot_id: graph.snapshot_id,
        generated_at_utc: graph.generated_at_utc,
        content: {
          ...identity.content,
          nodes: graph.nodes,
          edges: graph.edges,
          source_results: graph.source_results,
        },
      }
      setSnapshot(value)
      setSelectedId(value.content.nodes[0]?.id || '')
      setPhase(value.content.nodes.length ? 'success' : 'empty')
    } catch (reason) {
      setSnapshot(null)
      setError(reason instanceof Error ? reason.message : '系统图事实快照暂不可读。')
      setPhase('error')
    }
  }

  useEffect(() => { void load() }, [])

  const model = useMemo(() => snapshot ? buildGraphModel(snapshot) : null, [snapshot])
  const kinds = useMemo(() => model ? Array.from(new Set(model.nodes.map((node) => node.kind))).sort() : [], [model])
  const filtered = useMemo(() => {
    if (!model) return []
    const needle = query.trim().toLocaleLowerCase('zh-CN')
    return model.nodes.filter((node) => {
      if (status !== 'all' && graphDisplayStatus(node) !== status) return false
      if (kind !== 'all' && node.kind !== kind) return false
      return !needle || `${node.label} ${node.key} ${node.kind} ${node.sources?.join(' ') || ''}`.toLocaleLowerCase('zh-CN').includes(needle)
    })
  }, [kind, model, query, status])
  const maxPage = Math.max(0, Math.ceil(filtered.length / PAGE_SIZE) - 1)
  const visible = filtered.slice(Math.min(page, maxPage) * PAGE_SIZE, (Math.min(page, maxPage) + 1) * PAGE_SIZE)
  const selected = model?.byId.get(selectedId) || visible[0]

  useEffect(() => { setPage(0) }, [query, status, kind])

  const refresh = async () => {
    setRefreshState('正在登记刷新…')
    try {
      const response = await fetch('/api/omni/system-graph/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feature_ids: [], include_runtime: false, idempotency_key: `workspace-${new Date().toISOString().slice(0, 16)}` }),
      })
      const value = await response.json().catch(() => ({})) as { refresh_id?: string; error?: string }
      if (!response.ok) throw new Error(value.error || '刷新请求失败')
      setRefreshState(`刷新任务 ${value.refresh_id || '已受理'}；完成后重新载入快照。`)
    } catch (reason) {
      setRefreshState(reason instanceof Error ? reason.message : '刷新请求失败')
    }
  }

  if (phase === 'loading') return <section data-testid="system-graph-loading" className="rounded-xl border bg-white p-8 text-center text-sm text-slate-500"><Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" />正在读取受信任系统图快照…</section>
  if (phase === 'error') return <section data-testid="system-graph-error" className="rounded-xl border border-rose-200 bg-rose-50 p-6"><p role="alert" className="text-sm text-rose-800">{error}</p><button type="button" onClick={() => void load()} className="mt-3 rounded border bg-white px-3 py-1 text-sm">重试</button></section>
  if (phase === 'empty' || !model) return <section data-testid="system-graph-empty" className="rounded-xl border border-dashed bg-white p-8 text-center"><Boxes className="mx-auto mb-2 h-6 w-6 text-slate-400" /><p className="text-sm text-slate-600">快照存在，但没有可确认节点；不会把空数据显示成健康。</p><button type="button" onClick={() => void refresh()} className="mt-3 rounded border px-3 py-1 text-sm">创建刷新任务</button></section>

  return <section className="space-y-4" aria-label="系统图开发模式" data-testid="system-graph-success">
    <header className="rounded-xl border bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="flex items-center gap-2 text-lg font-semibold"><Boxes className="h-5 w-5 text-violet-700" />系统指挥中心 · 开发模式</h2><p className="mt-1 text-sm text-slate-600">静态事实图、代码证据和健康状态。未知即未知，不用推测补齐。</p></div>
        <div className="flex gap-2"><a href="/system-graph?legacy_plan=1" className="rounded border bg-white px-3 py-1.5 text-sm">候选接法计划</a><button type="button" onClick={() => void load()} className="rounded border bg-white px-3 py-1.5 text-sm"><RefreshCw className="mr-1 inline h-3.5 w-3.5" />重新载入</button><button type="button" onClick={() => void refresh()} className="rounded bg-violet-700 px-3 py-1.5 text-sm text-white">刷新事实图</button></div>
      </div>
      <div className="mt-3 text-xs text-slate-500">快照 {model.snapshotId} · 节点 {model.nodes.length} · 边 {model.edges.length} · 孤儿 {model.orphans.length}</div>
      {refreshState ? <p role="status" className="mt-2 text-xs text-violet-700">{refreshState}</p> : null}
      {model.partial ? <div role="status" className="mt-3 flex gap-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><span>当前是部分快照：{model.unavailableSources.join('、')}。相关节点保留 unknown，不推断为不存在。</span></div> : null}
    </header>

    <div className="grid gap-3 rounded-xl border bg-white p-4 md:grid-cols-[minmax(240px,1fr)_180px_200px]">
      <label className="relative"><Search className="absolute left-2 top-2.5 h-4 w-4 text-slate-400" /><span className="sr-only">搜索节点</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、key、类型或来源" className="w-full rounded border py-2 pl-8 pr-2 text-sm" /></label>
      <label className="text-xs text-slate-600">状态<select aria-label="按状态筛选" value={status} onChange={(event) => setStatus(event.target.value)} className="mt-1 block w-full rounded border p-2 text-sm"><option value="all">全部状态</option>{GRAPH_STATUSES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label className="text-xs text-slate-600">节点类型<select aria-label="按节点类型筛选" value={kind} onChange={(event) => setKind(event.target.value)} className="mt-1 block w-full rounded border p-2 text-sm"><option value="all">全部类型</option>{kinds.map((item) => <option key={item} value={item}>{nodeTypeDefinition(item).label} ({item})</option>)}</select></label>
    </div>

    <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
      <div className="space-y-3 rounded-xl border bg-slate-50 p-4" aria-label="思维导图视图">
        <div className="flex flex-wrap gap-2 text-[10px]">{GRAPH_STATUSES.map((item) => <span key={item} className={`rounded-full border px-2 py-1 ${STATUS_STYLE[item]}`}>{item}</span>)}</div>
        {visible.length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{visible.map((node) => <NodeCard key={node.id} node={node} selected={selected?.id === node.id} onSelect={() => setSelectedId(node.id)} />)}</div> : <p className="rounded border border-dashed bg-white p-6 text-center text-sm text-slate-500">没有匹配节点；这不是系统为空。</p>}
        <div className="flex items-center justify-between text-sm"><span>第 {Math.min(page, maxPage) + 1} / {maxPage + 1} 页，共 {filtered.length} 个匹配节点</span><span className="flex gap-2"><button type="button" disabled={page <= 0} onClick={() => setPage((value) => Math.max(0, value - 1))} className="rounded border bg-white p-1 disabled:opacity-30" aria-label="上一页"><ChevronLeft className="h-4 w-4" /></button><button type="button" disabled={page >= maxPage} onClick={() => setPage((value) => Math.min(maxPage, value + 1))} className="rounded border bg-white p-1 disabled:opacity-30" aria-label="下一页"><ChevronRight className="h-4 w-4" /></button></span></div>
      </div>

      <aside className="space-y-3 rounded-xl border bg-white p-4" aria-label="节点解释与证据">
        {selected ? <>
          <div><span className="text-[10px] uppercase text-slate-500">{nodeTypeDefinition(selected.kind).label}</span><h3 className="font-semibold text-slate-900">{selected.label}</h3><p className="mt-1 break-all text-xs text-slate-500">{selected.id}</p></div>
          <p className="text-sm text-slate-700">{nodeTypeDefinition(selected.kind).description}</p>
          <dl className="grid grid-cols-2 gap-2 text-xs"><div><dt className="text-slate-500">状态</dt><dd>{graphDisplayStatus(selected)}</dd></div><div><dt className="text-slate-500">健康</dt><dd>{selected.state.health}</dd></div><div><dt className="text-slate-500">入边</dt><dd>{model.incoming.get(selected.id)?.length || 0}</dd></div><div><dt className="text-slate-500">出边</dt><dd>{model.outgoing.get(selected.id)?.length || 0}</dd></div></dl>
          <div><h4 className="text-xs font-medium text-slate-700">可访问路径</h4><ol className="mt-1 space-y-1 text-xs text-slate-600">{pathToNode(model, selected.id).map((id) => <li key={id}>↳ {model.byId.get(id)?.label || id}</li>)}</ol></div>
          <div><h4 className="text-xs font-medium text-slate-700">代码证据</h4>{selected.evidence?.length ? <ul className="mt-1 max-h-40 space-y-1 overflow-auto text-xs text-slate-600">{selected.evidence.map((item) => <li key={`${item.path}:${item.line}:${item.blob}`} className="break-all">{item.path}:{item.line}{item.symbol ? ` · ${item.symbol}` : ''} · {item.blob.slice(0, 10)}</li>)}</ul> : <p className="mt-1 text-xs text-amber-700">暂无静态证据，状态不可提升为已验证。</p>}</div>
          {selected.attrs && Object.keys(selected.attrs).length ? <details><summary className="cursor-pointer text-xs font-medium">机器属性</summary><pre className="mt-1 max-h-40 overflow-auto rounded bg-slate-950 p-2 text-[10px] text-slate-100">{JSON.stringify(selected.attrs, null, 2)}</pre></details> : null}
        </> : <p className="text-sm text-slate-500">选择节点后查看中文解释与代码证据。</p>}
      </aside>
    </div>

    <details className="rounded-xl border bg-white p-4"><summary className="cursor-pointer font-medium">无图形依赖树（键盘与读屏可访问）</summary><ul role="tree" className="mt-3 max-h-72 space-y-1 overflow-auto text-sm">{filtered.map((node) => <li key={node.id} role="treeitem" aria-selected={selected?.id === node.id}><button type="button" onClick={() => setSelectedId(node.id)} className="w-full rounded px-2 py-1 text-left hover:bg-slate-100">{pathToNode(model, node.id).map((id) => model.byId.get(id)?.label || id).join(' › ')} <span className="text-xs text-slate-400">[{graphDisplayStatus(node)}]</span></button></li>)}</ul></details>
    {model.orphans.length ? <details className="rounded-xl border border-amber-200 bg-amber-50 p-4"><summary className="cursor-pointer text-sm font-medium text-amber-900">孤儿节点 {model.orphans.length}</summary><p className="mt-2 text-xs text-amber-800">这些节点有扫描证据，但尚无可信连接；不会自动猜测它们的依赖关系。</p></details> : null}
    <div className="rounded-xl border bg-white p-4"><OutputFeedback toolName="system_graph_get" label="这份系统图和解释是否准确？" /></div>
  </section>
}
