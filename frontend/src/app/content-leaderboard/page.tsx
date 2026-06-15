'use client'

/**
 * 「哪套内容真带货」榜（roadmap E2）—— 列已回传投后数据的素材，按 ROI/GMV 排行，
 * 点一条反查它的全链路（SKU → 卖点矩阵 → 人群 → 脚本）。E1 录了数据这页才有东西看。
 *
 * 数据通路：
 *   GET /api/omni/asset-metrics       → KE pipeline_list_asset_performance
 *   GET /api/omni/asset-lineage?asset_id=  → KE pipeline_get_asset_lineage
 */

import { Fragment, useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import OutputFeedback from '@/components/OutputFeedback'
import { Loader2, RefreshCw, ChevronDown, ChevronRight } from 'lucide-react'

interface PerfAsset {
  asset_id: string
  sku_id: string
  asset_type: string
  status?: string
  last_metrics_at?: string | null
  ad_metrics?: Record<string, unknown>
}

type SortKey = 'roi' | 'gmv' | 'completion_rate' | 'last_metrics_at'

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

// ROI 一律按原始 gmv/spend 现算（不信任回传里的手填 roi——R-4：手填 roi 会被后端标 suspect）
const computeRoi = (m: Record<string, unknown> | undefined): number | null => {
  if (!m) return null
  const gmv = num(m.gmv) ?? num(m.gmv_paid) ?? num(m.revenue)
  const spend = num(m.spend) ?? num(m.cost) ?? num(m.ad_cost)
  if (gmv != null && spend != null && spend > 0) return gmv / spend
  return null
}

const fmtMoney = (v: number | null) => (v == null ? '—' : v >= 10000 ? `${(v / 10000).toFixed(1)}w` : v.toFixed(0))
const fmtRoi = (v: number | null) => (v == null ? '—' : v.toFixed(2))
const fmtRate = (v: number | null) => (v == null ? '—' : `${v.toFixed(1)}%`)
const fmtTime = (s?: string | null) => (s ? s.replace('T', ' ').slice(0, 16) : '—')

export default function ContentLeaderboardPage() {
  const [skuFilter, setSkuFilter] = useState('')
  const [assets, setAssets] = useState<PerfAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('roi')

  const [openId, setOpenId] = useState<string | null>(null)
  const [lineage, setLineage] = useState<Record<string, unknown> | null>(null)
  const [lineageLoading, setLineageLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const qs = new URLSearchParams({ limit: '100' })
      if (skuFilter.trim()) qs.set('sku_id', skuFilter.trim())
      const res = await fetch(`/api/omni/asset-metrics?${qs.toString()}`, { cache: 'no-store' })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setAssets((json.data.assets as PerfAsset[]) || [])
      } else {
        setErr(json.data?.error || json.error || '加载失败')
      }
    } catch (e) {
      setErr(String(e))
    } finally {
      setLoading(false)
    }
  }, [skuFilter])

  useEffect(() => { load() }, [load])

  const openLineage = async (assetId: string) => {
    if (openId === assetId) { setOpenId(null); return }
    setOpenId(assetId)
    setLineage(null)
    setLineageLoading(true)
    try {
      const res = await fetch(`/api/omni/asset-lineage?asset_id=${encodeURIComponent(assetId)}`, { cache: 'no-store' })
      const json = await res.json()
      if (json.success && json.data?.ok) setLineage(json.data.lineage as Record<string, unknown>)
      else setLineage({ _error: json.data?.error || json.error || '反查失败' })
    } catch (e) {
      setLineage({ _error: String(e) })
    } finally {
      setLineageLoading(false)
    }
  }

  const sorted = [...assets].sort((a, b) => {
    if (sortKey === 'last_metrics_at') {
      return (b.last_metrics_at || '').localeCompare(a.last_metrics_at || '')
    }
    const get = (x: PerfAsset): number | null =>
      sortKey === 'roi' ? computeRoi(x.ad_metrics)
        : sortKey === 'gmv' ? (num(x.ad_metrics?.gmv) ?? num(x.ad_metrics?.gmv_paid))
        : num(x.ad_metrics?.completion_rate)
    const av = get(a), bv = get(b)
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    return bv - av
  })

  const sortBtn = (k: SortKey, label: string) => (
    <Button size="sm" variant={sortKey === k ? 'default' : 'outline'} className="text-xs h-7" onClick={() => setSortKey(k)}>
      {label}
    </Button>
  )

  return (
    <div className="px-6 py-6 max-w-6xl mx-auto space-y-4">
      <div>
        <h1 className="text-2xl font-bold">带货榜</h1>
        <p className="text-sm text-muted-foreground mt-1">
          哪套内容（卖点+人群+脚本）真带货——按投后数据排行，点一条反查全链路。数据来自「
          <Link href="/ad-metrics" className="text-violet-600 hover:underline">投后回传</Link>」。
        </p>
      </div>

      <Card>
        <CardContent className="py-3 flex items-center gap-2 flex-wrap text-sm">
          <Input
            placeholder="按 SKU 过滤（可空）"
            value={skuFilter}
            onChange={(e) => setSkuFilter(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') load() }}
            className="h-8 text-xs max-w-xs"
          />
          <Button size="sm" variant="outline" className="text-xs h-8" onClick={load} disabled={loading}>
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            <span className="ml-1">刷新</span>
          </Button>
          <span className="text-xs text-muted-foreground ml-2">排序：</span>
          {sortBtn('roi', 'ROI')}
          {sortBtn('gmv', 'GMV')}
          {sortBtn('completion_rate', '完播率')}
          {sortBtn('last_metrics_at', '最近回传')}
          <span className="text-xs text-muted-foreground ml-auto">{assets.length} 条已回传</span>
        </CardContent>
      </Card>

      {err && <div className="text-sm text-red-600 border border-red-200 rounded bg-red-50 px-3 py-2">加载失败：{err}</div>}

      {!loading && assets.length === 0 && !err && (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground space-y-2">
            <div>还没有任何素材回传投后数据。</div>
            <Link href="/ad-metrics">
              <Button size="sm" className="text-xs">去录第一条投后回传 →</Button>
            </Link>
          </CardContent>
        </Card>
      )}

      {sorted.length > 0 && (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr className="text-left">
                <th className="px-3 py-2 font-medium w-10">#</th>
                <th className="px-3 py-2 font-medium">SKU</th>
                <th className="px-3 py-2 font-medium">类型</th>
                <th className="px-3 py-2 font-medium text-right">GMV</th>
                <th className="px-3 py-2 font-medium text-right">消耗</th>
                <th className="px-3 py-2 font-medium text-right">ROI</th>
                <th className="px-3 py-2 font-medium text-right">完播率</th>
                <th className="px-3 py-2 font-medium text-right">播放</th>
                <th className="px-3 py-2 font-medium">回传时间</th>
                <th className="px-3 py-2 font-medium w-8"></th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {sorted.map((a, i) => {
                const m = a.ad_metrics || {}
                const roi = computeRoi(m)
                const open = openId === a.asset_id
                return (
                  <Fragment key={a.asset_id}>
                    <tr
                      className="hover:bg-muted/30 cursor-pointer"
                      onClick={() => openLineage(a.asset_id)}
                    >
                      <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                      <td className="px-3 py-2">
                        <div className="font-medium">{a.sku_id}</div>
                        <div className="font-mono text-[10px] text-muted-foreground">{a.asset_id.slice(0, 8)}</div>
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant="outline" className="text-[10px]">{a.asset_type}</Badge>
                      </td>
                      <td className="px-3 py-2 text-right">{fmtMoney(num(m.gmv) ?? num(m.gmv_paid))}</td>
                      <td className="px-3 py-2 text-right">{fmtMoney(num(m.spend) ?? num(m.cost))}</td>
                      <td className={`px-3 py-2 text-right font-semibold ${roi != null && roi >= 1 ? 'text-emerald-600' : roi != null ? 'text-amber-600' : ''}`}>{fmtRoi(roi)}</td>
                      <td className="px-3 py-2 text-right">{fmtRate(num(m.completion_rate))}</td>
                      <td className="px-3 py-2 text-right">{num(m.plays) ?? num(m.play_count) ?? '—'}</td>
                      <td className="px-3 py-2 text-muted-foreground">{fmtTime(a.last_metrics_at)}</td>
                      <td className="px-3 py-2">{open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}</td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={10} className="px-3 py-3 bg-muted/20">
                          {lineageLoading && <div className="text-xs text-muted-foreground flex items-center gap-1"><Loader2 className="w-3.5 h-3.5 animate-spin" />反查全链路…</div>}
                          {!lineageLoading && lineage && <LineagePanel lineage={lineage} />}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <OutputFeedback toolName="pipeline_list_asset_performance" label="这个带货榜有用吗？" />
    </div>
  )
}

function LineagePanel({ lineage }: { lineage: Record<string, unknown> }) {
  if (lineage._error) {
    return <div className="text-xs text-red-600">反查失败：{String(lineage._error)}</div>
  }
  const s = (k: string) => (lineage[k] == null ? '' : String(lineage[k]))
  const preview = (k: string, n = 240) => {
    const v = s(k)
    return v.length > n ? v.slice(0, n) + '…' : v
  }
  const row = (label: string, key: string, isPreview = false) => {
    const v = isPreview ? preview(key) : s(key)
    if (!v) return null
    return (
      <div className="flex gap-2 text-xs">
        <span className="text-muted-foreground shrink-0 w-20">{label}</span>
        <span className="whitespace-pre-wrap break-words">{v}</span>
      </div>
    )
  }
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-violet-700">全链路反查</div>
      {row('SKU', 'sku_name')}
      {row('品类', 'sku_category')}
      {row('人群', 'audience_name')}
      {row('人群标签', 'audience_layer_tags')}
      {row('DMP 标签', 'dmp_tags')}
      {row('内容目的', 'target_purpose')}
      {row('卖点矩阵', 'matrix_md', true)}
      {row('脚本', 'script_md', true)}
    </div>
  )
}
