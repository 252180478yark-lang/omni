'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { BarChart3, Plus, MoreHorizontal, Trash2, FileText, Users, Video, TrendingUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  type CampaignListItem,
  createCampaign,
  deleteCampaign,
  listCampaigns,
  listProducts,
} from '@/lib/ad-review-api'

const STATUS_CFG: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'bg-gray-100 text-gray-600' },
  data_uploaded: { label: '数据已上传', color: 'bg-blue-50 text-blue-700' },
  reviewed: { label: '已复盘', color: 'bg-green-50 text-green-700' },
  archived: { label: '已归档', color: 'bg-gray-50 text-gray-400' },
}

export default function AdReviewHomePage() {
  const [items, setItems] = useState<CampaignListItem[]>([])
  const [products, setProducts] = useState<{ id: string; name: string }[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [productFilter, setProductFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  const [form, setForm] = useState({
    product_name: '',
    product_sku: '',
    product_price: '',
    product_margin_rate: '',
    name: '',
    start_date: '',
    end_date: '',
    total_budget: '',
  })

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const qs = new URLSearchParams()
      if (productFilter) qs.set('product_id', productFilter)
      if (statusFilter) qs.set('status', statusFilter)
      const [c, p] = await Promise.all([listCampaigns(qs.toString()), listProducts()])
      setItems(c.items || [])
      setProducts(p.items || [])
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [productFilter, statusFilter])

  useEffect(() => {
    void load()
  }, [load])

  // Close menu on outside click
  useEffect(() => {
    if (!menuOpen) return
    const handler = () => setMenuOpen(null)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [menuOpen])

  const onCreate = async () => {
    setCreating(true)
    setError('')
    try {
      const body = {
        product_name: form.product_name.trim(),
        product_sku: form.product_sku.trim() || null,
        product_price: form.product_price ? Number(form.product_price) : null,
        product_margin_rate: form.product_margin_rate ? Number(form.product_margin_rate) / 100 : null,
        name: form.name.trim(),
        start_date: form.start_date,
        end_date: form.end_date,
        total_budget: form.total_budget ? Number(form.total_budget) : null,
      }
      const { id } = await createCampaign(body)
      setOpen(false)
      setForm({ product_name: '', product_sku: '', product_price: '', product_margin_rate: '', name: '', start_date: '', end_date: '', total_budget: '' })
      window.location.href = `/ad-review/${id}`
    } catch (e) {
      setError(String(e))
    } finally {
      setCreating(false)
    }
  }

  const onDelete = async (id: string) => {
    if (!confirm('确定删除该批次？关联人群包与素材将一并删除。')) return
    setMenuOpen(null)
    try {
      await deleteCampaign(id)
      void load()
    } catch (e) {
      setError(String(e))
    }
  }

  const productOptions = useMemo(() => products, [products])

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-16">
      <header className="border-b border-gray-200/80 bg-white/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 py-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Link href="/" className="text-sm text-gray-500 hover:text-gray-800">
              ← 控制台
            </Link>
            <h1 className="text-xl font-semibold text-gray-900">投放复盘</h1>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/ad-review/analytics">
              <Button variant="outline" size="sm" className="gap-1">
                <BarChart3 className="w-4 h-4" />
                趋势分析
              </Button>
            </Link>
            <Button size="sm" className="gap-1" onClick={() => setOpen(true)}>
              <Plus className="w-4 h-4" />
              创建新批次
            </Button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-4">
        {/* Filters */}
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <span className="text-xs text-gray-500 block mb-1">产品</span>
            <select
              className="h-9 rounded-md border border-input bg-white px-3 text-sm min-w-[160px]"
              value={productFilter}
              onChange={(e) => setProductFilter(e.target.value)}
            >
              <option value="">全部产品</option>
              {productOptions.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div>
            <span className="text-xs text-gray-500 block mb-1">状态</span>
            <select
              className="h-9 rounded-md border border-input bg-white px-3 text-sm min-w-[140px]"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">全部状态</option>
              {Object.entries(STATUS_CFG).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm">{error}</div>
        )}

        {loading ? (
          <p className="text-gray-500 text-sm py-8 text-center">加载中…</p>
        ) : items.length === 0 ? (
          <div className="py-16 text-center">
            <div className="text-4xl mb-3">📊</div>
            <p className="text-gray-500 text-sm mb-4">暂无投放批次</p>
            <Button size="sm" onClick={() => setOpen(true)} className="gap-1">
              <Plus className="w-4 h-4" /> 创建第一个批次
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((c) => {
              const st = STATUS_CFG[c.status || ''] || { label: c.status, color: 'bg-gray-100 text-gray-600' }
              return (
                <Card key={c.id} className="hover:shadow-md transition-shadow overflow-hidden">
                  <CardContent className="p-0">
                    <Link href={`/ad-review/${c.id}`} className="block p-4 pb-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <h3 className="font-medium text-gray-900 truncate">{c.name}</h3>
                          <p className="text-sm text-gray-500 mt-0.5">
                            {c.product_name} · {c.start_date} ~ {c.end_date}
                          </p>
                        </div>
                        <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${st.color}`}>
                          {st.label}
                        </span>
                      </div>
                    </Link>
                    {/* Metrics bar */}
                    <div className="px-4 pb-3 flex items-center justify-between gap-4">
                      <div className="flex gap-5 text-xs text-gray-500">
                        <span className="flex items-center gap-1">
                          <Users className="w-3.5 h-3.5" />
                          {c.audience_count ?? 0} 人群包
                        </span>
                        <span className="flex items-center gap-1">
                          <Video className="w-3.5 h-3.5" />
                          {c.material_count ?? 0} 素材
                        </span>
                        <span className="flex items-center gap-1">
                          <TrendingUp className="w-3.5 h-3.5" />
                          {c.best_ctr != null ? `最佳 CTR ${(Number(c.best_ctr) * 100).toFixed(2)}%` : 'CTR —'}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-700">
                          ¥{Number(c.total_cost || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                        </span>
                        {/* Action buttons */}
                        <Link href={`/ad-review/${c.id}/review`}>
                          <Button variant="outline" size="sm" className="gap-1 h-7 text-xs">
                            <FileText className="w-3 h-3" /> 复盘
                          </Button>
                        </Link>
                        <div className="relative">
                          <button
                            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600"
                            onClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === c.id ? null : c.id) }}
                          >
                            <MoreHorizontal className="w-4 h-4" />
                          </button>
                          {menuOpen === c.id && (
                            <div className="absolute right-0 top-8 z-20 w-32 bg-white border rounded-lg shadow-lg py-1">
                              <button
                                className="w-full text-left px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
                                onClick={() => void onDelete(c.id)}
                              >
                                <Trash2 className="w-3.5 h-3.5" /> 删除批次
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </main>

      {/* Create Dialog */}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>创建投放批次</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 py-2">
            <div>
              <label className="text-xs text-gray-500">产品名称</label>
              <Input
                value={form.product_name}
                onChange={(e) => setForm((f) => ({ ...f, product_name: e.target.value }))}
                placeholder="如：XX酱油"
              />
            </div>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <label className="text-xs text-gray-500">SKU（可选）</label>
                <Input value={form.product_sku} onChange={(e) => setForm((f) => ({ ...f, product_sku: e.target.value }))} placeholder="如：SY-001" />
              </div>
              <div>
                <label className="text-xs text-gray-500">产品单价（元）</label>
                <Input type="number" step="0.01" value={form.product_price} onChange={(e) => setForm((f) => ({ ...f, product_price: e.target.value }))} placeholder="29.90" />
              </div>
              <div>
                <label className="text-xs text-gray-500">毛利率（%）</label>
                <Input type="number" step="1" value={form.product_margin_rate} onChange={(e) => setForm((f) => ({ ...f, product_margin_rate: e.target.value }))} placeholder="如：40" />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500">批次名称</label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="如：春季推广第一轮"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-gray-500">开始日期</label>
                <Input type="date" value={form.start_date} onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))} />
              </div>
              <div>
                <label className="text-xs text-gray-500">结束日期</label>
                <Input type="date" value={form.end_date} onChange={(e) => setForm((f) => ({ ...f, end_date: e.target.value }))} />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500">总预算（可选）</label>
              <Input type="number" value={form.total_budget} onChange={(e) => setForm((f) => ({ ...f, total_budget: e.target.value }))} placeholder="元" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
            <Button onClick={() => void onCreate()} disabled={creating}>
              {creating ? '创建中…' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
