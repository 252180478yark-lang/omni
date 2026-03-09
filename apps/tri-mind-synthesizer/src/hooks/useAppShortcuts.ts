import { useEffect } from 'react'
import { useChatStore } from '../stores/chatStore'
import { useUIStore } from '../stores/uiStore'
import { ipc } from '../lib/ipc'

/**
 * 全局快捷键Hook
 * 
 * 快捷键列表：
 * - Ctrl+Enter: 发送消息
 * - Esc: 停止生成
 * - Ctrl+N: 新建会话 (由菜单处理)
 * - Ctrl+,: 打开设置 (由菜单处理)
 * - Ctrl+Shift+E: 导出辩论 (由菜单处理)
 */
export function useAppShortcuts() {
  const { isGenerating, stopGeneration } = useChatStore()
  const { setSettingsOpen } = useUIStore()

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Enter: 发送消息
      if (e.ctrlKey && e.key === 'Enter') {
        e.preventDefault()
        // 触发发送（由输入组件处理具体逻辑）
        const event = new CustomEvent('app:send-message')
        window.dispatchEvent(event)
      }

      // Esc: 停止生成
      if (e.key === 'Escape' && isGenerating) {
        e.preventDefault()
        stopGeneration()
      }
    }

    // 监听导出事件（来自菜单或快捷键）
    const handleExportDebate = () => {
      const sessionId = useChatStore.getState().sessionId
      if (!sessionId) {
        console.warn('没有活跃会话，无法导出')
        return
      }
      // 默认导出 Markdown 格式
      ipc.exportDebate?.({ sessionId, format: 'md' })
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('app:export-debate', handleExportDebate)

    // 监听菜单事件
    const cleanupNewSession = ipc.onNewSession?.(() => {
      const event = new CustomEvent('app:new-session')
      window.dispatchEvent(event)
    })

    const cleanupOpenSettings = ipc.onOpenSettings?.(() => {
      setSettingsOpen(true)
    })

    const cleanupExportDebate = ipc.onExportDebate?.(() => {
      const event = new CustomEvent('app:export-debate')
      window.dispatchEvent(event)
    })

    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('app:export-debate', handleExportDebate)
      cleanupNewSession?.()
      cleanupOpenSettings?.()
      cleanupExportDebate?.()
    }
  }, [isGenerating, stopGeneration, setSettingsOpen])
}
