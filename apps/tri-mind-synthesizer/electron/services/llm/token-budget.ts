import { ModelConfig, BudgetResult, RoundHistory } from '../../../src/lib/types'
import { MODEL_CONTEXT_WINDOWS } from './adapters/base.adapter'
import { estimateTokens as _estimateTokens } from '../../utils/token-counter'

/**
 * Token 预算管理器
 * 
 * 负责：
 * 1. 计算每个模型的 Token 预算
 * 2. 判断何时需要压缩历史上下文
 * 3. 执行智能压缩
 */
export class TokenBudgetManager {
  // 预留给输出的比例
  private readonly OUTPUT_RESERVE_RATIO = 0.25
  
  // 触发压缩的阈值（超过可用空间的50%）
  private readonly COMPRESS_THRESHOLD = 0.50
  
  // 触发截断警告的阈值（超过可用空间的80%）
  private readonly TRUNCATE_THRESHOLD = 0.80

  /**
   * 计算模型的 Token 预算
   */
  calculateBudget(model: ModelConfig, history: RoundHistory[], fileContext?: string): BudgetResult {
    const contextWindow = this.getContextWindow(model)
    const outputReserve = Math.floor(contextWindow * this.OUTPUT_RESERVE_RATIO)
    const availableForInput = contextWindow - outputReserve

    // 计算当前使用的 tokens
    const currentTokens = this.estimateHistoryTokens(history) + 
                          (fileContext ? this.estimateTokens(fileContext) : 0)

    const threshold50 = availableForInput * this.COMPRESS_THRESHOLD
    const threshold80 = availableForInput * this.TRUNCATE_THRESHOLD

    if (currentTokens <= threshold50) {
      return {
        strategy: 'pass-through',
        budget: availableForInput,
      }
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

  /**
   * 检查是否需要压缩
   */
  needsCompression(history: RoundHistory[], model: ModelConfig): boolean {
    const budget = this.calculateBudget(model, history)
    return budget.strategy !== 'pass-through'
  }

  /**
   * 压缩历史记录
   * 保留最后一轮完整内容，其他轮次生成摘要
   */
  async compressHistory(
    history: RoundHistory[],
    model: ModelConfig,
    summarizer?: (text: string) => Promise<string>
  ): Promise<RoundHistory[]> {
    if (history.length <= 1) {
      return history
    }

    const result: RoundHistory[] = []
    
    // 保留最后一轮
    const lastRound = history[history.length - 1]
    
    // 压缩前面的轮次
    for (let i = 0; i < history.length - 1; i++) {
      const round = history[i]
      
      if (round.compressed) {
        // 已经压缩过，保持原样
        result.push(round)
      } else {
        // 需要压缩
        const compressedResponses = new Map<string, string>()
        
        for (const [modelId, response] of round.responses) {
          if (summarizer) {
            // 使用提供的摘要函数
            const summary = await summarizer(response)
            compressedResponses.set(modelId, summary)
          } else {
            // 简单截断
            compressedResponses.set(modelId, this.truncateText(response, 500))
          }
        }
        
        result.push({
          ...round,
          responses: compressedResponses,
          compressed: true,
        })
      }
    }
    
    // 添加最后一轮（保持完整）
    result.push(lastRound)
    
    return result
  }

  /**
   * 截断历史到指定预算
   */
  truncateHistory(history: RoundHistory[], maxTokens: number): RoundHistory[] {
    const result: RoundHistory[] = []
    let currentTokens = 0
    
    // 从最后一轮开始，向前添加
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

  /**
   * 获取模型的上下文窗口大小
   */
  private getContextWindow(model: ModelConfig): number {
    return model.contextWindow || MODEL_CONTEXT_WINDOWS[model.modelId] || MODEL_CONTEXT_WINDOWS['default']
  }

  /**
   * 估算历史记录的 token 数量
   */
  private estimateHistoryTokens(history: RoundHistory[]): number {
    return history.reduce((total, round) => total + this.estimateRoundTokens(round), 0)
  }

  /**
   * 估算单轮的 token 数量
   */
  private estimateRoundTokens(round: RoundHistory): number {
    let tokens = 0
    for (const response of round.responses.values()) {
      tokens += this.estimateTokens(response)
    }
    return tokens
  }

  /**
   * 估算文本的 token 数量
   * 委托给独立的 token-counter 工具
   */
  estimateTokens(text: string): number {
    return _estimateTokens(text)
  }

  /**
   * 截断文本
   */
  private truncateText(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text
    return text.slice(0, maxLength - 20) + '\n\n[内容已截断...]'
  }
}

// 导出单例
export const tokenBudgetManager = new TokenBudgetManager()
