import type { ModelConfig, BudgetResult, RoundHistory } from './types'
import { MODEL_CONTEXT_WINDOWS } from './adapters/base.adapter'
import { estimateTokens as _estimateTokens } from './utils/token-counter'

export class TokenBudgetManager {
  private readonly OUTPUT_RESERVE_RATIO = 0.25
  private readonly COMPRESS_THRESHOLD = 0.5
  private readonly TRUNCATE_THRESHOLD = 0.8

  calculateBudget(
    model: ModelConfig,
    history: RoundHistory[],
    fileContext?: string
  ): BudgetResult {
    const contextWindow = this.getContextWindow(model)
    const outputReserve = Math.floor(contextWindow * this.OUTPUT_RESERVE_RATIO)
    const availableForInput = contextWindow - outputReserve

    const currentTokens =
      this.estimateHistoryTokens(history) +
      (fileContext ? this.estimateTokens(fileContext) : 0)

    const threshold50 = availableForInput * this.COMPRESS_THRESHOLD
    const threshold80 = availableForInput * this.TRUNCATE_THRESHOLD

    if (currentTokens <= threshold50) {
      return { strategy: 'pass-through', budget: availableForInput }
    } else if (currentTokens <= threshold80) {
      return {
        strategy: 'compress',
        budget: availableForInput,
        compressRounds: 'all-except-last',
      }
    } else {
      return {
        strategy: 'truncate-and-warn',
        budget: availableForInput,
        warning: '历史上下文已被截断，部分早期对话可能丢失',
      }
    }
  }

  needsCompression(history: RoundHistory[], model: ModelConfig): boolean {
    const budget = this.calculateBudget(model, history)
    return budget.strategy !== 'pass-through'
  }

  async compressHistory(
    history: RoundHistory[],
    model: ModelConfig,
    summarizer?: (text: string) => Promise<string>
  ): Promise<RoundHistory[]> {
    if (history.length <= 1) return history

    const result: RoundHistory[] = []
    const lastRound = history[history.length - 1]

    for (let i = 0; i < history.length - 1; i++) {
      const round = history[i]
      if (round.compressed) {
        result.push(round)
      } else {
        const compressedResponses = new Map<string, string>()
        for (const [modelId, response] of Array.from(round.responses)) {
          if (summarizer) {
            compressedResponses.set(modelId, await summarizer(response))
          } else {
            compressedResponses.set(modelId, this.truncateText(response, 500))
          }
        }
        result.push({ ...round, responses: compressedResponses, compressed: true })
      }
    }
    result.push(lastRound)
    return result
  }

  truncateHistory(history: RoundHistory[], maxTokens: number): RoundHistory[] {
    const result: RoundHistory[] = []
    let currentTokens = 0
    for (let i = history.length - 1; i >= 0; i--) {
      const round = history[i]
      const roundTokens = this.estimateRoundTokens(round)
      if (currentTokens + roundTokens <= maxTokens) {
        result.unshift(round)
        currentTokens += roundTokens
      } else {
        break
      }
    }
    return result
  }

  private getContextWindow(model: ModelConfig): number {
    return (
      model.contextWindow ||
      MODEL_CONTEXT_WINDOWS[model.modelId] ||
      MODEL_CONTEXT_WINDOWS['default']
    )
  }

  private estimateHistoryTokens(history: RoundHistory[]): number {
    return history.reduce(
      (total, round) => total + this.estimateRoundTokens(round),
      0
    )
  }

  private estimateRoundTokens(round: RoundHistory): number {
    let tokens = 0
    for (const response of Array.from(round.responses.values())) {
      tokens += this.estimateTokens(response)
    }
    return tokens
  }

  estimateTokens(text: string): number {
    return _estimateTokens(text)
  }

  private truncateText(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text
    return text.slice(0, maxLength - 20) + '\n\n[内容已截断...]'
  }
}

export const tokenBudgetManager = new TokenBudgetManager()
