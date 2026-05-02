'use client'

import Link from 'next/link'
import { BookOpen, CheckCircle2, ImageIcon, Layers, Settings2, Sparkles, Video } from 'lucide-react'

import { ContentStudioHubNav } from '@/components/content-studio-hub-nav'

const FLOW = [
  {
    title: '1. 建 Brief',
    desc: '先把产品卖点、目标人群、场景和口播风格沉淀成结构化 Brief。后续复盘指标会回灌到这个 Brief。',
  },
  {
    title: '2. 建 Avatar',
    desc: '在数字人脸库创建或选择一个稳定形象。新建流水线时绑定 Avatar，才能追踪同一人的 CTR / CVR / 样本数。',
  },
  {
    title: '3. 新建 Pipeline',
    desc: '使用向导选择 Brief + Avatar，并上传人脸参考图和产品图。缺少任一项，页面会提示你补齐。',
  },
  {
    title: '4. 生成 10 scene',
    desc: '按顺序生成文案、脚本、角色分析、分镜图、视频片段。脚本会强制校验 10 个 scene。',
  },
  {
    title: '5. 下载 / 投放 / 复盘',
    desc: '下载素材后投放。复盘时在 ad-review 素材上绑定 Pipeline，指标会回灌到 Brief 和 Avatar。',
  },
]

const MODEL_STEPS = [
  {
    icon: Sparkles,
    title: '文案 / 脚本',
    desc: '推荐使用强文本模型，例如 Gemini、OpenAI 的 gpt-5.5 或 gpt-5.2-chat-latest。',
  },
  {
    icon: ImageIcon,
    title: '角色人脸 / 分镜图',
    desc: '推荐 Seedream；也可以在“生成参数配置”里选择 OpenAI 的 gpt-image-2。',
  },
  {
    icon: Video,
    title: '视频片段',
    desc: '推荐 Seedance。若 2.0 未开通，可选择已开通的 Seedance 1.x 模型。',
  },
]

export default function ContentStudioGuidePage() {
  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <ContentStudioHubNav />

      <section className="rounded-2xl border border-violet-200 bg-gradient-to-br from-violet-50 to-white p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-violet-100 px-3 py-1 text-xs font-medium text-violet-700">
              <BookOpen className="h-3.5 w-3.5" />
              内容工坊使用指南
            </div>
            <h1 className="mt-3 text-2xl font-semibold text-gray-950">从 Brief 到可投放素材的闭环流程</h1>
            <p className="mt-2 max-w-2xl text-sm text-gray-600">
              内容工坊适合把投放复盘、产品卖点和数字人资产串起来，生成可下载、可投放、可复盘回灌的短视频素材。
            </p>
          </div>
          <Link
            href="/content-studio/new"
            className="shrink-0 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-700"
          >
            从向导新建
          </Link>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-5">
        {FLOW.map((item) => (
          <div key={item.title} className="rounded-xl border bg-white p-4 shadow-sm">
            <CheckCircle2 className="mb-3 h-5 w-5 text-emerald-500" />
            <h2 className="text-sm font-semibold text-gray-900">{item.title}</h2>
            <p className="mt-2 text-xs leading-5 text-gray-600">{item.desc}</p>
          </div>
        ))}
      </section>

      <section className="rounded-xl border bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <Settings2 className="h-5 w-5 text-violet-600" />
          <h2 className="text-lg font-semibold text-gray-950">如何选择大模型</h2>
        </div>
        <p className="mt-2 text-sm text-gray-600">
          打开任意流水线后，点击“生成参数配置”，在“分步模型选择”里给每个步骤指定 provider 和模型。不选则使用系统默认。
        </p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {MODEL_STEPS.map(({ icon: Icon, title, desc }) => (
            <div key={title} className="rounded-lg border border-gray-100 bg-gray-50 p-4">
              <Icon className="mb-2 h-5 w-5 text-violet-600" />
              <div className="text-sm font-medium text-gray-900">{title}</div>
              <p className="mt-1 text-xs leading-5 text-gray-600">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <Layers className="h-5 w-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-gray-950">生成前检查</h2>
          </div>
          <ul className="mt-3 space-y-2 text-sm text-gray-600">
            <li>确认 Brief、Avatar、人脸参考图、产品图都已绑定。</li>
            <li>确认脚本为 10 个 scene，scene_id 从 1 到 10。</li>
            <li>生成分镜后肉眼检查同一人、同一产品是否稳定可识别。</li>
          </ul>
        </div>
        <div className="rounded-xl border bg-white p-5 shadow-sm">
          <div className="flex items-center gap-2">
            <Video className="h-5 w-5 text-rose-600" />
            <h2 className="text-lg font-semibold text-gray-950">投放后回灌</h2>
          </div>
          <ul className="mt-3 space-y-2 text-sm text-gray-600">
            <li>在 ad-review 素材详情里绑定对应 Pipeline。</li>
            <li>复盘完成后 Brief 会显示 CTR / CVR / 样本数。</li>
            <li>Avatar 会累计 CTR / CVR / usage_count，用于晋级或归档。</li>
          </ul>
        </div>
      </section>
    </div>
  )
}
