'use client'

import Link from 'next/link'
import type React from 'react'
import { useEffect, useState } from 'react'

import { useContentStudioStore, type Brief } from '@/stores/contentStudioStore'
import { ContentStudioHubNav } from '@/components/content-studio-hub-nav'
import { PromptFeedback } from '@/components/prompt-feedback'
import { PromptNodeDrawer } from '@/components/prompt-node-drawer'

interface ProductOption {
  id: string
  name: string
}

export default function BriefLibraryPage() {
  const {
    briefs,
    fetchBriefs,
    createBrief,
    generateBrief,
    deriveBrief,
    deleteBrief,
    error,
  } = useContentStudioStore()

  const [products, setProducts] = useState<ProductOption[]>([])
  const [productId, setProductId] = useState('')

  // 一键生成
  const [genTitle, setGenTitle] = useState('')
  const [genHints, setGenHints] = useState('')
  const [genLoading, setGenLoading] = useState(false)
  const [genError, setGenError] = useState<string | null>(null)
  const [justGenerated, setJustGenerated] = useState<Brief | null>(null)
  const [drawerNode, setDrawerNode] = useState<string | null>(null)

  // 手动创建
  const [title, setTitle] = useState('')
  const [usp, setUsp] = useState('')

  useEffect(() => {
    void fetchBriefs()
    // 拉一份产品候选，便于一键生成挂关联
    void (async () => {
      try {
        const res = await fetch('/api/omni/ad-review/products', { cache: 'no-store' })
        if (!res.ok) return
        const body = await res.json()
        const list = (body?.data ?? body?.items ?? []) as Array<{ id: string; name: string }>
        setProducts(list.map((p) => ({ id: p.id, name: p.name })))
      } catch {
        /* tolerate ad-review service offline */
      }
    })()
  }, [fetchBriefs])

  const onGenerate = async () => {
    setGenLoading(true)
    setGenError(null)
    try {
      const hints: Record<string, unknown> = {}
      if (genHints.trim()) {
        hints.audience_hint = genHints.trim()
      }
      const created = await generateBrief({
        product_id: productId || undefined,
        title: genTitle || undefined,
        hints,
      })
      setJustGenerated(created)
      setGenTitle('')
      setGenHints('')
    } catch (e) {
      setGenError((e as Error).message)
    } finally {
      setGenLoading(false)
    }
  }

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <ContentStudioHubNav />
      <div>
        <h1 className="text-2xl font-semibold">Brief 库</h1>
        <p className="text-sm text-gray-500">
          结构化策略快照（USP + 场景 + 人群）。可一键 LLM 生成、可派生 v2、可挂入 chat 当上下文。
        </p>
      </div>

      {/* 一键生成（优先入口） */}
      <section className="border-2 border-violet-200 bg-violet-50/40 rounded-lg p-4 space-y-3">
        <h2 className="font-medium text-violet-800">⚡ 一键生成 Brief（LLM + 三 KB 联合召回）</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <select
            className="border rounded px-3 py-2 text-sm bg-white"
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
          >
            <option value="">不挂载具体产品</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <input
            className="border rounded px-3 py-2 text-sm bg-white"
            placeholder="（可选）Brief 标题，留空由 AI 生成"
            value={genTitle}
            onChange={(e) => setGenTitle(e.target.value)}
          />
        </div>
        <textarea
          className="w-full border rounded px-3 py-2 text-sm min-h-20 bg-white"
          placeholder="（可选）人群提示，例如：25-35 岁一线女性，偏好成分党，预算 500-1500"
          value={genHints}
          onChange={(e) => setGenHints(e.target.value)}
        />
        {genError && <div className="text-sm text-rose-600">{genError}</div>}
        <button
          type="button"
          className="px-4 py-2 rounded bg-violet-600 text-white text-sm disabled:opacity-60"
          disabled={genLoading}
          onClick={onGenerate}
        >
          {genLoading ? '生成中（约 30s）…' : '一键生成草稿'}
        </button>

        {justGenerated && (
          <div className="mt-2 rounded border bg-green-50/60 p-3 space-y-2">
            <div className="text-xs text-green-700">
              ✓ 已生成：<span className="font-medium">{justGenerated.title}</span>
              <Link
                href={`/content-studio/briefs/${justGenerated.id}`}
                className="ml-2 text-green-700 underline"
              >
                查看详情 →
              </Link>
            </div>
            <PromptFeedback
              nodeId="briefs.draft"
              inputRef={{
                brief_id: justGenerated.id,
                product_id: productId || null,
              }}
              output={JSON.stringify({
                title: justGenerated.title,
                usp: justGenerated.usp,
                scenarios: justGenerated.scenarios,
              }).slice(0, 4000)}
              onOpenDrawer={setDrawerNode}
            />
          </div>
        )}
      </section>

      {/* 手动新建 */}
      <section className="border rounded-lg p-4 space-y-3">
        <h2 className="font-medium">手动新建 Brief</h2>
        <input
          className="w-full border rounded px-3 py-2 text-sm"
          placeholder="标题"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          className="w-full border rounded px-3 py-2 text-sm min-h-24"
          placeholder="USP（多卖点用换行分隔即可）"
          value={usp}
          onChange={(e) => setUsp(e.target.value)}
        />
        <button
          type="button"
          className="px-4 py-2 rounded bg-gray-900 text-white text-sm"
          onClick={async () => {
            if (!title || !usp) return
            await createBrief({ title, usp })
            setTitle('')
            setUsp('')
          }}
        >
          创建
        </button>
      </section>

      {error && <div className="text-sm text-rose-600">{error}</div>}

      <section className="space-y-4">
        <h2 className="font-medium text-gray-700">已有 Brief（{briefs.length}）</h2>
        <BriefGroupedList
          briefs={briefs}
          onDerive={(id) => void deriveBrief(id)}
          onDelete={(id, title) => {
            if (window.confirm(`删除 Brief「${title}」？`)) void deleteBrief(id)
          }}
        />
      </section>
      <PromptNodeDrawer nodeId={drawerNode} onClose={() => setDrawerNode(null)} />
    </div>
  )
}


function BriefGroupedList({
  briefs,
  onDerive,
  onDelete,
}: {
  briefs: Brief[]
  onDerive: (id: string) => void
  onDelete: (id: string, title: string) => void
}) {
  // 1) 按 product_id 分组（无 product_id 归为"未关联产品"）
  const groups = new Map<string, { label: string; items: Brief[] }>()
  briefs.forEach((b) => {
    const key = b.product_id || '__noproduct__'
    const label = b.product_name || (key === '__noproduct__' ? '未关联产品' : '未命名产品')
    if (!groups.has(key)) groups.set(key, { label, items: [] })
    groups.get(key)!.items.push(b)
  })

  // 2) 每组内按 parent_brief_id 形成 root → children 列表
  const renderGroup = (label: string, items: Brief[]) => {
    const byParent: Record<string, Brief[]> = {}
    items.forEach((b) => {
      const k = b.parent_brief_id ?? '__root__'
      ;(byParent[k] ??= []).push(b)
    })
    const roots = byParent['__root__'] ?? items

    const renderNode = (b: Brief, depth: number): React.ReactNode => (
      <div key={b.id} style={{ marginLeft: depth * 16 }}>
        <BriefCard
          brief={b}
          onDerive={() => onDerive(b.id)}
          onDelete={() => onDelete(b.id, b.title)}
        />
        {(byParent[b.id] ?? []).map((child) => renderNode(child, depth + 1))}
      </div>
    )

    return (
      <div key={label} className="space-y-2">
        <div className="text-xs text-gray-500 uppercase tracking-wide">产品：{label}（{items.length}）</div>
        {roots.map((r) => renderNode(r, 0))}
      </div>
    )
  }

  return <div className="space-y-6">{Array.from(groups.values()).map((g) => renderGroup(g.label, g.items))}</div>
}


function BriefCard({
  brief,
  onDerive,
  onDelete,
}: {
  brief: Brief
  onDerive: () => void
  onDelete: () => void
}) {
  const extra = brief.extra as { last_ctr?: number; last_cvr?: number; last_samples?: number } | undefined
  const ctr = typeof extra?.last_ctr === 'number' ? `${(extra.last_ctr * 100).toFixed(2)}%` : '—'
  const cvr = typeof extra?.last_cvr === 'number' ? `${(extra.last_cvr * 100).toFixed(2)}%` : '—'
  const samples = typeof extra?.last_samples === 'number' ? String(extra.last_samples) : '—'

  return (
    <div className="border rounded-lg p-4 bg-white">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Link href={`/content-studio/briefs/${brief.id}`} className="font-medium hover:underline">
              {brief.title}
            </Link>
            {brief.version && brief.version > 1 && (
              <span className="text-[10px] bg-violet-100 text-violet-700 px-1.5 rounded">
                v{brief.version}
              </span>
            )}
            {brief.parent_brief_id && (
              <span className="text-[10px] text-gray-400">派生</span>
            )}
            {brief.status && brief.status !== 'active' && (
              <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 rounded">
                {brief.status}
              </span>
            )}
          </div>
          {brief.product_name && (
            <div className="text-xs text-gray-500 mt-0.5">产品：{brief.product_name}</div>
          )}
          <div className="text-sm text-gray-700 mt-2 whitespace-pre-line line-clamp-4">
            {brief.usp}
          </div>
          {Array.isArray(brief.scenarios) && brief.scenarios.length > 0 && (
            <div className="text-xs text-gray-500 mt-1">
              场景数：{brief.scenarios.length}
            </div>
          )}
          <div className="text-xs text-gray-500 mt-2 grid grid-cols-3 gap-2 max-w-sm">
            <div>CTR：{ctr}</div>
            <div>CVR：{cvr}</div>
            <div>样本：{samples}</div>
          </div>
        </div>

        <div className="flex flex-col gap-1.5 shrink-0">
          <Link
            href={`/chat?brief_id=${brief.id}`}
            className="text-xs px-2.5 py-1 rounded bg-violet-600 text-white hover:bg-violet-700"
          >
            去 chat 圈包
          </Link>
          <button
            type="button"
            className="text-xs px-2.5 py-1 rounded border border-gray-300 hover:bg-gray-50"
            onClick={onDerive}
          >
            派生 v{(brief.version ?? 1) + 1}
          </button>
          <button
            type="button"
            className="text-xs px-2.5 py-1 rounded border border-rose-300 text-rose-600 hover:bg-rose-50"
            onClick={onDelete}
          >
            删除
          </button>
        </div>
      </div>
    </div>
  )
}
