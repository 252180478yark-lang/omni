import { useState } from 'react'
import { useConfigStore } from '../../stores/configStore'
import { cn } from '../../lib/utils'
import { DEFAULT_RATES } from '../../lib/cost'
import { DollarSign } from 'lucide-react'

/**
 * 费率设置表格
 * 
 * 按厂商费率自动计算预估费用。
 * 用户可以自定义费率以匹配其实际价格。
 */
export function RateTable() {
  const { providers } = useConfigStore()
  const [customRates, setCustomRates] = useState<Record<string, { input: number; output: number }>>(
    () => {
      // 从 localStorage 加载自定义费率
      try {
        const saved = localStorage.getItem('tri-mind-rates')
        return saved ? JSON.parse(saved) : {}
      } catch {
        return {}
      }
    }
  )

  const getRate = (modelId: string): { input: number; output: number } => {
    return customRates[modelId] || DEFAULT_RATES[modelId] || { input: 0, output: 0 }
  }

  const setRate = (modelId: string, field: 'input' | 'output', value: number) => {
    const newRates = {
      ...customRates,
      [modelId]: {
        ...getRate(modelId),
        [field]: value,
      },
    }
    setCustomRates(newRates)
    localStorage.setItem('tri-mind-rates', JSON.stringify(newRates))
  }

  const resetToDefault = (modelId: string) => {
    const newRates = { ...customRates }
    delete newRates[modelId]
    setCustomRates(newRates)
    localStorage.setItem('tri-mind-rates', JSON.stringify(newRates))
  }

  // 获取所有启用的提供商及其模型
  const enabledProviders = providers.filter(p => p.enabled || p.models.some(m => m.enabled))

  if (enabledProviders.length === 0) {
    return (
      <div className="text-sm text-muted-foreground text-center py-8">
        请先启用至少一个模型以查看费率设置
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
        <DollarSign className="w-4 h-4 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          设置各模型的费率（USD / 1M tokens），用于预估辩论费用。
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left py-2 px-3 text-muted-foreground font-medium">模型</th>
              <th className="text-right py-2 px-3 text-muted-foreground font-medium">
                Input $/1M
              </th>
              <th className="text-right py-2 px-3 text-muted-foreground font-medium">
                Output $/1M
              </th>
              <th className="text-right py-2 px-3 text-muted-foreground font-medium w-16"></th>
            </tr>
          </thead>
          <tbody>
            {enabledProviders.map((provider) =>
              provider.models.map((model) => {
                const rate = getRate(model.modelId)
                const isCustom = model.modelId in customRates
                const isDefault = model.modelId in DEFAULT_RATES

                return (
                  <tr
                    key={model.id}
                    className="border-b border-border/50 hover:bg-muted/30"
                  >
                    <td className="py-2 px-3">
                      <div className="flex items-center gap-2">
                        <span className={cn(
                          model.enabled ? 'text-foreground' : 'text-muted-foreground'
                        )}>
                          {model.name}
                        </span>
                        {!isDefault && !isCustom && (
                          <span className="text-xs text-muted-foreground">(自定义模型)</span>
                        )}
                      </div>
                    </td>
                    <td className="py-2 px-3">
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={rate.input}
                        onChange={(e) => setRate(model.modelId, 'input', parseFloat(e.target.value) || 0)}
                        className={cn(
                          'w-24 text-right px-2 py-1 rounded',
                          'bg-background border border-input text-sm',
                          'focus:outline-none focus:ring-1 focus:ring-ring',
                          isCustom && 'border-primary/50'
                        )}
                      />
                    </td>
                    <td className="py-2 px-3">
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        value={rate.output}
                        onChange={(e) => setRate(model.modelId, 'output', parseFloat(e.target.value) || 0)}
                        className={cn(
                          'w-24 text-right px-2 py-1 rounded',
                          'bg-background border border-input text-sm',
                          'focus:outline-none focus:ring-1 focus:ring-ring',
                          isCustom && 'border-primary/50'
                        )}
                      />
                    </td>
                    <td className="py-2 px-3 text-right">
                      {isCustom && (
                        <button
                          onClick={() => resetToDefault(model.modelId)}
                          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                          重置
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* 费用估算说明 */}
      <div className="bg-muted/50 rounded-lg p-3 text-xs text-muted-foreground space-y-1">
        <p>费用估算 = (Input Tokens / 1,000,000 × Input Rate) + (Output Tokens / 1,000,000 × Output Rate)</p>
        <p>实际费用以各厂商账单为准，此处仅为参考估算。</p>
      </div>
    </div>
  )
}

