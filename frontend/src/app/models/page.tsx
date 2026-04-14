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
  apiKeySet?: boolean
}

export default function ModelsConfig() {
  const draftKey = 'omni-model-config-drafts'
  const [activeProvider, setActiveProvider] = useState('')
  const [providers, setProviders] = useState<ProviderItem[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [selectedChatModel, setSelectedChatModel] = useState('')
  const [selectedEmbeddingModel, setSelectedEmbeddingModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [testing, setTesting] = useState(false)
  const [connectionNotice, setConnectionNotice] = useState('')
  const [connectionOk, setConnectionOk] = useState<boolean | null>(null)
  const [savingKey, setSavingKey] = useState(false)

  const readDrafts = (): Record<string, { chatModel?: string; embeddingModel?: string }> => {
    if (typeof window === 'undefined') return {}
    try {
      const raw = window.localStorage.getItem(draftKey)
      if (!raw) return {}
      return JSON.parse(raw) as Record<string, { chatModel?: string; embeddingModel?: string }>
    } catch {
      return {}
    }
  }

  const writeDrafts = (drafts: Record<string, { chatModel?: string; embeddingModel?: string }>) => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(draftKey, JSON.stringify(drafts))
  }

  const loadProviders = async (method: 'GET' | 'POST' = 'GET') => {
    const res = await fetch('/api/omni/models', {
      method,
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: method === 'POST' ? JSON.stringify({ action: 'refresh' }) : undefined,
    })
    const json = (await res.json()) as { success: boolean; data?: { providers: ProviderItem[] }; error?: string }
    if (!json.success || !json.data) {
      throw new Error(json.error || '加载模型配置失败')
    }
    const drafts = readDrafts()
    const merged = json.data.providers.map((p) => {
      const d = drafts[p.id]
      if (!d) return p
      return {
        ...p,
        defaultChatModel: d.chatModel || p.defaultChatModel,
        defaultEmbeddingModel: d.embeddingModel || p.defaultEmbeddingModel,
      }
    })
    setProviders(merged)
    if (!activeProvider && json.data.providers.length > 0) {
      setActiveProvider(json.data.providers[0].id)
    }
  }

  useEffect(() => {
    const run = async () => {
      setError('')
      try {
        await loadProviders('GET')
      } catch (err) {
        setError(String(err))
      }
    }
    void run()
  }, [])

  const active = useMemo(() => providers.find((p) => p.id === activeProvider), [providers, activeProvider])

  useEffect(() => {
    if (!active) return
    setApiKeyInput('')
    setSelectedChatModel(active.defaultChatModel || active.models[0] || '')
    setSelectedEmbeddingModel(active.defaultEmbeddingModel || active.models[0] || '')
  }, [active?.id, active?.defaultChatModel, active?.defaultEmbeddingModel, active?.models])

  const handleRefreshModels = async () => {
    setRefreshing(true)
    setError('')
    setNotice('')
    try {
      const normalizedApiKey = apiKeyInput.trim()
      const outboundApiKey = normalizedApiKey.length > 0 ? normalizedApiKey : undefined
      const res = await fetch('/api/omni/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({
          action: 'refresh',
          providerId: active?.id,
          apiKey: active?.id === 'ollama' ? undefined : outboundApiKey,
        }),
      })
      const json = (await res.json()) as {
        success: boolean
        data?: {
          providers: ProviderItem[]
          connectionTest?: { success: boolean; message: string; models?: string[] }
        }
        error?: string
      }
      if (!json.success || !json.data) {
        throw new Error(json.error || '同步模型失败')
      }
      setProviders(json.data.providers)
      if (json.data.connectionTest?.message) {
        setConnectionNotice(json.data.connectionTest.message)
        setConnectionOk(Boolean(json.data.connectionTest.success))
      }
      setNotice('模型列表已刷新')
    } catch (err) {
      setError(String(err))
    } finally {
      setRefreshing(false)
    }
  }

  const updateActiveProviderDraft = (next: { chatModel?: string; embeddingModel?: string }) => {
    if (!active) return
    const drafts = readDrafts()
    drafts[active.id] = {
      chatModel: next.chatModel ?? drafts[active.id]?.chatModel ?? active.defaultChatModel ?? undefined,
      embeddingModel: next.embeddingModel ?? drafts[active.id]?.embeddingModel ?? active.defaultEmbeddingModel ?? undefined,
    }
    writeDrafts(drafts)

    setProviders((prev) =>
      prev.map((p) => {
        if (p.id !== active.id) return p
        return {
          ...p,
          defaultChatModel: next.chatModel ?? p.defaultChatModel,
          defaultEmbeddingModel: next.embeddingModel ?? p.defaultEmbeddingModel,
        }
      }),
    )
  }

  const handleTestConnection = async () => {
    if (!active) return
    setTesting(true)
    setError('')
    setConnectionNotice('')
    setConnectionOk(null)
    try {
      const normalizedApiKey = apiKeyInput.trim()
      const outboundApiKey = normalizedApiKey.length > 0 ? normalizedApiKey : undefined
      const res = await fetch('/api/omni/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({
          action: 'test-connection',
          providerId: active.id,
          apiKey: active.id === 'ollama' ? undefined : outboundApiKey,
        }),
      })
      const json = (await res.json()) as {
        success: boolean
        data?: {
          providers: ProviderItem[]
          connectionTest?: { success: boolean; message: string; models?: string[] }
        }
        error?: string
      }
      if (!json.success || !json.data) {
        throw new Error(json.error || '连接测试失败')
      }
      setProviders(json.data.providers)
      const test = json.data.connectionTest
      if (test) {
        setConnectionNotice(test.message || (test.success ? '连接成功' : '连接失败'))
        setConnectionOk(Boolean(test.success))
      }
    } catch (err) {
      setError(String(err))
      setConnectionOk(false)
    } finally {
      setTesting(false)
    }
  }

  const handleSaveApiKey = async () => {
    if (!active || active.id === 'ollama') return
    const normalizedApiKey = apiKeyInput.trim()
    if (!normalizedApiKey) {
      setError('请先输入 API Key')
      return
    }
    setSavingKey(true)
    setError('')
    setNotice('')
    try {
      const res = await fetch('/api/omni/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({
          action: 'update-provider',
          providerId: active.id,
          apiKey: normalizedApiKey,
          defaultChatModel: selectedChatModel,
          defaultEmbeddingModel: selectedEmbeddingModel,
        }),
      })
      const json = (await res.json()) as { success: boolean; data?: { providers: ProviderItem[] }; error?: string }
      if (!json.success || !json.data) {
        throw new Error(json.error || '保存 API Key 失败')
      }
      setProviders(json.data.providers)
      const drafts = readDrafts()
      delete drafts[active.id]
      writeDrafts(drafts)
      setNotice('API Key 已保存')
      setApiKeyInput('')
    } catch (err) {
      setError(String(err))
    } finally {
      setSavingKey(false)
    }
  }

  const handleSaveProviderConfig = async () => {
    if (!active) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const normalizedApiKey = apiKeyInput.trim()
      const outboundApiKey = normalizedApiKey.length > 0 ? normalizedApiKey : undefined
      const res = await fetch('/api/omni/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
        body: JSON.stringify({
          action: 'update-provider',
          providerId: active.id,
          apiKey: active.id === 'ollama' ? undefined : outboundApiKey,
          defaultChatModel: selectedChatModel,
          defaultEmbeddingModel: selectedEmbeddingModel,
        }),
      })
      const json = (await res.json()) as { success: boolean; data?: { providers: ProviderItem[] }; error?: string }
      if (!json.success || !json.data) {
        throw new Error(json.error || '保存配置失败')
      }
      setProviders(json.data.providers)
      const drafts = readDrafts()
      delete drafts[active.id]
      writeDrafts(drafts)
      setNotice('配置已保存')
      setApiKeyInput('')
    } catch (err) {
      setError(String(err))
    } finally {
      setSaving(false)
    }
  }

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
          <Button className="bg-purple-600 hover:bg-purple-700" onClick={handleSaveProviderConfig} disabled={!active || saving}>
            <Save className="w-4 h-4 mr-2" />
            {saving ? '保存中...' : '保存当前供应商配置'}
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

        {notice ? <div className="mb-4 rounded-xl border border-green-200 bg-green-50 text-green-700 px-4 py-3 text-sm">{notice}</div> : null}
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
                    {connectionOk === true ? (
                      <Badge variant="outline" className="text-green-600 bg-green-50 border-green-200">
                        连接测试通过
                      </Badge>
                    ) : connectionOk === false ? (
                      <Badge variant="outline" className="text-red-600 bg-red-50 border-red-200">
                        连接测试失败
                      </Badge>
                    ) : active.status === 'connected' ? (
                      <Badge variant="outline" className="text-green-600 bg-green-50 border-green-200">
                        服务在线
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
                      API Key
                    </label>
                    <div className="flex gap-2">
                      <input
                        type="password"
                        value={active.id === 'ollama' ? '无需密钥' : apiKeyInput}
                        onChange={(e) => setApiKeyInput(e.target.value)}
                        placeholder={active.id === 'ollama' ? 'Ollama 不需要 API Key' : active.apiKeySet ? '已配置，输入新值可覆盖' : '输入新的 API Key'}
                        disabled={active.id === 'ollama'}
                        className={`flex-1 h-10 px-3 rounded-md border text-sm font-mono ${
                          active.id === 'ollama'
                            ? 'border-gray-200 bg-gray-50 text-gray-500 cursor-not-allowed'
                            : 'border-gray-300 bg-white text-gray-900'
                        }`}
                      />
                      {active.id !== 'ollama' && (
                        <Button
                          size="sm"
                          className="h-10 bg-purple-600 hover:bg-purple-700 text-white px-4"
                          onClick={handleSaveApiKey}
                          disabled={savingKey || !apiKeyInput.trim()}
                        >
                          <Save className="w-4 h-4 mr-1" />
                          {savingKey ? '保存中...' : '保存'}
                        </Button>
                      )}
                    </div>
                    <p className="text-xs text-gray-400 mt-1">
                      {active.apiKeySet ? '✅ 已配置 API Key。' : '⚠️ 尚未配置 API Key。'}
                      输入后点击保存，会实时更新 AI Hub 运行配置并持久化（重启后自动恢复）。
                    </p>
                    <Button variant="outline" size="sm" onClick={handleTestConnection} disabled={testing} className="mt-2">
                      {testing ? '测试中...' : '测试连接'}
                    </Button>
                    {connectionNotice ? (
                      <p className={`text-xs mt-1 ${connectionOk ? 'text-green-600' : 'text-red-600'}`}>{connectionNotice}</p>
                    ) : null}
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-gray-700">默认对话模型</label>
                      <select
                        value={selectedChatModel}
                        onChange={(e) => {
                          const value = e.target.value
                          setSelectedChatModel(value)
                          updateActiveProviderDraft({ chatModel: value })
                        }}
                        className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
                      >
                        {(active.models.length > 0 ? active.models : [active.defaultChatModel || '']).filter(Boolean).map((m) => (
                          <option key={`chat-${m}`} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium text-gray-700">默认向量模型</label>
                      <select
                        value={selectedEmbeddingModel}
                        onChange={(e) => {
                          const value = e.target.value
                          setSelectedEmbeddingModel(value)
                          updateActiveProviderDraft({ embeddingModel: value })
                        }}
                        className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
                      >
                        {(active.models.length > 0 ? active.models : [active.defaultEmbeddingModel || '']).filter(Boolean).map((m) => (
                          <option key={`embedding-${m}`} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </div>
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
                    <Button variant="outline" size="sm" className="w-full mt-2" onClick={handleRefreshModels} disabled={refreshing}>
                      {refreshing ? '同步中...' : '同步模型列表 (Refresh Models)'}
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
