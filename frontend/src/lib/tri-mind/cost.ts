export const DEFAULT_RATES: Record<string, { input: number; output: number }> = {
  'gpt-5.2': { input: 2.5, output: 10 },
  'gpt-5-mini': { input: 0.15, output: 0.6 },
  'gpt-4o': { input: 2.5, output: 10 },
  'gpt-4o-mini': { input: 0.15, output: 0.6 },
  'claude-3-5-sonnet-20241022': { input: 3, output: 15 },
  'claude-3-opus-20240229': { input: 15, output: 75 },
  'claude-3-haiku-20240307': { input: 0.25, output: 1.25 },
  'gemini-3-pro-preview': { input: 1.25, output: 5 },
  'gemini-3-flash-preview': { input: 0.075, output: 0.3 },
  'gemini-1.5-pro': { input: 1.25, output: 5 },
  'gemini-1.5-flash': { input: 0.075, output: 0.3 },
  llama2: { input: 0, output: 0 },
}

export function estimateCost(
  modelId: string,
  inputTokens: number,
  outputTokens: number
): number {
  let rates = { ...DEFAULT_RATES }
  try {
    const saved = typeof window !== 'undefined' && localStorage.getItem('tri-mind-rates')
    if (saved) {
      const custom = JSON.parse(saved)
      rates = { ...rates, ...custom }
    }
  } catch {
    /* ignore */
  }
  const rate = rates[modelId] || { input: 0, output: 0 }
  return (inputTokens / 1_000_000) * rate.input + (outputTokens / 1_000_000) * rate.output
}

export function formatCost(cost: number): string {
  if (cost === 0) return '免费'
  if (cost < 0.001) return '< $0.001'
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  if (cost < 1) return `$${cost.toFixed(3)}`
  return `$${cost.toFixed(2)}`
}
