'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  ArrowLeft,
  ArrowUpRight,
  ArrowDownRight,
  BookOpen,
  Check,
  Database,
  Loader2,
  Minus,
  RefreshCw,
  Sparkles,
  TrendingUp,
  Zap,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { flywheelDashboard, listProducts } from '@/lib/ad-review-api'

type Round = Record<string, unknown>

function num(v: unknown): number {
  return typeof v === 'number' ? v : Number(v) || 0
}

function pct(v: unknown, digits = 2): string {
  return `${(num(v) * 100).toFixed(digits)}%`
}

function DeltaBadge({ value }: { value: unknown }) {
  if (value == null) return <Badge variant="outline" className="text-[10px] text-gray-400">--</Badge>
  const n = num(value)
  if (Math.abs(n) < 0.01) return <Badge variant="outline" className="text-[10px] text-gray-400"><Minus className="w-3 h-3 mr-0.5" />持平</Badge>
  if (n > 0) return <Badge className="text-[10px] bg-emerald-50 text-emerald-700 border-emerald-200"><ArrowUpRight className="w-3 h-3 mr-0.5" />+{n.toFixed(1)}%</Badge>
  return <Badge className="text-[10px] bg-red-50 text-red-600 border-red-200"><ArrowDownRight className="w-3 h-3 mr-0.5" />{n.toFixed(1)}%</Badge>
}

export default function FlywheelPage() {
  const [products, setProducts] = useState<{ id: string; name: string }[]>([])
  const [productId, setProductId] = useState('')
  const [rounds, setRounds] = useState<Round[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    void (async () => {
      try {
        const p = await listProducts()
        setProducts(p.items || [])
        if (p.items?.[0]?.id) setProductId(p.items[0].id)
      } catch (e) {
        setError(String(e))
      }
    })()
  }, [])

  useEffect(() => {
    if (!productId) return
    let cancelled = false
    setLoading(true)
    setError('')
    void (async () => {
      try {
        const data = await flywheelDashboard(productId)
        if (!cancelled) setRounds(data.rounds || [])
      } catch (e) {
        if (!cancelled) setError(String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [productId])

  const chartData = useMemo(() => rounds.map((r) => ({
    name: `R${num(r.round_num)}`,
    label: String(r.name || r.start_date || '').slice(0, 16),
    ctr: num(r.avg_ctr) * 100,
    cvr: num(r.avg_cvr) * 100,
    cpm: num(r.avg_cpm),
    completion: num(r.avg_completion_rate) * 100,
    cost: num(r.sum_cost),
    materials: num(r.material_count),
  })), [rounds])

  const latestRound = rounds.length > 0 ? rounds[rounds.length - 1] : null
  const firstRound = rounds.length > 0 ? rounds[0] : null

  const overallImprovement = useMemo(() => {
    if (!firstRound || !latestRound || rounds.length < 2) return null
    const firstCtr = num(firstRound.avg_ctr)
    const lastCtr = num(latestRound.avg_ctr)
    return firstCtr > 0 ? ((lastCtr - firstCtr) / firstCtr * 100) : null
  }, [firstRound, latestRound, rounds])

  const kbSyncedCount = rounds.filter((r) => r.kb_synced).length
  const reviewedCount = rounds.filter((r) => r.has_review).length

  const productName = products.find((p) => p.id === productId)?.name || ''

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-16">
      <header className="border-b border-gray-200/80 bg-white/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link href="/ad-review" className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800">
            <ArrowLeft className="w-4 h-4" /> 投放复盘
          </Link>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
              <RefreshCw className="w-3.5 h-3.5 text-white" />
            </div>
            <h1 className="text-lg font-semibold text-gray-900">飞轮仪表盘</h1>
          </div>
          <select
            className="ml-auto h-8 rounded-md border border-gray-200 bg-white px-2.5 text-sm min-w-[180px] focus:ring-1 focus:ring-violet-300 outline-none"
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
          >
            <option value="" disabled>选择产品</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm">{error}</div>
        )}

        {loading ? (
          <div className="h-64 flex items-center justify-center text-gray-400 text-sm">
            <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载飞轮数据...
          </div>
        ) : rounds.length === 0 ? (
          <div className="h-64 flex flex-col items-center justify-center text-gray-400 text-sm gap-3">
            <RefreshCw className="w-10 h-10 text-gray-300" />
            <p>{productId ? '该产品暂无投放数据' : '请先选择一个产品'}</p>
            <Link href="/ad-review">
              <Button variant="outline" size="sm">前往创建投放批次</Button>
            </Link>
          </div>
        ) : (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
              <Card className="border-none shadow-sm">
                <CardContent className="p-4">
                  <div className="text-xs text-gray-400 mb-1">投放轮次</div>
                  <div className="text-2xl font-bold text-gray-900">{rounds.length}</div>
                  <div className="text-xs text-gray-400 mt-1">{productName}</div>
                </CardContent>
              </Card>

              <Card className="border-none shadow-sm">
                <CardContent className="p-4">
                  <div className="text-xs text-gray-400 mb-1 flex items-center gap-1">
                    <TrendingUp className="w-3 h-3" /> CTR 总提升
                  </div>
                  <div className="text-2xl font-bold text-gray-900">
                    {overallImprovement != null ? `${overallImprovement > 0 ? '+' : ''}${overallImprovement.toFixed(1)}%` : '--'}
                  </div>
                  <div className="text-xs text-gray-400 mt-1">首轮 vs 最新</div>
                </CardContent>
              </Card>

              <Card className="border-none shadow-sm">
                <CardContent className="p-4">
                  <div className="text-xs text-gray-400 mb-1 flex items-center gap-1">
                    <Sparkles className="w-3 h-3" /> 已复盘
                  </div>
                  <div className="text-2xl font-bold text-gray-900">{reviewedCount}/{rounds.length}</div>
                  <div className="text-xs text-gray-400 mt-1">批次完成率</div>
                </CardContent>
              </Card>

              <Card className="border-none shadow-sm">
                <CardContent className="p-4">
                  <div className="text-xs text-gray-400 mb-1 flex items-center gap-1">
                    <Database className="w-3 h-3" /> 经验入库
                  </div>
                  <div className="text-2xl font-bold text-gray-900">{kbSyncedCount}/{rounds.length}</div>
                  <div className="text-xs text-gray-400 mt-1">知识库闭环</div>
                </CardContent>
              </Card>

              <Card className="border-none shadow-sm">
                <CardContent className="p-4">
                  <div className="text-xs text-gray-400 mb-1">总投入</div>
                  <div className="text-2xl font-bold text-gray-900">
                    {rounds.reduce((a, r) => a + num(r.sum_cost), 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
                  </div>
                  <div className="text-xs text-gray-400 mt-1">元</div>
                </CardContent>
              </Card>
            </div>

            {/* Flywheel loop visualization */}
            <Card className="border-none shadow-sm overflow-hidden">
              <div className="px-5 pt-5 pb-2">
                <h2 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                  <Zap className="w-4 h-4 text-violet-500" />
                  飞轮闭环状态
                </h2>
                <p className="text-xs text-gray-400 mt-0.5">每轮投放的闭环完成情况</p>
              </div>
              <CardContent className="pt-0 pb-5">
                <div className="flex items-start gap-3 overflow-x-auto pb-2">
                  {rounds.map((r, i) => {
                    const synced = !!r.kb_synced
                    const reviewed = !!r.has_review
                    const hasMats = num(r.material_count) > 0
                    const steps = [
                      { label: '投放', done: hasMats },
                      { label: '复盘', done: reviewed },
                      { label: '入库', done: synced },
                    ]
                    const completedSteps = steps.filter((s) => s.done).length
                    return (
                      <div key={String(r.id)} className="flex flex-col items-center min-w-[120px] shrink-0">
                        <div className="text-xs font-semibold text-gray-700 mb-2">第 {i + 1} 轮</div>
                        <div className={`w-16 h-16 rounded-full border-4 flex items-center justify-center text-sm font-bold ${
                          completedSteps === 3 ? 'border-emerald-500 text-emerald-600 bg-emerald-50' :
                          completedSteps >= 1 ? 'border-amber-400 text-amber-600 bg-amber-50' :
                          'border-gray-200 text-gray-400 bg-gray-50'
                        }`}>
                          {completedSteps === 3 ? <Check className="w-6 h-6" /> : `${completedSteps}/3`}
                        </div>
                        <div className="mt-2 space-y-0.5">
                          {steps.map((s) => (
                            <div key={s.label} className={`text-[10px] flex items-center gap-1 ${s.done ? 'text-emerald-600' : 'text-gray-400'}`}>
                              {s.done ? <Check className="w-2.5 h-2.5" /> : <Minus className="w-2.5 h-2.5" />}
                              {s.label}
                            </div>
                          ))}
                        </div>
                        <div className="text-[10px] text-gray-400 mt-1.5 text-center truncate max-w-[110px]">
                          {String(r.name || '').slice(0, 12)}
                        </div>
                        {i < rounds.length - 1 && (
                          <div className="absolute" style={{ display: 'none' }} />
                        )}
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>

            {/* CTR & CVR trend chart */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <Card className="border-none shadow-sm overflow-hidden">
                <div className="px-5 pt-5 pb-2">
                  <h2 className="text-sm font-semibold text-gray-900">CTR / 完播率 趋势</h2>
                </div>
                <CardContent className="pt-0 pb-5">
                  <div className="h-64 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData}>
                        <defs>
                          <linearGradient id="ctrGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                          </linearGradient>
                          <linearGradient id="compGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                        <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="#999" />
                        <YAxis tick={{ fontSize: 11 }} stroke="#999" />
                        <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12, border: '1px solid #e5e7eb' }} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Area type="monotone" dataKey="ctr" name="CTR %" stroke="#6366f1" fill="url(#ctrGrad)" strokeWidth={2} dot={{ r: 3 }} />
                        <Area type="monotone" dataKey="completion" name="完播率 %" stroke="#10b981" fill="url(#compGrad)" strokeWidth={2} dot={{ r: 3 }} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>

              <Card className="border-none shadow-sm overflow-hidden">
                <div className="px-5 pt-5 pb-2">
                  <h2 className="text-sm font-semibold text-gray-900">CPM / 消耗 趋势</h2>
                </div>
                <CardContent className="pt-0 pb-5">
                  <div className="h-64 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chartData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                        <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="#999" />
                        <YAxis yAxisId="left" tick={{ fontSize: 11 }} stroke="#999" />
                        <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} stroke="#999" />
                        <Tooltip contentStyle={{ borderRadius: 8, fontSize: 12, border: '1px solid #e5e7eb' }} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Line yAxisId="left" type="monotone" dataKey="cpm" name="CPM (元)" stroke="#f59e0b" strokeWidth={2} dot={{ r: 3 }} />
                        <Line yAxisId="right" type="monotone" dataKey="cost" name="消耗 (元)" stroke="#ef4444" strokeWidth={2} dot={{ r: 3 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Round-by-round detail table */}
            <Card className="border-none shadow-sm overflow-hidden">
              <div className="px-5 pt-5 pb-3">
                <h2 className="text-sm font-semibold text-gray-900">逐轮指标对比</h2>
                <p className="text-xs text-gray-400 mt-0.5">每轮环比变化一目了然</p>
              </div>
              <CardContent className="pt-0 pb-5">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100">
                        <th className="py-2.5 pr-3 text-left text-xs font-medium text-gray-500">轮次</th>
                        <th className="py-2.5 pr-3 text-left text-xs font-medium text-gray-500">批次名</th>
                        <th className="py-2.5 pr-3 text-right text-xs font-medium text-gray-500">素材数</th>
                        <th className="py-2.5 pr-3 text-right text-xs font-medium text-gray-500">消耗</th>
                        <th className="py-2.5 pr-3 text-right text-xs font-medium text-gray-500">CTR</th>
                        <th className="py-2.5 pr-3 text-center text-xs font-medium text-gray-500">CTR 环比</th>
                        <th className="py-2.5 pr-3 text-right text-xs font-medium text-gray-500">CVR</th>
                        <th className="py-2.5 pr-3 text-center text-xs font-medium text-gray-500">CVR 环比</th>
                        <th className="py-2.5 pr-3 text-right text-xs font-medium text-gray-500">CPM</th>
                        <th className="py-2.5 pr-3 text-right text-xs font-medium text-gray-500">完播率</th>
                        <th className="py-2.5 text-center text-xs font-medium text-gray-500">闭环</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {rounds.map((r, i) => (
                        <tr key={String(r.id)} className="hover:bg-gray-50/50">
                          <td className="py-2.5 pr-3">
                            <Badge variant="outline" className="text-[10px] rounded-full px-2">R{i + 1}</Badge>
                          </td>
                          <td className="py-2.5 pr-3 font-medium text-gray-900 max-w-[200px] truncate">
                            <Link href={`/ad-review/${String(r.id)}`} className="hover:text-violet-600 hover:underline">
                              {String(r.name || '')}
                            </Link>
                          </td>
                          <td className="py-2.5 pr-3 text-right text-gray-600">
                            {num(r.material_count)}
                            {num(r.iterated_material_count) > 0 && (
                              <span className="text-[10px] text-violet-500 ml-1">({num(r.iterated_material_count)}迭代)</span>
                            )}
                          </td>
                          <td className="py-2.5 pr-3 text-right text-gray-600">
                            {num(r.sum_cost).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}
                          </td>
                          <td className="py-2.5 pr-3 text-right font-medium text-gray-900">{pct(r.avg_ctr)}</td>
                          <td className="py-2.5 pr-3 text-center"><DeltaBadge value={r.ctr_delta} /></td>
                          <td className="py-2.5 pr-3 text-right font-medium text-gray-900">{pct(r.avg_cvr)}</td>
                          <td className="py-2.5 pr-3 text-center"><DeltaBadge value={r.cvr_delta} /></td>
                          <td className="py-2.5 pr-3 text-right text-gray-600">{num(r.avg_cpm).toFixed(1)}</td>
                          <td className="py-2.5 pr-3 text-right text-gray-600">{pct(r.avg_completion_rate)}</td>
                          <td className="py-2.5 text-center">
                            <div className="flex items-center justify-center gap-1">
                              {r.has_review ? (
                                <span className="w-5 h-5 rounded-full bg-emerald-100 flex items-center justify-center" title="已复盘">
                                  <Check className="w-3 h-3 text-emerald-600" />
                                </span>
                              ) : (
                                <span className="w-5 h-5 rounded-full bg-gray-100 flex items-center justify-center" title="未复盘">
                                  <Minus className="w-3 h-3 text-gray-400" />
                                </span>
                              )}
                              {r.kb_synced ? (
                                <span className="w-5 h-5 rounded-full bg-violet-100 flex items-center justify-center" title="已入库">
                                  <BookOpen className="w-3 h-3 text-violet-600" />
                                </span>
                              ) : (
                                <span className="w-5 h-5 rounded-full bg-gray-100 flex items-center justify-center" title="未入库">
                                  <Minus className="w-3 h-3 text-gray-400" />
                                </span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>

            {/* Action prompt */}
            {rounds.length > 0 && (
              <Card className="border-none shadow-sm bg-gradient-to-r from-violet-50 to-purple-50 overflow-hidden">
                <CardContent className="p-5 flex items-center gap-4">
                  <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center shadow-lg shadow-purple-200/50 shrink-0">
                    <RefreshCw className="w-6 h-6 text-white" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-900">启动下一轮迭代</h3>
                    <p className="text-xs text-gray-500 mt-0.5">
                      基于 {kbSyncedCount} 轮已入库的复盘经验，让 AI 为你生成更精准的下一轮内容策略
                    </p>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <Link href="/chat">
                      <Button size="sm" variant="outline" className="gap-1.5 rounded-lg">
                        <Sparkles className="w-3.5 h-3.5" /> 咨询 AI 策略
                      </Button>
                    </Link>
                    <Link href="/content-studio">
                      <Button size="sm" className="gap-1.5 rounded-lg bg-gradient-to-r from-violet-600 to-purple-500">
                        <Zap className="w-3.5 h-3.5" /> 创建新内容
                      </Button>
                    </Link>
                  </div>
                </CardContent>
              </Card>
            )}
          </>
        )}
      </main>
    </div>
  )
}
