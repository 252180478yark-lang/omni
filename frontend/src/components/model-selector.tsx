'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { ChevronDown, Check, Sparkles } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'

export type ModelCapability =
  | 'chat'
  | 'image_generation'
  | 'video_generation'
  | 'analysis'
  | 'vision'
  | 'embedding'

export interface ModelChoice {
  provider: string | null
  model: string | null
}

interface ProviderItem {
  id: string
  name: string
  models: string[]
  defaultChatModel: string | null
  capabilities?: string[]
  apiKeySet?: boolean
}

interface ProvidersApiResponse {
  success: boolean
  data?: { providers: ProviderItem[] }
}

const CAP_LABEL: Record<ModelCapability, string> = {
  chat: '文本',
  image_generation: '图像',
  video_generation: '视频',
  analysis: '分析',
  vision: '视觉',
  embedding: '向量',
}

// Module-level cache shared across instances; providers rarely change mid-session.
let providerCache: ProviderItem[] | null = null
let providerCachePromise: Promise<ProviderItem[]> | null = null

async function fetchProviders(): Promise<ProviderItem[]> {
  if (providerCache) return providerCache
  if (providerCachePromise) return providerCachePromise
  providerCachePromise = (async () => {
    try {
      const res = await fetch('/api/omni/models', { cache: 'no-store' })
      const json = (await res.json()) as ProvidersApiResponse
      const list = json?.data?.providers ?? []
      providerCache = list
      return list
    } catch {
      providerCache = []
      return []
    } finally {
      providerCachePromise = null
    }
  })()
  return providerCachePromise
}

export function invalidateProviderCache() {
  providerCache = null
}

interface ModelSelectorProps {
  capability: ModelCapability
  value: ModelChoice
  onChange: (value: ModelChoice) => void
  label?: string
  allowDefault?: boolean
  disabled?: boolean
  className?: string
  /** Placeholder shown when using system default. */
  defaultLabel?: string
  /** Compact chip style for inline use (e.g. inside step panels). */
  compact?: boolean
}

export function ModelSelector({
  capability,
  value,
  onChange,
  label,
  allowDefault = true,
  disabled = false,
  className,
  defaultLabel = '使用系统默认',
  compact = false,
}: ModelSelectorProps) {
  const [providers, setProviders] = useState<ProviderItem[]>([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchProviders().then((list) => {
      if (cancelled) return
      setProviders(list)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    return providers
      .filter((p) => p.apiKeySet && p.models.length > 0)
      .filter((p) => (p.capabilities || []).includes(capability))
  }, [providers, capability])

  const selectedLabel = useMemo(() => {
    if (!value.provider || !value.model) return defaultLabel
    return `${value.provider} · ${value.model}`
  }, [value, defaultLabel])

  const triggerClass = compact
    ? 'flex items-center gap-1.5 px-2 py-1 text-xs rounded-md border border-gray-200 bg-white hover:bg-gray-50 text-left max-w-[220px]'
    : 'flex items-center gap-2 min-w-[200px] max-w-[320px] px-3 py-2 text-sm rounded-xl border border-gray-200 bg-white/90 hover:bg-white shadow-sm text-left'

  return (
    <div className={className}>
      {label && !compact && (
        <label className="block text-xs font-medium text-gray-600 mb-1 flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5 text-gray-400" />
          {label}
        </label>
      )}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          type="button"
          className={triggerClass}
          disabled={disabled || loading}
        >
          <span className={compact ? 'text-[11px] text-gray-500 shrink-0' : 'text-[11px] text-gray-500 shrink-0'}>
            {CAP_LABEL[capability]}
          </span>
          <span className="truncate flex-1 font-medium text-gray-800">
            {loading ? '加载中...' : selectedLabel}
          </span>
          <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" />
        </PopoverTrigger>
        <PopoverContent className="w-72 p-0" align="start">
          <div className="max-h-80 overflow-auto py-1">
            {allowDefault && (
              <button
                type="button"
                onClick={() => {
                  onChange({ provider: null, model: null })
                  setOpen(false)
                }}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 flex items-center gap-2 ${
                  !value.provider ? 'bg-blue-50 text-blue-800' : ''
                }`}
              >
                <Sparkles className="w-3.5 h-3.5 shrink-0" />
                <span>{defaultLabel}</span>
                {!value.provider && <Check className="w-3.5 h-3.5 ml-auto text-blue-600" />}
              </button>
            )}
            {filtered.length === 0 && !loading && (
              <div className="px-3 py-4 text-xs text-gray-500 text-center">
                没有具备「{CAP_LABEL[capability]}」能力且已配置 Key 的供应商
              </div>
            )}
            {filtered.map((provider) => (
              <div key={provider.id}>
                <div className="px-3 pt-2 pb-1 text-[11px] font-semibold text-gray-500 uppercase tracking-wide bg-gray-50/50 border-t border-gray-100">
                  {provider.name}
                </div>
                {provider.models.map((model) => {
                  const active = value.provider === provider.id && value.model === model
                  return (
                    <button
                      key={`${provider.id}-${model}`}
                      type="button"
                      onClick={() => {
                        onChange({ provider: provider.id, model })
                        setOpen(false)
                      }}
                      className={`w-full text-left px-3 py-1.5 text-xs font-mono hover:bg-gray-50 flex items-center gap-2 ${
                        active ? 'bg-blue-50 text-blue-800' : ''
                      }`}
                    >
                      <span className="truncate flex-1">{model}</span>
                      {active && <Check className="w-3.5 h-3.5 text-blue-600 shrink-0" />}
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}
