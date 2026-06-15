'use client'

/**
 * 投后回传录入（roadmap E1）—— 测试投放后把真实数据写回素材血缘。
 *
 * 选素材（或填外部 video/creative id）→ 填 GMV/消耗/完播率等原始指标 → 落 ad_metrics。
 * ROI/ROAS 是计算字段（R-4）：这里只收原始 gmv/spend 并本地预览 ROI，不回传手填 ROI；
 * 后端 ad_metrics_validation 会把手填 roi 标 suspect 且不进汇总，提交后展示该校验报告。
 *
 * 数据通路：POST /api/omni/asset-metrics → KE /api/v1/mcp/exec/record_ad_metrics
 */

import { useState } from 'react'
import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import OutputFeedback from '@/components/OutputFeedback'
import { Loader2, Search, Trophy } from 'lucide-react'

interface AssetRow {
  id?: string
  asset_id?: string
  sku_id: string
  asset_type: string
  scene_no?: number | null
  file_url?: string | null
  prompt?: string | null
  status?: string
  external_video_id?: string | null
  created_at?: string | null
}

const MONEY: { k: string; label: string }[] = [
  { k: 'gmv', label: 'GMV 成交金额' },
  { k: 'spend', label: '消耗 / 花费' },
  { k: 'cost', label: '成本' },
]
const COUNTS: { k: string; label: string }[] = [
  { k: 'plays', label: '播放量' },
  { k: 'impressions', label: '曝光' },
  { k: 'clicks', label: '点击' },
  { k: 'orders', label: '订单数' },
  { k: 'conversions', label: '转化数' },
]
const RATES: { k: string; label: string }[] = [
  { k: 'ctr', label: '点击率 CTR(%)' },
  { k: 'cvr', label: '转化率 CVR(%)' },
  { k: 'completion_rate', label: '完播率(%)' },
]

const assetKey = (a: AssetRow) => a.id || a.asset_id || ''

export default function AdMetricsPage() {
  const [mode, setMode] = useState<'asset' | 'external'>('asset')

  // 素材选择器
  const [skuFilter, setSkuFilter] = useState('')
  const [assets, setAssets] = useState<AssetRow[]>([])
  const [loadingAssets, setLoadingAssets] = useState(false)
  const [assetsErr, setAssetsErr] = useState<string | null>(null)
  const [selected, setSelected] = useState<AssetRow | null>(null)

  // 外部 id 模式
  const [externalVideoId, setExternalVideoId] = useState('')
  const [externalCreativeId, setExternalCreativeId] = useState('')

  // 指标输入
  const [metrics, setMetrics] = useState<Record<string, string>>({})
  const [platform, setPlatform] = useState('douyin')
  const [campaign, setCampaign] = useState('')
  const [note, setNote] = useState('')
  const [advanced, setAdvanced] = useState('')
  const [markPublished, setMarkPublished] = useState(true)

  // 提交
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [submitErr, setSubmitErr] = useState<string | null>(null)

  const setMetric = (k: string, v: string) => setMetrics((s) => ({ ...s, [k]: v }))

  const loadAssets = async () => {
    setLoadingAssets(true)
    setAssetsErr(null)
    try {
      const qs = new URLSearchParams({ limit: '50' })
      if (skuFilter.trim()) qs.set('sku_id', skuFilter.trim())
      qs.set('asset_type', 'video') // 投放的基本都是视频；放开见下
      const res = await fetch(`/api/omni/assets?${qs.toString()}`, { cache: 'no-store' })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setAssets((json.data.assets as AssetRow[]) || [])
      } else {
        setAssetsErr(json.data?.error || json.error || '加载失败')
      }
    } catch (e) {
      setAssetsErr(String(e))
    } finally {
      setLoadingAssets(false)
    }
  }

  const gmvNum = parseFloat(metrics.gmv || '')
  const spendNum = parseFloat(metrics.spend || '')
  const derivedRoi =
    Number.isFinite(gmvNum) && Number.isFinite(spendNum) && spendNum > 0
      ? (gmvNum / spendNum).toFixed(2)
      : null

  const anchorOk =
    mode === 'asset'
      ? !!selected
      : !!(externalVideoId.trim() || externalCreativeId.trim())

  const buildMetrics = (): Record<string, number | string> => {
    const out: Record<string, number | string> = {}
    for (const k of [...MONEY, ...COUNTS, ...RATES].map((m) => m.k)) {
      const raw = (metrics[k] || '').trim()
      if (raw === '') continue
      const n = Number(raw)
      if (Number.isFinite(n)) out[k] = n
    }
    if (platform.trim()) out.platform = platform.trim()
    if (campaign.trim()) out.campaign = campaign.trim()
    if (note.trim()) out.note = note.trim()
    // 高级：一行一个 key=value 或 key:value（数字自动转 number）
    for (const line of advanced.split('\n')) {
      const m = line.match(/^\s*([a-zA-Z_][\w]*)\s*[=:]\s*(.+?)\s*$/)
      if (!m) continue
      const n = Number(m[2])
      out[m[1]] = Number.isFinite(n) && m[2].trim() !== '' ? n : m[2]
    }
    return out
  }

  const submit = async () => {
    setSubmitErr(null)
    setResult(null)
    const body: Record<string, unknown> = {
      metrics: buildMetrics(),
      mark_published: markPublished,
    }
    if (Object.keys(body.metrics as object).length === 0) {
      setSubmitErr('至少填一个指标（GMV / 消耗 / 完播率…）')
      return
    }
    if (mode === 'asset') {
      if (!selected) {
        setSubmitErr('先选一条素材')
        return
      }
      body.asset_id = assetKey(selected)
    } else {
      if (externalVideoId.trim()) body.external_video_id = externalVideoId.trim()
      if (externalCreativeId.trim()) body.external_creative_id = externalCreativeId.trim()
      if (!body.external_video_id && !body.external_creative_id) {
        setSubmitErr('填 external_video_id 或 external_creative_id 至少一个')
        return
      }
    }
    setSubmitting(true)
    try {
      const res = await fetch('/api/omni/asset-metrics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const json = await res.json()
      if (json.success) {
        setResult(json.data as Record<string, unknown>)
      } else {
        setSubmitErr(json.error || '提交失败')
      }
    } catch (e) {
      setSubmitErr(String(e))
    } finally {
      setSubmitting(false)
    }
  }

  // 解析返回的资产 + 校验报告
  const resAsset = (result?.ok ? (result.asset as Record<string, unknown>) : null) || null
  const resAdMetrics = (resAsset?.ad_metrics as Record<string, unknown>) || null
  const resValidation = (resAdMetrics?._validation as Record<string, unknown>) || null
  const suspect = (resValidation?.suspect as Record<string, { value: unknown; reason: string }>) || {}
  const unknownKeys = (resValidation?.unknown_keys as string[]) || []

  return (
    <div className="px-6 py-6 max-w-5xl mx-auto space-y-5">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">投后回传</h1>
          <p className="text-sm text-muted-foreground mt-1">
            测试投放后把真实数据写回这条素材的血缘，之后才能看「
            <Link href="/content-leaderboard" className="text-violet-600 hover:underline inline-flex items-center gap-0.5">
              <Trophy className="w-3.5 h-3.5" />带货榜
            </Link>
            」。ROI 由 GMV÷消耗 自动算、不手填（手填会被标可疑、不进汇总）。
          </p>
        </div>
      </div>

      {/* 1) 定位素材 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">① 这条数据是哪个素材的？</CardTitle>
          <CardDescription className="text-xs">
            优先用素材库里选（最准，自动挂血缘）；上传到抖店/千川后只记得平台 id 就走右边。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex gap-2">
            <Button size="sm" variant={mode === 'asset' ? 'default' : 'outline'} className="text-xs h-7" onClick={() => setMode('asset')}>
              从素材库选
            </Button>
            <Button size="sm" variant={mode === 'external' ? 'default' : 'outline'} className="text-xs h-7" onClick={() => setMode('external')}>
              填平台 id
            </Button>
          </div>

          {mode === 'asset' && (
            <div className="space-y-2">
              <div className="flex gap-2 items-center">
                <Input
                  placeholder="按 SKU 过滤（可空，如 SKU-367991-0002）"
                  value={skuFilter}
                  onChange={(e) => setSkuFilter(e.target.value)}
                  className="h-8 text-xs max-w-xs"
                  onKeyDown={(e) => { if (e.key === 'Enter') loadAssets() }}
                />
                <Button size="sm" variant="outline" className="text-xs h-8" onClick={loadAssets} disabled={loadingAssets}>
                  {loadingAssets ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
                  <span className="ml-1">加载视频素材</span>
                </Button>
              </div>
              {assetsErr && <div className="text-xs text-red-600">加载失败：{assetsErr}</div>}
              {assets.length > 0 && (
                <div className="max-h-64 overflow-y-auto border rounded divide-y">
                  {assets.map((a) => {
                    const k = assetKey(a)
                    const sel = selected && assetKey(selected) === k
                    return (
                      <button
                        key={k}
                        type="button"
                        onClick={() => setSelected(a)}
                        className={`w-full text-left px-3 py-2 text-xs flex items-center gap-3 transition-colors ${sel ? 'bg-violet-50' : 'hover:bg-muted/50'}`}
                      >
                        <span className={`w-2 h-2 rounded-full shrink-0 ${sel ? 'bg-violet-600' : 'bg-gray-300'}`} />
                        <span className="font-mono text-[10px] text-muted-foreground shrink-0">{k.slice(0, 8)}</span>
                        <Badge variant="outline" className="text-[10px] shrink-0">{a.asset_type}{a.scene_no != null ? ` #${a.scene_no}` : ''}</Badge>
                        <span className="text-muted-foreground shrink-0">{a.sku_id}</span>
                        <span className="truncate flex-1 text-muted-foreground">{a.prompt || a.file_url || ''}</span>
                        {a.status && <Badge variant="outline" className="text-[10px] shrink-0">{a.status}</Badge>}
                      </button>
                    )
                  })}
                </div>
              )}
              {!loadingAssets && assets.length === 0 && !assetsErr && (
                <div className="text-xs text-muted-foreground">点「加载视频素材」拉最近 50 条；按 SKU 过滤更快找到。</div>
              )}
              {selected && (
                <div className="text-xs text-violet-700 bg-violet-50 rounded px-2 py-1">
                  已选：<span className="font-mono">{assetKey(selected).slice(0, 8)}</span> · {selected.sku_id} · {selected.asset_type}
                </div>
              )}
            </div>
          )}

          {mode === 'external' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-muted-foreground">抖店/千川 video_id</label>
                <Input value={externalVideoId} onChange={(e) => setExternalVideoId(e.target.value)} className="h-8 text-xs mt-1" placeholder="上传后的视频 id" />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">千川 creative_id</label>
                <Input value={externalCreativeId} onChange={(e) => setExternalCreativeId(e.target.value)} className="h-8 text-xs mt-1" placeholder="计划/创意 id" />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 2) 填指标 */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">② 投放后真实数据</CardTitle>
          <CardDescription className="text-xs">能填多少填多少，可以隔几天再来补（按 key 累积合并）。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <div>
            <div className="text-xs font-medium mb-1.5 text-muted-foreground">金额（元）</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {MONEY.map((m) => (
                <div key={m.k}>
                  <label className="text-[11px] text-muted-foreground">{m.label}</label>
                  <Input type="number" inputMode="decimal" value={metrics[m.k] || ''} onChange={(e) => setMetric(m.k, e.target.value)} className="h-8 text-xs mt-0.5" />
                </div>
              ))}
            </div>
            {derivedRoi && (
              <div className="text-xs mt-2 text-emerald-700 bg-emerald-50 rounded px-2 py-1 inline-block">
                自动算 ROI = GMV ÷ 消耗 = <b>{derivedRoi}</b>（仅预览，不回传——系统按原始 GMV/消耗 自己算）
              </div>
            )}
          </div>
          <div>
            <div className="text-xs font-medium mb-1.5 text-muted-foreground">计数</div>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              {COUNTS.map((m) => (
                <div key={m.k}>
                  <label className="text-[11px] text-muted-foreground">{m.label}</label>
                  <Input type="number" inputMode="numeric" value={metrics[m.k] || ''} onChange={(e) => setMetric(m.k, e.target.value)} className="h-8 text-xs mt-0.5" />
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="text-xs font-medium mb-1.5 text-muted-foreground">比率（填百分数，如完播率 42.5）</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {RATES.map((m) => (
                <div key={m.k}>
                  <label className="text-[11px] text-muted-foreground">{m.label}</label>
                  <Input type="number" inputMode="decimal" value={metrics[m.k] || ''} onChange={(e) => setMetric(m.k, e.target.value)} className="h-8 text-xs mt-0.5" />
                </div>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="text-[11px] text-muted-foreground">平台</label>
              <Input value={platform} onChange={(e) => setPlatform(e.target.value)} className="h-8 text-xs mt-0.5" />
            </div>
            <div>
              <label className="text-[11px] text-muted-foreground">计划/活动名（可选）</label>
              <Input value={campaign} onChange={(e) => setCampaign(e.target.value)} className="h-8 text-xs mt-0.5" />
            </div>
            <div>
              <label className="text-[11px] text-muted-foreground">备注（可选）</label>
              <Input value={note} onChange={(e) => setNote(e.target.value)} className="h-8 text-xs mt-0.5" />
            </div>
          </div>
          <details className="text-xs">
            <summary className="cursor-pointer text-muted-foreground">其他指标（高级，一行一个 key=value）</summary>
            <textarea
              value={advanced}
              onChange={(e) => setAdvanced(e.target.value)}
              rows={3}
              placeholder={'play_3s=12000\ngpm=350\na3_cost=2.1'}
              className="w-full mt-2 border rounded px-2 py-1.5 text-xs font-mono bg-background"
            />
          </details>
          <label className="flex items-center gap-2 text-xs cursor-pointer select-none">
            <input type="checkbox" checked={markPublished} onChange={(e) => setMarkPublished(e.target.checked)} />
            把这条素材状态推到「已发布」(published)
          </label>

          <div className="flex items-center gap-3 pt-1">
            <Button onClick={submit} disabled={submitting || !anchorOk} className="text-sm">
              {submitting ? <><Loader2 className="w-4 h-4 mr-1 animate-spin" />回传中</> : '回传投后数据'}
            </Button>
            {!anchorOk && <span className="text-xs text-muted-foreground">先在 ① 选素材或填平台 id</span>}
          </div>
          {submitErr && <div className="text-xs text-red-600 border border-red-200 rounded bg-red-50 px-2 py-1.5">{submitErr}</div>}
        </CardContent>
      </Card>

      {/* 3) 结果 */}
      {result && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">回传结果</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {!result.ok && (
              <div className="text-xs text-red-600 border border-red-200 rounded bg-red-50 px-2 py-1.5">
                没定位到素材：{String(result.error)} {result.hint ? `· ${String(result.hint)}` : ''}
              </div>
            )}
            {resAsset && (
              <>
                <div className="flex items-center gap-2 flex-wrap text-xs">
                  <span className="text-emerald-700">✓ 已写回</span>
                  <span className="font-mono">{String(resAsset.asset_id).slice(0, 8)}</span>
                  <span>· {String(resAsset.sku_id)}</span>
                  <Badge variant="outline" className="text-[10px]">{String(resAsset.status)}</Badge>
                </div>
                {Object.keys(suspect).length > 0 && (
                  <div className="text-xs border border-amber-300 bg-amber-50 rounded px-2 py-1.5">
                    <div className="font-medium text-amber-800 mb-1">⚠️ 可疑值（不会进汇总）：</div>
                    {Object.entries(suspect).map(([k, v]) => (
                      <div key={k}>· <b>{k}</b>={String(v.value)} — {v.reason}</div>
                    ))}
                  </div>
                )}
                {unknownKeys.length > 0 && (
                  <div className="text-xs text-muted-foreground">未识别 key（仍存）：{unknownKeys.join(', ')}</div>
                )}
                <details className="text-xs">
                  <summary className="cursor-pointer text-muted-foreground">看完整 ad_metrics JSON</summary>
                  <pre className="mt-1 bg-muted/50 rounded p-2 overflow-x-auto text-[11px]">{JSON.stringify(resAdMetrics, null, 2)}</pre>
                </details>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <OutputFeedback toolName="record_ad_metrics" label="录入体验怎么样？" />
    </div>
  )
}
