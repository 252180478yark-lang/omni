'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Package, ArrowRight, RefreshCw, Star, TrendingDown, TrendingUp, Minus } from 'lucide-react'

interface Sku {
  id: string
  name: string
  category: string | null
  douyin_product_id: string
  status: string
  growth_class: string | null
  platform_status: string | null
  in_focus_pool: boolean
  focus_reason: string | null
  locked_by_user: boolean
  total_stock: number | null
  available_stock: number | null
}

const GROWTH_CONFIG: Record<string, { label: string; icon: React.ComponentType<{ className?: string }>; cls: string }> = {
  growing:  { label: '增长', icon: TrendingUp, cls: 'bg-emerald-100 text-emerald-700 border-emerald-200' },
  stable:   { label: '稳定', icon: Minus, cls: 'bg-blue-100 text-blue-700 border-blue-200' },
  declining:{ label: '衰退', icon: TrendingDown, cls: 'bg-rose-100 text-rose-700 border-rose-200' },
  new:      { label: '新品', icon: Star, cls: 'bg-violet-100 text-violet-700 border-violet-200' },
}

type Filter = 'all' | 'focus' | 'growing' | 'declining'

export default function ProductsPage() {
  const [skus, setSkus] = useState<Sku[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<Filter>('all')
  const [usePlaceholder, setUsePlaceholder] = useState(false)

  useEffect(() => {
    fetch('/api/omni/scout/skus')
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((data: Sku[]) => {
        if (data.length > 0) {
          setSkus(data)
        } else {
          setUsePlaceholder(true)
        }
      })
      .catch(() => setUsePlaceholder(true))
      .finally(() => setLoading(false))
  }, [])

  const placeholderSkus: Sku[] = [
    { id: 'SKU-A001', name: '主推爆品 #1（待同步）', category: '调味品/酱油', douyin_product_id: '', status: 'active', growth_class: 'growing', platform_status: null, in_focus_pool: true, focus_reason: 'gmv_top5', locked_by_user: false, total_stock: null, available_stock: null },
    { id: 'SKU-A002', name: '主推爆品 #2（待同步）', category: '调味品/酱油', douyin_product_id: '', status: 'active', growth_class: 'stable', platform_status: null, in_focus_pool: true, focus_reason: 'gmv_top5', locked_by_user: false, total_stock: null, available_stock: null },
    { id: 'SKU-A003', name: '增长款 #1（待同步）', category: '调味品/醋', douyin_product_id: '', status: 'active', growth_class: 'growing', platform_status: null, in_focus_pool: false, focus_reason: null, locked_by_user: false, total_stock: null, available_stock: null },
    { id: 'SKU-A004', name: '衰退款 #1（待同步）', category: '调味品/料酒', douyin_product_id: '', status: 'active', growth_class: 'declining', platform_status: null, in_focus_pool: false, focus_reason: null, locked_by_user: false, total_stock: null, available_stock: null },
  ]

  const displaySkus = usePlaceholder ? placeholderSkus : skus

  const filtered = displaySkus.filter((s) => {
    if (filter === 'focus') return s.in_focus_pool
    if (filter === 'growing') return s.growth_class === 'growing'
    if (filter === 'declining') return s.growth_class === 'declining'
    return true
  })

  const focusCount = displaySkus.filter((s) => s.in_focus_pool).length

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            <Package className="w-7 h-7 text-violet-600" />
            我的产品
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            点击 SKU 进入详情：指标趋势 · 动作日志 · AI 诊断
          </p>
        </div>
        {!usePlaceholder && (
          <div className="text-xs text-gray-400">{displaySkus.length} 个 SKU</div>
        )}
      </div>

      {/* Filter bar */}
      <div className="flex gap-2 mb-5 flex-wrap">
        {([
          ['all', `全部 (${displaySkus.length})`],
          ['focus', `重点池 (${focusCount})`],
          ['growing', '增长'],
          ['declining', '衰退'],
        ] as [Filter, string][]).map(([key, label]) => (
          <Button
            key={key}
            variant={filter === key ? 'default' : 'outline'}
            size="sm"
            className={`h-7 text-xs ${filter === key ? 'bg-violet-600 hover:bg-violet-700' : ''}`}
            onClick={() => setFilter(key)}
          >
            {label}
          </Button>
        ))}
      </div>

      {loading ? (
        <div className="text-sm text-gray-400 text-center py-12">加载中…</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((sku) => {
            const gc = GROWTH_CONFIG[sku.growth_class ?? '']
            const GcIcon = gc?.icon
            return (
              <Link key={sku.id} href={`/sku/${sku.id}`} className="group block">
                <Card className="hover:border-violet-200 hover:shadow-md transition-all h-full">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {sku.in_focus_pool && (
                          <Badge variant="outline" className="text-[10px] bg-amber-50 text-amber-700 border-amber-200">
                            重点池
                          </Badge>
                        )}
                        {gc && (
                          <Badge variant="outline" className={`text-[10px] ${gc.cls}`}>
                            {GcIcon && <GcIcon className="w-2.5 h-2.5 mr-0.5" />}
                            {gc.label}
                          </Badge>
                        )}
                      </div>
                      <ArrowRight className="w-4 h-4 text-gray-300 group-hover:text-violet-500 transition shrink-0" />
                    </div>
                    <div className="font-mono text-xs text-gray-400 mb-1">{sku.id}</div>
                    <div className="font-medium text-sm text-gray-900 mb-1 line-clamp-2">{sku.name}</div>
                    {sku.category && (
                      <div className="text-xs text-gray-500">{sku.category}</div>
                    )}
                    {sku.available_stock != null && (
                      <div className="text-[10px] text-gray-400 mt-1.5">
                        库存 {sku.available_stock.toLocaleString()}
                      </div>
                    )}
                  </CardContent>
                </Card>
              </Link>
            )
          })}
        </div>
      )}

      {usePlaceholder && (
        <Card className="mt-6 border-dashed">
          <CardContent className="p-5 text-center text-sm text-gray-500">
            <RefreshCw className="w-5 h-5 mx-auto text-gray-300 mb-2" />
            <p className="mb-1">scout-agent 未连接或尚无数据</p>
            <p className="text-xs text-gray-400">
              启动 scout-agent 并运行「B-SKU详情」runbook 后，真实商品数据会自动同步到这里
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
