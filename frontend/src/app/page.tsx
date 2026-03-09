import React from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import Link from 'next/link';
import { 
  Activity, 
  Cpu, 
  BrainCircuit, 
  TrendingUp, 
  Users, 
  ShoppingCart,
  Settings,
  MessageSquare
} from 'lucide-react';

export default function Home() {
  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      {/* Apple-style Top Navigation (Glassmorphism) */}
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-600 to-purple-500 flex items-center justify-center shadow-md">
                <BrainCircuit className="w-5 h-5 text-white" />
              </div>
              <span className="font-semibold text-lg tracking-tight">Omni-Vibe OS <span className="text-gray-400">Ultra</span></span>
            </div>
            <div className="flex items-center gap-4">
              <Link href="/tri-mind">
                <Button variant="default" className="rounded-full bg-gradient-to-r from-blue-600 to-purple-500 hover:from-blue-700 hover:to-purple-600 text-white shadow-md">
                  <MessageSquare className="w-4 h-4 mr-2" />
                  Tri-Mind 辩论
                </Button>
              </Link>
              <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 shadow-sm rounded-full px-3">
                <div className="w-2 h-2 rounded-full bg-green-500 mr-2 animate-pulse"></div>
                运行中
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
            控制台
          </h1>
          <p className="text-gray-500 text-lg">
            欢迎回来。您的混合架构智能系统运行状况良好。
          </p>
          <Link href="/tri-mind" className="inline-flex items-center gap-2 mt-4 text-blue-600 hover:text-blue-700 font-medium">
            <MessageSquare className="w-4 h-4" />
            进入 Tri-Mind 多模型辩论 →
          </Link>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
          {[
            { title: "全域情报 (Market Intelligence)", value: "98.2%", subtitle: "分析准确率", icon: TrendingUp, color: "text-blue-500", bg: "bg-blue-50" },
            { title: "内容工厂 (Content Factory)", value: "1,204", subtitle: "已生成素材", icon: BrainCircuit, color: "text-purple-500", bg: "bg-purple-50" },
            { title: "活跃机器人 (Active Bots)", value: "14", subtitle: "RPA & 微信私域", icon: Activity, color: "text-green-500", bg: "bg-green-50" },
            { title: "本地算力 (Local GPU)", value: "RTX 5070", subtitle: "当前负载: 45%", icon: Cpu, color: "text-orange-500", bg: "bg-orange-50" }
          ].map((stat, i) => (
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

        {/* Main Content Tabs */}
        <div className="apple-card p-2 md:p-6 mb-8">
          <Tabs defaultValue="overview" className="w-full">
            <div className="flex justify-center mb-8">
              <TabsList className="bg-gray-100/80 p-1 rounded-full border border-gray-200/50 shadow-inner">
                <TabsTrigger value="overview" className="rounded-full px-6 py-2 data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">系统总览</TabsTrigger>
                <TabsTrigger value="market" className="rounded-full px-6 py-2 data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">全域情报</TabsTrigger>
                <TabsTrigger value="content" className="rounded-full px-6 py-2 data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">内容工厂</TabsTrigger>
                <TabsTrigger value="learning" className="rounded-full px-6 py-2 data-[state=active]:bg-white data-[state=active]:shadow-sm transition-all">主动学习</TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="overview" className="space-y-6 animate-in fade-in duration-500">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Left Column: Activity */}
                <Card className="lg:col-span-2 apple-card border-none">
                  <CardHeader>
                    <CardTitle className="text-xl font-semibold">系统架构状态</CardTitle>
                    <CardDescription>混合计算与智能体工作流执行情况</CardDescription>
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
                             <h4 className="font-medium text-sm">Next.js 控制台</h4>
                             <p className="text-xs text-gray-500 mt-1">前端与交互中心</p>
                          </div>
                          <div className="flex flex-col items-center shrink-0">
                             <div className="h-0.5 w-12 lg:w-16 bg-gradient-to-r from-blue-200 to-purple-200"></div>
                             <span className="text-[10px] text-gray-400 font-mono mt-1">API</span>
                          </div>
                          <div className="glass border-purple-200 p-4 rounded-2xl flex-1 text-center shadow-md">
                             <div className="mx-auto w-12 h-12 bg-purple-100 text-purple-600 rounded-full flex items-center justify-center mb-3">
                               <BrainCircuit className="w-6 h-6" />
                             </div>
                             <h4 className="font-medium text-sm">LangGraph 控制器</h4>
                             <p className="text-xs text-gray-500 mt-1">思考环 (Thinking Loop)</p>
                          </div>
                          <div className="flex flex-col items-center shrink-0">
                             <div className="h-0.5 w-12 lg:w-16 bg-gradient-to-r from-purple-200 to-orange-200"></div>
                             <span className="text-[10px] text-gray-400 font-mono mt-1">EXEC</span>
                          </div>
                          <div className="glass border-orange-200 p-4 rounded-2xl flex-1 text-center shadow-md">
                             <div className="mx-auto w-12 h-12 bg-orange-100 text-orange-600 rounded-full flex items-center justify-center mb-3">
                               <Cpu className="w-6 h-6" />
                             </div>
                             <h4 className="font-medium text-sm">本地 GPU / ComfyUI</h4>
                             <p className="text-xs text-gray-500 mt-1">执行环 (Execution Loop)</p>
                          </div>
                       </div>
                    </div>
                  </CardContent>
                </Card>

                {/* Right Column: Recent Actions */}
                <Card className="apple-card border-none">
                  <CardHeader>
                    <CardTitle className="text-xl font-semibold">近期动作</CardTitle>
                    <CardDescription>最新的智能体执行记录</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-6">
                      {[
                        { title: "竞品价格已自动调整", time: "10 分钟前", icon: ShoppingCart, bg: "bg-blue-100", color: "text-blue-600" },
                        { title: "内容工厂生成 5 张商品图", time: "1 小时前", icon: BrainCircuit, bg: "bg-purple-100", color: "text-purple-600" },
                        { title: "GraphRAG 深度洞察已更新", time: "3 小时前", icon: Activity, bg: "bg-green-100", color: "text-green-600" },
                        { title: "完成夜间 LLaMA 微调任务", time: "12 小时前", icon: Cpu, bg: "bg-orange-100", color: "text-orange-600" },
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
            
            <TabsContent value="market" className="p-8 text-center text-gray-500">全域情报模块 (开发中)</TabsContent>
            <TabsContent value="content" className="p-8 text-center text-gray-500">内容工厂模块 (开发中)</TabsContent>
            <TabsContent value="learning" className="p-8 text-center text-gray-500">主动学习模块 (开发中)</TabsContent>
          </Tabs>
        </div>

        {/* Tri-Mind 入口 */}
        <Link href="/tri-mind">
          <Card className="apple-card border-none hover:shadow-[0_8px_30px_rgb(0,0,0,0.08)] transition-all duration-300 cursor-pointer group">
            <CardContent className="p-6">
              <div className="flex items-center gap-4">
                <div className="p-3 rounded-2xl bg-gradient-to-tr from-blue-500 to-purple-500 group-hover:scale-105 transition-transform">
                  <MessageSquare className="w-8 h-8 text-white" />
                </div>
                <div>
                  <h3 className="text-xl font-semibold text-gray-900">Tri-Mind 多模型辩论</h3>
                  <p className="text-sm text-gray-500 mt-1">让多个 AI 模型针对同一问题进行并发对比、交叉质疑与综合裁决</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </Link>
      </main>
    </div>
  );
}
