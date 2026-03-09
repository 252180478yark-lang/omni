import { useEffect, useState } from 'react'
import { MessageSquarePlus, MessageSquare, Trash2, ChevronLeft } from 'lucide-react'
import { cn, formatTimestamp, truncateText } from '../../lib/utils'
import { useUIStore } from '../../stores/uiStore'
import { useChatStore } from '../../stores/chatStore'
import { ipc } from '../../lib/ipc'
import { Session } from '../../lib/types'

export function Sidebar() {
  const { sidebarOpen, toggleSidebar } = useUIStore()
  const { sessionId, createNewSession, setSession, resetSession, loadSessionHistory } = useChatStore()
  const [sessions, setSessions] = useState<Session[]>([])

  // 加载会话列表
  useEffect(() => {
    loadSessions()
    
    // 监听新建会话事件
    const handleNewSession = () => {
      handleCreateSession()
    }
    window.addEventListener('app:new-session', handleNewSession)
    
    return () => {
      window.removeEventListener('app:new-session', handleNewSession)
    }
  }, [])

  const loadSessions = async () => {
    const result = await ipc.listSessions?.()
    if (result?.success && result.data) {
      setSessions(result.data)
    }
  }

  const handleCreateSession = async () => {
    await createNewSession()
    loadSessions()
  }

  const handleSelectSession = async (session: Session) => {
    // 不停止旧辩论，让它在后台继续跑
    // 只清除前端状态并加载目标会话
    resetSession()
    await loadSessionHistory(session.id)
  }

  const handleDeleteSession = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    await ipc.deleteSession?.(id)
    if (sessionId === id) {
      setSession(null)
      resetSession()
    }
    loadSessions()
  }

  return (
    <>
      {/* 侧边栏 */}
      <aside
        className={cn(
          'fixed left-0 top-0 h-full w-64 apple-card border-r border-gray-200/50',
          'flex flex-col transition-transform duration-300 z-40 shadow-sm',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200/50">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-600 to-purple-500 flex items-center justify-center shadow-md">
              <MessageSquare className="w-5 h-5 text-white" />
            </div>
            <h1 className="text-lg font-semibold text-gray-900">Tri-Mind</h1>
          </div>
          <button
            onClick={toggleSidebar}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 transition-colors"
            title="收起侧边栏"
          >
            <ChevronLeft className="w-5 h-5" />
          </button>
        </div>

        {/* 新建按钮 */}
        <div className="p-3">
          <button
            onClick={handleCreateSession}
            className={cn(
              'w-full flex items-center gap-2 px-3 py-2.5 rounded-xl',
              'bg-gradient-to-r from-blue-600 to-purple-500 text-white shadow-md',
              'hover:shadow-lg hover:opacity-95 transition-all'
            )}
          >
            <MessageSquarePlus className="w-5 h-5" />
            <span>新建会话</span>
          </button>
        </div>

        {/* 会话列表 */}
        <div className="flex-1 overflow-y-auto px-3 pb-3">
          <div className="space-y-1">
            {sessions.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                暂无会话
              </p>
            ) : (
              sessions.map((session) => (
                <div
                  key={session.id}
                  onClick={() => handleSelectSession(session)}
                  className={cn(
                    'group flex items-center gap-2 px-3 py-2.5 rounded-xl cursor-pointer',
                    'hover:bg-gray-100 transition-colors',
                    sessionId === session.id && 'bg-gray-100'
                  )}
                >
                  <MessageSquare className="w-4 h-4 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-900 truncate">
                      {truncateText(session.title, 20)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {formatTimestamp(session.updatedAt)}
                    </p>
                  </div>
                  <button
                    onClick={(e) => handleDeleteSession(e, session.id)}
                    className={cn(
                      'p-1 rounded opacity-0 group-hover:opacity-100',
                      'hover:bg-destructive/10 text-destructive',
                      'transition-opacity'
                    )}
                    title="删除会话"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* 底部信息 */}
        <div className="p-4 border-t border-gray-200/50">
          <p className="text-xs text-muted-foreground text-center">
            v1.0.0 MVP
          </p>
        </div>
      </aside>

      {/* 展开按钮（侧边栏收起时显示） */}
      {!sidebarOpen && (
        <button
          onClick={toggleSidebar}
          className={cn(
            'fixed left-4 top-4 z-50 p-2 rounded-xl',
            'apple-card border border-gray-200/50 shadow-sm',
            'hover:shadow-md transition-all'
          )}
          title="展开侧边栏"
        >
          <MessageSquare className="w-5 h-5 text-gray-900" />
        </button>
      )}
    </>
  )
}
