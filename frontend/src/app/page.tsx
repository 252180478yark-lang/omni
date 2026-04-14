'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import Link from 'next/link'
import {
  Activity,
  Cpu,
  BrainCircuit,
  MessageSquare,
  Database,
  Network,
  ListTodo,
  Newspaper,
  Clapperboard,
  Download,
  Radio,
  LineChart,
  ArrowRight,
  Sparkles,
  Zap,
  Shield,
  Palette,
  Search,
  TrendingUp,
} from 'lucide-react'

type HealthState = 'healthy' | 'down'

interface ActivityItem {
  id: string
  title: string
  status: string
  time: string
  source: 'knowledge' | 'news' | 'video' | 'livestream'
}

interface OverviewData {
  health: {
    aiHub: HealthState
    knowledge: HealthState
  }
  metrics: {
    aiTokenToday: number
    knowledgeDocuments: number
    infraUptime: number
    knowledgeBases: number
    runningTasks: number
  }
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}

const QUICK_TOOLS = [
  { href: '/chat', icon: MessageSquare, label: '智能问答', desc: 'RAG + 多模态 AI', color: 'from-violet-500 to-purple-600', badge: '热门' },
  { href: '/knowledge', icon: Database, label: '知识库', desc: 'pgvector 向量检索', color: 'from-emerald-500 to-teal-600', badge: null },
  { href: '/knowledge/harvester', icon: Download, label: '知识采集', desc: '网页/文档智能提取', color: 'from-blue-500 to-cyan-600', badge: null },
  { href: '/video-analysis', icon: Clapperboard, label: '短视频分析', desc: 'AI 多模态视频解读', color: 'from-pink-500 to-rose-600', badge: null },
  { href: '/livestream-analysis', icon: Radio, label: '直播分析', desc: '直播切片智能分析', color: 'from-orange-500 to-amber-600', badge: null },
  { href: '/ad-review', icon: LineChart, label: '投放复盘', desc: '广告数据分析', color: 'from-indigo-500 to-blue-600', badge: null },
  { href: '/content-studio', icon: Palette, label: '内容工坊', desc: '一键生成营销素材', color: 'from-fuchsia-500 to-pink-600', badge: '新' },
  { href: '/news', icon: Newspaper, label: '资讯中心', desc: '行业动态聚合', color: 'from-sky-500 to-blue-600', badge: null },
]

const FEATURES = [
  { icon: Zap, title: '极速部署', desc: '零代码配置，无环境依赖，开箱即用' },
  { icon: BrainCircuit, title: '智能引擎', desc: '内置多模型、RAG 检索和多模态分析' },
  { icon: Shield, title: '安全可靠', desc: '企业级安全架构，数据加密传输' },
]

export default function Home() {
  const [loading, setLoading] = useState(true)
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [error, setError] = useState<string>('')

  useEffect(() => {
    const run = async () => {
      setLoading(true)
      setError('')
      try {
        const [overviewRes, activityRes] = await Promise.all([
          fetch('/api/omni/overview', { cache: 'no-store' }),
          fetch('/api/omni/activity', { cache: 'no-store' }),
        ])
        const overviewJson = (await overviewRes.json()) as { success: boolean; data?: OverviewData; error?: string }
        if (!overviewJson.success || !overviewJson.data) {
          throw new Error(overviewJson.error || '加载失败')
        }
        setOverview(overviewJson.data)
        const activityJson = (await activityRes.json()) as { success: boolean; data?: ActivityItem[] }
        if (activityJson.success && activityJson.data) {
          setActivity(activityJson.data)
        }
      } catch (err) {
        setError(String(err))
      } finally {
        setLoading(false)
      }
    }
    void run()
  }, [])

  const statCards = useMemo(() => {
    const metrics = overview?.metrics
    return [
      { title: 'AI 网关', value: metrics?.aiTokenToday ?? 0, subtitle: '今日 Token 消耗', icon: BrainCircuit, color: 'text-violet-600', bg: 'bg-violet-50', ring: 'ring-violet-100' },
      { title: '知识引擎', value: metrics?.knowledgeDocuments ?? 0, subtitle: '已入库文档', icon: Database, color: 'text-emerald-600', bg: 'bg-emerald-50', ring: 'ring-emerald-100' },
      { title: '基础设施', value: `${metrics?.infraUptime ?? 0}%`, subtitle: '服务连通率', icon: Network, color: 'text-amber-600', bg: 'bg-amber-50', ring: 'ring-amber-100' },
      { title: '运行任务', value: metrics?.runningTasks ?? 0, subtitle: '正在执行', icon: Activity, color: 'text-blue-600', bg: 'bg-blue-50', ring: 'ring-blue-100' },
    ]
  }, [overview])

  const healthy = overview?.health && Object.values(overview.health).every((s) => s === 'healthy')

  return (
    <div className="min-h-screen pb-20">
      {/* Hero Section */}
      <div className="relative overflow-hidden rounded-b-3xl mb-8">
        <div className="hero-pattern">
          <div className="relative px-6 lg:px-10 pt-8 pb-10">
            {/* Status bar */}
            <div className="flex items-center justify-between mb-8">
              <div className="flex items-center gap-3">
                <Badge className="bg-violet-100 text-violet-700 border-violet-200 hover:bg-violet-100 rounded-full px-3 py-1 text-xs font-medium">
                  <div className={`w-2 h-2 rounded-full mr-2 ${healthy ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`} />
                  {healthy ? '全部服务运行正常' : loading ? '检测中...' : '部分服务异常'}
                </Badge>
              </div>
              <div className="flex items-center gap-2">
                <Link href="/models">
                  <Button variant="ghost" size="sm" className="text-gray-500 hover:text-gray-900 rounded-full text-xs gap-1.5">
                    <Cpu className="w-3.5 h-3.5" />
                    模型配置
                  </Button>
                </Link>
                <Link href="/tasks">
                  <Button variant="ghost" size="sm" className="text-gray-500 hover:text-gray-900 rounded-full text-xs gap-1.5">
                    <ListTodo className="w-3.5 h-3.5" />
                    任务队列
                  </Button>
                </Link>
              </div>
            </div>

            {/* Hero content */}
            <div className="flex flex-col lg:flex-row items-start gap-8 lg:gap-16">
              <div className="flex-1 min-w-0">
                <h1 className="text-3xl lg:text-4xl font-bold tracking-tight text-gray-900 mb-4">
                  Omni-Vibe OS
                  <span className="bg-gradient-to-r from-violet-600 to-purple-500 bg-clip-text text-transparent ml-2">Ultra</span>
                </h1>
                <p className="text-gray-500 text-base lg:text-lg mb-6 max-w-xl leading-relaxed">
                  {loading ? '正在初始化系统...' : error ? '系统状态读取异常，请检查后端服务' : '自进化混合架构认知操作系统，集成 AI 问答、知识管理、多模态分析于一体'}
                </p>

                {/* Search-like input */}
                <Link href="/chat" className="block max-w-lg">
                  <div className="flex items-center gap-3 px-5 py-3.5 bg-white rounded-2xl border border-gray-200/80 shadow-sm hover:shadow-md hover:border-violet-200 transition-all duration-300 cursor-pointer group">
                    <Search className="w-5 h-5 text-gray-300 group-hover:text-violet-400 transition-colors" />
                    <span className="text-gray-400 text-sm flex-1">向 AI 助手提问，或搜索知识库...</span>
                    <div className="px-3 py-1.5 rounded-xl bg-gradient-to-r from-violet-600 to-purple-500 text-white text-xs font-medium shadow-sm">
                      开始对话
                    </div>
                  </div>
                </Link>
              </div>

              {/* Decorative cards */}
              <div className="hidden lg:flex items-center gap-4 shrink-0">
                <div className="animate-float">
                  <div className="w-28 h-28 rounded-2xl bg-gradient-to-br from-violet-500 to-purple-600 shadow-xl shadow-purple-200/50 flex items-center justify-center">
                    <BrainCircuit className="w-12 h-12 text-white" />
                  </div>
                </div>
                <div className="flex flex-col gap-4">
                  <div className="animate-float-delayed">
                    <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-emerald-400 to-teal-500 shadow-lg shadow-teal-200/50 flex items-center justify-center">
                      <Database className="w-8 h-8 text-white" />
                    </div>
                  </div>
                  <div className="animate-float">
                    <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-amber-400 to-orange-500 shadow-lg shadow-orange-200/50 flex items-center justify-center">
                      <Sparkles className="w-8 h-8 text-white" />
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Features strip */}
            <div className="flex flex-wrap gap-6 mt-8 pt-8 border-t border-gray-200/50">
              {FEATURES.map((f) => (
                <div key={f.title} className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-xl bg-violet-100 flex items-center justify-center">
                    <f.icon className="w-4.5 h-4.5 text-violet-600" />
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-gray-900">{f.title}</div>
                    <div className="text-xs text-gray-400">{f.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="px-6 lg:px-10">
        {/* Stats Grid */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {statCards.map((stat, i) => (
            <Card key={i} className="border-none shadow-sm hover:shadow-md transition-all duration-300 group cursor-default overflow-hidden">
              <CardContent className="p-5">
                <div className="flex items-center gap-3 mb-3">
                  <div className={`w-10 h-10 rounded-xl ${stat.bg} ring-1 ${stat.ring} flex items-center justify-center group-hover:scale-110 transition-transform duration-300`}>
                    <stat.icon className={`w-5 h-5 ${stat.color}`} />
                  </div>
                  <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">{stat.title}</span>
                </div>
                <div className="text-2xl font-bold text-gray-900">{stat.value}</div>
                <div className="text-xs text-gray-400 mt-1">{stat.subtitle}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        {error && (
          <div className="mb-6 rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">
            状态读取失败：{error}
          </div>
        )}

        {/* Quick Tools Grid */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-lg font-bold text-gray-900">智能工具</h2>
              <p className="text-xs text-gray-400 mt-0.5">选择工具开始工作</p>
            </div>
            <div className="flex items-center gap-1.5">
              <Badge variant="outline" className="text-[10px] rounded-full px-2 py-0.5 border-violet-200 text-violet-600 bg-violet-50">
                {QUICK_TOOLS.length} 个可用
              </Badge>
            </div>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {QUICK_TOOLS.map((tool) => (
              <Link key={tool.href} href={tool.href}>
                <Card className="border-none shadow-sm hover:shadow-lg hover:-translate-y-1 transition-all duration-300 group cursor-pointer overflow-hidden h-full">
                  <CardContent className="p-5 flex flex-col h-full">
                    <div className="flex items-start justify-between mb-4">
                      <div className={`w-11 h-11 rounded-xl bg-gradient-to-br ${tool.color} shadow-lg flex items-center justify-center group-hover:scale-110 transition-transform duration-300`}>
                        <tool.icon className="w-5 h-5 text-white" />
                      </div>
                      {tool.badge && (
                        <Badge className={`text-[10px] rounded-full px-2 py-0.5 ${
                          tool.badge === '热门' ? 'bg-red-50 text-red-600 border-red-200' :
                          tool.badge === '新' ? 'bg-violet-50 text-violet-600 border-violet-200' :
                          'bg-gray-50 text-gray-500 border-gray-200'
                        }`}>
                          {tool.badge}
                        </Badge>
                      )}
                    </div>
                    <h3 className="font-semibold text-sm text-gray-900 mb-1 group-hover:text-violet-700 transition-colors">{tool.label}</h3>
                    <p className="text-xs text-gray-400 flex-1">{tool.desc}</p>
                    <div className="flex items-center gap-1 mt-3 text-xs text-violet-500 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                      <span>立即使用</span>
                      <ArrowRight className="w-3 h-3" />
                    </div>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        </div>

        {/* System Overview Tabs */}
        <Card className="border-none shadow-sm mb-8 overflow-hidden">
          <Tabs defaultValue="overview" className="w-full">
            <div className="px-6 pt-5 pb-0">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold text-gray-900">系统监控</h2>
                <TabsList className="bg-gray-100/80 p-1 rounded-full border border-gray-200/50">
                  <TabsTrigger value="overview" className="rounded-full px-4 py-1.5 text-xs data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">架构总览</TabsTrigger>
                  <TabsTrigger value="sp3" className="rounded-full px-4 py-1.5 text-xs data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">AI Hub</TabsTrigger>
                  <TabsTrigger value="sp4" className="rounded-full px-4 py-1.5 text-xs data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">Knowledge</TabsTrigger>
                </TabsList>
              </div>
            </div>

            <TabsContent value="overview" className="px-6 pb-6 space-y-6 animate-in fade-in duration-500">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Architecture */}
                <div className="lg:col-span-2">
                  <div className="rounded-2xl bg-gradient-to-br from-gray-50 to-gray-100/50 border border-gray-100 p-6 relative overflow-x-auto overflow-y-hidden">
                    <div className="flex flex-row items-center justify-between gap-4 min-w-[600px]">
                      <ServiceNode icon={Newspaper} label="News" sublabel="采集与归档" gradient="from-blue-100 to-blue-50" iconColor="text-blue-600" />
                      <ConnectorLine label="/api/v1/news" />
                      <ServiceNode icon={BrainCircuit} label="AI Hub" sublabel="模型路由分发" gradient="from-violet-100 to-violet-50" iconColor="text-violet-600" />
                      <ConnectorLine label="/api/v1/ai" />
                      <ServiceNode icon={Database} label="Knowledge" sublabel="向量检索 + RAG" gradient="from-emerald-100 to-emerald-50" iconColor="text-emerald-600" />
                    </div>
                  </div>
                </div>

                {/* Activity feed */}
                <div>
                  <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-violet-500" />
                    服务动态
                  </h3>
                  <div className="space-y-4">
                    {activity.length === 0 ? (
                      <p className="text-sm text-gray-400 text-center py-6">暂无近期活动</p>
                    ) : activity.slice(0, 5).map((item) => {
                      const iconMap: Record<string, { icon: React.ElementType; bg: string; color: string }> = {
                        knowledge: { icon: Database, bg: 'bg-emerald-100', color: 'text-emerald-600' },
                        news: { icon: Newspaper, bg: 'bg-blue-100', color: 'text-blue-600' },
                        video: { icon: Clapperboard, bg: 'bg-pink-100', color: 'text-pink-600' },
                        livestream: { icon: Radio, bg: 'bg-orange-100', color: 'text-orange-600' },
                      }
                      const { icon: Icon, bg, color } = iconMap[item.source] ?? { icon: Activity, bg: 'bg-gray-100', color: 'text-gray-600' }
                      return (
                        <div key={item.id} className="flex items-start gap-3">
                          <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${bg}`}>
                            <Icon className={`w-4 h-4 ${color}`} />
                          </div>
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-gray-900 truncate">{item.title}</p>
                            <p className="text-xs text-gray-400">{timeAgo(item.time)}</p>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="sp3" className="px-6 pb-6">
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center shadow-lg shadow-purple-200/50">
                    <BrainCircuit className="w-7 h-7 text-white" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold text-gray-900">AI 模型网关</h3>
                    <p className="text-sm text-gray-500">OpenAI 标准协议的模型路由分发与故障降级处理</p>
                  </div>
                </div>
                <Link href="/models">
                  <Button className="w-fit mt-2 bg-gradient-to-r from-violet-600 to-purple-500 hover:from-violet-700 hover:to-purple-600 rounded-xl shadow-md">
                    前往模型配置中心 <ArrowRight className="w-4 h-4 ml-1" />
                  </Button>
                </Link>
              </div>
            </TabsContent>

            <TabsContent value="sp4" className="px-6 pb-6">
              <div className="flex flex-col gap-4">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-lg shadow-teal-200/50">
                    <Database className="w-7 h-7 text-white" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold text-gray-900">知识检索引擎</h3>
                    <p className="text-sm text-gray-500">pgvector 向量检索 + GraphRAG 增强实体关系分析</p>
                  </div>
                </div>
                <div className="flex gap-3 mt-2">
                  <Link href="/knowledge">
                    <Button className="bg-gradient-to-r from-emerald-600 to-teal-500 hover:from-emerald-700 hover:to-teal-600 rounded-xl shadow-md">
                      管理知识库
                    </Button>
                  </Link>
                  <Link href="/tasks">
                    <Button variant="outline" className="rounded-xl">查看任务队列</Button>
                  </Link>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </Card>
      </div>
    </div>
  )
}

function ServiceNode({ icon: Icon, label, sublabel, gradient, iconColor }: {
  icon: React.ElementType
  label: string
  sublabel: string
  gradient: string
  iconColor: string
}) {
  return (
    <div className={`bg-gradient-to-br ${gradient} p-5 rounded-2xl flex-1 text-center border border-white/50 shadow-sm hover:shadow-md transition-all duration-300`}>
      <div className={`mx-auto w-12 h-12 bg-white rounded-xl flex items-center justify-center mb-3 shadow-sm`}>
        <Icon className={`w-6 h-6 ${iconColor}`} />
      </div>
      <h4 className="font-semibold text-sm text-gray-900">{label}</h4>
      <p className="text-xs text-gray-500 mt-1">{sublabel}</p>
    </div>
  )
}

function ConnectorLine({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center shrink-0">
      <div className="h-0.5 w-12 lg:w-16 bg-gradient-to-r from-violet-200 to-purple-200 rounded-full" />
      <span className="text-[10px] text-gray-400 font-mono mt-1">{label}</span>
    </div>
  )
}
