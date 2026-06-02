'use client'
import { useState } from 'react'
import { ChevronDown, ChevronRight, Copy, GitBranch, Zap } from 'lucide-react'
import { usePlaygroundStore, type ToolCallTrace } from '@/stores/playground'

export function TracePane() {
  const toolCalls = usePlaygroundStore((s) => s.toolCalls)
  const claudeCost = usePlaygroundStore((s) => s.claudeCostUsd)
  const toolApiCost = usePlaygroundStore((s) => s.toolApiCostUsd)
  const totalLatency = usePlaygroundStore((s) => s.totalLatencyMs)

  const llmToolCount = toolCalls.filter((t) => !!t.trace_field).length
  const regularToolCount = toolCalls.length - llmToolCount

  return (
    <aside className="w-[360px] shrink-0 border-l border-gray-100 bg-gray-50/40 flex flex-col h-full">
      <header className="h-14 px-4 border-b border-gray-100 flex items-center gap-2 bg-white">
        <GitBranch className="w-4 h-4 text-violet-600" />
        <h2 className="text-sm font-semibold text-gray-900">调用 Trace</h2>
        <span className="ml-auto text-[10px] text-gray-400">{toolCalls.length} 次</span>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        {toolCalls.length === 0 && (
          <div className="mt-20 text-center text-gray-400 text-xs px-4">
            没有 tool 调用记录.
            <div className="mt-2 text-[10px] text-gray-300">
              发送 prompt 后,主 Claude 调的每个 omni tool 都会出现在这里.
              <br />
              LLM tool(如 generate_brief) 会展开次级 LLM 调用详情.
            </div>
          </div>
        )}

        {/* 主 Claude 节点 */}
        {toolCalls.length > 0 && <ClaudeRootNode toolCalls={toolCalls} />}
      </div>

      {/* Sticky 总计 */}
      <footer className="px-3 py-3 border-t border-gray-100 bg-white space-y-1.5">
        <div className="text-[10px] text-gray-500 font-semibold uppercase">总计</div>
        <Stat
          label="真实 API cost"
          value={toolApiCost > 0 ? `$${toolApiCost.toFixed(4)}` : '—'}
          hint="次级 LLM (ai-provider-hub)"
        />
        <Stat
          label="Max 订阅 cost"
          value={claudeCost > 0 ? `$${claudeCost.toFixed(4)}` : '—'}
          hint="主 Claude 这层 (仅供参考)"
          muted
        />
        <Stat
          label="总 latency"
          value={totalLatency > 0 ? `${(totalLatency / 1000).toFixed(1)}s` : '—'}
        />
        <Stat
          label="tool calls"
          value={`${toolCalls.length} (${llmToolCount} LLM / ${regularToolCount} 普通)`}
        />
      </footer>
    </aside>
  )
}

function Stat({
  label,
  value,
  hint,
  muted,
}: {
  label: string
  value: string
  hint?: string
  muted?: boolean
}) {
  return (
    <div className={`flex items-baseline justify-between gap-2 ${muted ? 'opacity-60' : ''}`}>
      <div className="text-[11px] text-gray-600">
        {label}
        {hint && <span className="text-gray-400 ml-1">· {hint}</span>}
      </div>
      <div className="text-xs font-mono font-semibold text-gray-900">{value}</div>
    </div>
  )
}

function ClaudeRootNode({ toolCalls }: { toolCalls: ToolCallTrace[] }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="rounded-lg border border-violet-200 bg-white">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-violet-50"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <Zap className="w-3 h-3 text-violet-600" />
        <span className="text-xs font-semibold text-gray-900">主 Claude</span>
        <span className="text-[10px] text-gray-400 ml-auto">Max 订阅</span>
      </button>
      {open && (
        <div className="border-t border-violet-100 px-2 py-2 space-y-1.5">
          {toolCalls.map((tc, idx) => (
            <ToolCallNode key={tc.tool_use_id} tc={tc} idx={idx + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

function ToolCallNode({ tc, idx }: { tc: ToolCallTrace; idx: number }) {
  const [open, setOpen] = useState(false)
  const isLlm = !!tc.trace_field
  return (
    <div className="rounded border border-gray-200 bg-gray-50/50">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-2 py-1.5 flex items-center gap-1.5 text-left hover:bg-gray-100"
      >
        {open ? (
          <ChevronDown className="w-3 h-3 text-gray-400" />
        ) : (
          <ChevronRight className="w-3 h-3 text-gray-400" />
        )}
        <span className="text-[10px] text-gray-400 font-mono">#{idx}</span>
        <span className="text-[11px] font-mono font-semibold text-gray-800 truncate">
          {tc.tool_name}
        </span>
        {isLlm && (
          <span className="ml-auto text-[9px] px-1 py-0.5 rounded bg-violet-100 text-violet-700 shrink-0">
            LLM
          </span>
        )}
        <span
          className={`text-[10px] shrink-0 ${
            tc.status === 'completed'
              ? 'text-emerald-600'
              : tc.status === 'error'
                ? 'text-red-600'
                : 'text-blue-600'
          }`}
        >
          {tc.status === 'completed' ? '✓' : tc.status === 'error' ? '✗' : '...'}
        </span>
      </button>

      {open && (
        <div className="border-t border-gray-200 px-2 py-2 space-y-2 text-[10.5px]">
          {/* input */}
          <Field
            label="input"
            data={tc.input}
            empty={!tc.input || Object.keys(tc.input).length === 0}
          />

          {/* output */}
          <Field label="output" data={tc.parsed_output ?? tc.raw_output} empty={!tc.parsed_output && !tc.raw_output} />

          {/* trace (次级 LLM) */}
          {tc.trace_field && (
            <TraceFieldBlock
              trace={tc.trace_field}
              latencyMs={tc.latency_ms}
              costUsd={tc.cost_usd}
            />
          )}
        </div>
      )}
    </div>
  )
}

function Field({ label, data, empty }: { label: string; data: unknown; empty: boolean }) {
  const [open, setOpen] = useState(false)
  if (empty) {
    return (
      <div className="flex items-center justify-between">
        <span className="text-gray-500">{label}:</span>
        <span className="text-gray-300">(empty)</span>
      </div>
    )
  }
  const text = JSON.stringify(data, null, 2)
  const copy = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(() => undefined)
    }
  }
  return (
    <div>
      <div
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between cursor-pointer hover:bg-white px-1 py-0.5 rounded"
      >
        <div className="flex items-center gap-1">
          {open ? <ChevronDown className="w-2.5 h-2.5" /> : <ChevronRight className="w-2.5 h-2.5" />}
          <span className="text-gray-600 font-semibold">{label}</span>
          <span className="text-gray-400">· {text.length} chars</span>
        </div>
        <button onClick={copy} className="text-gray-400 hover:text-violet-600" title="复制 raw JSON">
          <Copy className="w-2.5 h-2.5" />
        </button>
      </div>
      {open && (
        <pre className="mt-1 px-2 py-1.5 bg-white border border-gray-200 rounded text-[10px] font-mono overflow-x-auto max-h-64 overflow-y-auto whitespace-pre">
          {text}
        </pre>
      )}
    </div>
  )
}

function TraceFieldBlock({
  trace,
  latencyMs,
  costUsd,
}: {
  trace: Record<string, unknown>
  latencyMs?: number
  costUsd?: number
}) {
  const [open, setOpen] = useState(true)
  const [promptOpen, setPromptOpen] = useState(false)
  const [paramsOpen, setParamsOpen] = useState(false)
  const provider = (trace.model_provider as string) || (trace.provider as string) || '?'
  const model = (trace.model as string) || '?'
  const finalPrompt = (trace.final_prompt as string) || ''
  const params = trace.params as Record<string, unknown> | undefined
  const costEstimate = (trace.cost_estimate as string) || ''
  const sources = trace.retrieved_sources as unknown[] | undefined

  return (
    <div className="rounded border border-violet-200 bg-violet-50/40 px-2 py-1.5">
      <div
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between cursor-pointer"
      >
        <div className="flex items-center gap-1">
          {open ? <ChevronDown className="w-2.5 h-2.5" /> : <ChevronRight className="w-2.5 h-2.5" />}
          <span className="text-violet-700 font-semibold">trace · 次级 LLM</span>
        </div>
        <span className="text-[10px] text-violet-600 font-mono">
          {provider} · {model}
        </span>
      </div>
      {open && (
        <div className="mt-1 space-y-1">
          {/* final_prompt */}
          {finalPrompt && (
            <div>
              <div
                onClick={() => setPromptOpen(!promptOpen)}
                className="flex items-center gap-1 cursor-pointer text-gray-600 hover:text-gray-900"
              >
                {promptOpen ? (
                  <ChevronDown className="w-2.5 h-2.5" />
                ) : (
                  <ChevronRight className="w-2.5 h-2.5" />
                )}
                <span>final_prompt · {finalPrompt.length} chars</span>
                <CopyBtn text={finalPrompt} className="ml-auto" />
              </div>
              {promptOpen && (
                <pre className="mt-1 px-2 py-1.5 bg-white border border-violet-100 rounded text-[10px] font-mono overflow-x-auto max-h-64 overflow-y-auto whitespace-pre-wrap">
                  {finalPrompt}
                </pre>
              )}
            </div>
          )}

          {/* params */}
          {params && Object.keys(params).length > 0 && (
            <div>
              <div
                onClick={() => setParamsOpen(!paramsOpen)}
                className="flex items-center gap-1 cursor-pointer text-gray-600 hover:text-gray-900"
              >
                {paramsOpen ? (
                  <ChevronDown className="w-2.5 h-2.5" />
                ) : (
                  <ChevronRight className="w-2.5 h-2.5" />
                )}
                <span>params</span>
                <CopyBtn text={JSON.stringify(params)} className="ml-auto" />
              </div>
              {paramsOpen && (
                <pre className="mt-1 px-2 py-1.5 bg-white border border-violet-100 rounded text-[10px] font-mono overflow-x-auto max-h-32 overflow-y-auto">
                  {JSON.stringify(params, null, 2)}
                </pre>
              )}
            </div>
          )}

          {/* retrieved_sources */}
          {Array.isArray(sources) && sources.length > 0 && (
            <div className="text-gray-600">
              retrieved_sources: <span className="font-mono">{sources.length}</span> 条
            </div>
          )}

          {/* latency */}
          {typeof latencyMs === 'number' && (
            <div className="text-gray-600">
              latency: <span className="font-mono">{(latencyMs / 1000).toFixed(2)}s</span>
            </div>
          )}

          {/* cost */}
          <div className="text-gray-600">
            cost: <span className="font-mono">{costUsd ? `$${costUsd.toFixed(4)}` : costEstimate || '—'}</span>
          </div>
        </div>
      )}
    </div>
  )
}

function CopyBtn({ text, className = '' }: { text: string; className?: string }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        if (typeof navigator !== 'undefined' && navigator.clipboard) {
          navigator.clipboard.writeText(text).catch(() => undefined)
        }
      }}
      className={`text-gray-400 hover:text-violet-600 ${className}`}
      title="复制"
    >
      <Copy className="w-2.5 h-2.5" />
    </button>
  )
}
