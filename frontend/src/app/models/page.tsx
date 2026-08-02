'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'
import { BrainCircuit, Settings2, Save, Key, Cpu, Sparkles, Image as ImageIcon, Video, MessageSquare } from 'lucide-react'
import { isWorkbenchFlagEnabled } from '@/lib/workbench-flags'

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

interface ConnectionTestResult {
  success: boolean
  message: string
  models?: string[]
  smoke_test?: {
    success: boolean
    type: string
    message: string
    image_url?: string
    model?: string
  } | null
}

const CAP = {
  CHAT: 'chat',
  EMBEDDING: 'embedding',
  IMAGE: 'image_generation',
  VIDEO: 'video_generation',
} as const

function hasCap(p: ProviderItem | undefined, cap: string): boolean {
  if (!p) return false
  return p.capabilities?.includes(cap)
}

type ModelDrafts = Record<string, { chatModel?: string; embeddingModel?: string }>

const MODEL_DRAFT_KEY = 'omni-model-config-drafts'

function readDrafts(): ModelDrafts {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(MODEL_DRAFT_KEY)
    if (!raw) return {}
    return JSON.parse(raw) as ModelDrafts
  } catch {
    return {}
  }
}

function writeDrafts(drafts: ModelDrafts): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(MODEL_DRAFT_KEY, JSON.stringify(drafts))
}

export default function ModelsConfig() {
  const unifiedReadOnly = isWorkbenchFlagEnabled('unified_shell')
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
  const [testImageUrl, setTestImageUrl] = useState('')
  const [testImageMeta, setTestImageMeta] = useState('')
  const [savingKey, setSavingKey] = useState(false)

  const loadProviders = useCallback(async () => {
    const res = await fetch('/api/omni/models', {
      method: 'GET',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
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
    setActiveProvider((current) => current || json.data?.providers[0]?.id || '')
  }, [])

  useEffect(() => {
    const run = async () => {
      setError('')
      try {
        await loadProviders()
      } catch (err) {
        setError(String(err))
      }
    }
    void run()
  }, [loadProviders])

  const active = useMemo(() => providers.find((p) => p.id === activeProvider), [providers, activeProvider])

  useEffect(() => {
    if (!active) return
    setApiKeyInput('')
    setSelectedChatModel(active.defaultChatModel || active.models[0] || '')
    setSelectedEmbeddingModel(active.defaultEmbeddingModel || active.models[0] || '')
  }, [active])

  useEffect(() => {
    setConnectionNotice('')
    setConnectionOk(null)
    setTestImageUrl('')
    setTestImageMeta('')
  }, [active?.id])

  const handleRefreshModels = async () => {
    if (unifiedReadOnly) return
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
    if (!active || unifiedReadOnly) return
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
    if (!active || unifiedReadOnly) return
    setTesting(true)
    setError('')
    setConnectionNotice('')
    setConnectionOk(null)
    setTestImageUrl('')
    setTestImageMeta('')
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
          defaultChatModel: selectedChatModel,
        }),
      })
      const json = (await res.json()) as {
        success: boolean
        data?: {
          providers: ProviderItem[]
          connectionTest?: ConnectionTestResult
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
        if (test.smoke_test?.image_url) {
          setTestImageUrl(test.smoke_test.image_url)
          setTestImageMeta(`${test.smoke_test.message}${test.smoke_test.model ? ` · ${test.smoke_test.model}` : ''}`)
        } else if (test.smoke_test?.message) {
          setTestImageMeta(test.smoke_test.message)
        }
      }
    } catch (err) {
      setError(String(err))
      setConnectionOk(false)
      setTestImageUrl('')
      setTestImageMeta('')
    } finally {
      setTesting(false)
    }
  }

  const handleSaveApiKey = async () => {
    if (!active || active.id === 'ollama' || unifiedReadOnly) return
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
    if (!active || unifiedReadOnly) return
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

      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 pt-10">
        <div className="mb-8 flex justify-between items-end">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-gray-900 mb-2">模型配置中心</h1>
            <p className="text-gray-600">管理多个 AI Provider 以及底层模型调用策略与降级顺序。</p>
          </div>
          <Button className="bg-purple-600 hover:bg-purple-700" onClick={handleSaveProviderConfig} disabled={unifiedReadOnly || !active || saving}>
            <Save className="w-4 h-4 mr-2" />
            {saving ? '保存中...' : '保存当前供应商配置'}
          </Button>
        </div>

        {unifiedReadOnly ? (
          <div
            className="mb-8 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
            role="status"
            data-testid="models-read-only-status"
          >
            开发工作台仅展示已解析的模型状态。配置、密钥、连接测试与刷新操作保持只读，需从受控的管理员流程执行。
          </div>
        ) : null}

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
                <label htmlFor="global-default-chat-model" className="text-sm font-medium text-gray-700">默认对话模型 (Default Chat)</label>
                <select id="global-default-chat-model" disabled={unifiedReadOnly} className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:cursor-not-allowed disabled:bg-gray-100">
                  {providers.filter((p) => hasCap(p, CAP.CHAT)).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} - {p.defaultChatModel || 'N/A'}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2">
                <label htmlFor="global-default-embedding-model" className="text-sm font-medium text-gray-700">默认向量模型 (Default Embedding)</label>
                <select id="global-default-embedding-model" disabled={unifiedReadOnly} className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:cursor-not-allowed disabled:bg-gray-100">
                  {providers.filter((p) => hasCap(p, CAP.EMBEDDING)).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} - {p.defaultEmbeddingModel || 'N/A'}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="mt-6 pt-6 border-t border-gray-100 space-y-3">
              <div className="text-sm font-medium text-gray-700">自动降级策略顺序</div>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-gray-500 w-12 shrink-0">对话</span>
                  <div className="flex flex-wrap gap-2">
                    {providers.filter((p) => hasCap(p, CAP.CHAT)).map((p, i) => (
                      <Badge key={p.id} className={`px-3 py-1 text-white font-mono text-xs ${i === 0 ? 'bg-gray-900' : 'bg-gray-500'}`}>
                        {i + 1}. {p.name}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-gray-500 w-12 shrink-0">图像</span>
                  <div className="flex flex-wrap gap-2">
                    {providers.filter((p) => hasCap(p, CAP.IMAGE)).map((p, i) => (
                      <Badge key={p.id} className={`px-3 py-1 text-white font-mono text-xs ${i === 0 ? 'bg-violet-700' : 'bg-violet-400'}`}>
                        {i + 1}. {p.name}
                      </Badge>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-gray-500 w-12 shrink-0">视频</span>
                  <div className="flex flex-wrap gap-2">
                    {providers.filter((p) => hasCap(p, CAP.VIDEO)).map((p, i) => (
                      <Badge key={p.id} className={`px-3 py-1 text-white font-mono text-xs ${i === 0 ? 'bg-rose-700' : 'bg-rose-400'}`}>
                        {i + 1}. {p.name}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {notice ? <div className="mb-4 rounded-xl border border-green-200 bg-green-50 text-green-700 px-4 py-3 text-sm" role="status" aria-live="polite">{notice}</div> : null}
        {error ? (
          <div className="mb-6 rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3 text-sm" role="alert">{error}</div>
        ) : null}

        <h2 className="text-xl font-bold tracking-tight text-gray-900 mb-4 mt-12 flex items-center gap-2">
          <BrainCircuit className="w-5 h-5 text-gray-500" />
          供应商管理 (Providers)
        </h2>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="col-span-1 space-y-4">
            {providers.map((p) => (
              <button
                type="button"
                key={p.id}
                onClick={() => setActiveProvider(p.id)}
                aria-pressed={activeProvider === p.id}
                className={`w-full p-4 rounded-xl cursor-pointer border text-left transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-600 ${activeProvider === p.id ? 'border-purple-500 bg-purple-50/50 shadow-sm' : 'border-gray-200 bg-white hover:border-gray-300'}`}
              >
                <span className="flex justify-between items-center mb-1">
                  <span className="font-semibold text-gray-900">{p.name}</span>
                  {p.status === 'connected' ? (
                    <span className="w-2 h-2 rounded-full bg-green-500" title="Connected" aria-label="服务在线" />
                  ) : (
                    <span className="w-2 h-2 rounded-full bg-gray-300" title="Offline" aria-label="服务离线" />
                  )}
                </span>
                <span className="block text-xs text-gray-500">
                  {p.status === 'connected' ? `能力: ${p.capabilities.join(', ') || 'N/A'}` : '服务不可用'}
                </span>
              </button>
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
                    <label htmlFor="provider-api-key" className="text-sm font-medium text-gray-700 flex items-center gap-2">
                      <Key className="w-4 h-4 text-gray-400" />
                      API Key
                    </label>
                    <div className="flex gap-2">
                      <input
                        id="provider-api-key"
                        type="password"
                        value={active.id === 'ollama' ? '无需密钥' : apiKeyInput}
                        onChange={(e) => setApiKeyInput(e.target.value)}
                        placeholder={active.id === 'ollama' ? 'Ollama 不需要 API Key' : active.apiKeySet ? '已配置，输入新值可覆盖' : '输入新的 API Key'}
                        disabled={unifiedReadOnly || active.id === 'ollama'}
                        className={`flex-1 h-10 px-3 rounded-md border text-sm font-mono ${
                          unifiedReadOnly || active.id === 'ollama'
                            ? 'border-gray-200 bg-gray-50 text-gray-500 cursor-not-allowed'
                            : 'border-gray-300 bg-white text-gray-900'
                        }`}
                      />
                      {active.id !== 'ollama' && (
                        <Button
                          size="sm"
                          className="h-10 bg-purple-600 hover:bg-purple-700 text-white px-4"
                          onClick={handleSaveApiKey}
                          disabled={unifiedReadOnly || savingKey || !apiKeyInput.trim()}
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
                    <Button variant="outline" size="sm" onClick={handleTestConnection} disabled={unifiedReadOnly || testing} className="mt-2">
                      {testing ? '测试中...' : hasCap(active, CAP.IMAGE) ? '测试连接 + 生成测试图' : '测试连接'}
                    </Button>
                    {connectionNotice ? (
                      <p className={`text-xs mt-1 ${connectionOk ? 'text-green-600' : 'text-red-600'}`}>{connectionNotice}</p>
                    ) : null}
                    {testImageMeta ? (
                      <p className={`text-xs mt-1 ${testImageUrl ? 'text-green-600' : 'text-red-600'}`}>{testImageMeta}</p>
                    ) : null}
                    {testImageUrl ? (
                      <div className="mt-3 rounded-lg border border-green-200 bg-green-50 p-2">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={testImageUrl}
                          alt="Provider smoke test"
                          className="h-32 w-32 rounded object-cover border bg-white"
                        />
                        <a
                          href={testImageUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1 block text-[11px] text-green-700 underline"
                        >
                          打开测试图
                        </a>
                      </div>
                    ) : null}
                  </div>

                  {/* 模型选择：按 capability 动态显示对应 label */}
                  <ProviderModelSelectors
                    active={active}
                    selectedChatModel={selectedChatModel}
                    selectedEmbeddingModel={selectedEmbeddingModel}
                    onChangeChat={(v) => {
                      setSelectedChatModel(v)
                      updateActiveProviderDraft({ chatModel: v })
                    }}
                    onChangeEmbedding={(v) => {
                      setSelectedEmbeddingModel(v)
                      updateActiveProviderDraft({ embeddingModel: v })
                    }}
                    readOnly={unifiedReadOnly}
                  />

                  <div className="space-y-3">
                    <h3 className="text-sm font-medium text-gray-700 flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-gray-400" />
                      已同步模型列表
                    </h3>
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
                    <Button variant="outline" size="sm" className="w-full mt-2" onClick={handleRefreshModels} disabled={unifiedReadOnly || refreshing}>
                      {refreshing ? '同步中...' : '同步模型列表 (Refresh Models)'}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  )
}


/* ── 按 provider capability 动态渲染默认模型选择器 ──
 *  - chat → "默认对话模型"
 *  - embedding → "默认向量模型"
 *  - image_generation → "默认图像模型"（复用 default_chat_model 字段承载）
 *  - video_generation → "默认视频模型"（同上）
 *
 *  Seedream / Seedance / Kling 这类纯媒体 provider，只会渲染图像/视频选项；
 *  不再强行让用户面对一个永远空的"默认对话模型"。
 */
function ProviderModelSelectors({
  active,
  selectedChatModel,
  selectedEmbeddingModel,
  onChangeChat,
  onChangeEmbedding,
  readOnly,
}: {
  active: ProviderItem
  selectedChatModel: string
  selectedEmbeddingModel: string
  onChangeChat: (v: string) => void
  onChangeEmbedding: (v: string) => void
  readOnly: boolean
}) {
  const isChat = hasCap(active, CAP.CHAT)
  const isEmbed = hasCap(active, CAP.EMBEDDING)
  const isImage = hasCap(active, CAP.IMAGE)
  const isVideo = hasCap(active, CAP.VIDEO)

  // 图像/视频 provider 的"默认模型"复用 default_chat_model 字段。
  // 同时支持图像+视频（如 kling）：用一个共享 selector 承载，因为后端只有一个 default_chat_model 字段。
  const isMedia = !isChat && !isEmbed && (isImage || isVideo)

  if (isMedia) {
    let label = '默认模型'
    let Icon: React.ComponentType<{ className?: string }> = Sparkles
    if (isImage && isVideo) {
      label = '默认模型（图像 / 视频共用）'
    } else if (isImage) {
      label = '默认图像模型'
      Icon = ImageIcon
    } else if (isVideo) {
      label = '默认视频模型'
      Icon = Video
    }

    const modelList = (active.models.length > 0
      ? active.models
      : [active.defaultChatModel || '']
    ).filter(Boolean)

    return (
      <div className="space-y-2">
        <label htmlFor="provider-media-model" className="text-sm font-medium text-gray-700 flex items-center gap-2">
          <Icon className="w-4 h-4 text-gray-400" />
          {label}
        </label>
        <select
          id="provider-media-model"
          value={selectedChatModel}
          onChange={(e) => onChangeChat(e.target.value)}
          disabled={readOnly}
          className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm font-mono focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:cursor-not-allowed disabled:bg-gray-100"
        >
          {modelList.length === 0 && <option value="">— 暂无可用模型，请先「测试连接」拉取 —</option>}
          {modelList.map((m) => (
            <option key={`media-${m}`} value={m}>
              {m}
            </option>
          ))}
        </select>
        <p className="text-[11px] text-gray-500">
          {readOnly ? '当前为只读状态，模型选择不会在此页变更。' : '切换后点击右上「保存当前供应商配置」，下次调用会使用新选择的 Model ID。'}
        </p>
      </div>
    )
  }

  // 普通 chat / embedding provider
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {isChat && (
        <div className="space-y-2">
          <label htmlFor="provider-chat-model" className="text-sm font-medium text-gray-700 flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-gray-400" />
            默认对话模型
          </label>
          <select
            id="provider-chat-model"
            value={selectedChatModel}
            onChange={(e) => onChangeChat(e.target.value)}
            disabled={readOnly}
            className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:cursor-not-allowed disabled:bg-gray-100"
          >
            {(active.models.length > 0 ? active.models : [active.defaultChatModel || '']).filter(Boolean).map((m) => (
              <option key={`chat-${m}`} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      )}
      {isEmbed && (
        <div className="space-y-2">
          <label htmlFor="provider-embedding-model" className="text-sm font-medium text-gray-700">默认向量模型</label>
          <select
            id="provider-embedding-model"
            value={selectedEmbeddingModel}
            onChange={(e) => onChangeEmbedding(e.target.value)}
            disabled={readOnly}
            className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:cursor-not-allowed disabled:bg-gray-100"
          >
            {(active.models.length > 0 ? active.models : [active.defaultEmbeddingModel || '']).filter(Boolean).map((m) => (
              <option key={`embedding-${m}`} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      )}
      {!isChat && !isEmbed && !isImage && !isVideo && (
        <div className="text-xs text-gray-400">该 provider 暂无可配置模型</div>
      )}
    </div>
  )
}
