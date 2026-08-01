'use client'

import React, { useEffect, useState } from 'react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  HelpCircle,
  X,
  Sparkles,
  MessageSquare,
  Database,
  Download,
  Cpu,
  Clapperboard,
  Radio,
  LineChart,
  Palette,
  Newspaper,
  ArrowRight,
  CheckCircle2,
  Lightbulb,
  Rocket,
  type LucideIcon,
} from 'lucide-react'
import { featureById } from '@/lib/feature-registry'

const STORAGE_KEY = 'omni_beginner_guide_seen_v1'

type TabId = 'what' | 'do' | 'start' | 'faq'

interface ToolPresentation {
  featureId: string
  icon: LucideIcon
  oneLine: string
  scene: string
  color: string
}

interface ToolExplain extends ToolPresentation {
  name: string
  href: string
}

const TOOL_PRESENTATION: ToolPresentation[] = [
  {
    featureId: 'chat',
    icon: MessageSquare,
    oneLine: '像微信一样和 AI 聊天，可以让它读你给的资料再回答',
    scene: '比如：把一份产品说明书丢进去，问"这款适合什么人用？"',
    color: 'from-violet-500 to-purple-600',
  },
  {
    featureId: 'knowledge',
    icon: Database,
    oneLine: '把你常用的资料（PDF、Word、网页）存进来，AI 就能"记住"它们',
    scene: '比如：把公司所有产品手册、FAQ、合同模板存进去，以后随时问',
    color: 'from-emerald-500 to-teal-600',
  },
  {
    featureId: 'knowledge-harvester',
    icon: Download,
    oneLine: '给一个网页或飞书文档链接，自动抓回来存进知识库',
    scene: '比如：看到一篇好文章，复制链接进去，3 秒后它就在你的知识库里了',
    color: 'from-blue-500 to-cyan-600',
  },
  {
    featureId: 'system-console',
    icon: Cpu,
    oneLine: '在这里填你的 AI 账号密码（API Key），整个系统才能用',
    scene: '第一次用必须来这里填一次，后面就不用管了',
    color: 'from-slate-500 to-gray-600',
  },
  {
    featureId: 'video-analysis',
    icon: Clapperboard,
    oneLine: '上传一段短视频，AI 看完直接给你写分析报告',
    scene: '比如：抖音爆款视频拖进去，告诉你它为什么火、节奏怎么剪',
    color: 'from-pink-500 to-rose-600',
  },
  {
    featureId: 'livestream-analysis',
    icon: Radio,
    oneLine: '上传直播录屏，自动切片打分，输出 Excel 报表',
    scene: '比如：复盘自己昨晚那场直播哪段话术效果最好',
    color: 'from-orange-500 to-amber-600',
  },
  {
    featureId: 'ad-review',
    icon: LineChart,
    oneLine: '把广告投放数据（巨量千川 CSV）丢进来，AI 帮你分析钱花得值不值',
    scene: '比如：上周投了 5 万块，AI 告诉你哪条素材最赚、下周该怎么改',
    color: 'from-indigo-500 to-blue-600',
  },
  {
    featureId: 'content-studio',
    icon: Palette,
    oneLine: '一句话说出你想要的视频，AI 帮你写脚本、做分镜、生成视频',
    scene: '比如："给一款保湿面霜写一条 30 秒的口播脚本"，自动出片',
    color: 'from-fuchsia-500 to-pink-600',
  },
  {
    featureId: 'news',
    icon: Newspaper,
    oneLine: '自动从全网帮你抓行业新闻，集中在一个页面看',
    scene: '比如：每天早上花 3 分钟刷一遍今天行业发生了什么',
    color: 'from-sky-500 to-blue-600',
  },
]

const TOOLS: ToolExplain[] = TOOL_PRESENTATION.flatMap((presentation) => {
  const definition = featureById(presentation.featureId)
  return definition?.visible && (definition.placements.includes('onboarding') || definition.placements.includes('home'))
    ? [{ ...presentation, name: definition.title, href: definition.href }]
    : []
})

interface Step {
  num: number
  title: string
  desc: string
  href: string
  cta: string
}

const STEPS: Step[] = [
  {
    num: 1,
    title: '配一下"AI 账号"',
    desc: '去「模型配置」页面，把你的 AI Key 填进去（OpenAI、Gemini、Deepseek 任选一个就够用）。这一步只做一次，相当于充话费。',
    href: '/models',
    cta: '去配置',
  },
  {
    num: 2,
    title: '试着和 AI 聊一句',
    desc: '去「智能问答」页面，问个最简单的问题，比如"你能干啥"。能正常回复，就说明系统打通了。',
    href: '/chat',
    cta: '去聊聊',
  },
  {
    num: 3,
    title: '建一个自己的"知识库"',
    desc: '去「知识库」页面，新建一个库（取个名字就行），上传几份你常用的 PDF/Word 文档。',
    href: '/knowledge',
    cta: '去建库',
  },
  {
    num: 4,
    title: '回到聊天，让 AI 看着你的资料回答',
    desc: '在聊天页面选中刚才的知识库，再提问，AI 就会"翻你的资料"再回答你，准确度立刻提高。',
    href: '/chat',
    cta: '去试试',
  },
]

interface FAQ {
  q: string
  a: string
}

const FAQS: FAQ[] = [
  {
    q: '我什么都不懂，能用吗？',
    a: '能。这个系统就是给"不懂技术的运营/老板"用的。你只需要会复制粘贴、会点鼠标。最复杂的一步是去 OpenAI/Gemini 官网申请一个 Key（找个会的朋友 5 分钟教你）。',
  },
  {
    q: '"API Key"是什么？要花钱吗？',
    a: '可以理解成"AI 公司给你的账号密码"。每次让 AI 干活，会按字数收一点点钱（聊一次大概几分钱）。OpenAI 新账号送 5 美元额度，够你玩很久。如果想完全免费，可以装本地的 Ollama 模型。',
  },
  {
    q: '"知识库"和"直接和 AI 聊"有什么区别？',
    a: '直接聊：AI 用的是它训练时学到的"通用知识"，不知道你公司的事。\n知识库：你把公司资料喂给它，它就能基于这些资料回答（比如"我们公司退货政策是几天"）。',
  },
  {
    q: '上传的资料安全吗？会被别人看到吗？',
    a: '资料只存在你这台电脑上的数据库里，不会上传到任何公网。但 AI 回答的时候，问题内容会发给 OpenAI/Gemini（这是它们必须收到才能回答）。如果是高度机密资料，建议用本地的 Ollama。',
  },
  {
    q: '为什么有些功能点进去是空的 / 报错？',
    a: '99% 是因为「模型配置」没填 Key，或者填错了。先回去那个页面点一下"测试连接"按钮，绿了再来用其他功能。',
  },
  {
    q: '"投放复盘"听起来很专业，我没投过广告也能用吗？',
    a: '这个模块是给电商投手用的（处理巨量千川的广告数据）。如果你不投广告，可以直接忽略这个菜单。',
  },
  {
    q: '我应该从哪个功能开始？',
    a: '推荐顺序：① 模型配置 → ② 智能问答（试试） → ③ 知识库（建一个）→ ④ 回到智能问答（这次选上知识库再问）。这条路走完，你就掌握了 80% 的能力。',
  },
]

export function BeginnerGuide() {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<TabId>('what')

  useEffect(() => {
    if (typeof window === 'undefined') return
    const seen = window.localStorage.getItem(STORAGE_KEY)
    if (!seen) {
      const t = setTimeout(() => setOpen(true), 800)
      return () => clearTimeout(t)
    }
  }, [])

  const close = () => {
    setOpen(false)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, '1')
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-[70] group flex items-center gap-2 pl-3 pr-4 py-3 rounded-full bg-gradient-to-r from-violet-600 to-purple-500 text-white shadow-xl shadow-purple-300/40 hover:shadow-purple-400/60 hover:scale-105 transition-all duration-200"
        aria-label="打开新手指南"
      >
        <HelpCircle className="w-5 h-5" />
        <span className="text-sm font-medium">新手指南</span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200"
          onClick={(e) => {
            if (e.target === e.currentTarget) close()
          }}
        >
          <div className="relative w-full max-w-3xl max-h-[90vh] bg-white rounded-3xl shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
            <div className="relative px-7 pt-7 pb-5 bg-gradient-to-br from-violet-50 via-purple-50 to-pink-50 border-b border-violet-100/60">
              <button
                type="button"
                onClick={close}
                className="absolute top-5 right-5 w-9 h-9 rounded-full bg-white/80 hover:bg-white flex items-center justify-center text-gray-500 hover:text-gray-900 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
              <div className="flex items-center gap-3 mb-3">
                <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-violet-600 to-purple-500 flex items-center justify-center shadow-lg shadow-purple-200/50">
                  <Sparkles className="w-6 h-6 text-white" />
                </div>
                <div>
                  <h2 className="text-xl font-bold text-gray-900">欢迎使用 Omni-Vibe，这是写给新手的说明书</h2>
                  <p className="text-sm text-gray-500 mt-0.5">不需要懂技术，跟着看 3 分钟就能上手</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5 mt-4">
                {(
                  [
                    { id: 'what', label: '它是什么？' },
                    { id: 'do', label: '能干什么？' },
                    { id: 'start', label: '怎么开始？' },
                    { id: 'faq', label: '常见疑问' },
                  ] as { id: TabId; label: string }[]
                ).map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setTab(t.id)}
                    className={
                      'px-4 py-1.5 rounded-full text-sm font-medium transition-all ' +
                      (tab === t.id
                        ? 'bg-white text-violet-700 shadow-sm'
                        : 'bg-white/40 text-gray-500 hover:bg-white/70')
                    }
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-7 py-6 chat-scroll">
              {tab === 'what' && <WhatTab />}
              {tab === 'do' && <DoTab onClose={close} />}
              {tab === 'start' && <StartTab onClose={close} />}
              {tab === 'faq' && <FaqTab />}
            </div>

            <div className="flex items-center justify-between px-7 py-4 border-t border-gray-100 bg-gray-50/50">
              <p className="text-xs text-gray-400">
                以后想再看这份指南，点页面右下角紫色"新手指南"按钮即可
              </p>
              <Button
                type="button"
                onClick={close}
                className="rounded-full bg-gradient-to-r from-violet-600 to-purple-500 hover:from-violet-700 hover:to-purple-600 shadow-md"
              >
                我懂了，开始使用 <ArrowRight className="w-4 h-4 ml-1" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function WhatTab() {
  return (
    <div className="space-y-5">
      <div className="rounded-2xl bg-gradient-to-br from-violet-50 to-purple-50/50 border border-violet-100 p-5">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-white shadow-sm flex items-center justify-center shrink-0">
            <Lightbulb className="w-5 h-5 text-amber-500" />
          </div>
          <div className="space-y-3 text-sm leading-relaxed text-gray-700">
            <p>
              <span className="font-semibold text-gray-900">一句话讲：</span>
              这是一个"AI 万能小助理"——你把工作里要看的资料、要分析的视频、要回的问题、要投的广告数据都丢给它，它帮你做完。
            </p>
            <p>
              <span className="font-semibold text-gray-900">用人话讲：</span>
              想象你雇了一个 24 小时不睡觉、读过所有资料、会做表的实习生。Omni 就是这个实习生的"工作台"，左边菜单里每个功能都是它的一项技能。
            </p>
            <p>
              <span className="font-semibold text-gray-900">谁适合用？</span>
              电商运营、内容创作者、产品经理、销售、老板……只要你每天要"看资料 + 做分析 + 写东西"，就能省一半时间。
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <InfoCard
          color="violet"
          title="不用装东西"
          desc="打开浏览器就能用，不需要你写代码、配环境"
        />
        <InfoCard
          color="emerald"
          title="数据在你电脑上"
          desc="上传的资料只存本地，不会被别的公司看到"
        />
        <InfoCard
          color="amber"
          title="按需付费"
          desc="只在你向 AI 提问时花钱，每次几分钱级别"
        />
      </div>

      <div className="rounded-2xl bg-amber-50/50 border border-amber-100 p-5">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-amber-100 flex items-center justify-center shrink-0">
            <Rocket className="w-4 h-4 text-amber-600" />
          </div>
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-1">现在该做什么？</h4>
            <p className="text-sm text-gray-600 leading-relaxed">
              点上面的"<span className="font-medium text-violet-700">怎么开始？</span>"标签，跟着 4 步走一遍，10 分钟内就能完整跑通。
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function InfoCard({ color, title, desc }: { color: 'violet' | 'emerald' | 'amber'; title: string; desc: string }) {
  const map = {
    violet: 'bg-violet-50 border-violet-100 text-violet-700',
    emerald: 'bg-emerald-50 border-emerald-100 text-emerald-700',
    amber: 'bg-amber-50 border-amber-100 text-amber-700',
  }
  return (
    <div className={`rounded-2xl border p-4 ${map[color]}`}>
      <CheckCircle2 className="w-4 h-4 mb-2" />
      <div className="font-semibold text-sm text-gray-900 mb-1">{title}</div>
      <div className="text-xs text-gray-600 leading-relaxed">{desc}</div>
    </div>
  )
}

function DoTab({ onClose }: { onClose: () => void }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-500 mb-2">
        系统里 9 个主要功能，每个都用大白话解释一遍。点卡片右边箭头可以直接跳过去试用：
      </p>
      {TOOLS.map((tool) => (
        <Link
          key={tool.href}
          href={tool.href}
          onClick={onClose}
          className="block rounded-2xl border border-gray-100 hover:border-violet-200 hover:bg-violet-50/30 p-4 transition-all group"
        >
          <div className="flex items-start gap-4">
            <div className={`w-11 h-11 rounded-xl bg-gradient-to-br ${tool.color} shadow-md flex items-center justify-center shrink-0`}>
              <tool.icon className="w-5 h-5 text-white" />
            </div>
            <div className="flex-1 min-w-0">
              <h4 className="font-semibold text-sm text-gray-900 mb-1">{tool.name}</h4>
              <p className="text-sm text-gray-600 leading-relaxed mb-1.5">{tool.oneLine}</p>
              <p className="text-xs text-gray-400 leading-relaxed">{tool.scene}</p>
            </div>
            <ArrowRight className="w-4 h-4 text-gray-300 group-hover:text-violet-500 group-hover:translate-x-1 transition-all shrink-0 mt-3" />
          </div>
        </Link>
      ))}
    </div>
  )
}

function StartTab({ onClose }: { onClose: () => void }) {
  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-gradient-to-br from-violet-50 to-purple-50/50 border border-violet-100 p-4">
        <p className="text-sm text-gray-700 leading-relaxed">
          <span className="font-semibold text-violet-700">10 分钟新手路线</span>
          ：跟着下面 4 步走一遍，你就完整体验过整个系统的核心能力了。
        </p>
      </div>

      <div className="space-y-3">
        {STEPS.map((step, idx) => (
          <div key={step.num} className="relative">
            {idx < STEPS.length - 1 && (
              <div className="absolute left-[22px] top-12 bottom-[-12px] w-0.5 bg-gradient-to-b from-violet-200 to-transparent" />
            )}
            <div className="flex items-start gap-4 p-4 rounded-2xl border border-gray-100 bg-white hover:border-violet-200 transition-colors">
              <div className="w-11 h-11 rounded-full bg-gradient-to-br from-violet-600 to-purple-500 text-white flex items-center justify-center shrink-0 shadow-md font-bold text-base">
                {step.num}
              </div>
              <div className="flex-1 min-w-0">
                <h4 className="font-semibold text-sm text-gray-900 mb-1">{step.title}</h4>
                <p className="text-sm text-gray-600 leading-relaxed mb-3">{step.desc}</p>
                <Link href={step.href} onClick={onClose}>
                  <Button
                    size="sm"
                    variant="outline"
                    className="rounded-full text-xs border-violet-200 text-violet-700 hover:bg-violet-50"
                  >
                    {step.cta} <ArrowRight className="w-3 h-3 ml-1" />
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="rounded-2xl bg-emerald-50/50 border border-emerald-100 p-4 mt-4">
        <p className="text-sm text-gray-700 leading-relaxed">
          <span className="font-semibold text-emerald-700">走完这 4 步</span>
          ，恭喜你已经掌握 80% 的用法。剩下的"短视频分析 / 直播分析 / 投放复盘 / 内容工坊"是给特定场景（电商投手、内容创作者）用的，按需点开看就行。
        </p>
      </div>
    </div>
  )
}

function FaqTab() {
  return (
    <div className="space-y-3">
      {FAQS.map((item, i) => (
        <details
          key={i}
          className="group rounded-2xl border border-gray-100 hover:border-violet-200 bg-white overflow-hidden"
        >
          <summary className="flex items-center justify-between gap-3 px-4 py-3 cursor-pointer list-none [&::-webkit-details-marker]:hidden">
            <div className="flex items-center gap-3 min-w-0">
              <Badge className="bg-violet-100 text-violet-700 hover:bg-violet-100 border-violet-200 rounded-full text-[10px] px-2 py-0.5 shrink-0">
                Q{i + 1}
              </Badge>
              <span className="text-sm font-medium text-gray-900 truncate">{item.q}</span>
            </div>
            <ArrowRight className="w-4 h-4 text-gray-300 shrink-0 group-open:rotate-90 transition-transform" />
          </summary>
          <div className="px-4 pb-4 pt-0">
            <p className="text-sm text-gray-600 leading-relaxed whitespace-pre-line pl-12">
              {item.a}
            </p>
          </div>
        </details>
      ))}
    </div>
  )
}
