import { useEffect, useState } from 'react'
import { Eye, EyeOff, Check, X, Loader2, ChevronDown, ChevronRight, Trash2, RotateCcw } from 'lucide-react'
import { useConfigStore } from '@/stores/tri-mind/configStore'
import {
  ModelProvider,
  PROVIDER_INFO,
  DEFAULT_MODELS,
  validateModelIdByProvider,
  DEFAULT_MODEL_ID_RULES,
} from '@/lib/tri-mind/types'
import { cn } from '@/lib/utils'
import { triMindApi } from '@/lib/tri-mind/api'

export function ModelSelector() {
  const { 
    providers, 
    apiKeyStatus,
    setProviderEnabled, 
    setProviderApiKey, 
    setProviderBaseUrl,
    setModelEnabled,
    addCustomModel,
    removeModel,
    restoreDefaultModels,
    modelIdRules,
    modelIdRulesSourceUrl,
    setModelIdRule,
    saveModelIdRules,
    resetModelIdRules,
    setModelIdRulesSourceUrl,
    syncModelIdRulesFromUrl,
    saveConfig,
  } = useConfigStore()
  const [syncingRules, setSyncingRules] = useState(false)
  const [syncMessage, setSyncMessage] = useState<string | null>(null)
  const [remoteUrlInput, setRemoteUrlInput] = useState(modelIdRulesSourceUrl || '')

  useEffect(() => {
    setRemoteUrlInput(modelIdRulesSourceUrl || '')
  }, [modelIdRulesSourceUrl])

  const handleRestoreDefaults = () => {
    const confirmed = window.confirm('将恢复所有默认模型列表，并移除当前自定义模型，是否继续？')
    if (!confirmed) return
    restoreDefaultModels()
    saveConfig()
  }

  const handleRestoreDefaultRules = async () => {
    const confirmed = window.confirm('将恢复所有 provider 的调用规范默认规则，是否继续？')
    if (!confirmed) return
    await resetModelIdRules()
  }

  const handleSyncRulesFromRemote = async () => {
    const url = remoteUrlInput.trim()
    if (!url) {
      setSyncMessage('请先填写远端 JSON 地址')
      return
    }
    setSyncingRules(true)
    setSyncMessage(null)
    setModelIdRulesSourceUrl(url)
    const result = await syncModelIdRulesFromUrl(url)
    if (result.ok) {
      setSyncMessage('规则同步成功')
    } else {
      setSyncMessage(`规则同步失败：${result.error || '未知错误'}`)
    }
    setSyncingRules(false)
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground mb-4">
        配置 API Key 并启用要参与辩论的模型。支持自定义 Base URL 以使用代理。
      </p>
      <div className="rounded-lg border border-border p-3 space-y-2">
        <p className="text-sm font-medium">远端规则更新</p>
        <div className="flex gap-2">
          <input
            type="text"
            value={remoteUrlInput}
            onChange={(e) => setRemoteUrlInput(e.target.value)}
            placeholder="https://example.com/model-id-rules.json"
            className={cn(
              'flex-1 px-3 py-2 rounded-md',
              'bg-background border border-input',
              'focus:outline-none focus:ring-2 focus:ring-ring',
              'text-sm'
            )}
          />
          <button
            onClick={handleSyncRulesFromRemote}
            disabled={syncingRules}
            className={cn(
              'px-3 py-2 rounded-md text-sm',
              'bg-primary text-primary-foreground',
              'hover:bg-primary/90 transition-colors',
              'flex items-center gap-2',
              syncingRules && 'opacity-70 cursor-not-allowed'
            )}
          >
            {syncingRules ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            一键更新规则
          </button>
        </div>
        <p className="text-xs text-muted-foreground">
          JSON 支持两种格式：直接 provider 键对象，或包含 <code>rules</code> 字段的包裹格式。
        </p>
        {syncMessage && (
          <p className={cn('text-xs', syncMessage.includes('失败') ? 'text-destructive' : 'text-green-600')}>
            {syncMessage}
          </p>
        )}
      </div>
      <div className="flex justify-end">
        <div className="flex items-center gap-2">
          <button
            onClick={handleRestoreDefaultRules}
            className={cn(
              'px-3 py-1.5 rounded-md text-sm',
              'bg-muted hover:bg-muted/80 transition-colors',
              'flex items-center gap-2'
            )}
          >
            <RotateCcw className="w-4 h-4" />
            恢复默认调用规范
          </button>
          <button
            onClick={handleRestoreDefaults}
            className={cn(
              'px-3 py-1.5 rounded-md text-sm',
              'bg-muted hover:bg-muted/80 transition-colors',
              'flex items-center gap-2'
            )}
          >
            <RotateCcw className="w-4 h-4" />
            一键恢复默认模型列表
          </button>
        </div>
      </div>
      
      {providers.map((provider) => (
        <ProviderCard
          key={provider.provider}
          provider={provider.provider}
          apiKey={provider.apiKey}
          baseUrl={provider.baseUrl || ''}
          enabled={provider.enabled}
          hasStoredApiKey={apiKeyStatus[provider.provider]}
          modelRule={modelIdRules[provider.provider] || DEFAULT_MODEL_ID_RULES[provider.provider]}
          models={provider.models}
          onToggleEnabled={(enabled) => {
            setProviderEnabled(provider.provider, enabled)
            saveConfig()
          }}
          onApiKeyChange={(apiKey) => setProviderApiKey(provider.provider, apiKey)}
          onBaseUrlChange={(baseUrl) => {
            setProviderBaseUrl(provider.provider, baseUrl)
            saveConfig()
          }}
          onModelToggle={(modelId, enabled) => {
            setModelEnabled(provider.provider, modelId, enabled)
            saveConfig()
          }}
          onRemoveModel={(modelId) => {
            removeModel(provider.provider, modelId)
            saveConfig()
          }}
          onAddModel={(model) => {
            addCustomModel(provider.provider, model)
            saveConfig()
          }}
          onModelRuleChange={(rule) => {
            setModelIdRule(provider.provider, rule)
          }}
          onSaveModelRules={async () => {
            await saveModelIdRules()
          }}
        />
      ))}
    </div>
  )
}

interface ProviderCardProps {
  provider: ModelProvider
  apiKey: string
  baseUrl: string
  enabled: boolean
  hasStoredApiKey: boolean
  modelRule: { pattern: string; example: string; notes: string }
  models: { id: string; name: string; enabled: boolean; modelId: string; contextWindow?: number }[]
  onToggleEnabled: (enabled: boolean) => void
  onApiKeyChange: (apiKey: string) => void
  onBaseUrlChange: (baseUrl: string) => void
  onModelToggle: (modelId: string, enabled: boolean) => void
  onRemoveModel: (modelId: string) => void
  onAddModel: (model: {
    id: string
    provider: ModelProvider
    modelId: string
    name: string
    enabled: boolean
    contextWindow: number
  }) => void
  onModelRuleChange: (rule: { pattern: string; example: string; notes: string }) => void
  onSaveModelRules: () => Promise<void>
}

function ProviderCard({
  provider,
  apiKey,
  baseUrl,
  enabled,
  hasStoredApiKey,
  modelRule,
  models,
  onToggleEnabled,
  onApiKeyChange,
  onBaseUrlChange,
  onModelToggle,
  onRemoveModel,
  onAddModel,
  onModelRuleChange,
  onSaveModelRules,
}: ProviderCardProps) {
  const [showApiKey, setShowApiKey] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string } | null>(null)
  const [newModelId, setNewModelId] = useState('')
  const [newModelName, setNewModelName] = useState('')
  const [newContextWindow, setNewContextWindow] = useState('128000')
  const [addModelError, setAddModelError] = useState<string | null>(null)
  const [rulePattern, setRulePattern] = useState(modelRule.pattern)
  const [ruleExample, setRuleExample] = useState(modelRule.example)
  const [ruleNotes, setRuleNotes] = useState(modelRule.notes)
  const [ruleSaveMessage, setRuleSaveMessage] = useState<string | null>(null)

  const info = PROVIDER_INFO[provider]
  const handleSaveRule = async () => {
    try {
      // 快速校验正则可编译
      // eslint-disable-next-line no-new
      new RegExp(rulePattern)
    } catch {
      setRuleSaveMessage('规则保存失败：正则表达式无效')
      return
    }

    onModelRuleChange({
      pattern: rulePattern.trim(),
      example: ruleExample.trim() || modelRule.example,
      notes: ruleNotes.trim() || modelRule.notes,
    })
    await onSaveModelRules()
    setRuleSaveMessage('调用规范已保存')
    setTimeout(() => setRuleSaveMessage(null), 1500)
  }

  const handleAddModel = () => {
    const modelId = newModelId.trim()
    const modelName = newModelName.trim() || modelId
    const contextWindow = Number.parseInt(newContextWindow, 10)

    if (!modelId) {
      setAddModelError('模型 ID 不能为空')
      return
    }
    if (!Number.isFinite(contextWindow) || contextWindow <= 0) {
      setAddModelError('上下文窗口必须是正整数')
      return
    }
    if (!validateModelIdByProvider(provider, modelId, {
      openai: provider === 'openai' ? { pattern: rulePattern, example: ruleExample || modelRule.example, notes: ruleNotes || modelRule.notes } : DEFAULT_MODEL_ID_RULES.openai,
      anthropic: provider === 'anthropic' ? { pattern: rulePattern, example: ruleExample || modelRule.example, notes: ruleNotes || modelRule.notes } : DEFAULT_MODEL_ID_RULES.anthropic,
      google: provider === 'google' ? { pattern: rulePattern, example: ruleExample || modelRule.example, notes: ruleNotes || modelRule.notes } : DEFAULT_MODEL_ID_RULES.google,
      ollama: provider === 'ollama' ? { pattern: rulePattern, example: ruleExample || modelRule.example, notes: ruleNotes || modelRule.notes } : DEFAULT_MODEL_ID_RULES.ollama,
    })) {
      setAddModelError(`modelId 不符合 ${info.name} 调用规范。示例: ${modelRule.example}`)
      return
    }
    if (models.some(m => m.modelId.toLowerCase() === modelId.toLowerCase())) {
      setAddModelError('该 provider 下已存在相同 modelId')
      return
    }

    const normalized = modelId.toLowerCase().replace(/[^a-z0-9-]/g, '-')
    const baseId = `${provider}-${normalized || 'custom'}`
    let uniqueId = baseId
    if (models.some(m => m.id === uniqueId)) {
      uniqueId = `${baseId}-${Date.now()}`
    }

    onAddModel({
      id: uniqueId,
      provider,
      modelId,
      name: modelName,
      enabled: true,
      contextWindow,
    })

    setNewModelId('')
    setNewModelName('')
    setNewContextWindow('128000')
    setAddModelError(null)
  }

  const handleTest = async () => {
    const testingApiKey = apiKey
    if (!testingApiKey && provider !== 'ollama') {
      setTestResult({ ok: false, error: 'API Key 不能为空' })
      return
    }

    setTesting(true)
    setTestResult(null)

    try {
      const testModelId = models.find((m) => m.enabled)?.modelId || models[0]?.modelId
      if (!testModelId) {
        setTestResult({ ok: false, error: '当前 provider 没有可测试的模型，请先新增或恢复默认模型' })
        return
      }
      const result = await triMindApi.testConnection({
        provider,
        apiKey: testingApiKey || 'ollama',
        baseUrl: baseUrl || info.defaultBaseUrl,
        model: testModelId,
      })

      if (result?.success && result.data) {
        setTestResult(result.data)
      } else {
        setTestResult({ ok: false, error: (result as { error?: string })?.error || '测试失败' })
      }
    } catch (error) {
      setTestResult({ ok: false, error: String(error) })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className={cn(
      'border rounded-lg overflow-hidden',
      enabled ? 'border-primary/50' : 'border-border'
    )}>
      {/* 头部 */}
      <div
        className={cn(
          'flex items-center justify-between px-4 py-3 cursor-pointer',
          'hover:bg-muted/50 transition-colors',
          enabled && 'bg-primary/5'
        )}
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="w-4 h-4 text-muted-foreground" />
          )}
          <span className="font-medium">{info.name}</span>
          {provider !== 'ollama' && (
            <span className={cn(
              'text-xs px-2 py-0.5 rounded-full',
              hasStoredApiKey ? 'bg-green-500/10 text-green-600' : 'bg-muted text-muted-foreground'
            )}>
              {hasStoredApiKey ? 'Key 已保存' : 'Key 未保存'}
            </span>
          )}
          {enabled && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary">
              已启用
            </span>
          )}
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onToggleEnabled(!enabled)
          }}
          className={cn(
            'px-3 py-1.5 rounded-md text-sm transition-colors',
            enabled
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted hover:bg-muted/80'
          )}
        >
          {enabled ? '禁用' : '启用'}
        </button>
      </div>

      {/* 展开内容 */}
      {expanded && (
        <div className="px-4 py-4 border-t border-border space-y-4">
          {/* API Key */}
          <div>
            <label className="block text-sm font-medium mb-1.5">API Key</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={showApiKey ? 'text' : 'password'}
                  value={apiKey}
                  onChange={(e) => onApiKeyChange(e.target.value)}
                  placeholder="输入 API Key..."
                  className={cn(
                    'w-full px-3 py-2 pr-10 rounded-md',
                    'bg-background border border-input',
                    'focus:outline-none focus:ring-2 focus:ring-ring',
                    'text-sm'
                  )}
                />
                <button
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted-foreground hover:text-foreground"
                >
                  {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <button
                onClick={handleTest}
                disabled={testing}
                className={cn(
                  'px-3 py-2 rounded-md text-sm',
                  'bg-secondary hover:bg-secondary/80',
                  'transition-colors flex items-center gap-2'
                )}
              >
                {testing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  '测试'
                )}
              </button>
            </div>
            {!apiKey && hasStoredApiKey && provider !== 'ollama' && (
              <p className="mt-2 text-xs text-muted-foreground">
                当前显示为空是安全策略，系统凭据中已有已保存的 API Key。
              </p>
            )}
            {testResult && (
              <div className={cn(
                'flex items-center gap-2 mt-2 text-sm',
                testResult.ok ? 'text-green-500' : 'text-destructive'
              )}>
                {testResult.ok ? <Check className="w-4 h-4" /> : <X className="w-4 h-4" />}
                {testResult.ok ? '连接成功' : testResult.error}
              </div>
            )}
          </div>

          {/* Base URL */}
          <div>
            <label className="block text-sm font-medium mb-1.5">
              Base URL <span className="text-muted-foreground font-normal">(可选，用于代理)</span>
            </label>
            <input
              type="text"
              value={baseUrl}
              onChange={(e) => onBaseUrlChange(e.target.value)}
              placeholder={info.defaultBaseUrl}
              className={cn(
                'w-full px-3 py-2 rounded-md',
                'bg-background border border-input',
                'focus:outline-none focus:ring-2 focus:ring-ring',
                'text-sm'
              )}
            />
          </div>

          {/* 模型选择 */}
          <div>
            <label className="block text-sm font-medium mb-2">选择模型</label>
            <div className="space-y-2">
              {models.map((model) => (
                <label
                  key={model.id}
                  className="flex items-center gap-3 p-2 rounded-md hover:bg-muted/50 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={model.enabled}
                    onChange={(e) => onModelToggle(model.id, e.target.checked)}
                    className="w-4 h-4 rounded border-input"
                  />
                  <span className="text-sm">{model.name}</span>
                  <span className="text-xs text-muted-foreground">{model.modelId}</span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      const isDefaultModel = DEFAULT_MODELS[provider].some(m => m.id === model.id)
                      const confirmed = window.confirm(
                        isDefaultModel
                          ? `将隐藏默认模型 "${model.name}"，可通过“一键恢复默认模型列表”恢复，确认删除吗？`
                          : `确认删除自定义模型 "${model.name}" 吗？`
                      )
                      if (!confirmed) return
                      onRemoveModel(model.id)
                    }}
                    className={cn(
                      'ml-auto p-1.5 rounded-md',
                      'text-muted-foreground hover:text-destructive hover:bg-destructive/10',
                      'transition-colors'
                    )}
                    title="删除模型"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </label>
              ))}
            </div>
          </div>

          {/* 新增模型 */}
          <div className="pt-2 border-t border-border">
            <label className="block text-sm font-medium mb-2">调用规范（可更新）</label>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mb-2">
              <input
                type="text"
                value={rulePattern}
                onChange={(e) => setRulePattern(e.target.value)}
                placeholder="正则表达式"
                className={cn(
                  'px-3 py-2 rounded-md',
                  'bg-background border border-input',
                  'focus:outline-none focus:ring-2 focus:ring-ring',
                  'text-sm font-mono'
                )}
              />
              <input
                type="text"
                value={ruleExample}
                onChange={(e) => setRuleExample(e.target.value)}
                placeholder="示例 modelId"
                className={cn(
                  'px-3 py-2 rounded-md',
                  'bg-background border border-input',
                  'focus:outline-none focus:ring-2 focus:ring-ring',
                  'text-sm'
                )}
              />
              <input
                type="text"
                value={ruleNotes}
                onChange={(e) => setRuleNotes(e.target.value)}
                placeholder="规则说明"
                className={cn(
                  'px-3 py-2 rounded-md',
                  'bg-background border border-input',
                  'focus:outline-none focus:ring-2 focus:ring-ring',
                  'text-sm'
                )}
              />
            </div>
            <div className="flex items-center justify-end mb-3">
              <button
                onClick={handleSaveRule}
                className={cn(
                  'px-3 py-1.5 rounded-md text-sm',
                  'bg-secondary hover:bg-secondary/80 transition-colors'
                )}
              >
                保存调用规范
              </button>
            </div>
            {ruleSaveMessage && (
              <p className="mb-2 text-xs text-muted-foreground">{ruleSaveMessage}</p>
            )}
            <label className="block text-sm font-medium mb-2">新增模型</label>
            <p className="text-xs text-muted-foreground mb-2">
              调用规范：{ruleNotes || modelRule.notes}，示例：<code>{ruleExample || modelRule.example}</code>
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <input
                type="text"
                value={newModelId}
                onChange={(e) => setNewModelId(e.target.value)}
                placeholder={`modelId（如 ${modelRule.example}）`}
                className={cn(
                  'px-3 py-2 rounded-md',
                  'bg-background border border-input',
                  'focus:outline-none focus:ring-2 focus:ring-ring',
                  'text-sm'
                )}
              />
              <input
                type="text"
                value={newModelName}
                onChange={(e) => setNewModelName(e.target.value)}
                placeholder="显示名称（可选）"
                className={cn(
                  'px-3 py-2 rounded-md',
                  'bg-background border border-input',
                  'focus:outline-none focus:ring-2 focus:ring-ring',
                  'text-sm'
                )}
              />
              <input
                type="number"
                min={1}
                value={newContextWindow}
                onChange={(e) => setNewContextWindow(e.target.value)}
                placeholder="上下文窗口"
                className={cn(
                  'px-3 py-2 rounded-md',
                  'bg-background border border-input',
                  'focus:outline-none focus:ring-2 focus:ring-ring',
                  'text-sm'
                )}
              />
            </div>
            <div className="mt-2 flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                新模型将默认启用，可立即参与辩论，并随配置一起持久化。
              </p>
              <button
                onClick={handleAddModel}
                className={cn(
                  'px-3 py-1.5 rounded-md text-sm',
                  'bg-primary text-primary-foreground',
                  'hover:bg-primary/90 transition-colors'
                )}
              >
                新增模型
              </button>
            </div>
            {addModelError && (
              <p className="mt-2 text-xs text-destructive">{addModelError}</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
