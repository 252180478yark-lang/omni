import { IpcMain } from 'electron'
import {
  TestConnectionParams,
  ProviderConfig,
  DEFAULT_MODELS,
  PROVIDER_INFO,
  ModelConfig,
  DEFAULT_MODEL_ID_RULES,
  ModelIdRule,
  ModelProvider,
} from '../../src/lib/types'
import { adapterManager } from '../services/llm/adapters'
import { saveConfig, getConfig } from '../services/db.service'

function mergeModels(defaultModels: ModelConfig[], saved?: ProviderConfig): ModelConfig[] {
  if (!saved) {
    return defaultModels.map((m) => ({ ...m }))
  }

  const hiddenDefault = new Set(saved.hiddenDefaultModelIds || [])
  const defaultById = new Map(defaultModels.map((m) => [m.id, m]))
  const savedById = new Map((saved.models || []).map((m) => [m.id, m]))

  const mergedDefaults = defaultModels
    .filter((def) => !hiddenDefault.has(def.id))
    .map((def) => {
      const existed = savedById.get(def.id)
      return existed ? { ...def, ...existed, id: def.id, provider: def.provider } : { ...def }
    })

  const customSaved = (saved.models || [])
    .filter((m) => !defaultById.has(m.id))
    .map((m) => ({ ...m }))

  return [...mergedDefaults, ...customSaved]
}

function mergeModelIdRules(
  savedRules?: Partial<Record<ModelProvider, ModelIdRule>> | null
): Record<ModelProvider, ModelIdRule> {
  const merged = { ...DEFAULT_MODEL_ID_RULES }
  if (!savedRules) return merged
  for (const provider of Object.keys(DEFAULT_MODEL_ID_RULES) as ModelProvider[]) {
    const saved = savedRules[provider]
    if (saved && saved.pattern && saved.example && saved.notes) {
      merged[provider] = { ...saved }
    }
  }
  return merged
}

function extractRemoteRules(payload: unknown): Partial<Record<ModelProvider, ModelIdRule>> {
  if (!payload || typeof payload !== 'object') return {}
  const obj = payload as Record<string, unknown>
  const candidate = (obj.rules && typeof obj.rules === 'object' ? obj.rules : obj) as Record<string, unknown>
  const result: Partial<Record<ModelProvider, ModelIdRule>> = {}
  for (const provider of Object.keys(DEFAULT_MODEL_ID_RULES) as ModelProvider[]) {
    const raw = candidate[provider]
    if (!raw || typeof raw !== 'object') continue
    const rule = raw as Record<string, unknown>
    if (typeof rule.pattern !== 'string' || typeof rule.example !== 'string' || typeof rule.notes !== 'string') continue
    try {
      // 验证正则合法性，非法则忽略该条
      // eslint-disable-next-line no-new
      new RegExp(rule.pattern)
      result[provider] = {
        pattern: rule.pattern,
        example: rule.example,
        notes: rule.notes,
      }
    } catch {
      // ignore invalid regex
    }
  }
  return result
}

export function registerConfigIPC(ipcMain: IpcMain) {
  // 获取模型配置
  ipcMain.handle('get-model-config', async () => {
    try {
      // 优先从数据库读取
      const savedConfigs = getConfig<ProviderConfig[] | null>('model-config', null)
      
      if (savedConfigs && Array.isArray(savedConfigs)) {
        // 合并已保存配置与默认配置（处理新增厂商与新增默认模型）
        const merged: ProviderConfig[] = Object.entries(DEFAULT_MODELS).map(([provider, defaultModels]) => {
          const saved = savedConfigs.find(c => c.provider === provider)
          if (saved) {
            return {
              provider: provider as keyof typeof DEFAULT_MODELS,
              apiKey: '', // API Key不返回给前端
              baseUrl: saved.baseUrl || PROVIDER_INFO[provider as keyof typeof PROVIDER_INFO].defaultBaseUrl,
              enabled: saved.enabled ?? false,
              hiddenDefaultModelIds: saved.hiddenDefaultModelIds || [],
              models: mergeModels(defaultModels, saved),
            }
          }
          return {
            provider: provider as keyof typeof DEFAULT_MODELS,
            apiKey: '',
            baseUrl: PROVIDER_INFO[provider as keyof typeof PROVIDER_INFO].defaultBaseUrl,
            enabled: false,
            hiddenDefaultModelIds: [],
            models: defaultModels.map(m => ({ ...m })),
          }
        })
        return { success: true, data: merged }
      }
      
      // 无已保存配置，返回默认值
      const configs: ProviderConfig[] = Object.entries(DEFAULT_MODELS).map(([provider, models]) => ({
        provider: provider as keyof typeof DEFAULT_MODELS,
        apiKey: '',
        baseUrl: PROVIDER_INFO[provider as keyof typeof PROVIDER_INFO].defaultBaseUrl,
        enabled: false,
        hiddenDefaultModelIds: [],
        models: models.map(m => ({ ...m })),
      }))
      
      return { success: true, data: configs }
    } catch (error) {
      console.error('获取配置失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 保存模型配置
  ipcMain.handle('save-model-config', async (_event, configs: ProviderConfig[]) => {
    try {
      console.log('保存模型配置')
      // 保存到数据库（移除 API Key，避免明文存储）
      const sanitized = configs.map(c => ({
        ...c,
        apiKey: '', // 不在数据库中存储API Key
      }))
      saveConfig('model-config', sanitized)
      return { success: true }
    } catch (error) {
      console.error('保存配置失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 获取模型ID调用规则
  ipcMain.handle('get-model-id-rules', async () => {
    try {
      const savedRules = getConfig<Partial<Record<ModelProvider, ModelIdRule>> | null>('model-id-rules-v1', null)
      return { success: true, data: mergeModelIdRules(savedRules) }
    } catch (error) {
      console.error('获取模型ID规则失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 保存模型ID调用规则
  ipcMain.handle('save-model-id-rules', async (_event, rules: Partial<Record<ModelProvider, ModelIdRule>>) => {
    try {
      const merged = mergeModelIdRules(rules)
      saveConfig('model-id-rules-v1', merged)
      return { success: true, data: merged }
    } catch (error) {
      console.error('保存模型ID规则失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 恢复默认模型ID调用规则
  ipcMain.handle('reset-model-id-rules', async () => {
    try {
      saveConfig('model-id-rules-v1', DEFAULT_MODEL_ID_RULES)
      return { success: true, data: DEFAULT_MODEL_ID_RULES }
    } catch (error) {
      console.error('重置模型ID规则失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 从远端 JSON 同步模型ID调用规则
  ipcMain.handle('sync-model-id-rules-from-url', async (_event, url: string) => {
    try {
      if (!url || typeof url !== 'string') {
        return { success: false, error: '规则地址不能为空' }
      }
      let parsedUrl: URL
      try {
        parsedUrl = new URL(url)
      } catch {
        return { success: false, error: '规则地址格式无效' }
      }
      if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
        return { success: false, error: '仅支持 http/https 规则地址' }
      }

      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 15000)
      try {
        const resp = await fetch(parsedUrl.toString(), {
          method: 'GET',
          headers: { Accept: 'application/json' },
          signal: controller.signal,
        })
        if (!resp.ok) {
          return { success: false, error: `拉取规则失败: HTTP ${resp.status}` }
        }
        const payload = await resp.json()
        const remoteRules = extractRemoteRules(payload)
        const merged = mergeModelIdRules(remoteRules)
        saveConfig('model-id-rules-v1', merged)
        saveConfig('model-id-rules-source-url', parsedUrl.toString())
        return { success: true, data: merged }
      } finally {
        clearTimeout(timeout)
      }
    } catch (error) {
      return { success: false, error: `拉取规则失败: ${String(error)}` }
    }
  })

  // 获取远端规则源 URL
  ipcMain.handle('get-model-id-rules-source-url', async () => {
    try {
      const url = getConfig<string>('model-id-rules-source-url', '')
      return { success: true, data: url }
    } catch (error) {
      return { success: false, error: String(error) }
    }
  })

  // 测试连接
  ipcMain.handle('test-connection', async (_event, params: TestConnectionParams) => {
    try {
      console.log('测试连接:', params.provider, params.model)
      
      if (!params.apiKey && params.provider !== 'ollama') {
        return { success: true, data: { ok: false, error: 'API Key 不能为空' } }
      }
      
      // 获取适配器
      const adapter = adapterManager.get(params.provider)
      if (!adapter) {
        return { success: true, data: { ok: false, error: `不支持的提供商: ${params.provider}` } }
      }
      
      // 执行连接测试
      const result = await adapter.testConnection({
        apiKey: params.apiKey,
        baseUrl: params.baseUrl,
        model: params.model,
      })
      
      return { success: true, data: result }
    } catch (error) {
      console.error('测试连接失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 保存API Key
  ipcMain.handle('save-api-key', async (_event, { provider, apiKey }: { provider: string; apiKey: string }) => {
    try {
      console.log('保存API Key:', provider)
      const { saveApiKey } = await import('../services/credential.service')
      await saveApiKey(provider, apiKey)
      return { success: true }
    } catch (error) {
      console.error('保存API Key失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 获取API Key
  ipcMain.handle('get-api-key', async (_event, provider: string) => {
    try {
      const { getApiKey } = await import('../services/credential.service')
      const apiKey = await getApiKey(provider)
      return { success: true, data: apiKey || '' }
    } catch (error) {
      console.error('获取API Key失败:', error)
      return { success: false, error: String(error) }
    }
  })

  // 检查API Key是否存在
  ipcMain.handle('has-api-key', async (_event, provider: string) => {
    try {
      const { hasApiKey } = await import('../services/credential.service')
      const exists = await hasApiKey(provider)
      return { success: true, data: exists }
    } catch (error) {
      console.error('检查API Key失败:', error)
      return { success: false, error: String(error) }
    }
  })
}
