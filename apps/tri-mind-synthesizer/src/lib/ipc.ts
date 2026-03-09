import type { ElectronAPI } from '../../electron/preload'

/**
 * 获取 Electron API
 * 使用 getter 延迟访问，避免在模块加载时 window.electronAPI 还未注入
 */
function getElectronAPI(): ElectronAPI | undefined {
  return (window as unknown as { electronAPI: ElectronAPI }).electronAPI
}

/**
 * 类型安全的 IPC 调用封装
 * 所有方法都通过 getter 延迟访问 electronAPI
 */
export const ipc = {
  // 辩论
  startDebate: (...args: Parameters<ElectronAPI['startDebate']>) => getElectronAPI()?.startDebate(...args),
  stopGeneration: (...args: Parameters<ElectronAPI['stopGeneration']>) => getElectronAPI()?.stopGeneration(...args),
  onDebateStream: (...args: Parameters<ElectronAPI['onDebateStream']>) => getElectronAPI()?.onDebateStream(...args),
  onDebateEvent: (...args: Parameters<ElectronAPI['onDebateEvent']>) => getElectronAPI()?.onDebateEvent(...args),
  
  // 配置
  getModelConfig: () => getElectronAPI()?.getModelConfig(),
  saveModelConfig: (...args: Parameters<ElectronAPI['saveModelConfig']>) => getElectronAPI()?.saveModelConfig(...args),
  getModelIdRules: () => getElectronAPI()?.getModelIdRules(),
  saveModelIdRules: (...args: Parameters<ElectronAPI['saveModelIdRules']>) => getElectronAPI()?.saveModelIdRules(...args),
  resetModelIdRules: (...args: Parameters<ElectronAPI['resetModelIdRules']>) => getElectronAPI()?.resetModelIdRules(...args),
  syncModelIdRulesFromUrl: (...args: Parameters<ElectronAPI['syncModelIdRulesFromUrl']>) => getElectronAPI()?.syncModelIdRulesFromUrl(...args),
  getModelIdRulesSourceUrl: () => getElectronAPI()?.getModelIdRulesSourceUrl(),
  testConnection: (...args: Parameters<ElectronAPI['testConnection']>) => getElectronAPI()?.testConnection(...args),
  saveApiKey: (...args: Parameters<ElectronAPI['saveApiKey']>) => getElectronAPI()?.saveApiKey(...args),
  getApiKey: (...args: Parameters<ElectronAPI['getApiKey']>) => getElectronAPI()?.getApiKey(...args),
  hasApiKey: (...args: Parameters<ElectronAPI['hasApiKey']>) => getElectronAPI()?.hasApiKey(...args),
  
  // 文件
  saveFile: (...args: Parameters<ElectronAPI['saveFile']>) => getElectronAPI()?.saveFile(...args),
  exportDebate: (...args: Parameters<ElectronAPI['exportDebate']>) => getElectronAPI()?.exportDebate(...args),
  openFiles: () => getElectronAPI()?.openFiles(),
  
  // 会话
  newSession: () => getElectronAPI()?.newSession(),
  loadSession: (...args: Parameters<ElectronAPI['loadSession']>) => getElectronAPI()?.loadSession(...args),
  listSessions: () => getElectronAPI()?.listSessions(),
  deleteSession: (...args: Parameters<ElectronAPI['deleteSession']>) => getElectronAPI()?.deleteSession(...args),
  updateSessionTitle: (...args: Parameters<ElectronAPI['updateSessionTitle']>) => getElectronAPI()?.updateSessionTitle(...args),
  
  // 菜单事件
  onNewSession: (...args: Parameters<ElectronAPI['onNewSession']>) => getElectronAPI()?.onNewSession(...args),
  onExportDebate: (...args: Parameters<ElectronAPI['onExportDebate']>) => getElectronAPI()?.onExportDebate(...args),
  onOpenSettings: (...args: Parameters<ElectronAPI['onOpenSettings']>) => getElectronAPI()?.onOpenSettings(...args),
}
