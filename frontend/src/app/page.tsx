 'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import Link from 'next/link';
import { 
  Activity, 
  Cpu, 
  BrainCircuit, 
  Users, 
  Settings,
  MessageSquare,
  Database,
  Network,
  ListTodo,
  Newspaper
} from 'lucide-react';

type HealthState = 'healthy' | 'down'

interface OverviewData {
  health: {
    identity: HealthState
    aiHub: HealthState
    knowledge: HealthState
  }
  metrics: {
    identityUsers: number
    aiTokenToday: number
    knowledgeDocuments: number
    infraUptime: number
    knowledgeBases: number
    runningTasks: number
  }
}

export default function Home() {
  const [loading, setLoading] = useState(true)
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [error, setError] = useState<string>('')

  useEffect(() => {
    const run = async () => {
      setLoading(true)
      setError('')
      try {
        const res = await fetch('/api/omni/overview', { cache: 'no-store' })
        const json = (await res.json()) as { success: boolean; data?: OverviewData; error?: string }
        if (!json.success || !json.data) {
          throw new Error(json.error || '加载失败')
        }
        setOverview(json.data)
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
      { title: "身份服务 (SP2)", value: metrics?.identityUsers ?? 0, subtitle: "已注册用户总数", icon: Users, color: "text-blue-500", bg: "bg-blue-50" },
      { title: "AI 网关 (SP3)", value: metrics?.aiTokenToday ?? 0, subtitle: "今日 Token 消耗", icon: BrainCircuit, color: "text-purple-500", bg: "bg-purple-50" },
      { title: "知识引擎 (SP4)", value: metrics?.knowledgeDocuments ?? 0, subtitle: "已入库文档总数", icon: Database, color: "text-green-500", bg: "bg-green-50" },
      { title: "基础设施 (SP1)", value: `${metrics?.infraUptime ?? 0}%`, subtitle: "数据库及 Redis 连通率", icon: Network, color: "text-orange-500", bg: "bg-orange-50" },
    ]
  }, [overview])

  const healthy = overview?.health && Object.values(overview.health).every((s) => s === 'healthy')

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      {/* Apple-style Top Navigation (Glassmorphism) */}
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-6">
              <Link href="/" className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-600 to-purple-500 flex items-center justify-center shadow-md">
                  <BrainCircuit className="w-5 h-5 text-white" />
                </div>
                <span className="font-semibold text-lg tracking-tight">Omni-Vibe OS <span className="text-gray-400">Console</span></span>
              </Link>
              <div className="hidden md:flex items-center gap-4 ml-8">
                <Link href="/news" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors flex items-center gap-1">
                  <Newspaper className="w-4 h-4" /> 资讯中心
                </Link>
                <Link href="/models" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors flex items-center gap-1">
                  <Cpu className="w-4 h-4" /> 模型配置
                </Link>
                <Link href="/knowledge" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors flex items-center gap-1">
                  <Database className="w-4 h-4" /> 知识库管理
                </Link>
                <Link href="/tasks" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors flex items-center gap-1">
                  <ListTodo className="w-4 h-4" /> 任务进度
                </Link>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <Link href="/tri-mind">
                <Button variant="default" className="rounded-full bg-gradient-to-r from-blue-600 to-purple-500 hover:from-blue-700 hover:to-purple-600 text-white shadow-md">
                  <MessageSquare className="w-4 h-4 mr-2" />
                  Tri-Mind 辩论
                </Button>
              </Link>
              <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 shadow-sm rounded-full px-3">
                <div className={`w-2 h-2 rounded-full mr-2 ${healthy ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`}></div>
                {healthy ? '系统正常' : '部分服务异常'}
              </Badge>
              <Button variant="ghost" size="icon" className="rounded-full">
                <Settings className="w-5 h-5 text-gray-500" />
              </Button>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
        {/* Header Section */}
        <div className="mb-10">
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight text-gray-900 mb-3">
            系统控制台
          </h1>
          <p className="text-gray-500 text-lg">
            {loading ? '正在加载服务状态...' : error ? '无法读取系统状态，请检查后端服务。' : '欢迎回来。您的多层架构系统已成功启动，正在运行中。'}
          </p>
        </div>

        {/* SP1-SP4 Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
          {statCards.map((stat, i) => (
            <Card key={i} className="apple-card border-none hover:shadow-[0_8px_30px_rgb(0,0,0,0.08)] transition-all duration-300">
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <div className={`p-3 rounded-2xl ${stat.bg}`}>
                    <stat.icon className={`w-6 h-6 ${stat.color}`} />
                  </div>
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-500">{stat.title}</p>
                  <h3 className="text-2xl font-bold text-gray-900 mt-1">{stat.value}</h3>
                  {stat.subtitle && <p className="text-xs text-gray-400 mt-1">{stat.subtitle}</p>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
        {error ? (
          <div className="mb-8 rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">
            状态读取失败：{error}
          </div>
        ) : null}

        {/* Main Content Tabs */}
        <div className="apple-card p-2 md:p-6 mb-8">
          <Tabs defaultValue="overview" className="w-full">
            <div className="flex justify-center mb-8">
              <TabsList className="bg-gray-100/80 p-1 rounded-full border border-gray-200/50 shadow-inner">
                <TabsTrigger value="overview" className="rounded-full px-6 py-2 data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">架构监控</TabsTrigger>
                <TabsTrigger value="sp2" className="rounded-full px-6 py-2 data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">Identity (SP2)</TabsTrigger>
                <TabsTrigger value="sp3" className="rounded-full px-6 py-2 data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">AI Hub (SP3)</TabsTrigger>
                <TabsTrigger value="sp4" className="rounded-full px-6 py-2 data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">Knowledge (SP4)</TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="overview" className="space-y-6 animate-in fade-in duration-500">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Left Column: Activity */}
                <Card className="lg:col-span-2 apple-card border-none">
                  <CardHeader>
                    <CardTitle className="text-xl font-semibold">系统架构链路</CardTitle>
                    <CardDescription>当前微服务间调用请求与依赖状态</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="h-[300px] w-full rounded-2xl bg-gray-50 border border-gray-100 p-6 relative overflow-x-auto overflow-y-hidden flex items-center justify-start md:justify-center">
                       <div className="absolute inset-0 bg-grid-gray-900/[0.04] bg-[size:20px_20px]"></div>
                       {/* Mock Diagram */}
                       <div className="relative z-10 flex flex-row items-center justify-between h-full gap-4 min-w-[700px] md:min-w-full">
                          <div className="glass p-4 rounded-2xl flex-1 text-center shadow-md">
                             <div className="mx-auto w-12 h-12 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center mb-3">
                               <Users className="w-6 h-6" />
                             </div>
                             <h4 className="font-medium text-sm">Identity Service</h4>
                             <p className="text-xs text-gray-500 mt-1">JWT Auth & RBAC</p>
                          </div>
                          <div className="flex flex-col items-center shrink-0">
                             <div className="h-0.5 w-12 lg:w-16 bg-gradient-to-r from-blue-200 to-purple-200"></div>
                             <span className="text-[10px] text-gray-400 font-mono mt-1">/api/v1/auth</span>
                          </div>
                          <div className="glass border-purple-200 p-4 rounded-2xl flex-1 text-center shadow-md">
                             <div className="mx-auto w-12 h-12 bg-purple-100 text-purple-600 rounded-full flex items-center justify-center mb-3">
                               <BrainCircuit className="w-6 h-6" />
                             </div>
                             <h4 className="font-medium text-sm">AI Provider Hub</h4>
                             <p className="text-xs text-gray-500 mt-1">OpenAI Compatible API</p>
                          </div>
                          <div className="flex flex-col items-center shrink-0">
                             <div className="h-0.5 w-12 lg:w-16 bg-gradient-to-r from-purple-200 to-orange-200"></div>
                             <span className="text-[10px] text-gray-400 font-mono mt-1">/api/v1/ai</span>
                          </div>
                          <div className="glass border-orange-200 p-4 rounded-2xl flex-1 text-center shadow-md">
                             <div className="mx-auto w-12 h-12 bg-orange-100 text-orange-600 rounded-full flex items-center justify-center mb-3">
                               <Database className="w-6 h-6" />
                             </div>
                             <h4 className="font-medium text-sm">Knowledge Engine</h4>
                             <p className="text-xs text-gray-500 mt-1">pgvector + GraphRAG</p>
                          </div>
                       </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Right Column: Recent Actions */}
                <Card className="apple-card border-none">
                  <CardHeader>
                    <CardTitle className="text-xl font-semibold">服务动态</CardTitle>
                    <CardDescription>各模块最新的事件日志</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-6">
                      {[
                        { title: "新用户注册 (id: 4a2b)", time: "5 分钟前", icon: Users, bg: "bg-blue-100", color: "text-blue-600" },
                        { title: "模型配置切换为 gpt-4o", time: "15 分钟前", icon: Cpu, bg: "bg-purple-100", color: "text-purple-600" },
                        { title: "文档入库任务完成 (doc_041)", time: "1 小时前", icon: Database, bg: "bg-green-100", color: "text-green-600" },
                        { title: "Redis 缓存全量刷新", time: "2 小时前", icon: Network, bg: "bg-orange-100", color: "text-orange-600" },
                      ].map((item, i) => (
                        <div key={i} className="flex items-start gap-4">
                          <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${item.bg}`}>
                            <item.icon className={`w-5 h-5 ${item.color}`} />
                          </div>
                          <div>
                            <p className="text-sm font-medium text-gray-900">{item.title}</p>
                            <p className="text-xs text-gray-500">{item.time}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </div>
            </TabsContent>
            
            <TabsContent value="sp2" className="p-8">
              <div className="flex flex-col gap-4">
                <h3 className="text-2xl font-semibold mb-2">身份鉴权服务 (Identity Service)</h3>
                <p className="text-gray-500 mb-6">提供 JWT 无状态认证与基于角色的访问控制。全网关统一认证入口。</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="p-4 rounded-xl border border-gray-200 bg-white">
                    <h4 className="font-semibold text-lg text-gray-800 mb-2">端点连通性测试</h4>
                    <pre className="bg-gray-900 text-green-400 p-3 rounded-lg text-sm overflow-x-auto">
                      GET /api/v1/auth/me HTTP/1.1{'\n'}
                      Authorization: Bearer eyJhb...{'\n'}
                      {'\n'}
                      200 OK{'\n'}
                      {'{"id": "usr_99x", "role": "admin"}'}
                    </pre>
                  </div>
                  <div className="p-4 rounded-xl border border-gray-200 bg-white flex items-center justify-center flex-col">
                    <Activity className="w-10 h-10 text-blue-500 mb-3" />
                    <span className="text-xl font-bold">140 QPS</span>
                    <span className="text-sm text-gray-500">当前并发鉴权请求</span>
                  </div>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="sp3" className="p-8">
              <div className="flex flex-col gap-4">
                <h3 className="text-2xl font-semibold mb-2">AI 模型网关 (Provider Hub)</h3>
                <p className="text-gray-500 mb-6">提供 OpenAI 标准协议的模型路由分发与故障降级处理。</p>
                <Link href="/models">
                  <Button className="w-fit">前往模型配置中心 →</Button>
                </Link>
              </div>
            </TabsContent>

            <TabsContent value="sp4" className="p-8">
              <div className="flex flex-col gap-4">
                <h3 className="text-2xl font-semibold mb-2">知识检索引擎 (Knowledge Engine)</h3>
                <p className="text-gray-500 mb-6">基于 pgvector 的向量检索，结合 GraphRAG 增强实体关系分析。</p>
                <div className="flex gap-4">
                  <Link href="/knowledge">
                    <Button variant="default">管理知识库</Button>
                  </Link>
                  <Link href="/tasks">
                    <Button variant="outline">查看入库异步任务</Button>
                  </Link>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </main>
    </div>
  );
}
