'use client'

import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'

// 运营洞察（阶段0 surfacing）：诊断官改进建议 + omni 运行成本 + cron 周期报 + 底座就绪度。
// 设计克制（蓝图 §1.7 不过度工程 + §6.1【R-8】图表层接现成 BI，不自研通用图表框架）。

interface Proposal {
  id: string
  mode: string
  source: string
  title: string
  observation: string
  hypothesis: string | null
  evidence: Record<string, unknown>
  sample_size: number
  confidence: string
  priority: number
  priority_reason: string | null
  occurrences: number
  status: string
  expires_at: string | null
}

interface SpendData {
  spend_month: string
  total_cost_usd: number
  cap_usd: number
  over_cap: boolean
  usage_ratio: number | null
  remaining_usd: number
  entry_count: number
}

interface CronReport {
  name: string
  title: string
  period: string
  content: string
  mtime?: number
}

export default function InsightsPage() {
  const [tab, setTab] = useState('proposals')

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-4">
      <div>
        <h1 className="text-2xl font-semibold bg-gradient-to-r from-violet-600 to-purple-500 bg-clip-text text-transparent">
          运营洞察
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          诊断官改进建议 · omni 运行成本 · 自动周期报 · 数据底座就绪度（阶段0 落地）
        </p>
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="proposals">改进建议</TabsTrigger>
          <TabsTrigger value="spend">运行成本</TabsTrigger>
          <TabsTrigger value="reports">周期报</TabsTrigger>
          <TabsTrigger value="foundation">底座状态</TabsTrigger>
        </TabsList>
        <TabsContent value="proposals"><ProposalsTab active={tab === 'proposals'} /></TabsContent>
        <TabsContent value="spend"><SpendTab active={tab === 'spend'} /></TabsContent>
        <TabsContent value="reports"><ReportsTab active={tab === 'reports'} /></TabsContent>
        <TabsContent value="foundation"><FoundationTab /></TabsContent>
      </Tabs>
    </div>
  )
}

function confidenceBadge(c: string) {
  return c === 'observed'
    ? <Badge variant="secondary">已观察 n≥5</Badge>
    : <Badge variant="outline">初步观察 待验证</Badge>
}

function ProposalsTab({ active }: { active: boolean }) {
  const [items, setItems] = useState<Proposal[]>([])
  const [stats, setStats] = useState<{ open_count?: number; digestion_rate_7d?: number | null }>({})
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true); setErr(null)
    try {
      const res = await fetch('/api/omni/proposals?status=open', { cache: 'no-store' })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '加载失败')
      setItems(json.data.proposals || [])
      setStats({ open_count: json.data.open_count, digestion_rate_7d: json.data.digestion_rate_7d })
    } catch (e) { setErr((e as Error).message) } finally { setLoading(false) }
  }, [])

  useEffect(() => { if (active) load() }, [active, load])

  const runDiagnose = async () => {
    setLoading(true); setErr(null)
    try {
      const res = await fetch('/api/omni/proposals', { method: 'POST', body: JSON.stringify({ mode: 'content', lookback_days: 7 }) })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '诊断失败')
      await load()
    } catch (e) { setErr((e as Error).message); setLoading(false) }
  }

  const resolve = async (id: string, action: string) => {
    setBusyId(id)
    try {
      const res = await fetch(`/api/omni/proposals/${id}/resolve`, { method: 'POST', body: JSON.stringify({ action }) })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || 'resolve 失败')
      await load()
    } catch (e) { setErr((e as Error).message) } finally { setBusyId(null) }
  }

  return (
    <div className="space-y-3 mt-3">
      <div className="flex items-center gap-3 flex-wrap">
        <Button onClick={runDiagnose} disabled={loading}>{loading ? '诊断中…' : '重新诊断'}</Button>
        <span className="text-sm text-muted-foreground">
          待办 {stats.open_count ?? 0} 条 · 7 天消化率 {stats.digestion_rate_7d == null ? '—' : `${Math.round((stats.digestion_rate_7d) * 100)}%`}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        诊断官只提议不碰开关（拍板权 100% 在你）。归因分两层（observation 客观 / hypothesis 假设），样本不足只作初步观察。
      </p>
      {err && <p className="text-sm text-red-500">{err}</p>}
      {!loading && items.length === 0 && (
        <Card><CardContent className="py-8 text-center text-sm text-muted-foreground">
          暂无待办提议。点「重新诊断」聚类最近 7 天的负反馈 + 投后数据。
        </CardContent></Card>
      )}
      {items.map((p) => (
        <Card key={p.id}>
          <CardHeader className="pb-2">
            <div className="flex items-start justify-between gap-2">
              <CardTitle className="text-base">{p.title}</CardTitle>
              <div className="flex items-center gap-1 shrink-0">
                {confidenceBadge(p.confidence)}
                <Badge variant="outline">优先级 {p.priority}</Badge>
              </div>
            </div>
            <CardDescription className="text-xs">
              来源 {p.source} · 样本 n={p.sample_size} · 出现 {p.occurrences} 次 · {p.priority_reason}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div><span className="font-medium text-violet-600">观察：</span>{p.observation}</div>
            {p.hypothesis && <div><span className="font-medium text-amber-600">可能原因（假设）：</span>{p.hypothesis}</div>}
            <div className="flex gap-2 pt-1">
              <Button size="sm" variant="default" disabled={busyId === p.id} onClick={() => resolve(p.id, 'accept')}>接受</Button>
              <Button size="sm" variant="outline" disabled={busyId === p.id} onClick={() => resolve(p.id, 'snooze')}>暂放(7天)</Button>
              <Button size="sm" variant="ghost" disabled={busyId === p.id} onClick={() => resolve(p.id, 'ignore')}>忽略(不再提醒同类)</Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function SpendTab({ active }: { active: boolean }) {
  const [data, setData] = useState<SpendData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (!active) return
    setData(null); setErr(null)  // 切回来先清旧值，避免显示过期数据
    fetch('/api/omni/spend', { cache: 'no-store' })
      .then((r) => r.json())
      .then((j) => { if (j.success) setData(j.data); else setErr(j.error) })
      .catch((e) => setErr(e.message))
  }, [active])

  if (err) return <p className="text-sm text-red-500 mt-3">{err}</p>
  if (!data) return <p className="text-sm text-muted-foreground mt-3">加载中…</p>
  // usage_ratio 为 null（cap 配置异常等）显式标 '—'，不伪装成 0%（与 digestion_rate 处理一致）
  const pct = data.usage_ratio != null ? Math.min(100, Math.round(data.usage_ratio * 100)) : null
  return (
    <div className="space-y-3 mt-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">omni 自身运行成本 · {data.spend_month}</CardTitle>
          <CardDescription className="text-xs">每次 Claude Code 会话跑完的 total_cost_usd 按月累计（蓝图 §4 L0-2 一等指标）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-end gap-2">
            <span className="text-3xl font-semibold">${data.total_cost_usd.toFixed(2)}</span>
            <span className="text-muted-foreground mb-1">/ 软上限 ${data.cap_usd.toFixed(0)}</span>
            {data.over_cap && <Badge variant="destructive" className="mb-1">已超软上限</Badge>}
          </div>
          <div className="h-2 w-full rounded bg-muted overflow-hidden">
            <div className={`h-full ${data.over_cap ? 'bg-red-500' : 'bg-violet-500'}`} style={{ width: `${pct ?? 0}%` }} />
          </div>
          <div className="text-xs text-muted-foreground">
            本月 {data.entry_count} 笔 · 用量 {pct != null ? `${pct}%` : '—'} · 剩余 ${data.remaining_usd.toFixed(2)}
          </div>
          <p className="text-xs text-muted-foreground">
            软上限改：KE <code>.env</code> 配 <code>OMNI_MONTHLY_SPEND_CAP_USD</code>（缺省回退 500 美元）。超额只提示不拦业务。
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

function ReportsTab({ active }: { active: boolean }) {
  const [reports, setReports] = useState<CronReport[]>([])
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (!active) return
    fetch('/api/omni/cron-reports', { cache: 'no-store' })
      .then((r) => r.json())
      .then((j) => { if (j.success) setReports(j.data.reports || []); else setErr(j.error) })
      .catch((e) => setErr(e.message))
  }, [active])

  if (err) return <p className="text-sm text-red-500 mt-3">{err}</p>
  return (
    <div className="space-y-3 mt-3">
      <p className="text-xs text-muted-foreground">cron 自动生成的周期报，直接推到这里（不用再去翻 markdown 文件）。</p>
      {reports.length === 0 && <p className="text-sm text-muted-foreground">暂无周期报（cron 还没跑过）。</p>}
      {reports.map((r) => (
        <Card key={r.name}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">{r.title}</CardTitle>
            <CardDescription className="text-xs">{r.period}{r.mtime ? ` · 更新于 ${new Date(r.mtime * 1000).toLocaleString('zh-CN')}` : ''}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="prose prose-sm max-w-none dark:prose-invert">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.content}</ReactMarkdown>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function FoundationTab() {
  return (
    <div className="space-y-3 mt-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">阶段0 数据底座就绪度</CardTitle>
          <CardDescription className="text-xs">蓝图 §3/§8 阶段0 schema 地基 + L0-2 + §6.2 诊断官落地状态</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <ul className="space-y-1">
            <li>✅ <code>mvp_daily_metric.platform</code> 维已加（存量回填 douyin）— 多平台 schema 形状就绪</li>
            <li>✅ <code>product</code> / <code>platform_listing</code> 表 + <code>v_metric_rollup</code> 视图（平台→品类→SKU 下钻）</li>
            <li>✅ <code>mcp.tool_calls.tool_use_id</code> 归因链列 + 传递层（差评→哪次调用→哪段 prompt）</li>
            <li>✅ <code>actor_id</code> 预留（反馈/决策/pipeline 表，单人→小团队不返工）</li>
            <li>✅ L0-2 月度成本总账（<code>mcp.monthly_spend</code>）已接线（见「运行成本」）</li>
            <li>✅ §6.2 诊断官已上线为可调用能力（见「改进建议」）</li>
          </ul>
          <p className="text-xs text-muted-foreground pt-2">
            多平台商业分析看板按蓝图 §6.1【R-8】<b>接现成 BI（Metabase/帆软 读 Postgres <code>v_metric_rollup</code>）</b>，
            不自研通用图表/筛选/下钻框架。京东/淘天自有经营数据尚未入库（§8.5 标「等数据源」），
            schema 形状已留好，数据接入后即可在 BI 里多平台同口径对比。
          </p>
          <p className="text-xs text-muted-foreground">
            STEP 2 contract（解绑 douyin 主键 / 换 UNIQUE 含 platform / NOT NULL）+ GMV·ROI 归一口径 = 待老板拍板（T2）。
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
