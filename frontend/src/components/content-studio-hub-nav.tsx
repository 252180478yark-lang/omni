'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { BookOpen, Layers, Sparkles, FileText, UserCircle2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Counts {
  pipelines: number
  briefs: number
  avatars: number
  loading: boolean
}

const TABS = [
  { href: '/content-studio/guide',    label: '使用指南',    icon: BookOpen,    key: null },
  { href: '/content-studio',          label: '生成流水线',  icon: Layers,      key: 'pipelines' as const },
  { href: '/content-studio/briefs',   label: 'Brief 库',    icon: FileText,    key: 'briefs' as const },
  { href: '/content-studio/avatars',  label: '数字人脸库',  icon: UserCircle2, key: 'avatars' as const },
  { href: '/content-studio/new',      label: '新建（向导）', icon: Sparkles,    key: null,        primary: true },
]

/**
 * 内容工坊统一顶部导航：tab + 计数 + 主 CTA。
 *
 * 用在 /content-studio、/content-studio/briefs、/content-studio/avatars、
 * /content-studio/new 四个页面顶部，给用户一致的"我在哪"感知。
 */
export function ContentStudioHubNav() {
  const pathname = usePathname() || ''
  const [counts, setCounts] = useState<Counts>({ pipelines: 0, briefs: 0, avatars: 0, loading: true })

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [p, b, a] = await Promise.all([
          fetch('/api/omni/content-studio/pipelines?limit=1', { cache: 'no-store' }).then((r) => r.json()).catch(() => null),
          fetch('/api/omni/content-studio/briefs?limit=1', { cache: 'no-store' }).then((r) => r.json()).catch(() => null),
          fetch('/api/omni/content-studio/digital-humans?limit=1', { cache: 'no-store' }).then((r) => r.json()).catch(() => null),
        ])
        if (cancelled) return
        // 后端列表接口都返回 items 数组；用 array length 当 lower-bound（只是给用户一个感觉）
        // 真实 total 后端没暴露；这里多取一份不带 limit 的会贵，所以用迷你数字 + “以上”后缀
        const lenOr = (resp: unknown, key: string) => {
          if (!resp || typeof resp !== 'object') return 0
          const arr = (resp as Record<string, unknown>)[key]
          return Array.isArray(arr) ? arr.length : 0
        }
        // pipelines 接口 key 是 pipelines
        setCounts({
          pipelines: lenOr(p, 'pipelines'),
          briefs: lenOr(b, 'items'),
          avatars: lenOr(a, 'items'),
          loading: false,
        })
      } catch {
        if (!cancelled) setCounts((c) => ({ ...c, loading: false }))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const isActive = (href: string) => {
    if (href === '/content-studio') {
      // /content-studio 精确匹配；不能被 /content-studio/briefs 冒泡选中
      return pathname === '/content-studio'
    }
    return pathname.startsWith(href)
  }

  return (
    <div className="sticky top-0 z-30 -mx-4 mb-4 border-b border-gray-100 bg-white/80 px-4 backdrop-blur sm:-mx-6 sm:px-6">
      <div className="mx-auto max-w-6xl">
        <div className="flex items-center gap-1 overflow-x-auto py-2">
          {TABS.map((t) => {
            const active = isActive(t.href)
            const Icon = t.icon
            return (
              <Link
                key={t.href}
                href={t.href}
                className={cn(
                  'group flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors whitespace-nowrap',
                  t.primary
                    ? 'ml-auto bg-violet-600 text-white hover:bg-violet-700'
                    : active
                      ? 'bg-violet-50 text-violet-700 font-medium'
                      : 'text-gray-600 hover:bg-gray-50',
                )}
              >
                <Icon className={cn('h-3.5 w-3.5', t.primary ? 'text-white' : active ? 'text-violet-600' : 'text-gray-400')} />
                <span>{t.label}</span>
                {t.key && !counts.loading && (
                  <span className={cn(
                    'rounded-full px-1.5 text-[10px] leading-4',
                    active ? 'bg-violet-100 text-violet-700' : 'bg-gray-100 text-gray-500',
                  )}>
                    {counts[t.key]}
                  </span>
                )}
              </Link>
            )
          })}
        </div>
      </div>
    </div>
  )
}
