'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { History, Loader2, MessageSquarePlus, Pencil, Search, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  deleteSession,
  listSessions,
  loadSessionMessages,
  renameSession,
  type ChatSessionMeta,
} from '@/lib/chat-sessions-api'
import { useChatStore } from '@/stores/chatStore'

interface ChatHistoryPanelProps {
  open: boolean
  onClose: () => void
  onNewSession: () => void
}

function formatRelative(ts: string | null): string {
  if (!ts) return ''
  const t = Date.parse(ts)
  if (Number.isNaN(t)) return ''
  const diff = (Date.now() - t) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  try {
    return new Date(t).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
  } catch {
    return ''
  }
}

export function ChatHistoryPanel({ open, onClose, onNewSession }: ChatHistoryPanelProps) {
  const currentSessionId = useChatStore((s) => s.sessionId)
  const loadSession = useChatStore((s) => s.loadSession)

  const [sessions, setSessions] = useState<ChatSessionMeta[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [switchingId, setSwitchingId] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await listSessions({ search: search.trim() || undefined, limit: 80 })
      setSessions(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [search])

  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  // 当 chat 页触发新一轮对话后，外部可调用 refresh；这里再挂一个 window 事件
  useEffect(() => {
    if (!open) return
    const handler = () => void refresh()
    window.addEventListener('omni-chat-sessions-refresh', handler)
    return () => window.removeEventListener('omni-chat-sessions-refresh', handler)
  }, [open, refresh])

  const visible = useMemo(() => sessions, [sessions])

  const handleSwitch = async (id: string) => {
    if (id === currentSessionId) {
      onClose()
      return
    }
    setSwitchingId(id)
    try {
      const { session, messages } = await loadSessionMessages(id)
      loadSession(session.id, messages, session.kb_ids || undefined)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSwitchingId(null)
    }
  }

  const handleDelete = async (id: string) => {
    if (!window.confirm('确定删除这条会话？（仅软删除，不影响其他用户）')) return
    try {
      await deleteSession(id)
      setSessions((prev) => prev.filter((s) => s.id !== id))
      // 如果删的是当前会话，开启新会话
      if (id === currentSessionId) {
        onNewSession()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const startEdit = (s: ChatSessionMeta) => {
    setEditingId(s.id)
    setEditValue(s.title || '')
  }

  const commitEdit = async () => {
    if (!editingId) return
    const id = editingId
    const title = editValue.trim()
    setEditingId(null)
    if (!title) return
    try {
      const updated = await renameSession(id, title)
      setSessions((prev) => prev.map((s) => (s.id === id ? updated : s)))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  if (!open) return null

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Drawer */}
      <aside className="fixed top-0 left-0 z-50 flex h-full w-[320px] max-w-[85vw] flex-col border-r border-gray-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-violet-500" />
            <span className="text-sm font-semibold text-gray-800">历史对话</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-2 border-b border-gray-100 px-3 py-2">
          <Button
            onClick={() => {
              onNewSession()
              onClose()
            }}
            className="w-full justify-center gap-2 rounded-lg bg-gradient-to-r from-violet-600 to-purple-500 text-white shadow-sm hover:from-violet-700 hover:to-purple-600"
            size="sm"
          >
            <MessageSquarePlus className="h-4 w-4" />
            新建对话
          </Button>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索标题 / 消息内容..."
              className="h-8 pl-8 pr-8 text-sm"
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                aria-label="清空搜索"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-gray-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中...
            </div>
          )}
          {!loading && visible.length === 0 && (
            <div className="px-4 py-10 text-center text-sm text-gray-400">
              {search ? '没有匹配的会话' : '还没有历史对话'}
            </div>
          )}
          {error && (
            <div className="mx-3 my-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
              {error}
            </div>
          )}
          <ul className="space-y-1 px-2 pb-4">
            {visible.map((s) => {
              const active = s.id === currentSessionId
              const isEditing = editingId === s.id
              const displayTitle = s.title || '未命名对话'
              return (
                <li
                  key={s.id}
                  className={`group relative rounded-lg border transition-colors ${
                    active
                      ? 'border-violet-300 bg-violet-50/70'
                      : 'border-transparent hover:border-gray-200 hover:bg-gray-50'
                  }`}
                >
                  {isEditing ? (
                    <div className="flex items-center gap-1 px-2 py-1.5">
                      <Input
                        autoFocus
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') void commitEdit()
                          if (e.key === 'Escape') setEditingId(null)
                        }}
                        onBlur={() => void commitEdit()}
                        className="h-7 text-sm"
                      />
                    </div>
                  ) : (
                    <button
                      onClick={() => void handleSwitch(s.id)}
                      disabled={switchingId === s.id}
                      className="flex w-full items-start gap-2 px-3 py-2 text-left"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span
                            className={`truncate text-sm ${
                              active ? 'font-semibold text-violet-700' : 'text-gray-800'
                            }`}
                          >
                            {displayTitle}
                          </span>
                          {switchingId === s.id && (
                            <Loader2 className="h-3 w-3 shrink-0 animate-spin text-violet-400" />
                          )}
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-[10px] text-gray-400">
                          <span>{s.message_count} 条</span>
                          <span>·</span>
                          <span>{formatRelative(s.last_message_at || s.updated_at)}</span>
                        </div>
                      </div>
                      <div className="hidden shrink-0 items-center gap-0.5 group-hover:flex">
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => {
                            e.stopPropagation()
                            startEdit(s)
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.stopPropagation()
                              e.preventDefault()
                              startEdit(s)
                            }
                          }}
                          className="cursor-pointer rounded p-1 text-gray-400 transition-colors hover:bg-gray-200 hover:text-gray-700"
                          title="重命名"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </span>
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => {
                            e.stopPropagation()
                            void handleDelete(s.id)
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.stopPropagation()
                              e.preventDefault()
                              void handleDelete(s.id)
                            }
                          }}
                          className="cursor-pointer rounded p-1 text-gray-400 transition-colors hover:bg-red-100 hover:text-red-600"
                          title="删除"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </span>
                      </div>
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      </aside>
    </>
  )
}
