'use client'

/**
 * 「💾 存入决策日志」按钮 —— v1.5 双写后端版
 *
 * 用法：
 *   <SaveToDecisionButton
 *     source="chat"               // 必填：来源模块
 *     sourceRunId="session-123"   // 可选：圆桌 session id 等
 *     defaultTitle="如何提升酱油 CTR"  // 默认标题（可编辑）
 *     content="..."               // 完整内容（markdown）
 *     summary="..."               // 摘要（缺省取 content 前 200 字）
 *     defaultSkuId="SKU-A001"    // 默认关联的 SKU
 *   />
 *
 * 行为：
 *   1. 点击按钮 → 弹出极简表单（标题 / SKU 关联 / 类型）
 *   2. 提交 → decisionStore.addAsync → POST /api/omni/scout/decisions + 落 localStorage
 *   3. 显示成功 toast，按钮变成"已存入"绿色徽章
 *
 * SKU 列表：从 /api/omni/scout/skus 拉真实 SKU（v1.5 起 sku_bootstrapper 自动同步全店 41 SKU），
 *          重点池 SKU 顶部置顶 ⭐ 标记
 */

import { useEffect, useState } from 'react'
import { CheckCircle2, ClipboardCheck, X, Loader2 } from 'lucide-react'
import {
  useDecisionStore,
  type DecisionSource,
  type DecisionType,
} from '@/stores/decisionStore'

const TYPES: { key: DecisionType; label: string }[] = [
  { key: 'suggestion', label: '行动建议' },
  { key: 'diagnosis', label: '诊断结论' },
  { key: 'experiment', label: '实验设计' },
  { key: 'anomaly', label: '异动告警' },
]

interface BackendSku {
  id: string
  name: string
  in_focus_pool?: boolean
  focus_reason?: string | null
}

export interface SaveToDecisionButtonProps {
  source: DecisionSource
  sourceRunId?: string
  defaultTitle?: string
  content: string
  summary?: string
  defaultSkuId?: string
  defaultType?: DecisionType
  /** 自定义按钮样式类（默认是 chat 风格的灰底圆角） */
  buttonClassName?: string
  /** 紧凑模式：只显示图标 + "存入" 二字 */
  compact?: boolean
}

export function SaveToDecisionButton({
  source,
  sourceRunId,
  defaultTitle,
  content,
  summary,
  defaultSkuId,
  defaultType = 'suggestion',
  buttonClassName,
  compact = false,
}: SaveToDecisionButtonProps) {
  const addAsync = useDecisionStore((s) => s.addAsync)
  const [open, setOpen] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [title, setTitle] = useState(defaultTitle ?? '')
  const [skuId, setSkuId] = useState(defaultSkuId ?? '')
  const [type, setType] = useState<DecisionType>(defaultType)
  const [skus, setSkus] = useState<BackendSku[]>([])
  const [skuLoadFailed, setSkuLoadFailed] = useState(false)

  // 弹窗打开时拉取真实 SKU 列表（重点池在前）
  useEffect(() => {
    if (!open || skus.length || skuLoadFailed) return
    fetch('/api/omni/scout/skus')
      .then((r) => { if (!r.ok) throw new Error(); return r.json() })
      .then((data: BackendSku[]) => setSkus(data))
      .catch(() => setSkuLoadFailed(true))
  }, [open, skus.length, skuLoadFailed])

  const handleSave = async () => {
    if (!title.trim()) {
      window.alert('请填写标题')
      return
    }
    setSaving(true)
    try {
      await addAsync({
        source,
        sourceRunId,
        type,
        skuId: skuId || undefined,
        title: title.trim(),
        summary: summary ?? content.slice(0, 200),
        fullContent: content,
      })
      setSaved(true)
      setOpen(false)
    } finally {
      setSaving(false)
    }
  }

  const baseBtn =
    buttonClassName ??
    'inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200 transition-all'

  if (saved) {
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200">
        <CheckCircle2 className="h-3 w-3" />
        已存入决策日志
      </span>
    )
  }

  return (
    <>
      <button onClick={() => setOpen(true)} className={baseBtn}>
        <ClipboardCheck className="h-3 w-3" />
        {compact ? '存入' : '存入决策日志'}
      </button>

      {open && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 p-5 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold flex items-center gap-2">
                <ClipboardCheck className="w-4 h-4 text-emerald-600" />
                存入决策日志
              </h3>
              <button
                onClick={() => setOpen(false)}
                className="text-gray-400 hover:text-gray-600"
                aria-label="close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  标题 <span className="text-rose-500">*</span>
                </label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="一句话概括这条决策"
                  className="w-full text-sm rounded-lg border border-gray-200 px-3 py-2 focus:outline-none focus:border-violet-400"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  关联 SKU
                  {skuLoadFailed && (
                    <span className="ml-2 text-amber-600">（SKU 列表加载失败，可手动输入 ID）</span>
                  )}
                </label>
                {skuLoadFailed ? (
                  <input
                    value={skuId}
                    onChange={(e) => setSkuId(e.target.value)}
                    placeholder="SKU ID（可留空）"
                    className="w-full text-sm rounded-lg border border-gray-200 px-3 py-2 focus:outline-none focus:border-violet-400"
                  />
                ) : (
                  <select
                    value={skuId}
                    onChange={(e) => setSkuId(e.target.value)}
                    className="w-full text-sm rounded-lg border border-gray-200 px-3 py-2 focus:outline-none focus:border-violet-400 bg-white"
                  >
                    <option value="">不关联 SKU</option>
                    {skus
                      .slice()
                      .sort((a, b) => Number(b.in_focus_pool ?? 0) - Number(a.in_focus_pool ?? 0))
                      .map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.in_focus_pool ? '⭐ ' : ''}
                          {s.name} ({s.id})
                        </option>
                      ))}
                  </select>
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  类型
                </label>
                <div className="flex gap-1.5 flex-wrap">
                  {TYPES.map((t) => (
                    <button
                      key={t.key}
                      onClick={() => setType(t.key)}
                      className={`px-3 py-1 rounded-full text-xs ${
                        type === t.key
                          ? 'bg-violet-600 text-white'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  内容预览
                </label>
                <div className="text-xs text-gray-500 bg-gray-50 rounded-lg p-2.5 max-h-32 overflow-y-auto whitespace-pre-wrap leading-relaxed">
                  {(summary ?? content).slice(0, 400)}
                  {(summary ?? content).length > 400 && '...'}
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-5">
              <button
                onClick={() => setOpen(false)}
                disabled={saving}
                className="px-4 py-2 text-sm rounded-lg text-gray-600 hover:bg-gray-100 disabled:opacity-50"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white shadow disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {saving ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
