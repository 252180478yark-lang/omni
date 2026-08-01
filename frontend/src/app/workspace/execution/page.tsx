import Link from 'next/link'

import { RuntimeOverlay } from '@/components/system-command-center/RuntimeOverlay'

export default function RuntimeExecutionPage() {
  return <main className="mx-auto max-w-7xl space-y-4 p-4 md:p-8">
    <div className="flex items-center justify-between">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">统一执行中台</h1>
        <p className="text-sm text-slate-600">计划、事实、运行与交付四层证据视图</p>
      </div>
      <Link href="/workspace" className="text-sm text-violet-700 hover:underline">返回工作台</Link>
    </div>
    <RuntimeOverlay />
  </main>
}
