
/**
 * 各厂商模型的默认费率 (USD per 1M tokens)
 */
export const DEFAULT_RATES: Record<string, { input: number; output: number }> = {
  // OpenAI
  'gpt-5.2': { input: 2.50, output: 10.00 },
  'gpt-5-mini': { input: 0.15, output: 0.60 },
  'gpt-4o': { input: 2.50, output: 10.00 },
  'gpt-4o-mini': { input: 0.15, output: 0.60 },
  // Anthropic
  'claude-3-5-sonnet-20241022': { input: 3.00, output: 15.00 },
  'claude-3-opus-20240229': { input: 15.00, output: 75.00 },
  'claude-3-haiku-20240307': { input: 0.25, output: 1.25 },
  // Google
  'gemini-3-pro-preview': { input: 1.25, output: 5.00 },
  'gemini-3-flash-preview': { input: 0.075, output: 0.30 },
  'gemini-1.5-pro': { input: 1.25, output: 5.00 },
  'gemini-1.5-flash': { input: 0.075, output: 0.30 },
  // Ollama (本地免费)
  'llama2': { input: 0, output: 0 },
}

/**
 * 根据 token 用量和模型费率估算费用
 */
export function estimateCost(
  modelId: string,
  inputTokens: number,
  outputTokens: number
): number {
  let rates: Record<string, { input: number; output: number }> = DEFAULT_RATES

  // 尝试加载自定义费率
  try {
    const saved = localStorage.getItem('tri-mind-rates')
    if (saved) {
      const custom = JSON.parse(saved)
      rates = { ...rates, ...custom }
    }
  } catch {
    // 使用默认费率
  }

  const rate = rates[modelId] || { input: 0, output: 0 }
  return (inputTokens / 1_000_000 * rate.input) + (outputTokens / 1_000_000 * rate.output)
}

/**
 * 格式化费用为人类可读格式
 */
export function formatCost(cost: number): string {
  if (cost === 0) return '免费'
  if (cost < 0.001) return '< $0.001'
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  if (cost < 1) return `$${cost.toFixed(3)}`
  return `$${cost.toFixed(2)}`
}
