'use client'

import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { useContentStudioStore, type Brief, type Pipeline } from '@/stores/contentStudioStore'

interface VersionTree {
  root: Brief | null
  tree: Brief[]
}

export default function BriefDetailPage() {
  const params = useParams<{ id: string }>()
  const briefId = params?.id ?? ''
  const router = useRouter()
  const {
    updateBrief,
    deriveBrief,
    deleteBrief,
    applyDmpSop,
    fetchBriefPipelines,
    fetchBriefVersionTree,
  } = useContentStudioStore()

  const [brief, setBrief] = useState<Brief | null>(null)
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [tree, setTree] = useState<VersionTree>({ root: null, tree: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // 编辑器
  const [title, setTitle] = useState('')
  const [usp, setUsp] = useState('')
  const [scenariosText, setScenariosText] = useState('')
  const [audienceText, setAudienceText] = useState('')
  const [toneText, setToneText] = useState('')
  const [dmpSop, setDmpSop] = useState('')
  const [dmpPackageId, setDmpPackageId] = useState('')
  const [dmpPackageName, setDmpPackageName] = useState('')
  const [sourceNotes, setSourceNotes] = useState('')

  useEffect(() => {
    if (!briefId) return
    let cancelled = false
    void (async () => {
      setLoading(true)
      try {
        const r = await fetch(`/api/omni/content-studio/briefs/${briefId}`, { cache: 'no-store' })
        if (!r.ok) throw new Error(`${r.status}`)
        const data = (await r.json()) as Brief
        if (cancelled) return
        setBrief(data)
        setTitle(data.title || '')
        setUsp(data.usp || '')
        setScenariosText(JSON.stringify(data.scenarios ?? [], null, 2))
        setAudienceText(JSON.stringify(data.audience_profile ?? {}, null, 2))
        setToneText(JSON.stringify(data.tone_style ?? {}, null, 2))
        setDmpSop(data.dmp_sop ?? '')
        const ap = (data.audience_profile ?? {}) as Record<string, unknown>
        setDmpPackageId(String((ap as { dmp_package_id?: string | null }).dmp_package_id || ''))
        setDmpPackageName(String((ap as { dmp_package_name?: string | null }).dmp_package_name || ''))
        setSourceNotes(data.source_notes ?? '')

        const [ps, vt] = await Promise.all([
          fetchBriefPipelines(briefId),
          fetchBriefVersionTree(briefId),
        ])
        if (cancelled) return
        setPipelines(ps)
        setTree(vt)
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [briefId, fetchBriefPipelines, fetchBriefVersionTree])

  const onSave = async () => {
    if (!brief) return
    setSaving(true)
    setError(null)
    try {
      let scenarios: unknown
      let audience: Record<string, unknown>
      let tone: unknown
      try {
        scenarios = JSON.parse(scenariosText || '[]')
        audience = JSON.parse(audienceText || '{}') as Record<string, unknown>
        tone = JSON.parse(toneText || '{}')
      } catch (e) {
        setError(`JSON 格式错误：${(e as Error).message}`)
        setSaving(false)
        return
      }
      // 把独立表单的 dmp_package_id / package_name 同步进 audience_profile
      if (dmpPackageId.trim()) {
        audience.dmp_package_id = dmpPackageId.trim()
      } else if ('dmp_package_id' in audience) {
        delete audience.dmp_package_id
      }
      if (dmpPackageName.trim()) {
        audience.dmp_package_name = dmpPackageName.trim()
      } else if ('dmp_package_name' in audience) {
        delete audience.dmp_package_name
      }

      const updated = await updateBrief(brief.id, {
        title,
        usp,
        scenarios: scenarios as Array<Record<string, unknown>>,
        audience_profile: audience,
        tone_style: tone as Record<string, unknown>,
        dmp_sop: dmpSop,
        source_notes: sourceNotes,
      })
      setBrief(updated)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const onDerive = async () => {
    if (!brief) return
    const v = await deriveBrief(brief.id)
    router.push(`/content-studio/briefs/${v.id}`)
  }

  const onDelete = async () => {
    if (!brief) return
    if (!window.confirm(`删除 Brief「${brief.title}」？此操作不可撤销`)) return
    await deleteBrief(brief.id)
    router.push('/content-studio/briefs')
  }

  const onApplySop = async () => {
    if (!brief) return
    if (!dmpSop.trim()) return
    await applyDmpSop(brief.id, dmpSop.trim())
  }

  if (loading) return <div className="p-6 text-sm text-gray-500">加载中…</div>
  if (!brief) return <div className="p-6 text-sm text-rose-500">Brief 不存在</div>

  const briefExtra = brief.extra as {
    last_ctr?: number
    last_cvr?: number
    last_samples?: number
    lessons_learned?: string
  } | undefined
  const audienceInsights = (brief.audience_profile?.insights ?? {}) as Record<string, unknown>
  const missingItems = [
    !brief.usp?.trim() && 'USP',
    !(brief.scenarios?.length) && '场景矩阵',
    !audienceInsights.motivation && '人群购买动机',
    !audienceInsights.objection && '人群犹豫点',
    !audienceInsights.language_style && '口播语言风格',
    pipelines.length === 0 && '引用此 Brief 的 Pipeline',
  ].filter(Boolean)

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Link href="/content-studio/briefs" className="text-xs text-gray-500 hover:underline">
            ← 返回 Brief 库
          </Link>
          <h1 className="text-2xl font-semibold mt-1">{brief.title}</h1>
          <div className="text-xs text-gray-500 mt-1 flex items-center gap-2">
            {brief.product_name && <span>产品：{brief.product_name}</span>}
            <span>v{brief.version ?? 1}</span>
            {brief.status && (
              <span className="bg-gray-100 px-1.5 rounded">{brief.status}</span>
            )}
            {brief.parent_brief_id && (
              <Link
                href={`/content-studio/briefs/${brief.parent_brief_id}`}
                className="text-violet-600 hover:underline"
              >
                派生自上一版 →
              </Link>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Link
            href={`/chat?brief_id=${brief.id}`}
            className="text-xs px-3 py-1.5 rounded bg-violet-600 text-white text-center hover:bg-violet-700"
          >
            去 chat 圈包
          </Link>
          <button
            type="button"
            className="text-xs px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-50"
            onClick={onDerive}
          >
            派生 v{(brief.version ?? 1) + 1}
          </button>
          <button
            type="button"
            className="text-xs px-3 py-1.5 rounded border border-rose-300 text-rose-600 hover:bg-rose-50"
            onClick={onDelete}
          >
            删除
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-rose-600 border border-rose-200 bg-rose-50 rounded p-2">{error}</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-4">
          <div className="border rounded-lg p-4 space-y-3">
            <h2 className="font-medium">基础信息</h2>
            <input
              className="w-full border rounded px-3 py-2 text-sm"
              placeholder="标题"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <textarea
              className="w-full border rounded px-3 py-2 text-sm min-h-32"
              placeholder="USP"
              value={usp}
              onChange={(e) => setUsp(e.target.value)}
            />
          </div>

          <div className="border rounded-lg p-4 space-y-2">
            <h2 className="font-medium">场景矩阵（JSON）</h2>
            <textarea
              className="w-full font-mono text-xs border rounded px-3 py-2 min-h-40"
              value={scenariosText}
              onChange={(e) => setScenariosText(e.target.value)}
            />
            <p className="text-[11px] text-gray-500">
              结构：[{'{'}context, trigger, pain, priority{'}'}, ...]
            </p>
          </div>

          <div className="border rounded-lg p-4 space-y-2">
            <h2 className="font-medium">人群画像（JSON）</h2>
            <textarea
              className="w-full font-mono text-xs border rounded px-3 py-2 min-h-40"
              value={audienceText}
              onChange={(e) => setAudienceText(e.target.value)}
            />
            <p className="text-[11px] text-gray-500">
              结构：{'{'}tags, insights:{'{'}motivation, objection, language_style{'}'}, dmp_package_id{'}'}
            </p>
          </div>

          <div className="border rounded-lg p-4 space-y-2">
            <h2 className="font-medium">口播口吻（JSON）</h2>
            <textarea
              className="w-full font-mono text-xs border rounded px-3 py-2 min-h-24"
              value={toneText}
              onChange={(e) => setToneText(e.target.value)}
            />
          </div>

          <div className="border rounded-lg p-4 space-y-2">
            <h2 className="font-medium">DMP 圈包结果</h2>
            <div className="grid grid-cols-2 gap-3">
              <input
                className="border rounded px-3 py-2 text-sm"
                placeholder="package_id（圈完后回填）"
                value={dmpPackageId}
                onChange={(e) => setDmpPackageId(e.target.value)}
              />
              <input
                className="border rounded px-3 py-2 text-sm"
                placeholder="package_name（可选）"
                value={dmpPackageName}
                onChange={(e) => setDmpPackageName(e.target.value)}
              />
            </div>
            <p className="text-[11px] text-gray-500">
              填写后，基于此 Brief 创建 Pipeline 时会自动带入 audience_package。
            </p>
          </div>

          <div className="border rounded-lg p-4 space-y-2">
            <h2 className="font-medium">圈包 SOP</h2>
            <textarea
              className="w-full text-sm border rounded px-3 py-2 min-h-32"
              placeholder="可在 chat 里让 AI 输出，然后回填这里"
              value={dmpSop}
              onChange={(e) => setDmpSop(e.target.value)}
            />
            <button
              type="button"
              className="text-xs px-3 py-1.5 rounded border border-violet-300 text-violet-700 hover:bg-violet-50"
              onClick={onApplySop}
            >
              仅保存 SOP（独立保存接口）
            </button>
          </div>

          <div className="border rounded-lg p-4 space-y-2">
            <h2 className="font-medium">备注</h2>
            <textarea
              className="w-full text-sm border rounded px-3 py-2 min-h-20"
              value={sourceNotes}
              onChange={(e) => setSourceNotes(e.target.value)}
            />
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              className="px-4 py-2 rounded bg-violet-600 text-white text-sm disabled:opacity-60"
              disabled={saving}
              onClick={onSave}
            >
              {saving ? '保存中…' : '保存全部修改'}
            </button>
            <button
              type="button"
              className="px-4 py-2 rounded border border-gray-300 text-sm"
              onClick={() => router.push('/content-studio/briefs')}
            >
              取消
            </button>
          </div>
        </section>

        <aside className="space-y-4">
          {missingItems.length > 0 && (
            <div className="border border-amber-200 bg-amber-50 rounded-lg p-4 text-xs text-amber-800">
              <h2 className="font-medium mb-1">闭环缺失项</h2>
              <div>当前还缺：{missingItems.join('、')}。</div>
              <Link href={`/content-studio/new?brief_id=${brief.id}`} className="mt-2 inline-block text-violet-700 underline">
                用此 Brief 新建 Pipeline
              </Link>
            </div>
          )}

          <div className="border rounded-lg p-4">
            <h2 className="font-medium mb-2">投放表现汇总</h2>
            <Stat label="last CTR" value={briefExtra?.last_ctr} percent />
            <Stat label="last CVR" value={briefExtra?.last_cvr} percent />
            <Stat label="样本数" value={briefExtra?.last_samples} />
            <Stat label="质量分" value={brief.quality_score} />
            {briefExtra?.lessons_learned && (
              <details className="mt-2 text-xs text-gray-600">
                <summary className="cursor-pointer">最近一次复盘要点</summary>
                <p className="mt-1 whitespace-pre-wrap">
                  {briefExtra.lessons_learned}
                </p>
              </details>
            )}
          </div>

          <div className="border rounded-lg p-4">
            <h2 className="font-medium mb-2">引用此 Brief 的流水线（{pipelines.length}）</h2>
            {pipelines.length === 0 ? (
              <div className="text-xs text-gray-400">暂无</div>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {pipelines.map((p) => (
                  <li key={p.id}>
                    <Link
                      href={`/content-studio?id=${p.id}`}
                      className="text-violet-700 hover:underline"
                    >
                      {p.title}
                    </Link>
                    <span className="ml-2 text-[10px] text-gray-500">{p.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border rounded-lg p-4">
            <h2 className="font-medium mb-2">版本树</h2>
            {tree.tree.length === 0 ? (
              <div className="text-xs text-gray-400">暂无版本</div>
            ) : (
              <VersionTreeView tree={tree.tree} currentId={brief.id} />
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}


function Stat({ label, value, percent }: { label: string; value?: number | null; percent?: boolean }) {
  if (value == null) {
    return (
      <div className="flex justify-between text-sm text-gray-400">
        <span>{label}</span>
        <span>—</span>
      </div>
    )
  }
  const v = percent ? `${(Number(value) * 100).toFixed(2)}%` : Number(value).toFixed(2)
  return (
    <div className="flex justify-between text-sm">
      <span className="text-gray-600">{label}</span>
      <span className="font-medium text-gray-800">{v}</span>
    </div>
  )
}


function VersionTreeView({ tree, currentId }: { tree: Brief[]; currentId: string }) {
  // 简化树形：父→子按 parent_brief_id 嵌套
  const byParent: Record<string, Brief[]> = {}
  tree.forEach((b) => {
    const k = b.parent_brief_id ?? '__root__'
    byParent[k] = byParent[k] ?? []
    byParent[k].push(b)
  })
  const roots = byParent['__root__'] ?? tree.filter((b) => !b.parent_brief_id)

  const renderNode = (b: Brief, depth: number) => (
    <div key={b.id}>
      <div
        className="flex items-center gap-1.5 text-sm py-0.5"
        style={{ paddingLeft: depth * 12 }}
      >
        <span className="text-gray-400">{depth > 0 ? '└─' : '•'}</span>
        {b.id === currentId ? (
          <span className="font-medium text-violet-700">v{b.version ?? 1} · {b.title}（当前）</span>
        ) : (
          <Link
            href={`/content-studio/briefs/${b.id}`}
            className="hover:underline text-gray-700"
          >
            v{b.version ?? 1} · {b.title}
          </Link>
        )}
      </div>
      {(byParent[b.id] ?? []).map((child) => renderNode(child, depth + 1))}
    </div>
  )

  return <div className="text-xs">{roots.map((r) => renderNode(r, 0))}</div>
}
