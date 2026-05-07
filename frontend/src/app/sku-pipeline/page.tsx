'use client'

import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Loader2, Sparkles, ChevronDown, ChevronRight, Copy, Download, Users } from 'lucide-react'

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

interface TraceShape {
  model_provider: string
  model: string
  final_prompt: string
  params: Record<string, any>
  cost_estimate: string
}

interface MatrixResp {
  ok: boolean
  result?: {
    matrix_md: string
    sku_id: string
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

interface AudienceResp {
  ok: boolean
  result?: {
    audience_md: string
    sku_id: string
    recall_meta?: {
      mode: string
      queries: string[]
      chunk_count: number
    }
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

export default function SkuPipelinePage() {
  const [skus, setSkus] = useState<SkuRow[]>([])
  const [skuId, setSkuId] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  // Step 2 state
  const [userInitialPoints, setUserInitialPoints] = useState('')
  const [userReviews, setUserReviews] = useState('')
  const [kbContext, setKbContext] = useState('')
  const [extraContext2, setExtraContext2] = useState('')
  const [running2, setRunning2] = useState(false)
  const [resp2, setResp2] = useState<MatrixResp | null>(null)
  const [showPrompt2, setShowPrompt2] = useState(false)

  // Step 3 state
  const [matrixMd3, setMatrixMd3] = useState('')
  const [extraContext3, setExtraContext3] = useState('')
  const [kbRecallOverride, setKbRecallOverride] = useState('')
  const [showOverride, setShowOverride] = useState(false)
  const [running3, setRunning3] = useState(false)
  const [resp3, setResp3] = useState<AudienceResp | null>(null)
  const [showPrompt3, setShowPrompt3] = useState(false)
  const [showQueries, setShowQueries] = useState(false)

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

  // step 2 跑完 → 自动同步 matrix_md 到 step 3 输入（老板可手改）
  useEffect(() => {
    if (resp2?.result?.matrix_md) {
      setMatrixMd3(resp2.result.matrix_md)
    }
  }, [resp2?.result?.matrix_md])

  const selectedSku = skus.find(s => s.id === skuId)

  const runStep2 = async () => {
    setRunning2(true)
    setResp2(null)
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
          extra_context: extraContext2 || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp2(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning2(false)
    }
  }

  const runStep3 = async () => {
    setRunning3(true)
    setResp3(null)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/audience-match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sku_id: skuId,
          matrix_md: matrixMd3,
          extra_context: extraContext3 || null,
          kb_recall_override: kbRecallOverride || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp3(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning3(false)
    }
  }

  const copyText = (text: string | undefined) => {
    if (text) navigator.clipboard.writeText(text)
  }
  const downloadMd = (text: string | undefined, filename: string) => {
    if (!text) return
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  // SKU 选择器（两个 step 共享）
  const SkuPicker = (
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
  )

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Sparkles className="w-6 h-6" /> SKU Pipeline 测试
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          单步测试通道。每步可独立跑（不强制走完整链路）；step 2 跑完后 matrix_md 会自动喂到 step 3。
        </p>
      </div>

      <Tabs defaultValue="step2" className="w-full">
        <TabsList variant="line">
          <TabsTrigger value="step2">
            <Sparkles className="w-3 h-3 mr-1" /> Step 2 · 卖点矩阵
          </TabsTrigger>
          <TabsTrigger value="step3">
            <Users className="w-3 h-3 mr-1" /> Step 3 · 人群匹配
          </TabsTrigger>
        </TabsList>

        {/* ============== STEP 2: 卖点矩阵 ============== */}
        <TabsContent value="step2" className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">输入</CardTitle>
                <CardDescription>
                  调味品行业专家 prompt — 5 部分输出（产品档案 / 三层卖点地图 / 五心智维度 /
                  结构化标签汇总 / 信息补全建议）
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

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

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    额外要求（extra_context）
                  </label>
                  <Textarea
                    placeholder="（可空）例：「这次主推送礼场景」「重点挖儿童辅食角度」"
                    value={extraContext2}
                    onChange={e => setExtraContext2(e.target.value)}
                    rows={2}
                    className="text-sm"
                  />
                </div>

                <Button
                  onClick={runStep2}
                  disabled={running2 || !skuId}
                  className="w-full"
                >
                  {running2 ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（约 60-120s，pro 模型推理慢）</> : '跑卖点矩阵'}
                </Button>

                {error && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">输出</CardTitle>
                  {resp2?.trace && (
                    <CardDescription className="text-xs">
                      {resp2.trace.model_provider}/{resp2.trace.model} · {resp2.trace.cost_estimate}
                    </CardDescription>
                  )}
                </div>
                {resp2?.result?.matrix_md && (
                  <div className="space-x-1">
                    <Button size="sm" variant="outline" onClick={() => copyText(resp2.result?.matrix_md)}>
                      <Copy className="w-3 h-3 mr-1" /> 复制
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => downloadMd(resp2.result?.matrix_md, `${skuId}_selling-points-matrix.md`)}>
                      <Download className="w-3 h-3 mr-1" /> 下载 .md
                    </Button>
                  </div>
                )}
              </CardHeader>
              <CardContent>
                {!resp2 && !running2 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左边填资料后点"跑卖点矩阵"，结果会显示在这里。
                  </div>
                )}
                {running2 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                    LLM 正在生成 5 部分报告...
                  </div>
                )}
                {resp2?.result?.matrix_md && (
                  <>
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {resp2.result.matrix_md}
                      </ReactMarkdown>
                    </div>

                    {resp2.trace?.final_prompt && (
                      <div className="mt-6 border-t pt-4">
                        <button
                          className="text-sm font-medium flex items-center gap-1"
                          onClick={() => setShowPrompt2(s => !s)}
                        >
                          {showPrompt2 ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          Final Prompt
                        </button>
                        {showPrompt2 && (
                          <pre className="mt-2 p-3 bg-muted text-xs rounded max-h-96 overflow-auto whitespace-pre-wrap">
                            {resp2.trace.final_prompt}
                          </pre>
                        )}
                      </div>
                    )}
                  </>
                )}
                {resp2 && !resp2.ok && (
                  <div className="text-sm text-red-500">
                    <div>Error: {resp2.error}</div>
                    {resp2.hint && <div className="text-xs text-muted-foreground mt-1">{resp2.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ============== STEP 3: 人群匹配 ============== */}
        <TabsContent value="step3" className="mt-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">输入</CardTitle>
                <CardDescription>
                  反向匹配 = 拿卖点+场景+心智去 KB 全部 chunks 里实打实挑对口人群。
                  2 部分输出（KB 匹配人群 ≥15 / 跨 ≥10 doc / 标签 ≥30）。KB 共 46 doc，全 KB 多 query 扩散召回。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    matrix_md（step 2 输出 — 必填）
                    {resp2?.result?.matrix_md && (
                      <Badge variant="outline" className="ml-2 text-xs">已自动同步 step 2 结果</Badge>
                    )}
                  </label>
                  <Textarea
                    placeholder="粘贴 step 2 的卖点矩阵 markdown（含三层卖点 + 5 心智 + 标签），或先去 step 2 跑一次自动同步"
                    value={matrixMd3}
                    onChange={e => setMatrixMd3(e.target.value)}
                    rows={10}
                    className="text-sm font-mono"
                  />
                  <div className="text-xs text-muted-foreground mt-1">
                    {matrixMd3.length} 字
                  </div>
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    额外要求（extra_context）
                  </label>
                  <Textarea
                    placeholder="（可空）例：「重点挖跨圈层」「假设里多列银发人群」「对标 X 品牌的人群路径」"
                    value={extraContext3}
                    onChange={e => setExtraContext3(e.target.value)}
                    rows={2}
                    className="text-sm"
                  />
                </div>

                <div>
                  <button
                    className="text-xs text-muted-foreground flex items-center gap-1"
                    onClick={() => setShowOverride(s => !s)}
                  >
                    {showOverride ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    高级：手动覆盖 KB 召回（极少用）
                  </button>
                  {showOverride && (
                    <Textarea
                      placeholder="（可空）老板想跳过自动多 query 召回，直接喂自定义 KB chunks 时贴这里。给了这个，tool 不再调 search_kb"
                      value={kbRecallOverride}
                      onChange={e => setKbRecallOverride(e.target.value)}
                      rows={4}
                      className="text-sm mt-2"
                    />
                  )}
                </div>

                <Button
                  onClick={runStep3}
                  disabled={running3 || !skuId || !matrixMd3.trim()}
                  className="w-full"
                >
                  {running3 ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（多 query 召回 + pro 推理 ~120s）</> : '跑人群匹配'}
                </Button>

                {error && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">输出</CardTitle>
                  {resp3?.trace && (
                    <CardDescription className="text-xs">
                      {resp3.trace.model_provider}/{resp3.trace.model} · {resp3.trace.cost_estimate}
                    </CardDescription>
                  )}
                </div>
                {resp3?.result?.audience_md && (
                  <div className="space-x-1">
                    <Button size="sm" variant="outline" onClick={() => copyText(resp3.result?.audience_md)}>
                      <Copy className="w-3 h-3 mr-1" /> 复制
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => downloadMd(resp3.result?.audience_md, `${skuId}_audience-match.md`)}>
                      <Download className="w-3 h-3 mr-1" /> 下载 .md
                    </Button>
                  </div>
                )}
              </CardHeader>
              <CardContent>
                {!resp3 && !running3 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左边贴 matrix_md 后点"跑人群匹配"，结果会显示在这里。
                  </div>
                )}
                {running3 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                    全 KB 多 query 召回（跨 46 doc）→ pro 模型反向匹配 → 资料诊断 + ≥15 个匹配人群 + 标签汇总...
                  </div>
                )}
                {resp3?.result?.audience_md && (
                  <>
                    {resp3.result.recall_meta && (
                      <div className="mb-4 p-3 bg-muted/50 rounded text-xs space-y-1">
                        <div className="flex items-center justify-between">
                          <div>
                            <span className="font-medium">召回模式：</span>
                            <Badge variant="outline" className="ml-1">
                              {resp3.result.recall_meta.mode === 'multi_query' ? '多 query 自动召回' : '手动覆盖'}
                            </Badge>
                            <span className="ml-3">
                              <span className="font-medium">queries:</span> {resp3.result.recall_meta.queries.length}
                            </span>
                            <span className="ml-3">
                              <span className="font-medium">chunks:</span> {resp3.result.recall_meta.chunk_count}
                            </span>
                          </div>
                          {resp3.result.recall_meta.queries.length > 0 && (
                            <button
                              className="flex items-center gap-1"
                              onClick={() => setShowQueries(s => !s)}
                            >
                              {showQueries ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                              展开 query 清单
                            </button>
                          )}
                        </div>
                        {showQueries && resp3.result.recall_meta.queries.length > 0 && (
                          <ul className="mt-2 list-disc list-inside text-muted-foreground">
                            {resp3.result.recall_meta.queries.map((q, i) => (
                              <li key={i}>{q}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}

                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {resp3.result.audience_md}
                      </ReactMarkdown>
                    </div>

                    {resp3.trace?.final_prompt && (
                      <div className="mt-6 border-t pt-4">
                        <button
                          className="text-sm font-medium flex items-center gap-1"
                          onClick={() => setShowPrompt3(s => !s)}
                        >
                          {showPrompt3 ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          Final Prompt（含 KB 召回原文）
                        </button>
                        {showPrompt3 && (
                          <pre className="mt-2 p-3 bg-muted text-xs rounded max-h-96 overflow-auto whitespace-pre-wrap">
                            {resp3.trace.final_prompt}
                          </pre>
                        )}
                      </div>
                    )}
                  </>
                )}
                {resp3 && !resp3.ok && (
                  <div className="text-sm text-red-500">
                    <div>Error: {resp3.error}</div>
                    {resp3.hint && <div className="text-xs text-muted-foreground mt-1">{resp3.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
