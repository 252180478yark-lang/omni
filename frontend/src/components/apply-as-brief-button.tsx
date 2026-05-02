'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Loader2, Wand2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  /** 标题种子 — 通常是用户的最近一句问题或会话主题。 */
  topic: string
  /** 内容种子 — 通常是最新 AI 回复 / 圆桌总结，作为 hints.usp_hint 注入。 */
  content: string
  /**
   * 可选：显式传 sku_id 覆盖 URL 检测。
   * 不传时会自动 useSearchParams() 读 ?sku_id 参数。
   */
  skuIdOverride?: string
  /** 紧凑模式（小尺寸圆角按钮，用于消息卡片内）。 */
  compact?: boolean
  /** 自定义按钮文案（默认根据 sku 上下文切换）。 */
  label?: string
}

/**
 * 把任意"AI 输出"一键应用为 Brief 草稿或 SKU 内容编排。
 *
 * 行为分流：
 *   - URL 带 ?sku_id（或显式传 skuIdOverride）→ 起 SKU 内容编排（最强闭环）
 *   - 否则 → 调 briefs/generate 落一份独立 Brief 草稿
 *
 * 复用方：圆桌总结区、chat 每条 AI 消息底部、scout 异动卡（已用类似逻辑）。
 */
export function ApplyAsBriefButton({
  topic,
  content,
  skuIdOverride,
  compact = false,
  label,
}: Props) {
  const searchParams = useSearchParams()
  const skuId = (skuIdOverride ?? searchParams.get('sku_id') ?? '').trim()

  const [working, setWorking] = useState(false)
  const [result, setResult] = useState<{ kind: 'orch' | 'brief'; id: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const apply = async () => {
    if (!content.trim()) {
      setErr('内容为空')
      return
    }
    setWorking(true)
    setErr(null)
    try {
      if (skuId) {
        const r = await fetch('/api/omni/content-studio/sku-orchestrations', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            sku_id: skuId,
            title: `[${topic.slice(0, 40)}] 来自智能问答/圆桌`.slice(0, 100),
            target_purpose: null,
          }),
        })
        if (!r.ok) throw new Error(`orch ${r.status}`)
        const data = await r.json()
        setResult({ kind: 'orch', id: data.id })
      } else {
        const r = await fetch('/api/omni/content-studio/briefs/generate', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            title: topic.slice(0, 80) || 'AI 对话生成草稿',
            hints: {
              usp_hint: content.slice(0, 4000),
            },
          }),
        })
        if (!r.ok) throw new Error(`brief ${r.status}`)
        const data = await r.json()
        setResult({ kind: 'brief', id: data.id })
      }
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setWorking(false)
    }
  }

  const sizeClass = compact
    ? 'h-7 px-3 text-xs rounded-full'
    : 'gap-2'

  if (result) {
    if (result.kind === 'orch') {
      return (
        <Link href={`/sku/${skuId}?tab=content`}>
          <Button variant="outline" className={`${sizeClass} border-emerald-300 text-emerald-700 bg-emerald-50/50`}>
            ✓ 已起编排，去 SKU 工作台 →
          </Button>
        </Link>
      )
    }
    return (
      <Link href={`/content-studio/briefs/${result.id}`}>
        <Button variant="outline" className={`${sizeClass} border-emerald-300 text-emerald-700 bg-emerald-50/50`}>
          ✓ 已生成 Brief，去查看 →
        </Button>
      </Link>
    )
  }

  const fallbackLabel = skuId ? '应用为 SKU 内容编排' : '应用为 Brief 草稿'

  return (
    <Button
      variant={compact ? 'default' : 'outline'}
      className={
        compact
          ? `${sizeClass} bg-gradient-to-r from-violet-500 to-purple-500 text-white hover:from-violet-600 hover:to-purple-600 shadow-sm`
          : `${sizeClass} border-violet-300 text-violet-700 hover:bg-violet-50`
      }
      onClick={() => void apply()}
      disabled={working}
      title={skuId ? '把 AI 输出作为种子，给当前 SKU 起一份内容编排' : '把 AI 输出作为种子生成一份 Brief 草稿'}
    >
      {working ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
      {label || fallbackLabel}
      {err && <span className="text-[11px] text-rose-100 ml-1">({err})</span>}
    </Button>
  )
}
