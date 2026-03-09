'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'
import { BrainCircuit, Settings2, Save, Key, Cpu, Sparkles } from 'lucide-react'

interface ProviderItem {
  id: string
  name: string
  status: string
  capabilities: string[]
  defaultChatModel: string | null
  defaultEmbeddingModel: string | null
  models: string[]
}

export default function ModelsConfig() {
  const [activeProvider, setActiveProvider] = useState('')
  const [providers, setProviders] = useState<ProviderItem[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    const run = async () => {
      setError('')
      try {
        const res = await fetch('/api/omni/models', { cache: 'no-store' })
        const json = (await res.json()) as { success: boolean; data?: { providers: ProviderItem[] }; error?: string }
        if (!json.success || !json.data) {
          throw new Error(json.error || '加载模型配置失败')
        }
        setProviders(json.data.providers)
        if (json.data.providers.length > 0) {
          setActiveProvider(json.data.providers[0].id)
        }
      } catch (err) {
        setError(String(err))
      }
    }
    void run()
  }, [])

  const active = useMemo(() => providers.find((p) => p.id === activeProvider), [providers, activeProvider])

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-4">
              <Link href="/" className="font-semibold text-lg text-gray-500 hover:text-gray-900 transition-colors">
                ← 返回控制台
              </Link>
            </div>
            <div className="font-semibold text-lg text-gray-900 flex items-center gap-2">
              <Cpu className="w-5 h-5 text-purple-600" />
              模型提供商配置 (AI Hub)
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 pt-10">
        <div className="mb-8 flex justify-between items-end">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-gray-900 mb-2">模型配置中心</h1>
            <p className="text-gray-500">管理多个 AI Provider 以及底层模型调用策略与降级顺序。</p>
          </div>
          <Button className="bg-purple-600 hover:bg-purple-700" disabled>
            <Save className="w-4 h-4 mr-2" />
            配置由环境变量管理
          </Button>
        </div>

        <Card className="apple-card mb-8 border-none shadow-sm">
          <CardHeader>
            <CardTitle className="text-xl flex items-center gap-2">
              <Settings2 className="w-5 h-5 text-gray-500" />
              全局路由策略 (Fallback Chain)
            </CardTitle>
            <CardDescription>配置默认模型与出现故障时的自动切换顺序</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <label className="text-sm font-medium text-gray-700">默认对话模型 (Default Chat)</label>
                <select className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500">
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} - {p.defaultChatModel || 'N/A'}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium text-gray-700">默认向量模型 (Default Embedding)</label>
                <select className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500">
                  {providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} - {p.defaultEmbeddingModel || 'N/A'}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mt-6 pt-6 border-t border-gray-100">
              <label className="text-sm font-medium text-gray-700 block mb-3">自动降级策略顺序</label>
              <div className="flex flex-wrap gap-2">
                {providers.length === 0 ? (
                  <Badge className="px-3 py-1 bg-gray-500 text-white font-mono text-xs">暂无 Provider</Badge>
                ) : (
                  providers.map((p, index) => (
                    <Badge key={p.id} className={`px-3 py-1 text-white font-mono text-xs ${index === 0 ? 'bg-gray-900' : 'bg-gray-500'}`}>
                      {index + 1}. {p.name}
                    </Badge>
                  ))
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {error ? (
          <div className="mb-6 rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm">{error}</div>
        ) : null}

        <h2 className="text-xl font-bold tracking-tight text-gray-900 mb-4 mt-12 flex items-center gap-2">
          <BrainCircuit className="w-5 h-5 text-gray-500" />
          供应商管理 (Providers)
        </h2>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="col-span-1 space-y-4">
            {providers.map((p) => (
              <div
                key={p.id}
                onClick={() => setActiveProvider(p.id)}
                className={`p-4 rounded-xl cursor-pointer border transition-all ${activeProvider === p.id ? 'border-purple-500 bg-purple-50/50 shadow-sm' : 'border-gray-200 bg-white hover:border-gray-300'}`}
              >
                <div className="flex justify-between items-center mb-1">
                  <h3 className="font-semibold text-gray-900">{p.name}</h3>
                  {p.status === 'connected' ? (
                    <div className="w-2 h-2 rounded-full bg-green-500" title="Connected"></div>
                  ) : (
                    <div className="w-2 h-2 rounded-full bg-gray-300" title="Offline"></div>
                  )}
                </div>
                <p className="text-xs text-gray-500">
                  {p.status === 'connected' ? `能力: ${p.capabilities.join(', ') || 'N/A'}` : '服务不可用'}
                </p>
              </div>
            ))}
          </div>

          <div className="col-span-2">
            {active ? (
              <Card key={active.id} className="apple-card border-none shadow-sm h-full animate-in fade-in slide-in-from-right-4 duration-300">
                <CardHeader>
                  <div className="flex justify-between items-start">
                    <div>
                      <CardTitle className="text-xl">{active.name} 配置</CardTitle>
                      <CardDescription>配置 API 密钥和可用模型列表</CardDescription>
                    </div>
                    {active.status === 'connected' ? (
                      <Badge variant="outline" className="text-green-600 bg-green-50 border-green-200">
                        连通测试通过
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-gray-500 bg-gray-100 border-gray-200">
                        服务离线
                      </Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
                      <Key className="w-4 h-4 text-gray-400" />
                      API Key (环境变量)
                    </label>
                    <input
                      type="password"
                      value={active.id === 'ollama' ? '无需密钥' : '••••••••••••••••••••••••••••'}
                      disabled
                      className="w-full h-10 px-3 rounded-md border border-gray-200 bg-gray-50 text-sm text-gray-500 font-mono cursor-not-allowed"
                    />
                    <p className="text-xs text-gray-400 mt-1">
                      请在 <code className="bg-gray-100 px-1 py-0.5 rounded">.env</code> 文件中修改
                      <code className="bg-gray-100 px-1 py-0.5 rounded ml-1">{active.id.toUpperCase()}_API_KEY</code>
                    </p>
                  </div>

                  <div className="space-y-3">
                    <label className="text-sm font-medium text-gray-700 flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-gray-400" />
                      已同步模型列表
                    </label>
                    <div className="bg-gray-50 rounded-lg p-4 border border-gray-100">
                      {active.models.length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                          {active.models.map((m) => (
                            <Badge key={m} variant="secondary" className="font-mono font-normal">
                              {m}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-gray-500 text-center py-2">无可用模型</p>
                      )}
                    </div>
                    <Button variant="outline" size="sm" className="w-full mt-2" disabled>
                      同步模型列表 (Refresh Models)
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ) : null}
          </div>
        </div>
      </main>
    </div>
  )
}
