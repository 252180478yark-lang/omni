'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ArrowLeft, BarChart3, Loader2, Users } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { audienceCompare, listCampaigns, listProducts, productTrend } from '@/lib/ad-review-api'

export default function AdReviewAnalyticsPage() {
  const [products, setProducts] = useState<{ id: string; name: string }[]>([])
  const [productId, setProductId] = useState('')
  const [trend, setTrend] = useState<Record<string, unknown>[]>([])
  const [trendLoading, setTrendLoading] = useState(false)

  const [campaigns, setCampaigns] = useState<Record<string, unknown>[]>([])
  const [cid, setCid] = useState('')
  const [compareRows, setCompareRows] = useState<Record<string, unknown>[]>([])
  const [compareLoading, setCompareLoading] = useState(false)

  const [error, setError] = useState('')

  /* ── Init ────────────────────────────────────────────────────────── */
  useEffect(() => {
    void (async () => {
      try {
        const [p, c] = await Promise.all([listProducts(), listCampaigns()])
        setProducts(p.items || [])
        setCampaigns(c.items || [])
        if (p.items?.[0]?.id) setProductId(p.items[0].id)
        if (c.items?.[0]) setCid(String(c.items[0].id))
      } catch (e) {
        setError(String(e))
      }
    })()
  }, [])

  /* ── Auto-load trend when product changes ────────────────────────── */
  useEffect(() => {
    if (!productId) return
    let cancelled = false
    setTrendLoading(true)
    void (async () => {
      try {
        const t = await productTrend(productId)
        if (!cancelled) setTrend(t.points || [])
      } catch (e) {
        if (!cancelled) setError(String(e))
      } finally {
        if (!cancelled) setTrendLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [productId])

  /* ── Auto-load compare when campaign changes ─────────────────────── */
  useEffect(() => {
    if (!cid) return
    let cancelled = false
    setCompareLoading(true)
    void (async () => {
      try {
        const r = await audienceCompare(cid)
        if (!cancelled) setCompareRows(r.rows || [])
      } catch (e) {
        if (!cancelled) setError(String(e))
      } finally {
        if (!cancelled) setCompareLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [cid])

  const chartData = trend.map((p) => ({
    name: String(p.name || p.start_date || '').slice(0, 12),
    avg_ctr: Number(p.avg_ctr || 0) * 100,
    total_cost: Number(p.total_cost || 0),
  }))

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-16">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <header className="border-b border-gray-200/80 bg-white/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link href="/ad-review" className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800">
            <ArrowLeft className="w-4 h-4" /> 投放复盘
          </Link>
          <h1 className="text-lg font-semibold text-gray-900">趋势分析</h1>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-6">
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm">{error}</div>
        )}

        {/* ── Product Trend ────────────────────────────────────────── */}
        <Card className="overflow-hidden">
          <div className="px-5 pt-5 pb-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-indigo-500" />
              <h2 className="text-sm font-semibold text-gray-900">产品投放趋势</h2>
            </div>
            <select
              className="h-8 rounded-md border border-gray-200 bg-white px-2.5 text-sm min-w-[160px] focus:ring-1 focus:ring-indigo-300 focus:border-indigo-400 outline-none"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
            >
              <option value="" disabled>选择产品</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <CardContent className="pt-0 pb-5">
            {trendLoading ? (
              <div className="h-64 flex items-center justify-center text-gray-400 text-sm">
                <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载中…
              </div>
            ) : chartData.length === 0 ? (
              <div className="h-64 flex items-center justify-center text-gray-400 text-sm">
                暂无趋势数据，请选择产品
              </div>
            ) : (
              <div className="h-72 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="#999" />
                    <YAxis yAxisId="left" tick={{ fontSize: 11 }} stroke="#999" />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} stroke="#999" />
                    <Tooltip
                      contentStyle={{ borderRadius: 8, fontSize: 13, border: '1px solid #e5e7eb' }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="avg_ctr"
                      name="平均 CTR %"
                      stroke="#6366f1"
                      strokeWidth={2}
                      dot={{ r: 3, fill: '#6366f1' }}
                      activeDot={{ r: 5 }}
                    />
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="total_cost"
                      name="消耗 (元)"
                      stroke="#10b981"
                      strokeWidth={2}
                      dot={{ r: 3, fill: '#10b981' }}
                      activeDot={{ r: 5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Audience Compare ─────────────────────────────────────── */}
        <Card className="overflow-hidden">
          <div className="px-5 pt-5 pb-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4 text-emerald-500" />
              <h2 className="text-sm font-semibold text-gray-900">人群包对比</h2>
            </div>
            <select
              className="h-8 rounded-md border border-gray-200 bg-white px-2.5 text-sm min-w-[200px] focus:ring-1 focus:ring-emerald-300 focus:border-emerald-400 outline-none"
              value={cid}
              onChange={(e) => setCid(e.target.value)}
            >
              <option value="" disabled>选择批次</option>
              {campaigns.map((c) => (
                <option key={String(c.id)} value={String(c.id)}>{String(c.name)}</option>
              ))}
            </select>
          </div>
          <CardContent className="pt-0 pb-5">
            {compareLoading ? (
              <div className="h-32 flex items-center justify-center text-gray-400 text-sm">
                <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载中…
              </div>
            ) : compareRows.length === 0 ? (
              <div className="h-32 flex items-center justify-center text-gray-400 text-sm">
                暂无对比数据，请选择批次
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="py-2.5 pr-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">人群包</th>
                      <th className="py-2.5 pr-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">素材数</th>
                      <th className="py-2.5 pr-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">消耗</th>
                      <th className="py-2.5 pr-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">平均 CTR</th>
                      <th className="py-2.5 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">完播率</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {compareRows.map((r) => {
                      const ctr = r.avg_ctr != null ? Number(r.avg_ctr) * 100 : null
                      return (
                        <tr key={String(r.audience_pack_id)} className="hover:bg-gray-50/50">
                          <td className="py-2.5 pr-3 font-medium text-gray-900">{String(r.audience_name)}</td>
                          <td className="py-2.5 pr-3 text-right text-gray-600">{String(r.material_count)}</td>
                          <td className="py-2.5 pr-3 text-right text-gray-600">
                            {Number(r.total_cost || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </td>
                          <td className={`py-2.5 pr-3 text-right font-medium ${ctr != null && ctr >= 3 ? 'text-green-600' : 'text-gray-600'}`}>
                            {ctr != null ? `${ctr.toFixed(2)}%` : '—'}
                          </td>
                          <td className="py-2.5 text-right text-gray-600">
                            {r.avg_completion_rate != null ? `${(Number(r.avg_completion_rate) * 100).toFixed(2)}%` : '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  )
}
