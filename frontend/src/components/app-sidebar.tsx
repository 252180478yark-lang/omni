'use client'

import React, { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'
import { featuresForPlacement, type FeatureRegistryEntry } from '@/lib/feature-registry'
import {
  BrainCircuit,
  BookOpen,
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
  ChevronDown,
  RefreshCw,
  Sparkles,
  Palette,
  Wand2,
  Inbox,
  Package,
  ScanSearch,
  ClipboardCheck,
  CalendarDays,
  Calculator,
  Activity,
  Brain,
  FlaskConical,
  Send,
  Trophy,
  Network,
  type LucideIcon,
} from 'lucide-react'

interface NavItem {
  href: string
  icon: LucideIcon
  label: string
  /** 一句话讲清楚这个菜单是干嘛的，给小白看 */
  hint: string
  badge?: string
}

interface NavGroup {
  id: string
  icon: LucideIcon
  label: string
  hint: string
  defaultHref: string
  children: NavItem[]
}

interface NavSection {
  kind: 'section'
  label: string
}

type NavEntry = NavItem | NavGroup | NavSection

function isGroup(entry: NavEntry): entry is NavGroup {
  return 'children' in entry
}

function isSection(entry: NavEntry): entry is NavSection {
  return (entry as NavSection).kind === 'section'
}

const SIDEBAR_PRESENTATION: Record<string, { icon: LucideIcon; hint: string; section: string; order: number }> = {
  'workspace-operations': { icon: Inbox, hint: '经营、开发与执行共用的统一入口', section: '工作流', order: 10 },
  'product-management': { icon: Package, hint: 'SKU 数据、资产、动作与诊断', section: '工作流', order: 20 },
  'scout-monitoring': { icon: ScanSearch, hint: '自动采集与异动检测', section: '数据与采集', order: 30 },
  'sku-pipeline': { icon: Sparkles, hint: '按封闭操作契约运行 SKU 前链路', section: '内容生产', order: 40 },
  'reverse-engineer': { icon: Wand2, hint: '把素材拆成可复用镜头和提示词', section: '内容生产', order: 50 },
  'cost-management': { icon: Calculator, hint: '结构化成本与利润核算', section: '投放与复盘', order: 60 },
  'commerce-feedback': { icon: Send, hint: '把投后真实指标写回血缘', section: '投放与复盘', order: 70 },
  'approval-inbox': { icon: ClipboardCheck, hint: '查看和处理显式审批 Gate', section: '投放与复盘', order: 80 },
  'system-console': { icon: Home, hint: '系统服务、指标与健康监控', section: '系统', order: 90 },
}

function projectedNavItem(feature: FeatureRegistryEntry): NavItem {
  const presentation = SIDEBAR_PRESENTATION[feature.feature_id] || { icon: Network, hint: feature.domain, section: '其他', order: 999 }
  return { href: feature.href, label: feature.title, icon: presentation.icon, hint: presentation.hint }
}

const NAV_ITEMS: NavEntry[] = (() => {
  const result: NavEntry[] = []
  let section = ''
  const features = featuresForPlacement('sidebar').sort((a, b) => (SIDEBAR_PRESENTATION[a.feature_id]?.order ?? 999) - (SIDEBAR_PRESENTATION[b.feature_id]?.order ?? 999))
  for (const feature of features) {
    const nextSection = SIDEBAR_PRESENTATION[feature.feature_id]?.section || '其他'
    if (nextSection !== section) {
      section = nextSection
      result.push({ kind: 'section', label: section })
    }
    result.push(projectedNavItem(feature))
  }
  return result
})()

export function AppSidebar() {
  const pathname = usePathname()
  // 进入"内容工坊"任意子页时，默认展开侧边栏让用户能直接看到 Brief / 数字人脸 / 新建向导
  const [expanded, setExpanded] = useState(() => (pathname || '').startsWith('/content-studio'))
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {}
    if ((pathname || '').startsWith('/content-studio')) {
      initial['content-studio'] = true
    }
    return initial
  })

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/'
    return pathname.startsWith(href)
  }

  useEffect(() => {
    if ((pathname || '').startsWith('/content-studio')) {
      setExpanded(true)
    }
    NAV_ITEMS.forEach((entry) => {
      if (!isGroup(entry)) return
      const inThis = entry.children.some((c) => isActive(c.href))
      if (inThis && !openGroups[entry.id]) {
        setOpenGroups((s) => ({ ...s, [entry.id]: true }))
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname])

  const toggleGroup = (id: string) =>
    setOpenGroups((s) => ({ ...s, [id]: !s[id] }))

  const renderItem = (item: NavItem, isChild = false) => {
    const active = isActive(item.href)
    const Icon = item.icon
    return (
      <Link
        key={item.href}
        href={item.href}
        className={cn(
          'group relative flex items-center gap-3 rounded-xl transition-all duration-200',
          isChild ? 'pl-7 pr-2.5 py-1.5' : 'px-2.5 py-2.5',
          active
            ? 'bg-gradient-to-r from-violet-50 to-purple-50 text-violet-700'
            : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900',
        )}
      >
        {active && !isChild && (
          <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 rounded-r-full bg-violet-600" />
        )}
        {!isChild && (
          <div
            className={cn(
              'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-all duration-200',
              active
                ? 'bg-violet-600 text-white shadow-md shadow-violet-200/50'
                : 'bg-gray-100 text-gray-500 group-hover:bg-gray-200 group-hover:text-gray-700',
            )}
          >
            <Icon className="w-4 h-4" />
          </div>
        )}
        {isChild && <Icon className="w-3.5 h-3.5 shrink-0" />}
        {expanded && (
          <div
            className={cn(
              'min-w-0 flex-1 animate-in fade-in slide-in-from-left-2 duration-200',
            )}
          >
            <div
              className={cn(
                'truncate',
                isChild ? 'text-xs' : 'text-sm font-medium',
              )}
            >
              {item.label}
            </div>
            {!isChild && item.hint && (
              <div className="text-[10.5px] text-gray-400 truncate mt-0.5 leading-tight">
                {item.hint}
              </div>
            )}
            {isChild && item.hint && (
              <div className="text-[10px] text-gray-400 truncate leading-tight">
                {item.hint}
              </div>
            )}
          </div>
        )}
        {!expanded && !isChild && (
          <div className="absolute left-full ml-2 px-3 py-2 rounded-lg bg-gray-900 text-white text-xs whitespace-nowrap opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none shadow-lg z-50 max-w-[260px]">
            <div className="font-medium">{item.label}</div>
            {item.hint && (
              <div className="text-[10.5px] text-gray-300 mt-0.5 whitespace-normal leading-snug">
                {item.hint}
              </div>
            )}
            <div className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1 w-2 h-2 bg-gray-900 rotate-45" />
          </div>
        )}
      </Link>
    )
  }

  const renderSection = (section: NavSection, idx: number) => {
    if (!expanded) {
      // 收起态用一条细分隔线代替分组标题
      return (
        <div
          key={`section-${idx}`}
          className="mx-3 my-1.5 h-px bg-gray-200/60"
        />
      )
    }
    return (
      <div
        key={`section-${idx}`}
        className="px-3 pt-3 pb-1 first:pt-1"
      >
        <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400">
          {section.label}
        </div>
      </div>
    )
  }

  const renderGroup = (group: NavGroup) => {
    const Icon = group.icon
    const groupActive = group.children.some((c) => isActive(c.href))
    const open = openGroups[group.id] ?? groupActive

    if (!expanded) {
      return (
        <Link
          key={group.id}
          href={group.defaultHref}
          className={cn(
            'group relative flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-all duration-200',
            groupActive
              ? 'bg-gradient-to-r from-violet-50 to-purple-50 text-violet-700'
              : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900',
          )}
        >
          {groupActive && (
            <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 rounded-r-full bg-violet-600" />
          )}
          <div
            className={cn(
              'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-all duration-200',
              groupActive
                ? 'bg-violet-600 text-white shadow-md shadow-violet-200/50'
                : 'bg-gray-100 text-gray-500 group-hover:bg-gray-200 group-hover:text-gray-700',
            )}
          >
            <Icon className="w-4 h-4" />
          </div>
          <div className="absolute left-full ml-2 px-3 py-2 rounded-lg bg-gray-900 text-white text-xs whitespace-nowrap opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none shadow-lg z-50 max-w-[260px]">
            <div className="font-medium">{group.label}</div>
            {group.hint && (
              <div className="text-[10.5px] text-gray-300 mt-0.5 whitespace-normal leading-snug">
                {group.hint}
              </div>
            )}
            <div className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-1 w-2 h-2 bg-gray-900 rotate-45" />
          </div>
        </Link>
      )
    }

    return (
      <div key={group.id}>
        <button
          type="button"
          onClick={() => toggleGroup(group.id)}
          className={cn(
            'w-full group relative flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-all duration-200 text-left',
            groupActive
              ? 'bg-gradient-to-r from-violet-50 to-purple-50 text-violet-700'
              : 'text-gray-500 hover:bg-gray-50 hover:text-gray-900',
          )}
        >
          {groupActive && (
            <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 rounded-r-full bg-violet-600" />
          )}
          <div
            className={cn(
              'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-all duration-200',
              groupActive
                ? 'bg-violet-600 text-white shadow-md shadow-violet-200/50'
                : 'bg-gray-100 text-gray-500 group-hover:bg-gray-200 group-hover:text-gray-700',
            )}
          >
            <Icon className="w-4 h-4" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate">{group.label}</div>
            {group.hint && (
              <div className="text-[10.5px] text-gray-400 truncate mt-0.5 leading-tight">
                {group.hint}
              </div>
            )}
          </div>
          {open ? (
            <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-gray-400 shrink-0" />
          )}
        </button>
        {open && (
          <div className="mt-0.5 mb-1 space-y-0.5">
            {group.children.map((c) => renderItem(c, true))}
          </div>
        )}
      </div>
    )
  }

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-[60] h-screen flex flex-col bg-white border-r border-gray-100 transition-all duration-300 ease-in-out shadow-sm',
        expanded ? 'w-60' : 'w-[68px]',
      )}
    >
      {/* Logo */}
      <div className="flex items-center h-16 px-3 shrink-0 border-b border-gray-100">
        <Link href="/workspace" className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-600 to-purple-500 flex items-center justify-center shadow-lg shadow-purple-200/50 shrink-0">
            <BrainCircuit className="w-5 h-5 text-white" />
          </div>
          {expanded && (
            <div className="flex flex-col min-w-0 animate-in fade-in slide-in-from-left-2 duration-200">
              <span className="font-bold text-sm text-gray-900 truncate">Omni-Vibe</span>
              <span className="text-[10px] text-gray-400 truncate">你的 AI 万能小助理</span>
            </div>
          )}
        </Link>
      </div>

      {/* Hint banner when expanded */}
      {expanded && (
        <div className="px-3 pt-3 pb-1 animate-in fade-in slide-in-from-top-1 duration-300">
          <div className="rounded-lg bg-gradient-to-br from-violet-50 to-purple-50 border border-violet-100/60 px-3 py-2">
            <p className="text-[10.5px] text-gray-500 leading-relaxed">
              每天先看「工作台」，遇到异动点 SKU 卡片进诊断，做完动作记得登记。
            </p>
          </div>
        </div>
      )}

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden py-3 px-2.5 space-y-1 scrollbar-hide">
        {NAV_ITEMS.map((entry, idx) => {
          if (isSection(entry)) return renderSection(entry, idx)
          if (isGroup(entry)) return renderGroup(entry)
          return renderItem(entry)
        })}
      </nav>

      {/* Toggle */}
      <div className="px-2.5 py-3 border-t border-gray-100 shrink-0">
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-center gap-2 rounded-xl px-2.5 py-2 text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-all duration-200"
        >
          {expanded ? (
            <>
              <ChevronLeft className="w-4 h-4 shrink-0" />
              <span className="text-xs font-medium animate-in fade-in duration-200">收起菜单</span>
            </>
          ) : (
            <ChevronRight className="w-4 h-4" />
          )}
        </button>
      </div>
    </aside>
  )
}
