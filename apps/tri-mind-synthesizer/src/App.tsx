import { AppLayout } from './components/layout/AppLayout'
import { useAppShortcuts } from './hooks/useAppShortcuts'
import { useStreamHandler } from './hooks/useStreamHandler'
import { useEffect } from 'react'
import { useConfigStore } from './stores/configStore'

function App() {
  const initConfig = useConfigStore((state) => state.initConfig)

  // 注册全局快捷键
  useAppShortcuts()
  
  // 注册流式数据处理
  useStreamHandler()

  // 启动时从主进程加载模型配置和 API Key 状态
  useEffect(() => {
    initConfig()
  }, [initConfig])

  return (
    <div className="h-screen w-screen overflow-hidden bg-[#F5F5F7] text-gray-900 antialiased">
      <AppLayout />
    </div>
  )
}

export default App
