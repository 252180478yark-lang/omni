'use client'

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
} from '@/lib/tri-mind/types'

interface ConfigState {
  providers: ProviderConfig[]
  apiKeyStatus: Record<ModelProvider, boolean>
  modelIdRules: Record<ModelProvider, ModelIdRule>
  modelIdRulesSourceUrl: string
  initialized: boolean
  reportDetailLevel: ReportDetailLevel

  initConfig: () => Promise<void>
  setProviderEnabled: (provider: ModelProvider, enabled: boolean) => void
  setProviderApiKey: (provider: ModelProvider, apiKey: string) => void
  setProviderBaseUrl: (provider: ModelProvider, baseUrl: string) => void
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
  getEnabledModels: () => ModelConfig[]
  saveConfig: () => void
}

function createDefaultProviders(): ProviderConfig[] {
  const providers = Object.entries(DEFAULT_MODELS).map(([provider, models]) => ({
    provider: provider as ModelProvider,
    apiKey: '',
    baseUrl: PROVIDER_INFO[provider as ModelProvider].defaultBaseUrl,
    enabled: false,
    models: models.map((m) => ({ ...m })),
    hiddenDefaultModelIds: [],
  }))

  // In integration test mode, route OpenAI calls to ai-provider-hub without requiring real API keys.
  if (process.env.NEXT_PUBLIC_USE_BACKEND_HUB === 'true') {
    return providers.map((p) => {
      if (p.provider === 'openai') {
        return {
          ...p,
          enabled: true,
          apiKey: 'local-dev-token',
        }
      }
      if (p.provider === 'ollama') {
        return { ...p, enabled: false }
      }
      return p
    })
  }

  return providers
}

function createDefaultApiKeyStatus(): Record<ModelProvider, boolean> {
  if (process.env.NEXT_PUBLIC_USE_BACKEND_HUB === 'true') {
    return { openai: true, anthropic: false, google: false, ollama: false }
  }
  return { openai: false, anthropic: false, google: false, ollama: false }
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

      initConfig: async () => { set({ initialized: true }) },

      setProviderEnabled: (provider, enabled) =>
        set((s) => ({
          providers: s.providers.map((p) =>
            p.provider === provider ? { ...p, enabled } : p
          ),
        })),

      setProviderApiKey: (provider, apiKey) =>
        set((s) => ({
          providers: s.providers.map((p) =>
            p.provider === provider ? { ...p, apiKey } : p
          ),
          apiKeyStatus: { ...s.apiKeyStatus, [provider]: apiKey.trim().length > 0 },
        })),

      setProviderBaseUrl: (provider, baseUrl) =>
        set((s) => ({
          providers: s.providers.map((p) =>
            p.provider === provider ? { ...p, baseUrl } : p
          ),
        })),

      setModelEnabled: (provider, modelId, enabled) =>
        set((s) => ({
          providers: s.providers.map((p) =>
            p.provider === provider
              ? { ...p, models: p.models.map((m) => (m.id === modelId ? { ...m, enabled } : m)) }
              : p
          ),
        })),

      addCustomModel: (provider, model) => {
        const normalizedModelId = model.modelId.trim()
        const rules = get().modelIdRules
        if (!normalizedModelId || !validateModelIdByProvider(provider, normalizedModelId, rules))
          return
        set((s) => ({
          providers: s.providers.map((p) =>
            p.provider !== provider
              ? p
              : (() => {
                  const exists = p.models.some(
                    (m) => m.modelId.toLowerCase() === normalizedModelId.toLowerCase()
                  )
                  if (exists) return p
                  return {
                    ...p,
                    models: [...p.models, { ...model, provider, modelId: normalizedModelId }],
                  }
                })()
          ),
        }))
      },

      removeModel: (provider, modelId) =>
        set((s) => ({
          providers: s.providers.map((p) =>
            p.provider !== provider
              ? p
              : {
                  ...p,
                  models: p.models.filter((m) => m.id !== modelId),
                  hiddenDefaultModelIds: [],
                }
          ),
        })),

      restoreDefaultModels: () =>
        set((s) => ({
          providers: s.providers.map((p) => ({
            ...p,
            models: DEFAULT_MODELS[p.provider].map((m) => ({ ...m })),
            hiddenDefaultModelIds: [],
          })),
        })),

      setReportDetailLevel: (level) => set({ reportDetailLevel: level }),
      setModelIdRule: (provider, rule) =>
        set((s) => ({
          modelIdRules: { ...s.modelIdRules, [provider]: rule },
        })),
      saveModelIdRules: async () => {},
      resetModelIdRules: async () => { set({ modelIdRules: { ...DEFAULT_MODEL_ID_RULES } }) },
      setModelIdRulesSourceUrl: (url) => set({ modelIdRulesSourceUrl: url }),
      syncModelIdRulesFromUrl: async () => ({ ok: false, error: 'Web 版暂不支持' }),
      saveConfig: () => {},

      getEnabledModels: () => {
        const { providers } = get()
        const enabledModels: ModelConfig[] = []
        providers.forEach((p) => {
          if (p.enabled) {
            p.models.forEach((m) => {
              if (m.enabled) {
                enabledModels.push({ ...m, baseUrl: p.baseUrl })
              }
            })
          }
        })
        return enabledModels
      },
    }),
    {
      name: 'tri-mind-config-web',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        providers: state.providers,
        apiKeyStatus: state.apiKeyStatus,
        modelIdRules: state.modelIdRules,
        modelIdRulesSourceUrl: state.modelIdRulesSourceUrl,
        initialized: state.initialized,
        reportDetailLevel: state.reportDetailLevel,
      }),
    }
  )
)
