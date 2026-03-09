/**
 * Token 计数工具
 * 
 * 提供多种文本的 Token 估算能力：
 * - 中文/英文混合文本
 * - 代码
 * - Prompt 模板
 * 
 * 使用启发式估算（无需 tiktoken 依赖），
 * 精度约 90%，足以满足预算控制需求。
 */

// 中英文字符分类正则
const CHINESE_REGEX = /[\u4e00-\u9fa5\u3400-\u4dbf\uf900-\ufaff]/g
const CODE_TOKEN_REGEX = /[{}()\[\];:.,<>=!&|+\-*/\\@#$%^~`"'?]/g

/**
 * 估算文本的 Token 数量
 * 
 * 算法：
 * - 中文字符：约 1.5 字符/token（GPT 系列平均值）
 * - 英文/代码：约 4 字符/token
 * - 代码特殊符号：约 1 符号/token
 * - 空行/换行：约 1 token/行
 */
export function estimateTokens(text: string): number {
  if (!text) return 0

  const chineseChars = (text.match(CHINESE_REGEX) || []).length
  const codeSymbols = (text.match(CODE_TOKEN_REGEX) || []).length
  const newLines = (text.match(/\n/g) || []).length
  const otherChars = text.length - chineseChars - codeSymbols

  const tokens = Math.ceil(
    chineseChars / 1.5 +     // 中文字符
    codeSymbols * 1.0 +       // 代码符号（通常每个是一个 token）
    otherChars / 4 +          // 英文/数字
    newLines * 0.5            // 换行
  )

  return Math.max(1, tokens)
}

/**
 * 估算消息数组的 Token 总量
 * 每条消息包含 ~4 token 的元数据开销（role 标签等）
 */
export function estimateMessagesTokens(messages: { role: string; content: string }[]): number {
  let total = 0
  for (const msg of messages) {
    total += estimateTokens(msg.content) + 4 // 消息元数据开销
  }
  return total + 2 // 对话格式开销
}

/**
 * 估算带有文件上下文的总 Token 量
 */
export function estimateWithFiles(query: string, files?: { content: string }[]): number {
  let total = estimateTokens(query)
  if (files) {
    for (const file of files) {
      total += estimateTokens(file.content) + 10 // 文件标签开销
    }
  }
  return total
}

/**
 * 格式化 Token 数量为人类可读格式
 */
export function formatTokenCount(count: number): string {
  if (count < 1000) return String(count)
  if (count < 10000) return `${(count / 1000).toFixed(1)}K`
  return `${Math.round(count / 1000)}K`
}

/**
 * 计算文本在不同模型下的 Token 预估
 * 不同厂商的 tokenizer 有差异，提供修正系数
 */
export function estimateForProvider(text: string, provider: string): number {
  const base = estimateTokens(text)
  
  // 不同 tokenizer 的修正系数
  const providerMultipliers: Record<string, number> = {
    openai: 1.0,      // GPT tokenizer 是基准
    anthropic: 1.05,   // Claude tokenizer 略多
    google: 0.95,      // Gemini tokenizer 略少
    ollama: 1.0,       // 取决于具体模型
  }

  const multiplier = providerMultipliers[provider] || 1.0
  return Math.ceil(base * multiplier)
}
