import { useRef, useEffect, useState } from 'react'
import { Send, Square, Paperclip } from 'lucide-react'
import { useChatStore } from '../../stores/chatStore'
import { useConfigStore } from '../../stores/configStore'
import { cn } from '../../lib/utils'
import { RoundControl } from './RoundControl'
import { Dropzone } from './Dropzone'
import { FileAttachment } from '../../lib/types'

export function ControlPanel() {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { 
    inputValue, 
    setInputValue, 
    sendMessage, 
    stopGeneration, 
    isGenerating,
    totalRounds,
    setRounds,
  } = useChatStore()
  
  // 文件附件状态
  const [files, setFiles] = useState<FileAttachment[]>([])
  const [showDropzone, setShowDropzone] = useState(false)
  
  // 从 configStore 实时获取启用的模型数量
  const { providers } = useConfigStore()
  const hasEnabledModels = providers.some(p => p.enabled && p.models.some(m => m.enabled))

  // 自动调整文本框高度
  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px'
    }
  }, [inputValue])

  // 监听发送消息事件
  useEffect(() => {
    const handleSend = () => {
      if (!isGenerating && inputValue.trim()) {
        sendMessage(undefined, files.length > 0 ? files : undefined)
        setFiles([])
        setShowDropzone(false)
      }
    }
    window.addEventListener('app:send-message', handleSend)
    return () => window.removeEventListener('app:send-message', handleSend)
  }, [isGenerating, inputValue, sendMessage, files])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Ctrl+Enter 发送
    if (e.ctrlKey && e.key === 'Enter') {
      e.preventDefault()
      if (!isGenerating && inputValue.trim()) {
        sendMessage()
      }
    }
  }

  const handleSubmit = () => {
    if (!isGenerating && inputValue.trim()) {
      sendMessage(undefined, files.length > 0 ? files : undefined)
      // 发送后清除文件
      setFiles([])
      setShowDropzone(false)
    }
  }

  const canSend = !isGenerating && inputValue.trim() && hasEnabledModels

  return (
    <div className="border-t border-gray-200/50 glass p-4">
      <div className="max-w-4xl mx-auto">
        {/* 顶部控制栏 */}
        <div className="flex items-center justify-between mb-3">
          {/* 辩论轮数控制 */}
          <RoundControl
            rounds={totalRounds}
            onRoundsChange={setRounds}
            disabled={isGenerating}
          />
          
          {/* 快捷键提示 */}
          <div className="text-xs text-muted-foreground">
            <kbd className="px-1.5 py-0.5 bg-gray-200 rounded">Ctrl+Enter</kbd> 发送
            {isGenerating && (
              <>
                {' | '}
                <kbd className="px-1.5 py-0.5 bg-gray-200 rounded">Esc</kbd> 停止
              </>
            )}
          </div>
        </div>

        {/* 文件拖拽区域 */}
        {showDropzone && (
          <div className="mb-3">
            <Dropzone
              files={files}
              onFilesChange={setFiles}
              disabled={isGenerating}
            />
          </div>
        )}

        {/* 输入区域 */}
        <div className="flex gap-2">
          {/* 附件按钮 */}
          <button
            onClick={() => setShowDropzone(!showDropzone)}
            disabled={isGenerating}
            className={cn(
              'relative px-3 py-3 rounded-xl transition-colors',
              'hover:bg-gray-100',
              showDropzone && 'bg-gray-100 text-blue-600',
              isGenerating && 'opacity-50 cursor-not-allowed'
            )}
            title="添加文件"
          >
            <Paperclip className="w-5 h-5" />
            {files.length > 0 && (
              <span className="absolute -top-1 -right-1 bg-gradient-to-r from-blue-600 to-purple-500 text-white text-xs w-4 h-4 rounded-full flex items-center justify-center">
                {files.length}
              </span>
            )}
          </button>

          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                !hasEnabledModels
                  ? '请先在设置中启用至少一个模型...'
                  : '输入您的问题，让多个AI模型为您辩论...'
              }
              disabled={!hasEnabledModels}
              className={cn(
                'w-full px-4 py-3 rounded-xl resize-none',
                'bg-white border border-gray-200',
                'focus:outline-none focus:ring-2 focus:ring-blue-500/30',
                'placeholder:text-gray-400',
                'min-h-[52px] max-h-[200px]',
                !hasEnabledModels && 'opacity-50 cursor-not-allowed'
              )}
              rows={1}
            />
          </div>

          {/* 发送/停止按钮 */}
          {isGenerating ? (
            <button
              onClick={stopGeneration}
              className={cn(
                'px-4 py-3 rounded-lg',
                'bg-destructive text-destructive-foreground',
                'hover:bg-destructive/90 transition-colors',
                'flex items-center gap-2'
              )}
            >
              <Square className="w-5 h-5" />
              <span>停止</span>
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!canSend}
              className={cn(
                'px-4 py-3 rounded-xl',
                'bg-gradient-to-r from-blue-600 to-purple-500 text-white shadow-md',
                'hover:shadow-lg hover:opacity-95 transition-all',
                'flex items-center gap-2',
                !canSend && 'opacity-50 cursor-not-allowed'
              )}
            >
              <Send className="w-5 h-5" />
              <span>发送</span>
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
