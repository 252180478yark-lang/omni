'use client'

import React, { useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'
import {
  BrainCircuit,
  MessageSquare,
  Database,
  Newspaper,
  Cpu,
  Download,
  ListTodo,
  Clapperboard,
  Radio,
  LineChart,
  Home,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Palette,
} from 'lucide-react'

interface NavItem {
  href: string
  icon: React.ElementType
  label: string
  badge?: string
}

const NAV_ITEMS: NavItem[] = [
  { href: '/', icon: Home, label: '控制台' },
  { href: '/chat', icon: MessageSquare, label: '智能问答' },
  { href: '/knowledge', icon: Database, label: '知识库' },
  { href: '/knowledge/harvester', icon: Download, label: '知识采集' },
  { href: '/news', icon: Newspaper, label: '资讯中心' },
  { href: '/models', icon: Cpu, label: '模型配置' },
  { href: '/tasks', icon: ListTodo, label: '任务进度' },
  { href: '/video-analysis', icon: Clapperboard, label: '短视频分析' },
  { href: '/livestream-analysis', icon: Radio, label: '直播分析' },
  { href: '/ad-review', icon: LineChart, label: '投放复盘' },
  { href: '/content-studio', icon: Palette, label: '内容工坊' },
]

export function AppSidebar() {
  const pathname = usePathname()
  const [expanded, setExpanded] = useState(false)

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/'
    return pathname.startsWith(href)
  }

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-[60] h-screen flex flex-col bg-white border-r border-gray-100 transition-all duration-300 ease-in-out shadow-sm',
        expanded ? 'w-56' : 'w-[68px]',
      )}
    >
      {/* Logo */}
      <div className="flex items-center h-16 px-3 shrink-0 border-b border-gray-100">
        <Link href="/" className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600 to-purple-500 flex items-center justify-center shadow-lg shadow-purple-200/50 shrink-0">
            <BrainCircuit className="w-5 h-5 text-white" />
          </div>
          {expanded && (
            <div className="flex flex-col min-w-0 animate-in fade-in slide-in-from-left-2 duration-200">
              <span className="font-bold text-sm text-gray-900 truncate">Omni-Vibe</span>
              <span className="text-[10px] text-gray-400 truncate">OS Ultra</span>
            </div>
          )}
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden py-4 px-2.5 space-y-1 scrollbar-hide">
        {NAV_ITEMS.map((item) => {
          const active = isActive(item.href)
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'group relative flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-all duration-200',
                active
                  ? 'bg-gradient-to-r from-violet-50 to-purple-50 text-violet-700'
                  : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900',
              )}
            >
              {active && (
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 rounded-r-full bg-violet-600" />
              )}
              <div
                className={cn(
                  'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-all duration-200',
                  active
                    ? 'bg-violet-600 text-white shadow-md shadow-violet-200/50'
                    : 'bg-gray-100 text-gray-500 group-hover:bg-gray-200 group-hover:text-gray-700',
                )}
              >
                <item.icon className="w-4 h-4" />
              </div>
              {expanded && (
                <span className="text-sm font-medium truncate animate-in fade-in slide-in-from-left-2 duration-200">
                  {item.label}
                </span>
              )}
              {!expanded && (
                <div className="absolute left-full ml-2 px-2.5 py-1.5 rounded-lg bg-gray-900 text-white text-xs font-medium whitespace-nowrap opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none shadow-lg z-50">
                  {item.label}
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1 w-2 h-2 bg-gray-900 rotate-45" />
                </div>
              )}
            </Link>
          )
        })}
      </nav>

      {/* Quick AI Access */}
      <div className="px-2.5 pb-2">
        <Link
          href="/chat"
          className={cn(
            'flex items-center gap-3 rounded-xl px-2.5 py-2.5 bg-gradient-to-r from-violet-600 to-purple-500 text-white shadow-lg shadow-purple-300/30 hover:shadow-purple-300/50 transition-all duration-200',
          )}
        >
          <div className="w-8 h-8 rounded-lg bg-white/20 flex items-center justify-center shrink-0">
            <Sparkles className="w-4 h-4" />
          </div>
          {expanded && (
            <span className="text-sm font-medium truncate animate-in fade-in slide-in-from-left-2 duration-200">
              AI 对话
            </span>
          )}
        </Link>
      </div>

      {/* Toggle */}
      <div className="px-2.5 py-3 border-t border-gray-100 shrink-0">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-center gap-3 rounded-xl px-2.5 py-2 text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-all duration-200"
        >
          {expanded ? (
            <>
              <ChevronLeft className="w-4 h-4 shrink-0" />
              <span className="text-xs font-medium animate-in fade-in duration-200">收起</span>
            </>
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </button>
      </div>
    </aside>
  )
}
