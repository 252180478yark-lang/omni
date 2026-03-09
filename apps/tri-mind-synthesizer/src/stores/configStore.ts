import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import {
  ProviderConfig,
  ModelConfig,
  ModelProvider,
  DEFAULT_MODELS,
  PROVIDER_INFO,
  ReportDetailLevel,
  ModelIdRule,
  DEFAULT_MODEL_ID_RULES,
  validateModelIdByProvider,
} from '../lib/types'
import { ipc } from '../lib/ipc'

interface ConfigState {
  // 提供商配置
  providers: ProviderConfig[]
  apiKeyStatus: Record<ModelProvider, boolean>
  modelIdRules: Record<ModelProvider, ModelIdRule>
  modelIdRulesSourceUrl: string
  
  // 是否已初始化
  initialized: boolean
  reportDetailLevel: ReportDetailLevel
  
  // Actions
  initConfig: () => Promise<void>
  
  // 提供商操作
  setProviderEnabled: (provider: ModelProvider, enabled: boolean) => void
  setProviderApiKey: (provider: ModelProvider, apiKey: string) => void
  setProviderBaseUrl: (provider: ModelProvider, baseUrl: string) => void
  
  // 模型操作
  setModelEnabled: (provider: ModelProvider, modelId: string, enabled: boolean) => void
  addCustomModel: (provider: ModelProvider, model: ModelConfig) => void
  removeModel: (provider: ModelProvider, modelId: string) => void
  restoreDefaultModels: () => void
  setReportDetailLevel: (level: ReportDetailLevel) => void
  setModelIdRule: (provider: ModelProvider, rule: ModelIdRule) => void
  saveModelIdRules: () => Promise<void>
  resetModelIdRules: () => Promise<void>
  setModelIdRulesSourceUrl: (url: string) => void
  syncModelIdRulesFromUrl: (url?: string) => Promise<{ ok: boolean; error?: string }>
  
  // 获取启用的模型
  getEnabledModels: () => ModelConfig[]
  
  // 保存配置到主进程
  saveConfig: () => void
}

// 创建默认配置
function createDefaultProviders(): ProviderConfig[] {
  return Object.entries(DEFAULT_MODELS).map(([provider, models]) => ({
    provider: provider as ModelProvider,
    apiKey: '',
    baseUrl: PROVIDER_INFO[provider as ModelProvider].defaultBaseUrl,
    enabled: false,
    models: models.map(m => ({ ...m })),
    hiddenDefaultModelIds: [],
  }))
}

function createDefaultApiKeyStatus(): Record<ModelProvider, boolean> {
  return {
    openai: false,
    anthropic: false,
    google: false,
    ollama: false,
  }
}

export const useConfigStore = create<ConfigState>()(
  persist(
    (set, get) => ({
      providers: createDefaultProviders(),
      apiKeyStatus: createDefaultApiKeyStatus(),
      modelIdRules: { ...DEFAULT_MODEL_ID_RULES },
      modelIdRulesSourceUrl: '',
      initialized: false,
      reportDetailLevel: 'standard',

      initConfig: async () => {
        try {
          const [configResult, rulesResult, rulesSourceUrlResult, ...keyStatusResults] = await Promise.all([
            ipc.getModelConfig?.(),
            ipc.getModelIdRules?.(),
            ipc.getModelIdRulesSourceUrl?.(),
            ...Object.keys(PROVIDER_INFO).map((provider) =>
              ipc.hasApiKey?.(provider)
            ),
          ])

          const providersFromMain = configResult?.success && configResult.data
            ? configResult.data
            : get().providers

          const providerKeys = Object.keys(PROVIDER_INFO) as ModelProvider[]
          const apiKeyStatus = createDefaultApiKeyStatus()
          const modelIdRules = rulesResult?.success && rulesResult.data
            ? rulesResult.data
            : { ...DEFAULT_MODEL_ID_RULES }
          const modelIdRulesSourceUrl = rulesSourceUrlResult?.success && typeof rulesSourceUrlResult.data === 'string'
            ? rulesSourceUrlResult.data
            : ''
          providerKeys.forEach((provider, index) => {
            const result = keyStatusResults[index]
            apiKeyStatus[provider] = Boolean(result?.success && result.data)
          })

          set({
            providers: providersFromMain,
            apiKeyStatus,
            modelIdRules,
            modelIdRulesSourceUrl,
            initialized: true,
          })
        } catch (error) {
          console.error('初始化配置失败，回退本地缓存:', error)
          set({ initialized: true })
        }
      },

      setProviderEnabled: (provider, enabled) => {
        set(state => ({
          providers: state.providers.map(p =>
            p.provider === provider ? { ...p, enabled } : p
          ),
        }))
      },

      setProviderApiKey: (provider, apiKey) => {
        set(state => ({
          providers: state.providers.map(p =>
            p.provider === provider ? { ...p, apiKey } : p
          ),
          apiKeyStatus: {
            ...state.apiKeyStatus,
            [provider]: apiKey.trim().length > 0,
          },
        }))
        // 同步保存到主进程加密存储
        ipc.saveApiKey?.(provider, apiKey)
      },

      setProviderBaseUrl: (provider, baseUrl) => {
        set(state => ({
          providers: state.providers.map(p =>
            p.provider === provider ? { ...p, baseUrl } : p
          ),
        }))
      },

      setModelEnabled: (provider, modelId, enabled) => {
        set(state => ({
          providers: state.providers.map(p =>
            p.provider === provider
              ? {
                  ...p,
                  models: p.models.map(m =>
                    m.id === modelId ? { ...m, enabled } : m
                  ),
                }
              : p
          ),
        }))
      },

      addCustomModel: (provider, model) => {
        const normalizedModelId = model.modelId.trim()
        const rules = get().modelIdRules
        if (!normalizedModelId || !validateModelIdByProvider(provider, normalizedModelId, rules)) {
          console.warn(`新增模型失败: ${provider} 的 modelId 不符合规范 -> ${model.modelId}`)
          return
        }

        set(state => ({
          providers: state.providers.map(p =>
            p.provider !== provider
              ? p
              : (() => {
                  const exists = p.models.some((m) => m.modelId.toLowerCase() === normalizedModelId.toLowerCase())
                  if (exists) {
                    console.warn(`新增模型失败: ${provider} 已存在 modelId=${normalizedModelId}`)
                    return p
                  }
                  return {
                    ...p,
                    models: [
                      ...p.models,
                      {
                        ...model,
                        provider,
                        modelId: normalizedModelId,
                      },
                    ],
                  }
                })()
          ),
        }))
      },

      removeModel: (provider, modelId) => {
        set(state => ({
          providers: state.providers.map(p =>
            p.provider !== provider
              ? p
              : (() => {
                  const existing = p.models.find((m) => m.id === modelId)
                  if (!existing) return p
                  const isDefaultModel = DEFAULT_MODELS[provider].some(m => m.id === modelId)
                  const prevHidden = p.hiddenDefaultModelIds || []
                  return {
                    ...p,
                    models: p.models.filter(m => m.id !== modelId),
                    hiddenDefaultModelIds: isDefaultModel
                      ? Array.from(new Set([...prevHidden, modelId]))
                      : prevHidden.filter((id) => id !== modelId),
                  }
                })()
          ),
        }))
      },

      restoreDefaultModels: () => {
        set(state => ({
          providers: state.providers.map(p => ({
            ...p,
            models: DEFAULT_MODELS[p.provider].map(m => ({ ...m })),
            hiddenDefaultModelIds: [],
          })),
        }))
      },

      setReportDetailLevel: (level) => {
        set({ reportDetailLevel: level })
      },

      setModelIdRule: (provider, rule) => {
        set((state) => ({
          modelIdRules: {
            ...state.modelIdRules,
            [provider]: {
              pattern: rule.pattern,
              example: rule.example,
              notes: rule.notes,
            },
          },
        }))
      },

      saveModelIdRules: async () => {
        const rules = get().modelIdRules
        await ipc.saveModelIdRules?.(rules)
      },

      resetModelIdRules: async () => {
        const result = await ipc.resetModelIdRules?.()
        if (result?.success && result.data) {
          set({ modelIdRules: result.data })
        } else {
          set({ modelIdRules: { ...DEFAULT_MODEL_ID_RULES } })
        }
      },

      setModelIdRulesSourceUrl: (url) => {
        set({ modelIdRulesSourceUrl: url })
      },

      syncModelIdRulesFromUrl: async (url) => {
        const sourceUrl = (url ?? get().modelIdRulesSourceUrl).trim()
        if (!sourceUrl) {
          return { ok: false, error: '规则地址不能为空' }
        }
        const result = await ipc.syncModelIdRulesFromUrl?.(sourceUrl)
        if (result?.success && result.data) {
          set({
            modelIdRules: result.data,
            modelIdRulesSourceUrl: sourceUrl,
          })
          return { ok: true }
        }
        return { ok: false, error: result?.error || '同步失败' }
      },

      getEnabledModels: () => {
        const { providers } = get()
        const enabledModels: ModelConfig[] = []
        
        providers.forEach(p => {
          if (p.enabled) {
            p.models.forEach(m => {
              if (m.enabled) {
                enabledModels.push({
                  ...m,
                  baseUrl: p.baseUrl,
                })
              }
            })
          }
        })
        
        return enabledModels
      },

      saveConfig: () => {
        const { providers } = get()
        // 异步保存到主进程数据库（API Key 单独加密存储）
        ipc.saveModelConfig?.(providers)
      },
    }),
    {
      name: 'tri-mind-config-v3', // localStorage key (v3 重置旧缓存, 加入 qwen3)
      storage: createJSONStorage(() => localStorage),
      // 持久化 providers 但排除 apiKey（API Key 单独加密存储）
      partialize: (state) => ({
        providers: state.providers.map(p => ({
          ...p,
          apiKey: '', // 不在 localStorage 中存储 API Key
        })),
        apiKeyStatus: state.apiKeyStatus,
        modelIdRules: state.modelIdRules,
        modelIdRulesSourceUrl: state.modelIdRulesSourceUrl,
        initialized: state.initialized,
        reportDetailLevel: state.reportDetailLevel,
      }),
    }
  )
)
