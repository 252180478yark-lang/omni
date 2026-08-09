'use client'

import Link from 'next/link'
import {
  ArrowUpRight,
  BookOpenText,
  Clapperboard,
  Layers3,
  ScanSearch,
  type LucideIcon,
} from 'lucide-react'

import { workbenchNavigationForMode, type WorkbenchGroupId } from '@/lib/workbench-ia'

const GROUP_PRESENTATION: Record<
  Extract<WorkbenchGroupId, 'production' | 'analysis' | 'library'>,
  { icon: LucideIcon; eyebrow: string; description: string }
> = {
  production: {
    icon: Layers3,
    eyebrow: '01 / PRODUCE',
    description: '从 SKU、卖点和人群出发，进入正式内容生产链路。',
  },
  analysis: {
    icon: ScanSearch,
    eyebrow: '02 / ANALYZE',
    description: '拆素材、看短视频与直播，把证据沉淀回下一轮生产。',
  },
  library: {
    icon: BookOpenText,
    eyebrow: '03 / LIBRARY',
    description: '管理产品、知识和采集来源，让每次生成都有可追溯依据。',
  },
}

const ENTRY_DESCRIPTION: Record<string, string> = {
  'workspace-operations': '内容任务总入口',
  'sku-pipeline': '卖点、人群与圈包前链路',
  'content-studio': '脚本、Brief 与内容资产',
  'reverse-engineer': '把参考素材拆成可复用提示词',
  'video-analysis': '短视频证据与结构分析',
  'livestream-analysis': '直播内容与表现分析',
  'product-management': 'SKU 与产品事实',
  knowledge: '知识库与可信检索',
  'knowledge-harvester': '外部资料采集与入库',
}

export function ContentWorkspace() {
  const groups = workbenchNavigationForMode('work')

  return (
    <div className="mx-auto w-full max-w-[1440px] px-5 py-8 sm:px-8 lg:px-10 lg:py-10" data-testid="content-workspace">
      <header className="grid gap-6 border-b border-slate-200 pb-8 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-700">Omni Content OS</p>
          <h1 className="mt-3 max-w-3xl text-3xl font-semibold tracking-[-0.03em] text-slate-950 sm:text-4xl">
            从产品事实到内容资产，
            <span className="text-slate-500">只保留真正会用的链路。</span>
          </h1>
        </div>
        <p className="max-w-md text-sm leading-6 text-slate-600">
          生产、分析、资料三块工作面共用同一份 FeatureDefinition。这里隐藏的是冗余入口，不是删除数据或能力。
        </p>
      </header>

      <div className="grid gap-4 py-8 lg:grid-cols-3" aria-label="内容工作区">
        {groups.map((group) => {
          const presentation = GROUP_PRESENTATION[group.id as keyof typeof GROUP_PRESENTATION]
          const Icon = presentation?.icon || Clapperboard
          return (
            <section key={group.id} className="flex min-h-[360px] flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]" data-content-group={group.id}>
              <div className="flex items-start justify-between gap-3 border-b border-slate-100 pb-5">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-600">{presentation?.eyebrow}</p>
                  <h2 className="mt-2 text-lg font-semibold tracking-tight text-slate-950">{group.label}</h2>
                </div>
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-950 text-cyan-300">
                  <Icon className="h-4 w-4" aria-hidden="true" />
                </span>
              </div>
              <p className="mt-4 min-h-12 text-sm leading-6 text-slate-500">{presentation?.description}</p>
              <div className="mt-5 space-y-1">
                {group.entries.map((entry, index) => (
                  <Link
                    key={`${group.id}:${entry.featureId}:${entry.relationship}`}
                    href={entry.href}
                    className="workbench-focusable group flex items-center gap-3 rounded-lg px-3 py-3 transition-colors hover:bg-slate-50"
                  >
                    <span className="w-5 text-[10px] font-semibold tabular-nums text-slate-600">{String(index + 1).padStart(2, '0')}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-slate-800 group-hover:text-slate-950">{entry.title}</span>
                      <span className="mt-0.5 block truncate text-xs text-slate-600">{ENTRY_DESCRIPTION[entry.featureId] || entry.href}</span>
                    </span>
                    <ArrowUpRight className="h-4 w-4 text-slate-300 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-cyan-700" aria-hidden="true" />
                  </Link>
                ))}
              </div>
            </section>
          )
        })}
      </div>

      <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-5 text-xs text-slate-500">
        <span>当前主工作面：{groups.length} 组 · {groups.reduce((total, group) => total + group.entries.length, 0)} 个入口</span>
        <span>内容血缘、直达链接与历史页面保持不变</span>
      </footer>
    </div>
  )
}
