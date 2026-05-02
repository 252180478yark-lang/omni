'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import Link from 'next/link'
import {
  MessageSquare,
  Database,
  Download,
  Clapperboard,
  Radio,
  LineChart,
  Palette,
  Newspaper,
  Cpu,
  ListTodo,
  ArrowRight,
  Sparkles,
  Search,
  HelpCircle,
  Rocket,
  CheckCircle2,
  type LucideIcon,
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

interface ToolCard {
  href: string
  icon: LucideIcon
  label: string
  desc: string
  scene: string
  color: string
  badge: string | null
}

const QUICK_TOOLS: ToolCard[] = [
  {
    href: '/chat',
    icon: MessageSquare,
    label: '智能问答',
    desc: '像微信一样和 AI 聊天',
    scene: '问问题、写文案、总结资料都能用',
    color: 'from-violet-500 to-purple-600',
    badge: '最常用',
  },
  {
    href: '/knowledge',
    icon: Database,
    label: '知识库',
    desc: '把你的资料存进来给 AI 看',
    scene: '存 PDF、Word、网页，AI 就能基于这些回答',
    color: 'from-emerald-500 to-teal-600',
    badge: null,
  },
  {
    href: '/knowledge/harvester',
    icon: Download,
    label: '知识采集',
    desc: '丢一个网址，自动抓回来存库',
    scene: '看到好文章，复制链接进去就行',
    color: 'from-blue-500 to-cyan-600',
    badge: null,
  },
  {
    href: '/video-analysis',
    icon: Clapperboard,
    label: '短视频分析',
    desc: '上传视频，AI 给你写报告',
    scene: '抖音爆款拖进去看为什么火',
    color: 'from-pink-500 to-rose-600',
    badge: null,
  },
  {
    href: '/livestream-analysis',
    icon: Radio,
    label: '直播分析',
    desc: '上传直播录屏自动复盘',
    scene: '看哪段话术效果好，输出 Excel',
    color: 'from-orange-500 to-amber-600',
    badge: null,
  },
  {
    href: '/ad-review',
    icon: LineChart,
    label: '投放复盘',
    desc: '分析广告数据钱花得值不值',
    scene: '巨量千川 CSV 拖进来即可',
    color: 'from-indigo-500 to-blue-600',
    badge: null,
  },
  {
    href: '/content-studio',
    icon: Palette,
    label: '内容工坊',
    desc: '一句话生成视频脚本+成片',
    scene: '"写条 30 秒口播"自动出片',
    color: 'from-fuchsia-500 to-pink-600',
    badge: '新',
  },
  {
    href: '/news',
    icon: Newspaper,
    label: '资讯中心',
    desc: '帮你抓全网行业新闻',
    scene: '每天 3 分钟刷完今天的事',
    color: 'from-sky-500 to-blue-600',
    badge: null,
  },
]

interface Step {
  num: number
  title: string
  desc: string
  href: string
}

const FIRST_STEPS: Step[] = [
  {
    num: 1,
    title: '配置 AI 账号',
    desc: '把你的 AI Key 填进去（只做一次）',
    href: '/models',
  },
  {
    num: 2,
    title: '试着聊一句',
    desc: '问 AI 一个问题，确认能正常对话',
    href: '/chat',
  },
  {
    num: 3,
    title: '建一个知识库',
    desc: '上传几份你常用的 PDF / Word',
    href: '/knowledge',
  },
  {
    num: 4,
    title: '让 AI 看着资料回答',
    desc: '回到聊天页选中知识库再提问',
    href: '/chat',
  },
]

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}

const ONBOARD_KEY = 'omni_homepage_onboard_done_v1'

export default function Home() {
  const [loading, setLoading] = useState(true)
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [activity, setActivity] = useState<ActivityItem[]>([])
  const [error, setError] = useState<string>('')
  const [showOnboard, setShowOnboard] = useState(false)

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setShowOnboard(window.localStorage.getItem(ONBOARD_KEY) !== '1')
    }
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

  const dismissOnboard = () => {
    setShowOnboard(false)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(ONBOARD_KEY, '1')
    }
  }

  const friendlyStats = useMemo(() => {
    const m = overview?.metrics
    return [
      {
        title: '今天用 AI 的字数',
        value: m?.aiTokenToday ? formatBig(m.aiTokenToday) : '0',
        hint: '把 AI 当成员工，今天它帮你处理的字数',
        color: 'bg-violet-50 ring-violet-100 text-violet-600',
      },
      {
        title: '知识库里的资料',
        value: `${m?.knowledgeDocuments ?? 0} 份`,
        hint: '你已经"喂"给 AI 多少份文件',
        color: 'bg-emerald-50 ring-emerald-100 text-emerald-600',
      },
      {
        title: '系统健康度',
        value: `${m?.infraUptime ?? 0}%`,
        hint: '后台各项服务是不是正常工作',
        color: 'bg-amber-50 ring-amber-100 text-amber-600',
      },
      {
        title: '正在干的活',
        value: `${m?.runningTasks ?? 0} 个`,
        hint: '后台正在跑的任务（抓网页 / 分析视频等）',
        color: 'bg-blue-50 ring-blue-100 text-blue-600',
      },
    ]
  }, [overview])

  const healthy = overview?.health && Object.values(overview.health).every((s) => s === 'healthy')

  return (
    <div className="min-h-screen pb-20">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-b-3xl mb-6">
        <div className="hero-pattern">
          <div className="relative px-6 lg:px-10 pt-8 pb-10">
            {/* Status bar */}
            <div className="flex items-center justify-between mb-8 flex-wrap gap-3">
              <Badge className="bg-white text-gray-700 border-gray-200 hover:bg-white rounded-full px-3 py-1 text-xs font-medium shadow-sm">
                <div
                  className={`w-2 h-2 rounded-full mr-2 ${
                    healthy ? 'bg-emerald-500 animate-pulse' : loading ? 'bg-amber-400 animate-pulse' : 'bg-red-500'
                  }`}
                />
                {healthy ? '系统就绪，可以开始用了' : loading ? '正在检查系统...' : '部分功能可能用不了，请看下方提示'}
              </Badge>
              <div className="flex items-center gap-2">
                <Link href="/models">
                  <Button variant="ghost" size="sm" className="text-gray-500 hover:text-gray-900 rounded-full text-xs gap-1.5">
                    <Cpu className="w-3.5 h-3.5" />
                    AI 账号配置
                  </Button>
                </Link>
                <Link href="/tasks">
                  <Button variant="ghost" size="sm" className="text-gray-500 hover:text-gray-900 rounded-full text-xs gap-1.5">
                    <ListTodo className="w-3.5 h-3.5" />
                    后台任务
                  </Button>
                </Link>
              </div>
            </div>

            {/* Hero content */}
            <div className="flex flex-col lg:flex-row items-start gap-8 lg:gap-12">
              <div className="flex-1 min-w-0">
                <h1 className="text-3xl lg:text-4xl font-bold tracking-tight text-gray-900 mb-3">
                  你的 AI 万能小助理
                </h1>
                <p className="text-gray-500 text-base lg:text-lg mb-5 max-w-2xl leading-relaxed">
                  把工作里要看的资料、要分析的视频、要回的问题、要投的广告数据都丢给它——它都能帮你做完。
                  <span className="text-gray-400 text-sm block mt-1">
                    不需要懂技术，不需要写代码，会用微信就会用它。
                  </span>
                </p>

                <Link href="/chat" className="block max-w-xl">
                  <div className="flex items-center gap-3 px-5 py-3.5 bg-white rounded-2xl border border-gray-200/80 shadow-sm hover:shadow-md hover:border-violet-200 transition-all duration-300 cursor-pointer group">
                    <Search className="w-5 h-5 text-gray-300 group-hover:text-violet-400 transition-colors" />
                    <span className="text-gray-400 text-sm flex-1">想问 AI 什么？比如"帮我写一段产品介绍"...</span>
                    <div className="px-3 py-1.5 rounded-xl bg-gradient-to-r from-violet-600 to-purple-500 text-white text-xs font-medium shadow-sm whitespace-nowrap">
                      开始聊天
                    </div>
                  </div>
                </Link>

                <p className="text-xs text-gray-400 mt-3">
                  💡 第一次用？右下角紫色「<span className="text-violet-600 font-medium">新手指南</span>」按钮里有完整的 3 分钟入门讲解
                </p>
              </div>

              {/* Decorative */}
              <div className="hidden lg:flex items-center gap-4 shrink-0">
                <div className="animate-float">
                  <div className="w-28 h-28 rounded-2xl bg-gradient-to-br from-violet-500 to-purple-600 shadow-xl shadow-purple-200/50 flex items-center justify-center">
                    <Sparkles className="w-12 h-12 text-white" />
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
                      <Clapperboard className="w-8 h-8 text-white" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="px-6 lg:px-10">
        {/* Onboarding panel - shown until user dismisses */}
        {showOnboard && (
          <Card className="border-none shadow-md mb-6 overflow-hidden bg-gradient-to-br from-violet-50 via-purple-50/40 to-pink-50/30">
            <CardContent className="p-6">
              <div className="flex items-start justify-between gap-4 mb-5">
                <div className="flex items-center gap-3">
                  <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-violet-600 to-purple-500 flex items-center justify-center shadow-lg shadow-purple-200/50">
                    <Rocket className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold text-gray-900">第一次用？跟着这 4 步走一遍</h2>
                    <p className="text-xs text-gray-500 mt-0.5">10 分钟内就能完整体验，每个步骤都可以直接点进去</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={dismissOnboard}
                  className="text-xs text-gray-400 hover:text-gray-700 transition-colors px-2 py-1 rounded-md hover:bg-white/60"
                >
                  我已熟悉，关掉它
                </button>
              </div>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {FIRST_STEPS.map((s, i) => (
                  <Link key={s.num} href={s.href}>
                    <div className="group relative h-full bg-white rounded-2xl p-4 border border-violet-100/60 hover:border-violet-300 hover:shadow-md transition-all">
                      <div className="flex items-center gap-2 mb-2">
                        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-violet-600 to-purple-500 text-white flex items-center justify-center text-xs font-bold shrink-0">
                          {s.num}
                        </div>
                        {i < FIRST_STEPS.length - 1 && (
                          <ArrowRight className="w-3 h-3 text-violet-300" />
                        )}
                      </div>
                      <h4 className="font-semibold text-sm text-gray-900 mb-1">{s.title}</h4>
                      <p className="text-xs text-gray-500 leading-relaxed">{s.desc}</p>
                      <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity">
                        <ArrowRight className="w-4 h-4 text-violet-500" />
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Friendly Stats */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {friendlyStats.map((stat, i) => (
            <Card key={i} className="border-none shadow-sm hover:shadow-md transition-all duration-300 group cursor-default overflow-hidden">
              <CardContent className="p-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-medium text-gray-500">{stat.title}</span>
                  <div className="relative group/tip">
                    <HelpCircle className="w-3.5 h-3.5 text-gray-300 hover:text-violet-500 cursor-help transition-colors" />
                    <div className="absolute right-0 top-full mt-1.5 px-2.5 py-1.5 rounded-lg bg-gray-900 text-white text-[11px] whitespace-nowrap opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-all pointer-events-none shadow-lg z-30 max-w-[220px] whitespace-normal w-max">
                      {stat.hint}
                    </div>
                  </div>
                </div>
                <div className="text-2xl font-bold text-gray-900">{stat.value}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        {error && (
          <div className="mb-6 rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">
            <span className="font-medium">系统状态读不出来：</span>{error}
            <div className="text-xs text-red-500 mt-1">
              通常是后台服务还没启动。如果你是开发者，请确认运行了 <code className="bg-white/60 px-1.5 py-0.5 rounded">.\dev-start.ps1</code> 或者 docker compose 容器都起来了。
            </div>
          </div>
        )}

        {/* Tool cards */}
        <div className="mb-8">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-bold text-gray-900">我能用它做什么？</h2>
              <p className="text-xs text-gray-500 mt-0.5">点开任意卡片即可开始使用，每张卡都有"做什么用"和"什么场景适合"</p>
            </div>
            <Badge variant="outline" className="text-[10px] rounded-full px-2 py-0.5 border-violet-200 text-violet-600 bg-violet-50">
              共 {QUICK_TOOLS.length} 个功能
            </Badge>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {QUICK_TOOLS.map((tool) => (
              <Link key={tool.href} href={tool.href}>
                <Card className="border-none shadow-sm hover:shadow-lg hover:-translate-y-1 transition-all duration-300 group cursor-pointer overflow-hidden h-full">
                  <CardContent className="p-5 flex flex-col h-full">
                    <div className="flex items-start justify-between mb-3">
                      <div className={`w-11 h-11 rounded-xl bg-gradient-to-br ${tool.color} shadow-lg flex items-center justify-center group-hover:scale-110 transition-transform duration-300`}>
                        <tool.icon className="w-5 h-5 text-white" />
                      </div>
                      {tool.badge && (
                        <Badge className={`text-[10px] rounded-full px-2 py-0.5 ${
                          tool.badge === '最常用' ? 'bg-red-50 text-red-600 border-red-200' :
                          tool.badge === '新' ? 'bg-violet-50 text-violet-600 border-violet-200' :
                          'bg-gray-50 text-gray-500 border-gray-200'
                        }`}>
                          {tool.badge}
                        </Badge>
                      )}
                    </div>
                    <h3 className="font-semibold text-sm text-gray-900 mb-1.5 group-hover:text-violet-700 transition-colors">{tool.label}</h3>
                    <p className="text-xs text-gray-600 leading-relaxed mb-2">{tool.desc}</p>
                    <p className="text-[11px] text-gray-400 leading-relaxed flex-1 italic">
                      💡 {tool.scene}
                    </p>
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

        {/* Use cases / scenarios */}
        <div className="mb-8">
          <div className="mb-4">
            <h2 className="text-lg font-bold text-gray-900">看看别人都怎么用</h2>
            <p className="text-xs text-gray-500 mt-0.5">不知道从哪里开始？选一个最像你的场景，按推荐组合用</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <ScenarioCard
              title="我是电商运营"
              desc="复盘广告 + 抄爆款 + 出新素材"
              flow={[
                { tool: '投放复盘', href: '/ad-review', tip: '把千川数据丢进去' },
                { tool: '短视频分析', href: '/video-analysis', tip: '把竞品爆款丢进去' },
                { tool: '内容工坊', href: '/content-studio', tip: '生成自家新素材' },
              ]}
              color="from-pink-500 to-rose-600"
            />
            <ScenarioCard
              title="我是内容创作者"
              desc="抄爆款 + 写脚本 + 拍直播复盘"
              flow={[
                { tool: '短视频分析', href: '/video-analysis', tip: '研究爆款套路' },
                { tool: '内容工坊', href: '/content-studio', tip: '一键出脚本和成片' },
                { tool: '直播分析', href: '/livestream-analysis', tip: '复盘直播话术' },
              ]}
              color="from-fuchsia-500 to-pink-600"
            />
            <ScenarioCard
              title="我只是想用 AI 帮我读资料"
              desc="把资料喂给 AI，问什么答什么"
              flow={[
                { tool: '知识采集', href: '/knowledge/harvester', tip: '一键抓网页/飞书' },
                { tool: '知识库', href: '/knowledge', tip: '上传 PDF / Word' },
                { tool: '智能问答', href: '/chat', tip: '选中知识库再提问' },
              ]}
              color="from-emerald-500 to-teal-600"
            />
          </div>
        </div>

        {/* Recent activity */}
        {activity.length > 0 && (
          <Card className="border-none shadow-sm mb-8">
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-lg font-bold text-gray-900">系统最近在忙什么</h2>
                  <p className="text-xs text-gray-500 mt-0.5">显示最近后台跑的任务（抓网页、分析视频之类）</p>
                </div>
                <Link href="/tasks">
                  <Button variant="ghost" size="sm" className="text-xs rounded-full text-gray-500 hover:text-violet-600">
                    看全部任务 <ArrowRight className="w-3 h-3 ml-1" />
                  </Button>
                </Link>
              </div>
              <div className="space-y-3">
                {activity.slice(0, 6).map((item) => {
                  const iconMap: Record<string, { icon: LucideIcon; bg: string; color: string; tag: string }> = {
                    knowledge: { icon: Database, bg: 'bg-emerald-100', color: 'text-emerald-600', tag: '知识库' },
                    news: { icon: Newspaper, bg: 'bg-blue-100', color: 'text-blue-600', tag: '资讯' },
                    video: { icon: Clapperboard, bg: 'bg-pink-100', color: 'text-pink-600', tag: '视频' },
                    livestream: { icon: Radio, bg: 'bg-orange-100', color: 'text-orange-600', tag: '直播' },
                  }
                  const meta = iconMap[item.source] ?? { icon: CheckCircle2, bg: 'bg-gray-100', color: 'text-gray-600', tag: '其他' }
                  const Icon = meta.icon
                  return (
                    <div key={item.id} className="flex items-center gap-3 py-1.5">
                      <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${meta.bg}`}>
                        <Icon className={`w-4 h-4 ${meta.color}`} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-900 truncate">{item.title}</p>
                        <div className="flex items-center gap-2 mt-0.5">
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0 rounded-full border-gray-200 text-gray-500">
                            {meta.tag}
                          </Badge>
                          <span className="text-xs text-gray-400">{timeAgo(item.time)}</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Bottom CTA */}
        <Card className="border-none shadow-sm overflow-hidden bg-gradient-to-br from-violet-600 to-purple-600">
          <CardContent className="p-7 lg:p-8">
            <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-5">
              <div className="text-white">
                <h3 className="text-xl font-bold mb-1.5">还是不知道怎么开始？</h3>
                <p className="text-sm text-violet-100 leading-relaxed max-w-xl">
                  点页面右下角紫色「新手指南」按钮，里面有 3 分钟讲清楚：它是什么、能干什么、第一步该做什么、常见疑问都怎么解决。
                </p>
              </div>
              <Link href="/chat">
                <Button className="bg-white text-violet-700 hover:bg-violet-50 rounded-full px-6 shadow-md whitespace-nowrap">
                  直接开始聊天 <ArrowRight className="w-4 h-4 ml-1" />
                </Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function formatBig(n: number): string {
  if (n >= 100000) return `${(n / 10000).toFixed(1)} 万`
  if (n >= 10000) return `${(n / 10000).toFixed(2)} 万`
  return n.toLocaleString('zh-CN')
}

function ScenarioCard({
  title,
  desc,
  flow,
  color,
}: {
  title: string
  desc: string
  flow: { tool: string; href: string; tip: string }[]
  color: string
}) {
  return (
    <Card className="border-none shadow-sm hover:shadow-md transition-all duration-300 overflow-hidden h-full">
      <CardContent className="p-5">
        <div className={`inline-block px-3 py-1 rounded-full bg-gradient-to-r ${color} text-white text-xs font-medium mb-3`}>
          {title}
        </div>
        <p className="text-sm text-gray-600 leading-relaxed mb-4">{desc}</p>
        <div className="space-y-2">
          {flow.map((step, i) => (
            <Link key={i} href={step.href} className="block group">
              <div className="flex items-center gap-2.5 px-3 py-2 rounded-xl bg-gray-50 hover:bg-violet-50 transition-colors">
                <div className="w-5 h-5 rounded-full bg-white text-gray-500 group-hover:text-violet-600 flex items-center justify-center text-[10px] font-bold shrink-0 shadow-sm">
                  {i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold text-gray-900 group-hover:text-violet-700 transition-colors">{step.tool}</div>
                  <div className="text-[11px] text-gray-400 truncate">{step.tip}</div>
                </div>
                <ArrowRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-violet-500 group-hover:translate-x-0.5 transition-all shrink-0" />
              </div>
            </Link>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
