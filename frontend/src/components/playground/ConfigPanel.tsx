'use client'
import { useEffect, useState } from 'react'
import { Play, RefreshCw, CheckSquare, Square, Sliders } from 'lucide-react'
import { cn } from '@/lib/utils'
import { usePlaygroundStore, type PlaygroundModel } from '@/stores/playground'
import { fetchToolList, TOOL_GROUPS, allToolNames } from '@/lib/playground/api'

interface Props {
  onRun: () => void
  canRun: boolean
}

const MODELS: Array<{ key: PlaygroundModel; label: string; hint: string }> = [
  { key: 'sonnet', label: 'Sonnet 4.6', hint: '默认 — 日常调试用' },
  { key: 'opus', label: 'Opus 4.7', hint: '复杂推理 — 慢且贵' },
  { key: 'haiku', label: 'Haiku 4.5', hint: '最快 — 简单任务' },
]

export function ConfigPanel({ onRun, canRun }: Props) {
  const config = usePlaygroundStore((s) => s.config)
  const setConfig = usePlaygroundStore((s) => s.setConfig)
  const [tools, setTools] = useState<string[]>(allToolNames())
  const [toolsFromKe, setToolsFromKe] = useState(false)
  const [loadingTools, setLoadingTools] = useState(false)

  const loadTools = async () => {
    setLoadingTools(true)
    try {
      const { tools: list, fromKe } = await fetchToolList()
      setTools(list)
      setToolsFromKe(fromKe)
    } finally {
      setLoadingTools(false)
    }
  }

  useEffect(() => {
    loadTools()
  }, [])

  const selected = new Set(config.allowedTools)
  const allOn = config.allowedTools.length === 0 || config.allowedTools.length === tools.length

  const toggleTool = (name: string) => {
    if (allOn) {
      // 当前全开,点击一个 = 反向"只关那个"
      setConfig({ allowedTools: tools.filter((t) => t !== name) })
      return
    }
    const next = new Set(selected)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    if (next.size === tools.length) setConfig({ allowedTools: [] })
    else setConfig({ allowedTools: Array.from(next) })
  }

  const setAll = (on: boolean) => {
    if (on) setConfig({ allowedTools: [] })
    else setConfig({ allowedTools: ['__none__'] }) // 占位防被理解成全开
  }

  return (
    <aside className="w-[280px] shrink-0 border-r border-gray-100 bg-gray-50/40 flex flex-col h-full">
      <header className="h-14 px-4 border-b border-gray-100 flex items-center gap-2 bg-white">
        <Sliders className="w-4 h-4 text-violet-600" />
        <h2 className="text-sm font-semibold text-gray-900">调试配置</h2>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
        {/* Section 1: Model */}
        <section>
          <h3 className="text-xs font-semibold text-gray-700 mb-2">模型</h3>
          <div className="space-y-1.5">
            {MODELS.map((m) => (
              <label
                key={m.key}
                className={cn(
                  'flex items-start gap-2 px-2.5 py-2 rounded-md border cursor-pointer transition-colors',
                  config.model === m.key
                    ? 'border-violet-300 bg-violet-50'
                    : 'border-gray-200 bg-white hover:border-gray-300',
                )}
              >
                <input
                  type="radio"
                  name="pg-model"
                  className="mt-0.5"
                  checked={config.model === m.key}
                  onChange={() => setConfig({ model: m.key })}
                />
                <div className="min-w-0">
                  <div className="text-xs font-medium text-gray-900">{m.label}</div>
                  <div className="text-[10px] text-gray-500 mt-0.5">{m.hint}</div>
                </div>
              </label>
            ))}
          </div>
        </section>

        {/* Section 2: Tools */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-gray-700">
              可用 Tool
              <span className="ml-1 text-gray-400 font-normal">
                ({allOn ? `全开 ${tools.length}` : `${config.allowedTools.length}/${tools.length}`})
              </span>
            </h3>
            <button
              onClick={loadTools}
              disabled={loadingTools}
              className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 disabled:opacity-40"
              title={toolsFromKe ? '从 KE 拉的实时清单' : 'KE 不可达,用了 fallback hard-code 清单'}
            >
              <RefreshCw className={cn('w-3 h-3', loadingTools && 'animate-spin')} />
            </button>
          </div>
          <div className="flex gap-1.5 mb-2">
            <button
              onClick={() => setAll(true)}
              className="flex-1 inline-flex items-center justify-center gap-1 text-[10px] px-2 py-1 rounded border border-violet-200 bg-violet-50 text-violet-700 hover:bg-violet-100"
            >
              <CheckSquare className="w-3 h-3" />
              全选
            </button>
            <button
              onClick={() => setAll(false)}
              className="flex-1 inline-flex items-center justify-center gap-1 text-[10px] px-2 py-1 rounded border border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
            >
              <Square className="w-3 h-3" />
              全不选
            </button>
          </div>
          <div className="space-y-3">
            {TOOL_GROUPS.map((group) => {
              const inGroup = group.tools.filter((t) => tools.includes(t))
              if (inGroup.length === 0) return null
              return (
                <div key={group.label}>
                  <div className="text-[10px] font-semibold text-gray-500 uppercase mb-1">
                    {group.label}
                  </div>
                  <div className="space-y-0.5">
                    {inGroup.map((name) => {
                      const on = allOn || selected.has(name)
                      return (
                        <label
                          key={name}
                          className="flex items-center gap-1.5 px-1.5 py-0.5 rounded cursor-pointer hover:bg-white"
                        >
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => toggleTool(name)}
                            className="h-3 w-3"
                          />
                          <span className="text-[11px] font-mono text-gray-700 truncate">
                            {name}
                          </span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              )
            })}
            {/* 如果有 KE 返了但不在 group 里的 tool, 也列出来 */}
            {toolsFromKe && (
              <ExtraTools known={TOOL_GROUPS.flatMap((g) => g.tools)} all={tools} selected={selected} allOn={allOn} onToggle={toggleTool} />
            )}
          </div>
        </section>

        {/* Section 3: Extra system prompt */}
        <section>
          <h3 className="text-xs font-semibold text-gray-700 mb-2">额外 system prompt</h3>
          <textarea
            value={config.extraSystemPrompt}
            onChange={(e) => setConfig({ extraSystemPrompt: e.target.value })}
            placeholder="贴一段 SKILL.md description 测试 / 或贴 system 改造 prompt"
            rows={5}
            className="w-full text-[11px] font-mono px-2 py-1.5 rounded border border-gray-200 focus:outline-none focus:border-violet-400 resize-y bg-white"
          />
          <div className="text-[10px] text-gray-400 mt-1">
            会拼到第一条 user message 前;主 Claude 视为额外指令
          </div>
        </section>

        {/* Section 4: max_turns */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-gray-700">max_turns</h3>
            <span className="text-xs text-violet-700 font-mono">{config.maxTurns}</span>
          </div>
          <input
            type="range"
            min={1}
            max={30}
            value={config.maxTurns}
            onChange={(e) => setConfig({ maxTurns: parseInt(e.target.value, 10) })}
            className="w-full accent-violet-600"
          />
          <div className="flex justify-between text-[9px] text-gray-400 mt-0.5">
            <span>1</span>
            <span>30</span>
          </div>
        </section>
      </div>

      <footer className="px-4 py-3 border-t border-gray-100 bg-white">
        <button
          onClick={onRun}
          disabled={!canRun}
          className="w-full inline-flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Play className="w-3.5 h-3.5" />
          运行
        </button>
      </footer>
    </aside>
  )
}

function ExtraTools({
  known,
  all,
  selected,
  allOn,
  onToggle,
}: {
  known: string[]
  all: string[]
  selected: Set<string>
  allOn: boolean
  onToggle: (name: string) => void
}) {
  const knownSet = new Set(known)
  const extra = all.filter((t) => !knownSet.has(t))
  if (extra.length === 0) return null
  return (
    <div>
      <div className="text-[10px] font-semibold text-gray-500 uppercase mb-1">其他</div>
      <div className="space-y-0.5">
        {extra.map((name) => {
          const on = allOn || selected.has(name)
          return (
            <label
              key={name}
              className="flex items-center gap-1.5 px-1.5 py-0.5 rounded cursor-pointer hover:bg-white"
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => onToggle(name)}
                className="h-3 w-3"
              />
              <span className="text-[11px] font-mono text-gray-700 truncate">{name}</span>
            </label>
          )
        })}
      </div>
    </div>
  )
}
