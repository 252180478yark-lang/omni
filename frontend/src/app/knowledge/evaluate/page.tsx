'use client'

import React, { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft,
  Play,
  Loader2,
  TrendingUp,
  TrendingDown,
  Minus,
  Clock,
  Target,
  BarChart3,
  ChevronDown,
  ChevronUp,
  Plus,
  X,
  Zap,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface KBItem {
  id: string
  name: string
}

interface StageInfo {
  name: string
  duration_ms: number
  input_count: number
  output_count: number
  details: Record<string, unknown>
}

interface QualityScores {
  relevancy: number
  completeness: number
  coherence: number
  overall: number
  comment: string
}

interface PipelineResult {
  query: string
  mode: string
  total_ms: number
  stages: StageInfo[]
  answer_length: number
  answer_preview: string
  source_count: number
  avg_chunk_score: number
  quality_scores: QualityScores
}

interface Comparison {
  quality_improvement: {
    optimized_overall: number
    baseline_overall: number
    delta: number
    improved: boolean
    pct_change: number
  }
  latency: {
    optimized_total_ms: number
    baseline_total_ms: number
    overhead_ms: number
    overhead_pct: number
  }
  retrieval: {
    optimized_sources: number
    baseline_sources: number
    optimized_avg_score: number
    baseline_avg_score: number
  }
  stage_timings: Record<string, { optimized_ms: number; baseline_ms: number; delta_ms: number }>
  verdict: string
}

interface EvalResult {
  query: string
  optimized: PipelineResult
  baseline: PipelineResult
  comparison: Comparison
}

interface BatchResult {
  total_queries: number
  successful: number
  failed: number
  summary: {
    avg_optimized_score: number
    avg_baseline_score: number
    avg_quality_delta: number
    improvement_rate: string
    avg_optimized_latency_ms: number
    avg_baseline_latency_ms: number
    avg_overhead_ms: number
  }
  details: EvalResult[]
}

const STAGE_LABELS: Record<string, string> = {
  query_enhancement: '查询增强',
  embedding: '向量化',
  retrieval: '检索',
  reranking: '精排',
  context_window: '上下文扩展',
  crag: 'CRAG 评估',
  compression: '压缩',
  generation: '生成',
}

export default function EvaluatePage() {
  const [kbs, setKbs] = useState<KBItem[]>([])
  const [selectedKb, setSelectedKb] = useState('')
  const [queries, setQueries] = useState<string[]>([''])
  const [running, setRunning] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildResult, setRebuildResult] = useState<string>('')
  const [result, setResult] = useState<EvalResult | BatchResult | null>(null)
  const [expandedQuery, setExpandedQuery] = useState<number | null>(null)

  useEffect(() => {
    fetch('/api/omni/knowledge/bases')
      .then(r => r.json())
      .then(d => {
        const list = d?.data?.data ?? d?.data ?? []
        setKbs(list)
        if (list.length > 0) setSelectedKb(list[0].id)
      })
      .catch(() => {})
  }, [])

  const rebuildKb = useCallback(async () => {
    if (!selectedKb) return
    setRebuilding(true)
    setRebuildResult('')
    try {
      const resp = await fetch(`/api/omni/knowledge/bases/${selectedKb}/rebuild`, { method: 'POST' })
      const json = await resp.json()
      const data = json.data ?? json
      setRebuildResult(data?.message || data?.data?.message || '已提交重建任务')
    } catch (e) {
      setRebuildResult(`重建失败: ${e}`)
    } finally {
      setRebuilding(false)
    }
  }, [selectedKb])

  const addQuery = useCallback(() => setQueries(q => [...q, '']), [])
  const removeQuery = useCallback((i: number) => setQueries(q => q.filter((_, idx) => idx !== i)), [])
  const updateQuery = useCallback((i: number, v: string) => {
    setQueries(q => q.map((old, idx) => (idx === i ? v : old)))
  }, [])

  const runEval = useCallback(async () => {
    if (!selectedKb) return
    const validQueries = queries.filter(q => q.trim())
    if (validQueries.length === 0) return
    setRunning(true)
    setResult(null)
    try {
      const body = validQueries.length === 1
        ? { query: validQueries[0], kb_ids: [selectedKb] }
        : { queries: validQueries, kb_ids: [selectedKb] }
      const resp = await fetch('/api/omni/knowledge/rag/evaluate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const json = await resp.json()
      setResult(json.data ?? json)
    } catch (e) {
      console.error(e)
    } finally {
      setRunning(false)
    }
  }, [selectedKb, queries])

  const isBatch = result && 'summary' in result
  const singleResult = !isBatch && result ? (result as EvalResult) : null
  const batchResult = isBatch ? (result as BatchResult) : null

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Link href="/chat">
            <Button variant="ghost" size="icon"><ArrowLeft className="w-4 h-4" /></Button>
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-slate-800">RAG 优化评估</h1>
            <p className="text-sm text-slate-500">对比优化前后的检索质量、回答质量和延迟</p>
          </div>
        </div>

        {/* Input Panel */}
        <Card>
          <CardContent className="pt-6 space-y-4">
            <div className="flex gap-4 items-end">
              <div className="flex-1">
                <label className="text-sm font-medium text-slate-700">知识库</label>
                <select
                  value={selectedKb}
                  onChange={e => setSelectedKb(e.target.value)}
                  className="mt-1 w-full rounded-md border border-slate-200 px-3 py-2 text-sm bg-white"
                >
                  {kbs.map(kb => <option key={kb.id} value={kb.id}>{kb.name}</option>)}
                </select>
              </div>
              <Button onClick={rebuildKb} disabled={rebuilding || !selectedKb} variant="outline" className="gap-2 border-orange-300 text-orange-700 hover:bg-orange-50">
                {rebuilding ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                {rebuilding ? '重建中...' : '重建索引'}
              </Button>
              <Button onClick={runEval} disabled={running || !selectedKb} className="gap-2">
                {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                {running ? '评估中...' : '开始评估'}
              </Button>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">测试查询</label>
              {queries.map((q, i) => (
                <div key={i} className="flex gap-2">
                  <input
                    value={q}
                    onChange={e => updateQuery(i, e.target.value)}
                    placeholder={`查询 ${i + 1}...`}
                    className="flex-1 rounded-md border border-slate-200 px-3 py-2 text-sm"
                    onKeyDown={e => e.key === 'Enter' && runEval()}
                  />
                  {queries.length > 1 && (
                    <Button variant="ghost" size="icon" onClick={() => removeQuery(i)}>
                      <X className="w-4 h-4" />
                    </Button>
                  )}
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={addQuery} className="gap-1">
                <Plus className="w-3 h-3" /> 添加查询
              </Button>
            </div>
            {rebuildResult && (
              <div className="p-3 rounded-md bg-orange-50 border border-orange-200 text-sm text-orange-800">
                {rebuildResult}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Batch Summary */}
        {batchResult?.summary && (
          <Card className="border-blue-200 bg-blue-50/30">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-blue-600" />
                批量评估汇总 ({batchResult.successful}/{batchResult.total_queries} 成功)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  label="优化后平均分"
                  value={batchResult.summary.avg_optimized_score}
                  suffix="/10"
                  color="green"
                />
                <MetricCard
                  label="基线平均分"
                  value={batchResult.summary.avg_baseline_score}
                  suffix="/10"
                  color="slate"
                />
                <MetricCard
                  label="质量提升"
                  value={batchResult.summary.avg_quality_delta}
                  prefix={batchResult.summary.avg_quality_delta > 0 ? '+' : ''}
                  color={batchResult.summary.avg_quality_delta > 0 ? 'green' : 'red'}
                />
                <MetricCard
                  label="提升率"
                  value={batchResult.summary.improvement_rate}
                  color="blue"
                  isText
                />
              </div>
              <div className="mt-3 grid grid-cols-3 gap-4 text-sm text-slate-600">
                <div>优化后平均延迟: <strong>{Math.round(batchResult.summary.avg_optimized_latency_ms)}ms</strong></div>
                <div>基线平均延迟: <strong>{Math.round(batchResult.summary.avg_baseline_latency_ms)}ms</strong></div>
                <div>额外开销: <strong>{Math.round(batchResult.summary.avg_overhead_ms)}ms</strong></div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Single Result */}
        {singleResult && <ComparisonView result={singleResult} />}

        {/* Batch Details */}
        {batchResult?.details?.map((detail, idx) => {
          if ('error' in detail) return (
            <Card key={idx} className="border-red-200">
              <CardContent className="pt-4 text-red-600 text-sm">
                查询 &quot;{(detail as unknown as {query:string}).query}&quot; 评估失败
              </CardContent>
            </Card>
          )
          const d = detail as EvalResult
          return (
            <div key={idx}>
              <button
                onClick={() => setExpandedQuery(expandedQuery === idx ? null : idx)}
                className="w-full text-left px-4 py-3 bg-white rounded-lg border border-slate-200 flex items-center justify-between hover:bg-slate-50 transition"
              >
                <span className="text-sm font-medium text-slate-800">{d.query}</span>
                <div className="flex items-center gap-3">
                  <QualityBadge delta={d.comparison.quality_improvement.delta} />
                  <Badge variant="outline" className="text-xs">
                    {Math.round(d.optimized.total_ms)}ms
                  </Badge>
                  {expandedQuery === idx ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </div>
              </button>
              {expandedQuery === idx && <ComparisonView result={d} />}
            </div>
          )
        })}
      </div>
    </div>
  )
}


function ComparisonView({ result }: { result: EvalResult }) {
  const { comparison: comp, optimized: opt, baseline: base } = result
  return (
    <div className="space-y-4 mt-4">
      {/* Verdict */}
      <Card className={
        comp.quality_improvement.improved
          ? 'border-green-200 bg-green-50/30'
          : 'border-yellow-200 bg-yellow-50/30'
      }>
        <CardContent className="pt-4 flex items-center gap-3">
          {comp.quality_improvement.improved
            ? <TrendingUp className="w-6 h-6 text-green-600" />
            : comp.quality_improvement.delta === 0
              ? <Minus className="w-6 h-6 text-yellow-600" />
              : <TrendingDown className="w-6 h-6 text-red-600" />
          }
          <div>
            <div className="font-semibold text-slate-800">{comp.verdict}</div>
            <div className="text-sm text-slate-600">
              质量 {comp.quality_improvement.optimized_overall} vs {comp.quality_improvement.baseline_overall}
              {comp.quality_improvement.delta !== 0 && (
                <span className={comp.quality_improvement.improved ? 'text-green-600' : 'text-red-600'}>
                  {' '}({comp.quality_improvement.delta > 0 ? '+' : ''}{comp.quality_improvement.delta})
                </span>
              )}
              {' · '}延迟 {Math.round(comp.latency.optimized_total_ms)}ms vs {Math.round(comp.latency.baseline_total_ms)}ms
              <span className="text-slate-400"> (+{Math.round(comp.latency.overhead_ms)}ms)</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Score Comparison */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <PipelineCard title="优化后" mode="optimized" data={opt} />
        <PipelineCard title="基线" mode="baseline" data={base} />
      </div>

      {/* Stage Timings */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Clock className="w-4 h-4" /> 各阶段耗时对比
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {Object.entries(comp.stage_timings).map(([name, timing]) => (
              <div key={name} className="flex items-center gap-2 text-sm">
                <span className="w-28 text-slate-600 shrink-0">{STAGE_LABELS[name] || name}</span>
                <div className="flex-1 flex items-center gap-1">
                  <div
                    className="h-5 bg-blue-500 rounded-sm flex items-center justify-end pr-1"
                    style={{ width: `${Math.min(timing.optimized_ms / 10, 100)}%`, minWidth: timing.optimized_ms > 0 ? '20px' : '0' }}
                  >
                    <span className="text-[10px] text-white">{Math.round(timing.optimized_ms)}</span>
                  </div>
                </div>
                <div className="flex-1 flex items-center gap-1">
                  <div
                    className="h-5 bg-slate-400 rounded-sm flex items-center justify-end pr-1"
                    style={{ width: `${Math.min(timing.baseline_ms / 10, 100)}%`, minWidth: timing.baseline_ms > 0 ? '20px' : '0' }}
                  >
                    <span className="text-[10px] text-white">{Math.round(timing.baseline_ms)}</span>
                  </div>
                </div>
                <span className={`w-16 text-right text-xs ${timing.delta_ms > 100 ? 'text-red-500' : 'text-slate-400'}`}>
                  {timing.delta_ms > 0 ? '+' : ''}{Math.round(timing.delta_ms)}ms
                </span>
              </div>
            ))}
          </div>
          <div className="mt-2 flex gap-4 text-xs text-slate-400">
            <span className="flex items-center gap-1"><span className="w-3 h-2 bg-blue-500 rounded-sm inline-block" />优化后</span>
            <span className="flex items-center gap-1"><span className="w-3 h-2 bg-slate-400 rounded-sm inline-block" />基线</span>
          </div>
        </CardContent>
      </Card>

      {/* Answer Preview */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Zap className="w-4 h-4 text-blue-500" /> 优化后回答
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-slate-600 whitespace-pre-wrap">{opt.answer_preview}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">基线回答</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-slate-600 whitespace-pre-wrap">{base.answer_preview}</p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}


function PipelineCard({ title, mode, data }: { title: string; mode: string; data: PipelineResult }) {
  const q = data.quality_scores
  const isOpt = mode === 'optimized'
  return (
    <Card className={isOpt ? 'border-blue-200' : ''}>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          {isOpt && <Target className="w-4 h-4 text-blue-500" />}
          {title}
          <Badge variant="outline" className="text-[10px]">{Math.round(data.total_ms)}ms</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="grid grid-cols-4 gap-2 text-center">
          <ScoreCircle label="相关性" score={q?.relevancy ?? -1} />
          <ScoreCircle label="完整性" score={q?.completeness ?? -1} />
          <ScoreCircle label="连贯性" score={q?.coherence ?? -1} />
          <ScoreCircle label="综合" score={q?.overall ?? -1} highlight />
        </div>
        {q?.comment && <p className="text-xs text-slate-500 italic">{q.comment}</p>}
        <div className="text-xs text-slate-400 flex gap-3">
          <span>引用: {data.source_count}</span>
          <span>平均分: {data.avg_chunk_score}</span>
          <span>回答: {data.answer_length}字</span>
        </div>
      </CardContent>
    </Card>
  )
}

function ScoreCircle({ label, score, highlight }: { label: string; score: number; highlight?: boolean }) {
  const color = score < 0 ? 'text-slate-300' : score >= 8 ? 'text-green-600' : score >= 5 ? 'text-yellow-600' : 'text-red-600'
  return (
    <div>
      <div className={`text-2xl font-bold ${highlight ? 'text-blue-600' : color}`}>
        {score < 0 ? '-' : score}
      </div>
      <div className="text-[10px] text-slate-500">{label}</div>
    </div>
  )
}

function QualityBadge({ delta }: { delta: number }) {
  if (delta > 0) return <Badge className="bg-green-100 text-green-700 text-xs">+{delta}</Badge>
  if (delta < 0) return <Badge className="bg-red-100 text-red-700 text-xs">{delta}</Badge>
  return <Badge className="bg-slate-100 text-slate-500 text-xs">0</Badge>
}

function MetricCard({
  label, value, prefix, suffix, color, isText,
}: {
  label: string; value: number | string; prefix?: string; suffix?: string; color: string; isText?: boolean
}) {
  const colorMap: Record<string, string> = {
    green: 'text-green-600',
    red: 'text-red-600',
    blue: 'text-blue-600',
    slate: 'text-slate-600',
  }
  return (
    <div className="bg-white rounded-lg border border-slate-100 p-3 text-center">
      <div className={`text-2xl font-bold ${colorMap[color] || 'text-slate-800'}`}>
        {prefix}{isText ? value : typeof value === 'number' ? value.toFixed(1) : value}{suffix}
      </div>
      <div className="text-xs text-slate-500 mt-1">{label}</div>
    </div>
  )
}
