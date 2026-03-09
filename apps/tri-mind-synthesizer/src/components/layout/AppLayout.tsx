import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { ChatGrid } from '../chat/ChatGrid'
import { ControlPanel } from '../control/ControlPanel'
import { SettingsDialog } from '../settings/SettingsDialog'
import { useUIStore } from '../../stores/uiStore'
import { cn } from '../../lib/utils'

export function AppLayout() {
  const { sidebarOpen } = useUIStore()

  return (
    <div className="flex h-full">
      {/* 侧边栏 */}
      <Sidebar />

      {/* 主内容区 */}
      <div
        className={cn(
          'flex flex-col flex-1 h-full transition-all duration-300',
          sidebarOpen ? 'ml-64' : 'ml-0'
        )}
      >
        {/* 顶部工具栏 */}
        <Header />

        {/* 聊天区域 */}
        <main className="flex-1 overflow-hidden">
          <ChatGrid />
        </main>

        {/* 底部输入区 */}
        <ControlPanel />
      </div>

      {/* 设置弹窗 */}
      <SettingsDialog />
    </div>
  )
}
