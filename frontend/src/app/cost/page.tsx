'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Calculator, MessageSquareText, Plus, Trash2, Pencil, X, Loader2, RefreshCw, Upload, FileText, CheckSquare, Square } from 'lucide-react'

type Category = 'product' | 'logistics' | 'partner_quote'

interface CostItem {
  id: string
  sku_id: string | null
  category: Category
  item_name: string
  unit_cost: number
  currency: string
  unit: string
  quantity_per_unit: number
  vendor: string | null
  valid_from: string
  valid_to: string | null
  is_active: boolean
  notes: string | null
  created_at: string
  updated_at: string
}

const CATEGORY_OPTIONS: { value: Category; label: string; desc: string }[] = [
  { value: 'product', label: '产品成本', desc: '原料/包装/瓶身/标签/箱/人工' },
  { value: 'logistics', label: '物流成本', desc: '顺丰/京东专线/同城配送' },
  { value: 'partner_quote', label: '合作报价', desc: '代工厂/服务商报价（仅参考，不计净利）' },
]

const CATEGORY_BADGE_STYLES: Record<Category, string> = {
  product: 'bg-blue-50 text-blue-700 border-blue-200',
  logistics: 'bg-amber-50 text-amber-700 border-amber-200',
  partner_quote: 'bg-violet-50 text-violet-700 border-violet-200',
}

function categoryLabel(c: Category): string {
  return CATEGORY_OPTIONS.find((x) => x.value === c)?.label || c
}

interface ExtractedItem {
  category: 'product' | 'logistics' | 'partner_quote'
  item_name: string
  unit_cost: number
  currency: string
  unit: string
  quantity_per_unit: number
  vendor: string | null
  sku_id: string | null
  notes: string | null
  confidence: number
}

const SUPPORTED_FILE_EXTS = '.csv,.xlsx,.xls,.pdf,.docx,.txt,.md,.html,.htm,.srt'

interface CostItemFormState {
  sku_id: string
  category: Category
  item_name: string
  unit_cost: string
  currency: string
  unit: string
  quantity_per_unit: string
  vendor: string
  valid_from: string
  valid_to: string
  notes: string
  is_active: boolean
}

const EMPTY_FORM: CostItemFormState = {
  sku_id: '',
  category: 'product',
  item_name: '',
  unit_cost: '',
  currency: 'CNY',
  unit: '件',
  quantity_per_unit: '1',
  vendor: '',
  valid_from: '',
  valid_to: '',
  notes: '',
  is_active: true,
}

export default function CostPage() {
  const [items, setItems] = useState<CostItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // 筛选
  const [filterSku, setFilterSku] = useState('')
  const [filterCategory, setFilterCategory] = useState<Category | ''>('')
  const [filterName, setFilterName] = useState('')
  const [filterActiveOnly, setFilterActiveOnly] = useState(true)

  // 录入/编辑 modal
  const [showFormModal, setShowFormModal] = useState(false)
  const [formMode, setFormMode] = useState<'create' | 'edit'>('create')
  const [editingId, setEditingId] = useState<string>('')
  const [form, setForm] = useState<CostItemFormState>(EMPTY_FORM)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  // 净利率 modal
  const [showMarginModal, setShowMarginModal] = useState(false)
  const [marginSku, setMarginSku] = useState('')
  const [marginPrice, setMarginPrice] = useState('')
  const [marginQty, setMarginQty] = useState('1')
  const [marginFeeRate, setMarginFeeRate] = useState('0.05')
  const [marginIncludeShared, setMarginIncludeShared] = useState(true)
  const [marginLoading, setMarginLoading] = useState(false)
  const [marginError, setMarginError] = useState('')
  const [marginResult, setMarginResult] = useState<any>(null)

  // 文件导入 modal
  const [showImportModal, setShowImportModal] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importDefaultSku, setImportDefaultSku] = useState('')
  const [importLoading, setImportLoading] = useState(false)
  const [importError, setImportError] = useState('')
  const [previewItems, setPreviewItems] = useState<ExtractedItem[]>([])
  const [selectedRows, setSelectedRows] = useState<Set<number>>(new Set())
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkSummary, setBulkSummary] = useState<{ created: number; errors: number } | null>(null)
  const importInputRef = React.useRef<HTMLInputElement>(null)

  // 自然语言问询 modal
  const [showQueryModal, setShowQueryModal] = useState(false)
  const [nlQuery, setNlQuery] = useState('')
  const [nlSku, setNlSku] = useState('')
  const [nlPrice, setNlPrice] = useState('')
  const [nlLoading, setNlLoading] = useState(false)
  const [nlError, setNlError] = useState('')
  const [nlResult, setNlResult] = useState<any>(null)

  const loadItems = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams()
      if (filterSku) params.set('sku_id', filterSku)
      if (filterCategory) params.set('category', filterCategory)
      if (filterName) params.set('item_name_search', filterName)
      params.set('active_only', String(filterActiveOnly))
      const res = await fetch(`/api/omni/cost/cost-items?${params.toString()}`, { cache: 'no-store' })
      const json = (await res.json()) as { success: boolean; data?: CostItem[]; error?: string }
      if (!json.success || !json.data) throw new Error(json.error || 'load failed')
      setItems(json.data)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [filterSku, filterCategory, filterName, filterActiveOnly])

  useEffect(() => { loadItems() }, [loadItems])

  const openCreate = () => {
    setFormMode('create')
    setEditingId('')
    setForm(EMPTY_FORM)
    setFormError('')
    setShowFormModal(true)
  }

  const openEdit = (item: CostItem) => {
    setFormMode('edit')
    setEditingId(item.id)
    setForm({
      sku_id: item.sku_id || '',
      category: item.category,
      item_name: item.item_name,
      unit_cost: String(item.unit_cost),
      currency: item.currency,
      unit: item.unit,
      quantity_per_unit: String(item.quantity_per_unit),
      vendor: item.vendor || '',
      valid_from: item.valid_from || '',
      valid_to: item.valid_to || '',
      notes: item.notes || '',
      is_active: item.is_active,
    })
    setFormError('')
    setShowFormModal(true)
  }

  const submitForm = async () => {
    if (!form.item_name.trim()) { setFormError('请填写项目名称'); return }
    const unitCost = Number(form.unit_cost)
    if (isNaN(unitCost) || unitCost < 0) { setFormError('单价必须 ≥ 0'); return }
    const qpu = Number(form.quantity_per_unit)
    if (isNaN(qpu) || qpu <= 0) { setFormError('单位换算数必须 > 0'); return }

    setSubmitting(true)
    setFormError('')
    try {
      const payload: Record<string, unknown> = {
        sku_id: form.sku_id.trim() || null,
        category: form.category,
        item_name: form.item_name.trim(),
        unit_cost: unitCost,
        currency: form.currency || 'CNY',
        unit: form.unit || '件',
        quantity_per_unit: qpu,
        vendor: form.vendor.trim() || null,
        valid_from: form.valid_from || null,
        valid_to: form.valid_to || null,
        notes: form.notes.trim() || null,
      }
      if (formMode === 'edit') {
        payload.is_active = form.is_active
      }
      const url = formMode === 'create'
        ? '/api/omni/cost/cost-items'
        : `/api/omni/cost/cost-items/${editingId}`
      const method = formMode === 'create' ? 'POST' : 'PATCH'
      const res = await fetch(url, {
        method, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '提交失败')
      setShowFormModal(false)
      await loadItems()
    } catch (e) {
      setFormError(String(e))
    } finally {
      setSubmitting(false)
    }
  }

  const removeItem = async (id: string) => {
    if (!confirm('确定删除该成本项？')) return
    try {
      const res = await fetch(`/api/omni/cost/cost-items/${id}`, { method: 'DELETE' })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '删除失败')
      await loadItems()
    } catch (e) {
      alert(String(e))
    }
  }

  const computeMargin = async () => {
    if (!marginSku.trim()) { setMarginError('请填写 SKU'); return }
    const price = Number(marginPrice)
    if (isNaN(price) || price <= 0) { setMarginError('售价必须 > 0'); return }
    const qty = Number(marginQty) || 1
    const fee = Number(marginFeeRate) || 0
    setMarginLoading(true)
    setMarginError('')
    setMarginResult(null)
    try {
      const res = await fetch('/api/omni/cost/margin', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sku_id: marginSku.trim(),
          sale_price: price,
          quantity: qty,
          platform_fee_rate: fee,
          include_shared_logistics: marginIncludeShared,
        }),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '计算失败')
      setMarginResult(json.data)
    } catch (e) {
      setMarginError(String(e))
    } finally {
      setMarginLoading(false)
    }
  }

  const openImport = () => {
    setImportFile(null)
    setImportDefaultSku('')
    setImportError('')
    setPreviewItems([])
    setSelectedRows(new Set())
    setBulkSummary(null)
    setShowImportModal(true)
  }

  const runExtract = async () => {
    if (!importFile) { setImportError('请先选择文件'); return }
    setImportLoading(true)
    setImportError('')
    setPreviewItems([])
    setSelectedRows(new Set())
    try {
      const fd = new FormData()
      fd.append('file', importFile, importFile.name)
      if (importDefaultSku.trim()) fd.append('sku_id', importDefaultSku.trim())
      const res = await fetch('/api/omni/cost/extract', { method: 'POST', body: fd })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '解析失败')
      const items = (json.data?.items || []) as ExtractedItem[]
      setPreviewItems(items)
      setSelectedRows(new Set(items.map((_, i) => i)))
      if (items.length === 0) {
        setImportError('LLM 没有从文件中识别出成本项；请检查文件内容或换一份')
      }
    } catch (e) {
      setImportError(String(e))
    } finally {
      setImportLoading(false)
    }
  }

  const updatePreviewItem = (idx: number, patch: Partial<ExtractedItem>) => {
    setPreviewItems((prev) => prev.map((it, i) => (i === idx ? { ...it, ...patch } : it)))
  }

  const toggleRow = (idx: number) => {
    setSelectedRows((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx); else next.add(idx)
      return next
    })
  }

  const toggleAll = () => {
    if (selectedRows.size === previewItems.length) {
      setSelectedRows(new Set())
    } else {
      setSelectedRows(new Set(previewItems.map((_, i) => i)))
    }
  }

  const submitBulk = async () => {
    const picked = previewItems.filter((_, i) => selectedRows.has(i))
    if (picked.length === 0) { setImportError('请至少勾选一行'); return }
    // 校验
    for (let i = 0; i < picked.length; i++) {
      const it = picked[i]
      if (!it.item_name?.trim()) { setImportError(`第 ${i + 1} 条缺名称`); return }
      if (!(it.unit_cost >= 0)) { setImportError(`第 ${i + 1} 条单价不合法`); return }
      if (!it.category) { setImportError(`第 ${i + 1} 条品类未选`); return }
    }
    setBulkLoading(true)
    setImportError('')
    try {
      const items = picked.map((it) => ({
        sku_id: it.sku_id || null,
        category: it.category,
        item_name: it.item_name.trim(),
        unit_cost: Number(it.unit_cost),
        currency: it.currency || 'CNY',
        unit: it.unit || '件',
        quantity_per_unit: Number(it.quantity_per_unit) || 1,
        vendor: it.vendor || null,
        notes: it.notes || null,
      }))
      const res = await fetch('/api/omni/cost/cost-items/bulk', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items }),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '入库失败')
      const created = (json.data?.created || []).length
      const errs = (json.data?.errors || []).length
      setBulkSummary({ created, errors: errs })
      await loadItems()
    } catch (e) {
      setImportError(String(e))
    } finally {
      setBulkLoading(false)
    }
  }

  const askNL = async () => {
    if (!nlQuery.trim()) { setNlError('请输入问题'); return }
    setNlLoading(true)
    setNlError('')
    setNlResult(null)
    try {
      const res = await fetch('/api/omni/cost/query', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: nlQuery.trim(),
          sku_id: nlSku.trim() || null,
          sale_price: nlPrice ? Number(nlPrice) : null,
        }),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '问询失败')
      setNlResult(json.data)
    } catch (e) {
      setNlError(String(e))
    } finally {
      setNlLoading(false)
    }
  }

  const summary = useMemo(() => {
    const byCat: Record<string, number> = {}
    for (const it of items) byCat[it.category] = (byCat[it.category] || 0) + 1
    return byCat
  }, [items])

  return (
    <div className="container mx-auto p-6 space-y-6 max-w-7xl">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Calculator className="w-5 h-5" /> 成本 / 算账
            </CardTitle>
            <CardDescription>
              结构化录入产品/物流/合作报价成本，精确算净利率（不再 RAG 模糊匹配）
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button onClick={openCreate}><Plus className="w-4 h-4 mr-1" />新增成本项</Button>
            <Button variant="outline" onClick={openImport}>
              <Upload className="w-4 h-4 mr-1" />从文件导入
            </Button>
            <Button variant="outline" onClick={() => { setMarginResult(null); setMarginError(''); setShowMarginModal(true) }}>
              <Calculator className="w-4 h-4 mr-1" />净利率计算
            </Button>
            <Button variant="outline" onClick={() => { setNlResult(null); setNlError(''); setShowQueryModal(true) }}>
              <MessageSquareText className="w-4 h-4 mr-1" />自然语言问询
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* 筛选 */}
          <div className="flex flex-wrap gap-3 items-end border-b pb-4">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">SKU ID</label>
              <input
                value={filterSku}
                onChange={(e) => setFilterSku(e.target.value)}
                className="border rounded px-3 py-1.5 text-sm w-44"
                placeholder="留空 = 全部"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">品类</label>
              <select
                value={filterCategory}
                onChange={(e) => setFilterCategory(e.target.value as Category | '')}
                className="border rounded px-3 py-1.5 text-sm"
              >
                <option value="">全部</option>
                {CATEGORY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">名称搜索</label>
              <input
                value={filterName}
                onChange={(e) => setFilterName(e.target.value)}
                className="border rounded px-3 py-1.5 text-sm w-44"
                placeholder="模糊搜索"
              />
            </div>
            <label className="flex items-center gap-2 text-sm pb-1.5">
              <input
                type="checkbox"
                checked={filterActiveOnly}
                onChange={(e) => setFilterActiveOnly(e.target.checked)}
              />
              仅显示当前有效
            </label>
            <Button size="sm" variant="outline" onClick={loadItems}>
              <RefreshCw className="w-3.5 h-3.5 mr-1" />刷新
            </Button>
            <div className="ml-auto text-xs text-muted-foreground">
              共 {items.length} 条 · 产品 {summary.product || 0} · 物流 {summary.logistics || 0} · 报价 {summary.partner_quote || 0}
            </div>
          </div>

          {error && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
              加载失败：{error}
            </div>
          )}

          {/* 表格 */}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b bg-muted/30">
                  <th className="px-3 py-2 font-medium">名称</th>
                  <th className="px-3 py-2 font-medium">品类</th>
                  <th className="px-3 py-2 font-medium text-right">单价</th>
                  <th className="px-3 py-2 font-medium">单位</th>
                  <th className="px-3 py-2 font-medium text-right">换算</th>
                  <th className="px-3 py-2 font-medium">SKU</th>
                  <th className="px-3 py-2 font-medium">供应商</th>
                  <th className="px-3 py-2 font-medium">有效期</th>
                  <th className="px-3 py-2 font-medium w-24">操作</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={9} className="text-center py-8 text-muted-foreground">
                    <Loader2 className="w-4 h-4 inline animate-spin mr-2" />加载中…
                  </td></tr>
                )}
                {!loading && items.length === 0 && (
                  <tr><td colSpan={9} className="text-center py-8 text-muted-foreground">
                    暂无成本项，点「新增成本项」开始录入
                  </td></tr>
                )}
                {items.map((it) => (
                  <tr key={it.id} className="border-b hover:bg-muted/20">
                    <td className="px-3 py-2">
                      <div className="font-medium">{it.item_name}</div>
                      {it.notes && <div className="text-xs text-muted-foreground line-clamp-1">{it.notes}</div>}
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant="outline" className={CATEGORY_BADGE_STYLES[it.category]}>
                        {categoryLabel(it.category)}
                      </Badge>
                      {!it.is_active && <Badge variant="outline" className="ml-1 bg-gray-100 text-gray-500">停用</Badge>}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {it.unit_cost.toFixed(2)} {it.currency}
                    </td>
                    <td className="px-3 py-2">{it.unit}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {it.quantity_per_unit !== 1 ? `1 ${it.unit} = ${it.quantity_per_unit}` : '—'}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{it.sku_id || <span className="text-muted-foreground">共享</span>}</td>
                    <td className="px-3 py-2">{it.vendor || '—'}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {it.valid_from}{it.valid_to ? ` ~ ${it.valid_to}` : ' ~ 至今'}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1">
                        <Button size="sm" variant="ghost" onClick={() => openEdit(it)}><Pencil className="w-3.5 h-3.5" /></Button>
                        <Button size="sm" variant="ghost" onClick={() => removeItem(it.id)}>
                          <Trash2 className="w-3.5 h-3.5 text-red-500" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* 录入/编辑 Modal */}
      {showFormModal && (
        <Modal title={formMode === 'create' ? '新增成本项' : '编辑成本项'} onClose={() => setShowFormModal(false)}>
          <div className="grid grid-cols-2 gap-3">
            <FormField label="品类 *">
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as Category })}
                className="border rounded px-3 py-1.5 text-sm w-full"
              >
                {CATEGORY_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label} — {o.desc}</option>
                ))}
              </select>
            </FormField>
            <FormField label="项目名称 *">
              <input
                value={form.item_name}
                onChange={(e) => setForm({ ...form, item_name: e.target.value })}
                placeholder="如：玻璃瓶 250ml / 顺丰华东 / 代工厂A 整箱报价"
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="单价 *">
              <input
                type="number" step="0.0001"
                value={form.unit_cost}
                onChange={(e) => setForm({ ...form, unit_cost: e.target.value })}
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="货币">
              <input
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase().slice(0, 3) })}
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="单位">
              <input
                value={form.unit}
                onChange={(e) => setForm({ ...form, unit: e.target.value })}
                placeholder="件 / 瓶 / 箱 / kg / 单"
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="单位换算（每单位含多少件）">
              <input
                type="number" step="0.0001"
                value={form.quantity_per_unit}
                onChange={(e) => setForm({ ...form, quantity_per_unit: e.target.value })}
                placeholder="一箱 24 瓶 → 填 24"
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="SKU ID（留空 = 共享成本）">
              <input
                value={form.sku_id}
                onChange={(e) => setForm({ ...form, sku_id: e.target.value })}
                placeholder="例如物流费可不填"
                className="border rounded px-3 py-1.5 text-sm w-full font-mono"
              />
            </FormField>
            <FormField label="供应商">
              <input
                value={form.vendor}
                onChange={(e) => setForm({ ...form, vendor: e.target.value })}
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="生效日期（默认今天）">
              <input
                type="date"
                value={form.valid_from}
                onChange={(e) => setForm({ ...form, valid_from: e.target.value })}
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="失效日期（留空 = 至今）">
              <input
                type="date"
                value={form.valid_to}
                onChange={(e) => setForm({ ...form, valid_to: e.target.value })}
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="备注" className="col-span-2">
              <textarea
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                rows={2}
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            {formMode === 'edit' && (
              <FormField label="状态" className="col-span-2">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.is_active}
                    onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                  />
                  启用（取消勾选则停用）
                </label>
              </FormField>
            )}
          </div>
          {formError && <div className="text-sm text-red-600 mt-3">{formError}</div>}
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowFormModal(false)}>取消</Button>
            <Button onClick={submitForm} disabled={submitting}>
              {submitting && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
              {formMode === 'create' ? '创建' : '保存'}
            </Button>
          </div>
        </Modal>
      )}

      {/* 净利率 Modal */}
      {showMarginModal && (
        <Modal title="净利率计算" onClose={() => setShowMarginModal(false)}>
          <div className="grid grid-cols-2 gap-3">
            <FormField label="SKU ID *">
              <input
                value={marginSku}
                onChange={(e) => setMarginSku(e.target.value)}
                className="border rounded px-3 py-1.5 text-sm w-full font-mono"
              />
            </FormField>
            <FormField label="售价（单件）*">
              <input
                type="number" step="0.01"
                value={marginPrice}
                onChange={(e) => setMarginPrice(e.target.value)}
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="售卖件数">
              <input
                type="number" step="1"
                value={marginQty}
                onChange={(e) => setMarginQty(e.target.value)}
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="平台佣金率（0.05 = 5%）">
              <input
                type="number" step="0.01" min="0" max="1"
                value={marginFeeRate}
                onChange={(e) => setMarginFeeRate(e.target.value)}
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <FormField label="" className="col-span-2">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={marginIncludeShared}
                  onChange={(e) => setMarginIncludeShared(e.target.checked)}
                />
                包含共享物流成本（sku_id 为空的物流项）
              </label>
            </FormField>
          </div>
          {marginError && <div className="text-sm text-red-600 mt-3">{marginError}</div>}
          {marginResult && (
            <div className="mt-4 border rounded p-3 bg-muted/20 text-sm space-y-2">
              <div className="flex justify-between">
                <span>营收</span>
                <span className="tabular-nums">{marginResult.revenue} CNY</span>
              </div>
              <div className="flex justify-between text-muted-foreground">
                <span>平台佣金（{(marginResult.platform_fee_rate * 100).toFixed(1)}%）</span>
                <span className="tabular-nums">- {marginResult.platform_fee}</span>
              </div>
              {Object.entries(marginResult.cost_by_category as Record<string, number>).map(([k, v]) => (
                <div key={k} className="flex justify-between text-muted-foreground">
                  <span>{categoryLabel(k as Category)}成本</span>
                  <span className="tabular-nums">- {v}</span>
                </div>
              ))}
              <div className="border-t pt-2 flex justify-between font-medium">
                <span>净利润</span>
                <span className="tabular-nums">{marginResult.net_profit} CNY</span>
              </div>
              <div className="flex justify-between font-bold text-lg">
                <span>净利率</span>
                <span className={marginResult.net_margin >= 0 ? 'text-green-600' : 'text-red-600'}>
                  {(marginResult.net_margin * 100).toFixed(2)}%
                </span>
              </div>
              {marginResult.cost_breakdown && marginResult.cost_breakdown.length > 0 && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-muted-foreground">明细（{marginResult.cost_breakdown.length} 项）</summary>
                  <table className="w-full text-xs mt-2">
                    <thead><tr className="text-left text-muted-foreground">
                      <th className="py-1">项目</th><th>品类</th><th className="text-right">行成本</th>
                    </tr></thead>
                    <tbody>
                      {marginResult.cost_breakdown.map((b: any) => (
                        <tr key={b.item_id}>
                          <td className="py-1">{b.item_name}{b.shared && <span className="text-muted-foreground"> (共享)</span>}</td>
                          <td>{categoryLabel(b.category)}</td>
                          <td className="text-right tabular-nums">{b.line_cost}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              )}
            </div>
          )}
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowMarginModal(false)}>关闭</Button>
            <Button onClick={computeMargin} disabled={marginLoading}>
              {marginLoading && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
              计算
            </Button>
          </div>
        </Modal>
      )}

      {/* 文件导入 Modal */}
      {showImportModal && (
        <Modal title="从文件导入成本项" size="xl" onClose={() => setShowImportModal(false)}>
          {/* Step 1: 选文件 */}
          {previewItems.length === 0 && (
            <div className="space-y-3">
              <div className="text-sm text-muted-foreground">
                支持 Excel / PDF / Word / CSV / 文本。AI 会自动识别其中的成本项，你预览编辑后再批量入库。
              </div>
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-violet-400 transition-colors">
                <input
                  ref={importInputRef}
                  type="file"
                  accept={SUPPORTED_FILE_EXTS}
                  onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                  className="hidden"
                />
                {!importFile ? (
                  <Button variant="outline" onClick={() => importInputRef.current?.click()}>
                    <FileText className="w-4 h-4 mr-1" />选择文件
                  </Button>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center justify-center gap-2">
                      <FileText className="w-4 h-4 text-violet-600" />
                      <span className="font-medium">{importFile.name}</span>
                      <span className="text-xs text-muted-foreground">
                        ({(importFile.size / 1024).toFixed(1)} KB)
                      </span>
                      <Button size="sm" variant="ghost" onClick={() => setImportFile(null)}>
                        <X className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </div>
                )}
                <div className="text-xs text-muted-foreground mt-3">
                  支持类型：{SUPPORTED_FILE_EXTS.replace(/\./g, '').replace(/,/g, ' / ')}
                </div>
              </div>
              <FormField label="默认 SKU（选填，AI 没识别到 SKU 时填这个）">
                <input
                  value={importDefaultSku}
                  onChange={(e) => setImportDefaultSku(e.target.value)}
                  placeholder="如 TEST-001；不填则保持空（共享成本）"
                  className="border rounded px-3 py-1.5 text-sm w-full font-mono"
                />
              </FormField>
              {importError && <div className="text-sm text-red-600">{importError}</div>}
              <div className="flex justify-end gap-2 pt-2 border-t">
                <Button variant="outline" onClick={() => setShowImportModal(false)}>取消</Button>
                <Button onClick={runExtract} disabled={!importFile || importLoading}>
                  {importLoading && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
                  AI 解析
                </Button>
              </div>
            </div>
          )}

          {/* Step 2: 预览编辑 */}
          {previewItems.length > 0 && !bulkSummary && (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-sm">
                <div>
                  共识别 <span className="font-bold text-violet-600">{previewItems.length}</span> 条
                  · 已勾选 <span className="font-bold">{selectedRows.size}</span> 条
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="ghost" onClick={toggleAll}>
                    {selectedRows.size === previewItems.length
                      ? <><Square className="w-3.5 h-3.5 mr-1" />全部取消</>
                      : <><CheckSquare className="w-3.5 h-3.5 mr-1" />全部勾选</>}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => {
                    setPreviewItems([]); setSelectedRows(new Set()); setImportError('')
                  }}>
                    <Upload className="w-3.5 h-3.5 mr-1" />重新选文件
                  </Button>
                </div>
              </div>

              <div className="overflow-x-auto border rounded">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-muted/40 border-b">
                      <th className="px-2 py-2 w-8"></th>
                      <th className="px-2 py-2 text-left font-medium">名称 *</th>
                      <th className="px-2 py-2 text-left font-medium">品类 *</th>
                      <th className="px-2 py-2 text-right font-medium">单价 *</th>
                      <th className="px-2 py-2 text-left font-medium">单位</th>
                      <th className="px-2 py-2 text-right font-medium">换算</th>
                      <th className="px-2 py-2 text-left font-medium">供应商</th>
                      <th className="px-2 py-2 text-left font-medium">SKU</th>
                      <th className="px-2 py-2 text-left font-medium">备注</th>
                      <th className="px-2 py-2 text-right font-medium">置信</th>
                    </tr>
                  </thead>
                  <tbody>
                    {previewItems.map((it, idx) => (
                      <tr key={idx} className={`border-b ${selectedRows.has(idx) ? '' : 'opacity-40'}`}>
                        <td className="px-2 py-1.5 text-center">
                          <input
                            type="checkbox"
                            checked={selectedRows.has(idx)}
                            onChange={() => toggleRow(idx)}
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <input
                            value={it.item_name}
                            onChange={(e) => updatePreviewItem(idx, { item_name: e.target.value })}
                            className="border rounded px-1.5 py-0.5 text-xs w-full"
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <select
                            value={it.category}
                            onChange={(e) => updatePreviewItem(idx, { category: e.target.value as any })}
                            className="border rounded px-1.5 py-0.5 text-xs"
                          >
                            {CATEGORY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                          </select>
                        </td>
                        <td className="px-2 py-1.5">
                          <input
                            type="number" step="0.0001"
                            value={it.unit_cost}
                            onChange={(e) => updatePreviewItem(idx, { unit_cost: Number(e.target.value) })}
                            className="border rounded px-1.5 py-0.5 text-xs w-20 text-right tabular-nums"
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <input
                            value={it.unit}
                            onChange={(e) => updatePreviewItem(idx, { unit: e.target.value })}
                            className="border rounded px-1.5 py-0.5 text-xs w-12"
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <input
                            type="number" step="0.0001"
                            value={it.quantity_per_unit}
                            onChange={(e) => updatePreviewItem(idx, { quantity_per_unit: Number(e.target.value) })}
                            className="border rounded px-1.5 py-0.5 text-xs w-14 text-right tabular-nums"
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <input
                            value={it.vendor || ''}
                            onChange={(e) => updatePreviewItem(idx, { vendor: e.target.value || null })}
                            className="border rounded px-1.5 py-0.5 text-xs w-24"
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <input
                            value={it.sku_id || ''}
                            onChange={(e) => updatePreviewItem(idx, { sku_id: e.target.value || null })}
                            className="border rounded px-1.5 py-0.5 text-xs w-20 font-mono"
                          />
                        </td>
                        <td className="px-2 py-1.5">
                          <input
                            value={it.notes || ''}
                            onChange={(e) => updatePreviewItem(idx, { notes: e.target.value || null })}
                            className="border rounded px-1.5 py-0.5 text-xs w-32"
                          />
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <span className={`tabular-nums ${it.confidence < 0.5 ? 'text-red-600 font-bold' : it.confidence < 0.8 ? 'text-amber-600' : 'text-green-600'}`}>
                            {(it.confidence * 100).toFixed(0)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="text-xs text-muted-foreground">
                提示：置信度 &lt; 50% 的行 AI 没把握，请重点核对单价/单位/换算。
              </div>

              {importError && <div className="text-sm text-red-600">{importError}</div>}
              <div className="flex justify-end gap-2 pt-2 border-t">
                <Button variant="outline" onClick={() => setShowImportModal(false)}>取消</Button>
                <Button onClick={submitBulk} disabled={bulkLoading || selectedRows.size === 0}>
                  {bulkLoading && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
                  确认导入 {selectedRows.size} 条
                </Button>
              </div>
            </div>
          )}

          {/* Step 3: 完成 */}
          {bulkSummary && (
            <div className="text-center py-6 space-y-3">
              <CheckSquare className="w-12 h-12 text-green-600 mx-auto" />
              <div className="text-lg font-medium">
                成功导入 {bulkSummary.created} 条
                {bulkSummary.errors > 0 && <span className="text-amber-600"> · {bulkSummary.errors} 条失败</span>}
              </div>
              <Button onClick={() => setShowImportModal(false)}>关闭</Button>
            </div>
          )}
        </Modal>
      )}

      {/* 自然语言问询 Modal */}
      {showQueryModal && (
        <Modal title="自然语言问询" onClose={() => setShowQueryModal(false)}>
          <div className="space-y-3">
            <FormField label="问题">
              <textarea
                value={nlQuery}
                onChange={(e) => setNlQuery(e.target.value)}
                rows={2}
                placeholder='如："SKU-001 卖 19.9 元的净利率是多少？" 或 "对比一下代工厂报价"'
                className="border rounded px-3 py-1.5 text-sm w-full"
              />
            </FormField>
            <div className="grid grid-cols-2 gap-3">
              <FormField label="上下文 SKU（可选）">
                <input
                  value={nlSku}
                  onChange={(e) => setNlSku(e.target.value)}
                  className="border rounded px-3 py-1.5 text-sm w-full font-mono"
                />
              </FormField>
              <FormField label="上下文售价（可选）">
                <input
                  type="number" step="0.01"
                  value={nlPrice}
                  onChange={(e) => setNlPrice(e.target.value)}
                  className="border rounded px-3 py-1.5 text-sm w-full"
                />
              </FormField>
            </div>
          </div>
          {nlError && <div className="text-sm text-red-600 mt-3">{nlError}</div>}
          {nlResult && (
            <div className="mt-4 border rounded p-3 bg-muted/20 text-xs space-y-2">
              <div>
                <span className="text-muted-foreground">意图：</span>
                <Badge variant="outline">{nlResult.intent}</Badge>
                {nlResult.parsed?.explanation && (
                  <span className="ml-2 text-muted-foreground">{nlResult.parsed.explanation}</span>
                )}
              </div>
              {!nlResult.ok && (
                <div className="text-red-600">{nlResult.reason}</div>
              )}
              {nlResult.ok && (
                <pre className="bg-white border rounded p-2 overflow-x-auto max-h-80">
                  {JSON.stringify(nlResult.result, null, 2)}
                </pre>
              )}
            </div>
          )}
          <div className="flex justify-end gap-2 mt-4">
            <Button variant="outline" onClick={() => setShowQueryModal(false)}>关闭</Button>
            <Button onClick={askNL} disabled={nlLoading}>
              {nlLoading && <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />}
              问
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function Modal({ title, children, onClose, size = 'md' }: { title: string; children: React.ReactNode; onClose: () => void; size?: 'md' | 'lg' | 'xl' }) {
  const widthClass = size === 'xl' ? 'max-w-6xl' : size === 'lg' ? 'max-w-4xl' : 'max-w-2xl'
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className={`bg-white rounded-lg shadow-xl w-full ${widthClass} max-h-[90vh] overflow-y-auto`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-5 py-3">
          <h2 className="font-semibold">{title}</h2>
          <Button size="sm" variant="ghost" onClick={onClose}><X className="w-4 h-4" /></Button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

function FormField({ label, children, className = '' }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      {label && <label className="text-xs text-muted-foreground block mb-1">{label}</label>}
      {children}
    </div>
  )
}
