'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'

interface SkuSummary {
  id: string
  name: string
  category: string | null
  status: string
  push_tier: string | null
  growth_class: string | null
  owner_selling_points?: Array<{ text?: string } | string> | null
  owner_notes?: string | null
  price_min?: number | null
  price_max?: number | null
}

interface Orchestration {
  id: string
  title: string | null
  status: string
  current_step: string
  target_purpose: string | null
  linked_brief_id?: string | null
  linked_pipeline_id?: string | null
}

const PURPOSE_LABEL: Record<string, string> = {
  awareness: '曝光',
  planting: '种草',
  conversion: '收割',
}

const STATUS_LABEL: Record<string, string> = {
  in_progress: '进行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
}

export function SkuContextPanel() {
  const searchParams = useSearchParams()
  const skuId = searchParams.get('sku_id') || ''

  const [sku, setSku] = useState<SkuSummary | null>(null)
  const [orchestrations, setOrchestrations] = useState<Orchestration[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!skuId) {
      setSku(null)
      setOrchestrations([])
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const [sRes, oRes] = await Promise.all([
          fetch(`/api/omni/scout/skus/${skuId}`, { cache: 'no-store' }),
          fetch(`/api/omni/content-studio/sku-orchestrations?sku_id=${skuId}&limit=5`, { cache: 'no-store' }),
        ])
        if (!sRes.ok) throw new Error(`SKU ${sRes.status}`)
        const skuData = (await sRes.json()) as SkuSummary
        const orchData = oRes.ok ? await oRes.json() : { items: [] }
        if (!cancelled) {
          setSku(skuData)
          setOrchestrations(orchData.items || [])
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [skuId])

  if (!skuId) return null
  if (error) {
    return (
      <div className="mx-auto my-2 max-w-3xl rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
        无法加载 SKU 上下文（{error}）
      </div>
    )
  }
  if (!sku) {
    return (
      <div className="mx-auto my-2 max-w-3xl rounded border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500">
        加载 SKU 上下文中…
      </div>
    )
  }

  const sellingPoints: string[] = (sku.owner_selling_points || [])
    .map((sp) => (typeof sp === 'string' ? sp : (sp?.text || '')))
    .filter((t) => t.trim())
    .slice(0, 3)

  const priceText = (() => {
    if (sku.price_min != null && sku.price_max != null) return `¥${sku.price_min}-${sku.price_max}`
    if (sku.price_min != null) return `¥${sku.price_min}+`
    if (sku.price_max != null) return `≤¥${sku.price_max}`
    return ''
  })()

  const inProgress = orchestrations.find((o) => o.status === 'in_progress')
  const completed = orchestrations.filter((o) => o.status === 'completed').length

  return (
    <div className="mx-auto my-3 max-w-3xl rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-xs">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="font-medium text-amber-900 flex items-center gap-1.5">
          📦 当前会话已挂载 SKU：{sku.name}
          {sku.category && <span className="text-[10px] font-normal text-amber-600">· {sku.category}</span>}
          {priceText && <span className="text-[10px] font-normal text-amber-600">· {priceText}</span>}
        </div>
        <Link
          href={`/sku/${skuId}`}
          className="rounded border border-amber-300 bg-white px-2 py-0.5 text-[11px] text-amber-700 hover:bg-amber-100"
        >
          去 SKU 工作台 →
        </Link>
      </div>

      {sellingPoints.length > 0 && (
        <div className="mb-1 text-amber-900">
          <span className="text-amber-600">老板卖点：</span>
          {sellingPoints.join(' · ')}
          {(sku.owner_selling_points?.length || 0) > 3 && (
            <span className="text-amber-500"> +{(sku.owner_selling_points?.length || 0) - 3}</span>
          )}
        </div>
      )}

      {sku.owner_notes && (
        <div className="mb-1 text-amber-800 line-clamp-1">
          <span className="text-amber-600">备注：</span>
          {sku.owner_notes}
        </div>
      )}

      {(inProgress || completed > 0) && (
        <div className="mt-2 pt-2 border-t border-amber-200/60 text-amber-800 flex items-center gap-3 flex-wrap">
          {inProgress && (
            <Link
              href={`/sku/${skuId}?tab=content`}
              className="text-violet-700 hover:underline"
            >
              ⚡ 编排进行中：{PURPOSE_LABEL[inProgress.target_purpose || ''] || '智能推荐'} · {STATUS_LABEL[inProgress.status] || inProgress.status} · {inProgress.current_step}
            </Link>
          )}
          {completed > 0 && (
            <span className="text-emerald-700">✓ 已完成 {completed} 份编排</span>
          )}
        </div>
      )}
    </div>
  )
}
