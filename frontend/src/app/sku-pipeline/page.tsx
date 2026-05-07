'use client'

import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Loader2, Sparkles, ChevronDown, ChevronRight, Copy, Download } from 'lucide-react'

interface SkuRow {
  id: string
  name: string
  status: string
  platform_status: string | null
  growth_class: string | null
  in_focus_pool: boolean
  push_tier: string | null
  price_min: number | null
  price_max: number | null
}

interface MatrixResp {
  ok: boolean
  result?: {
    matrix_md: string
    sku_id: string
  }
  trace?: {
    model_provider: string
    model: string
    final_prompt: string
    params: Record<string, any>
    cost_estimate: string
  }
  error?: string
  hint?: string
}

export default function SkuPipelinePage() {
  const [skus, setSkus] = useState<SkuRow[]>([])
  const [skuId, setSkuId] = useState<string>('')
  const [userInitialPoints, setUserInitialPoints] = useState('')
  const [userReviews, setUserReviews] = useState('')
  const [kbContext, setKbContext] = useState('')
  const [extraContext, setExtraContext] = useState('')
  const [running, setRunning] = useState(false)
  const [resp, setResp] = useState<MatrixResp | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/omni/scout/skus?status=active')
      .then(r => r.json())
      .then(data => {
        const arr: SkuRow[] = Array.isArray(data) ? data : (data.data || data.skus || [])
        setSkus(arr)
        if (arr.length > 0 && !skuId) setSkuId(arr[0].id)
      })
      .catch(e => setError(`SKU 列表加载失败: ${String(e)}`))
  }, [])

  const selectedSku = skus.find(s => s.id === skuId)

  const runMatrix = async () => {
    setRunning(true)
    setResp(null)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/selling-points-matrix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sku_id: skuId,
          user_initial_points: userInitialPoints,
          user_reviews: userReviews,
          kb_context: kbContext || null,
          extra_context: extraContext || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning(false)
    }
  }

  const copyMd = () => {
    if (resp?.result?.matrix_md) {
      navigator.clipboard.writeText(resp.result.matrix_md)
    }
  }

  const downloadMd = () => {
    if (!resp?.result?.matrix_md) return
    const blob = new Blob([resp.result.matrix_md], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${skuId}_selling-points-matrix.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Sparkles className="w-6 h-6" /> SKU Pipeline · Step 2 卖点矩阵
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          调味品行业专家 prompt — 5 部分输出（产品档案 / 三层卖点地图 / 五心智维度 /
          结构化标签汇总 / 信息补全建议）。每个卖点 5 关键词 + 强度评分 + 匹配场景 + USP 排他性检验。
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 左侧：输入 */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">输入</CardTitle>
            <CardDescription>
              选 SKU + 4 项资料（任一缺失都行，越全越好；空的部分输出会标"信息不足"）
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* SKU 选择 */}
            <div>
              <label className="text-sm font-medium mb-1 block">SKU（共 {skus.length} 个 active）</label>
              <select
                className="w-full border rounded px-2 py-2 text-sm bg-background"
                value={skuId}
                onChange={e => setSkuId(e.target.value)}
              >
                {skus.map(s => (
                  <option key={s.id} value={s.id}>
                    {s.id} — {s.name.substring(0, 30)} {s.in_focus_pool ? '⭐' : ''}
                    {s.platform_status === 'on_sale' ? '' : ` [${s.platform_status}]`}
                  </option>
                ))}
              </select>
              {selectedSku && (
                <div className="text-xs text-muted-foreground mt-1 space-x-2">
                  <Badge variant="outline">{selectedSku.platform_status || 'unknown'}</Badge>
                  {selectedSku.growth_class && (
                    <Badge variant="outline">{selectedSku.growth_class}</Badge>
                  )}
                  {selectedSku.price_min !== null && (
                    <span>¥{selectedSku.price_min}{selectedSku.price_max && selectedSku.price_max !== selectedSku.price_min ? ` - ¥${selectedSku.price_max}` : ''}</span>
                  )}
                </div>
              )}
            </div>

            {/* user_initial_points */}
            <div>
              <label className="text-sm font-medium mb-1 block">
                ④ 自己观察到的显性卖点（user_initial_points）
              </label>
              <Textarea
                placeholder="例：日式风味、有机、零添加、180 天发酵、玻璃瓶包装、33 年源头工厂..."
                value={userInitialPoints}
                onChange={e => setUserInitialPoints(e.target.value)}
                rows={3}
                className="text-sm"
              />
            </div>

            {/* user_reviews */}
            <div>
              <label className="text-sm font-medium mb-1 block">
                ③ 用户评价（user_reviews）
              </label>
              <Textarea
                placeholder="好评关键词 / 差评关键词 / 客服反馈 / 私域反馈，例：「鲜味浓不咸」「玻璃瓶有质感」「滴几滴提鲜」「价格偏贵」「物流泡沫薄」..."
                value={userReviews}
                onChange={e => setUserReviews(e.target.value)}
                rows={4}
                className="text-sm"
              />
            </div>

            {/* kb_context */}
            <div>
              <label className="text-sm font-medium mb-1 block">
                可选补充（kb_context — 竞品 / 品牌故事 / 工艺细节 / 历史血统）
              </label>
              <Textarea
                placeholder="（可空）建议先 search_kb 拿同品类爆款拆解 / 品牌资产再贴这里"
                value={kbContext}
                onChange={e => setKbContext(e.target.value)}
                rows={3}
                className="text-sm"
              />
            </div>

            {/* extra_context */}
            <div>
              <label className="text-sm font-medium mb-1 block">
                额外要求（extra_context）
              </label>
              <Textarea
                placeholder="（可空）例：「这次主推送礼场景」「重点挖儿童辅食角度」"
                value={extraContext}
                onChange={e => setExtraContext(e.target.value)}
                rows={2}
                className="text-sm"
              />
            </div>

            <Button
              onClick={runMatrix}
              disabled={running || !skuId}
              className="w-full"
            >
              {running ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（约 30-60s）</> : '跑卖点矩阵'}
            </Button>

            {error && (
              <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                {error}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 右侧：结果 */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-base">输出</CardTitle>
              {resp?.trace && (
                <CardDescription className="text-xs">
                  {resp.trace.model_provider}/{resp.trace.model} · {resp.trace.cost_estimate}
                </CardDescription>
              )}
            </div>
            {resp?.result?.matrix_md && (
              <div className="space-x-1">
                <Button size="sm" variant="outline" onClick={copyMd}>
                  <Copy className="w-3 h-3 mr-1" /> 复制
                </Button>
                <Button size="sm" variant="outline" onClick={downloadMd}>
                  <Download className="w-3 h-3 mr-1" /> 下载 .md
                </Button>
              </div>
            )}
          </CardHeader>
          <CardContent>
            {!resp && !running && (
              <div className="text-sm text-muted-foreground py-12 text-center">
                左边填资料后点"跑卖点矩阵"，结果会显示在这里。
              </div>
            )}
            {running && (
              <div className="text-sm text-muted-foreground py-12 text-center">
                <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                LLM 正在生成 5 部分报告（产品档案 / 三层卖点 / 5 心智 / 标签 / 补全建议）...
              </div>
            )}
            {resp?.result?.matrix_md && (
              <>
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {resp.result.matrix_md}
                  </ReactMarkdown>
                </div>

                {/* 折叠 final_prompt 区 — 让老板看 LLM 真收到啥 */}
                {resp.trace?.final_prompt && (
                  <div className="mt-6 border-t pt-4">
                    <button
                      className="text-sm font-medium flex items-center gap-1"
                      onClick={() => setShowPrompt(s => !s)}
                    >
                      {showPrompt ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                      Final Prompt（system + user 完整发给 LLM 的内容）
                    </button>
                    {showPrompt && (
                      <pre className="mt-2 p-3 bg-muted text-xs rounded max-h-96 overflow-auto whitespace-pre-wrap">
                        {resp.trace.final_prompt}
                      </pre>
                    )}
                  </div>
                )}
              </>
            )}
            {resp && !resp.ok && (
              <div className="text-sm text-red-500">
                <div>Error: {resp.error}</div>
                {resp.hint && <div className="text-xs text-muted-foreground mt-1">{resp.hint}</div>}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
