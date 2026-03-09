import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron'
import type { 
  DebateParams, 
  TestConnectionParams, 
  SaveFileParams, 
  ExportDebateParams,
  StreamChunk,
  ProviderConfig,
  DebateEvent,
  ModelIdRule,
  ModelProvider
} from '../src/lib/types'

// 定义暴露给渲染进程的API
const electronAPI = {
  // ==================== 辩论相关 ====================
  
  /** 开始辩论 */
  startDebate: (params: DebateParams) => {
    return ipcRenderer.invoke('start-debate', params)
  },
  
  /** 停止生成 */
  stopGeneration: (sessionId: string) => {
    return ipcRenderer.invoke('stop-generation', sessionId)
  },
  
  /** 监听辩论流式数据 */
  onDebateStream: (callback: (chunk: StreamChunk) => void) => {
    const handler = (_event: IpcRendererEvent, chunk: StreamChunk) => callback(chunk)
    ipcRenderer.on('debate-stream', handler)
    return () => ipcRenderer.removeListener('debate-stream', handler)
  },
  
  /** 监听辩论事件（轮次完成、辩论完成等） */
  onDebateEvent: (callback: (event: DebateEvent) => void) => {
    const handler = (_event: IpcRendererEvent, data: DebateEvent) => callback(data)
    ipcRenderer.on('debate-event', handler)
    return () => ipcRenderer.removeListener('debate-event', handler)
  },

  // ==================== 配置相关 ====================
  
  /** 获取模型配置 */
  getModelConfig: () => {
    return ipcRenderer.invoke('get-model-config')
  },
  
  /** 保存模型配置 */
  saveModelConfig: (config: ProviderConfig[]) => {
    return ipcRenderer.invoke('save-model-config', config)
  },

  /** 获取模型ID调用规范 */
  getModelIdRules: () => {
    return ipcRenderer.invoke('get-model-id-rules')
  },

  /** 保存模型ID调用规范 */
  saveModelIdRules: (rules: Partial<Record<ModelProvider, ModelIdRule>>) => {
    return ipcRenderer.invoke('save-model-id-rules', rules)
  },

  /** 恢复默认模型ID调用规范 */
  resetModelIdRules: () => {
    return ipcRenderer.invoke('reset-model-id-rules')
  },

  /** 从远端JSON同步模型ID调用规范 */
  syncModelIdRulesFromUrl: (url: string) => {
    return ipcRenderer.invoke('sync-model-id-rules-from-url', url)
  },

  /** 获取规则源URL */
  getModelIdRulesSourceUrl: () => {
    return ipcRenderer.invoke('get-model-id-rules-source-url')
  },
  
  /** 测试连接 */
  testConnection: (params: TestConnectionParams) => {
    return ipcRenderer.invoke('test-connection', params)
  },
  
  /** 保存API Key */
  saveApiKey: (provider: string, apiKey: string) => {
    return ipcRenderer.invoke('save-api-key', { provider, apiKey })
  },
  
  /** 获取API Key */
  getApiKey: (provider: string) => {
    return ipcRenderer.invoke('get-api-key', provider)
  },
  
  /** 检查API Key是否存在 */
  hasApiKey: (provider: string) => {
    return ipcRenderer.invoke('has-api-key', provider)
  },

  // ==================== 文件相关 ====================
  
  /** 保存文件 */
  saveFile: (params: SaveFileParams) => {
    return ipcRenderer.invoke('save-file', params)
  },
  
  /** 导出辩论记录 */
  exportDebate: (params: ExportDebateParams) => {
    return ipcRenderer.invoke('export-debate', params)
  },
  
  /** 打开文件对话框并解析 */
  openFiles: () => {
    return ipcRenderer.invoke('open-files')
  },

  // ==================== 会话相关 ====================
  
  /** 新建会话 */
  newSession: () => {
    return ipcRenderer.invoke('new-session')
  },
  
  /** 加载会话 */
  loadSession: (sessionId: string) => {
    return ipcRenderer.invoke('load-session', sessionId)
  },
  
  /** 获取会话列表 */
  listSessions: () => {
    return ipcRenderer.invoke('list-sessions')
  },
  
  /** 删除会话 */
  deleteSession: (sessionId: string) => {
    return ipcRenderer.invoke('delete-session', sessionId)
  },
  
  /** 更新会话标题 */
  updateSessionTitle: (sessionId: string, title: string) => {
    return ipcRenderer.invoke('update-session-title', { sessionId, title })
  },

  // ==================== 菜单事件监听 ====================
  
  /** 监听新建会话菜单事件 */
  onNewSession: (callback: () => void) => {
    const handler = () => callback()
    ipcRenderer.on('new-session', handler)
    return () => ipcRenderer.removeListener('new-session', handler)
  },
  
  /** 监听导出事件 */
  onExportDebate: (callback: () => void) => {
    const handler = () => callback()
    ipcRenderer.on('export-debate', handler)
    return () => ipcRenderer.removeListener('export-debate', handler)
  },
  
  /** 监听打开设置事件 */
  onOpenSettings: (callback: () => void) => {
    const handler = () => callback()
    ipcRenderer.on('open-settings', handler)
    return () => ipcRenderer.removeListener('open-settings', handler)
  },
}

// 暴露API到渲染进程
contextBridge.exposeInMainWorld('electronAPI', electronAPI)

// 类型声明
export type ElectronAPI = typeof electronAPI
