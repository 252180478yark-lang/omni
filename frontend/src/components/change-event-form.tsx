'use client'

import { useState, useRef, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Plus, Upload, Loader2, CheckCircle2, X,
} from 'lucide-react'

const ASSET_TYPES = [
  { value: 'product',        label: '商品主图/详情' },
  { value: 'price',          label: '价格/促销' },
  { value: 'ad',             label: '广告投放' },
  { value: 'content',        label: '内容/短视频' },
  { value: 'audience',       label: '人群/定向' },
  { value: 'talent',         label: '达人合作' },
  { value: 'service',        label: '客服/评价' },
  { value: 'campaign',       label: '活动报名' },
  { value: 'shop_ops',       label: '店铺运营' },
  { value: 'user_reach',     label: '触达/私域' },
  { value: 'brand_strategy', label: '品牌策略' },
  { value: 'asset',          label: '其他素材' },
]

const INTENT_OPTIONS = [
  { value: 'click',      label: '提升点击率' },
  { value: 'cvr',        label: '提升转化率' },
  { value: 'impression', label: '扩大曝光' },
  { value: 'aov',        label: '提升客单价' },
  { value: 'refund',     label: '降低退款' },
  { value: 'experience', label: '改善体验分' },
  { value: '5a_flow',    label: '5A人群流转' },
  { value: 'other',      label: '其他' },
]

interface Props {
  skuId?: string
  skuName?: string
  onSuccess?: () => void
  onCancel?: () => void
}

export function ChangeEventForm({ skuId, skuName, onSuccess, onCancel }: Props) {
  const [trackBCount, setTrackBCount] = useState<number>(0)

  // Check if Track B (platform) events exist for this SKU today
  useEffect(() => {
    if (!skuId) return
    const today = new Date().toISOString().slice(0, 10)
    fetch(`/api/omni/scout/change-events?sku_id=${skuId}&source=shop_admin_log&limit=50`)
      .then((r) => r.ok ? r.json() : [])
      .then((events: { executed_at: string }[]) => {
        const todayCount = events.filter((e) => e.executed_at.startsWith(today)).length
        setTrackBCount(todayCount)
      })
      .catch(() => {})
  }, [skuId])
  const [assetType, setAssetType] = useState('')
  const [description, setDescription] = useState('')
  const [intent, setIntent] = useState('')
  const [screenshotPath, setScreenshotPath] = useState('')
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/omni/uploads', { method: 'POST', body: fd })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'Upload failed')
      setScreenshotPath(data.path)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!assetType || !description.trim()) {
      setError('请填写动作类型和描述')
      return
    }
    setSaving(true)
    setError('')
    try {
      const body = {
        sku_id: skuId || null,
        asset_type: assetType,
        change_description: description.trim(),
        optimization_intent: intent || null,
        screenshot_path: screenshotPath || null,
        expected_kpis: [],
      }
      const res = await fetch('/api/omni/scout/change-events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(d.detail || 'Save failed')
      }
      setDone(true)
      setTimeout(() => onSuccess?.(), 800)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  if (done) {
    return (
      <div className="flex flex-col items-center gap-2 py-8">
        <CheckCircle2 className="w-10 h-10 text-emerald-500" />
        <p className="text-sm font-medium text-emerald-700">已登记！7 天后自动验证效果</p>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Context */}
      {skuName && (
        <div className="flex items-center gap-1.5 text-xs text-gray-500">
          <Badge variant="outline" className="text-[10px]">{skuName}</Badge>
          <span>的动作登记</span>
        </div>
      )}

      {/* Track B hint (V07-9) */}
      {trackBCount > 0 && (
        <div className="rounded-lg bg-blue-50 border border-blue-200 px-3 py-2 text-xs text-blue-700">
          系统已自动抓到 <strong>{trackBCount}</strong> 条抖店后台动作（今日）。手动登记可与之合并。
        </div>
      )}

      {/* Asset type */}
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1.5">动作类型 *</label>
        <div className="grid grid-cols-3 gap-1.5">
          {ASSET_TYPES.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => setAssetType(t.value)}
              className={`text-xs py-1.5 px-2 rounded-lg border text-left transition-all ${
                assetType === t.value
                  ? 'border-violet-400 bg-violet-50 text-violet-700 font-medium'
                  : 'border-gray-200 hover:border-gray-300 text-gray-600'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Description */}
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1.5">描述这次改动 *</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="例：将主图换成场景图，突出零添加卖点"
          rows={2}
          maxLength={100}
          className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 resize-none focus:outline-none focus:ring-1 focus:ring-violet-400"
        />
        <div className="text-right text-[10px] text-gray-400 mt-0.5">{description.length}/100</div>
      </div>

      {/* Intent */}
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1.5">优化目标（可选）</label>
        <div className="flex flex-wrap gap-1.5">
          {INTENT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setIntent(intent === opt.value ? '' : opt.value)}
              className={`text-xs py-1 px-2.5 rounded-full border transition-all ${
                intent === opt.value
                  ? 'border-violet-400 bg-violet-50 text-violet-700'
                  : 'border-gray-200 text-gray-500 hover:border-gray-300'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Screenshot */}
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1.5">截图凭证（可选）</label>
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleUpload} />
        {screenshotPath ? (
          <div className="flex items-center gap-2">
            <img src={screenshotPath} alt="screenshot" className="h-12 rounded border object-cover" />
            <button
              type="button"
              onClick={() => setScreenshotPath('')}
              className="text-gray-400 hover:text-rose-500"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 text-xs text-gray-500 border border-dashed border-gray-300 rounded-lg px-3 py-2 hover:border-violet-300 hover:text-violet-600 transition-all"
          >
            {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            上传截图
          </button>
        )}
      </div>

      {error && <p className="text-xs text-rose-600">{error}</p>}

      {/* Actions */}
      <div className="flex items-center justify-end gap-2 pt-1">
        {onCancel && (
          <Button type="button" variant="ghost" size="sm" onClick={onCancel} className="h-8 text-xs">
            取消
          </Button>
        )}
        <Button
          type="submit"
          size="sm"
          disabled={saving || !assetType || !description.trim()}
          className="h-8 text-xs bg-violet-600 hover:bg-violet-700"
        >
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Plus className="w-3.5 h-3.5 mr-1" />}
          登记动作
        </Button>
      </div>
    </form>
  )
}
