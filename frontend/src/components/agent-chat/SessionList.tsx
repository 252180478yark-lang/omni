'use client'
import { useEffect, useState } from 'react'
import { Plus, MessageSquare, Trash2, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface SessionRow {
  id: string
  title: string
  sku_id: string | null
  last_message_preview: string | null
  message_count: number
  updated_at: string
}

interface Props {
  currentId: string | null
  onSelect: (id: string) => void
  /** 移动端: 是否打开抽屉。大屏自动忽略 */
  mobileOpen?: boolean
  /** 移动端: 关闭抽屉回调 */
  onClose?: () => void
}

export function SessionList({ currentId, onSelect, mobileOpen = false, onClose }: Props) {
  const [list, setList] = useState<SessionRow[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const r = await fetch('/api/agent-chat/sessions', { cache: 'no-store' })
      const j = await r.json()
      if (j.success) setList(j.data)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { refresh() }, [])

  const createNew = async () => {
    const r = await fetch('/api/agent-chat/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    const j = await r.json()
    if (j.success) {
      await refresh()
      onSelect(j.data.id)
    }
  }

  const removeOne = async (id: string) => {
    if (!confirm('删除这个对话？')) return
    await fetch(`/api/agent-chat/sessions/${id}`, { method: 'DELETE' })
    await refresh()
    if (currentId === id) onSelect('')
  }

  return (
    <aside
      className={cn(
        // 基础: 大屏 static, 小屏 fixed 抽屉
        'border-r border-gray-100 bg-white flex flex-col',
        // 大屏: 64 宽固定
        'md:static md:w-64 md:translate-x-0',
        // 小屏: fixed 抽屉, 默认 -translate 隐藏, mobileOpen=true 滑入
        'fixed inset-y-0 left-0 z-50 w-72 transition-transform duration-200',
        mobileOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full',
      )}
    >
      <div className="px-4 h-14 border-b border-gray-100 flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-700">对话</span>
        <div className="flex items-center gap-1">
          <button
            onClick={createNew}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-600 text-white text-xs hover:bg-violet-700"
          >
            <Plus className="w-3.5 h-3.5" />
            新建
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="md:hidden p-1.5 rounded-md text-gray-500 hover:bg-gray-100"
              aria-label="关闭"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto py-2 space-y-1 px-2">
        {loading && <div className="px-3 py-2 text-xs text-gray-400">加载中...</div>}
        {!loading && list.length === 0 && (
          <div className="px-3 py-8 text-center text-xs text-gray-400">还没有对话<br />点新建开始</div>
        )}
        {list.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={cn(
              'w-full text-left px-3 py-2 rounded-lg flex items-start gap-2 group relative transition-colors',
              currentId === s.id ? 'bg-violet-50 text-violet-700' : 'hover:bg-gray-50 text-gray-700',
            )}
          >
            <MessageSquare className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium truncate">{s.title}</div>
              {s.last_message_preview && (
                <div className="text-[10px] text-gray-400 truncate mt-0.5">{s.last_message_preview}</div>
              )}
              <div className="text-[9px] text-gray-300 mt-1">{new Date(s.updated_at).toLocaleString()}</div>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); removeOne(s.id) }}
              className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 shrink-0"
              title="删除"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </button>
        ))}
      </div>
    </aside>
  )
}
