import { X } from 'lucide-react'
import { useUIStore } from '@/stores/tri-mind/uiStore'
import { useConfigStore } from '@/stores/tri-mind/configStore'
import { cn } from '@/lib/utils'
import { ModelSelector } from './ModelSelector'
import { RateTable } from './RateTable'

export function SettingsDialog() {
  const { settingsOpen, setSettingsOpen, settingsTab, setSettingsTab } = useUIStore()

  if (!settingsOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={() => setSettingsOpen(false)}
      />

      {/* 对话框 */}
      <div className="relative w-full max-w-3xl max-h-[80vh] apple-card rounded-2xl shadow-xl overflow-hidden border border-gray-200/50">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200/50">
          <h2 className="text-lg font-semibold">设置</h2>
          <button
            onClick={() => setSettingsOpen(false)}
            className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 标签页 */}
        <div className="flex border-b border-gray-200/50">
          <button
            onClick={() => setSettingsTab('models')}
            className={cn(
              'px-6 py-3 text-sm font-medium transition-colors',
              settingsTab === 'models'
                ? 'text-blue-600 border-b-2 border-blue-600'
                : 'text-gray-500 hover:text-gray-900'
            )}
          >
            模型配置
          </button>
          <button
            onClick={() => setSettingsTab('rates')}
            className={cn(
              'px-6 py-3 text-sm font-medium transition-colors',
              settingsTab === 'rates'
                ? 'text-blue-600 border-b-2 border-blue-600'
                : 'text-gray-500 hover:text-gray-900'
            )}
          >
            费率设置
          </button>
          <button
            onClick={() => setSettingsTab('general')}
            className={cn(
              'px-6 py-3 text-sm font-medium transition-colors',
              settingsTab === 'general'
                ? 'text-blue-600 border-b-2 border-blue-600'
                : 'text-gray-500 hover:text-gray-900'
            )}
          >
            通用设置
          </button>
        </div>

        {/* 内容区域 */}
        <div className="p-6 overflow-y-auto max-h-[calc(80vh-140px)]">
          {settingsTab === 'models' ? (
            <ModelSelector />
          ) : settingsTab === 'rates' ? (
            <RateTable />
          ) : (
            <GeneralSettings />
          )}
        </div>
      </div>
    </div>
  )
}

function GeneralSettings() {
  const { theme, setTheme } = useUIStore()
  const { reportDetailLevel, setReportDetailLevel } = useConfigStore()

  return (
    <div className="space-y-6">
      {/* 主题设置 */}
      <div>
        <h3 className="text-sm font-medium mb-3">主题</h3>
        <div className="flex gap-2">
          {(['light', 'dark', 'system'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTheme(t)}
              className={cn(
                'px-4 py-2 rounded-lg text-sm transition-colors',
                theme === t
                  ? 'bg-gradient-to-r from-blue-600 to-purple-500 text-white'
                  : 'bg-gray-100 hover:bg-gray-200'
              )}
            >
              {t === 'light' ? '浅色' : t === 'dark' ? '深色' : '跟随系统'}
            </button>
          ))}
        </div>
      </div>

      {/* 关于 */}
      <div>
        <h3 className="text-sm font-medium mb-3">报告详细度</h3>
        <div className="grid grid-cols-3 gap-2">
          {([
            { id: 'brief', label: '简略', desc: '重点结论，短篇输出' },
            { id: 'standard', label: '标准', desc: '平衡细节与可读性' },
            { id: 'detailed', label: '详细', desc: '深度分析，长篇报告' },
          ] as const).map((item) => (
            <button
              key={item.id}
              onClick={() => setReportDetailLevel(item.id)}
              className={cn(
                'p-3 rounded-lg text-left transition-colors border',
                reportDetailLevel === item.id
                  ? 'border-blue-500 bg-blue-50 text-blue-600'
                  : 'border-gray-200 bg-gray-50 hover:bg-gray-100'
              )}
            >
              <p className="text-sm font-medium">{item.label}</p>
              <p className="text-xs text-gray-500 mt-1">{item.desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* 关于 */}
      <div>
        <h3 className="text-sm font-medium mb-3">关于</h3>
        <div className="bg-gray-100 rounded-xl p-4">
          <p className="text-sm text-gray-500">
            <strong>Tri-Mind Synthesizer</strong> v1.0.0
          </p>
          <p className="text-sm text-muted-foreground mt-2">
            多模型辩论工具 - 让多个LLM针对同一问题进行并发对比、交叉质疑与综合裁决。
          </p>
          <p className="text-xs text-gray-500 mt-3">
            技术栈: Electron + React 19 + TypeScript + Vite + Zustand + Tailwind CSS
          </p>
        </div>
      </div>
    </div>
  )
}
