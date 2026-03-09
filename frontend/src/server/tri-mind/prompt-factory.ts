import { v4 as uuidv4 } from 'uuid'
import type {
  Message,
  ModelConfig,
  RoundHistory,
  FileAttachment,
  ReportDetailLevel,
} from './types'

interface BuildPromptParams {
  round: number
  originalQuery: string
  previousRounds: RoundHistory[]
  fileContext?: FileAttachment[]
  userIntervention?: string
  isVerdict?: boolean
  reportDetailLevel?: ReportDetailLevel
}

export class PromptFactory {
  buildSystemPrompt(
    round: number,
    isVerdict = false,
    reportDetailLevel: ReportDetailLevel = 'standard'
  ): string {
    if (isVerdict) {
      const lengthRule: Record<ReportDetailLevel, string> = {
        brief: '篇幅控制在约 500-900 字，强调结论与关键证据。',
        standard: '篇幅控制在约 1200-2200 字，覆盖完整分析链路。',
        detailed: '篇幅控制在约 2500-4500 字，展开深度推理、细节比较与落地方案。',
      }

      const detailRule: Record<ReportDetailLevel, string> = {
        brief: '每个章节 2-4 个要点，避免冗长背景。',
        standard: '每个章节 4-8 个要点，兼顾深度与可读性。',
        detailed: '每个章节 6-12 个要点，必须展示充分证据与推理过程。',
      }

      return `你是一位"多模型辩论总评裁判"，目标是把多轮辩论整合成一份可执行、可审计、可复盘的最终报告。

输出要求（严格遵守）：
1) 使用清晰的 Markdown 标题与小节。
2) 明确引用证据来源（来自哪一轮、哪位模型的关键论点）。
3) 对不确定性进行标注，不得伪造证据。
4) ${lengthRule[reportDetailLevel]}
5) ${detailRule[reportDetailLevel]}

请按以下结构输出（不可省略）：
## 1. 问题背景与目标重述
## 2. 各方观点总览
## 3. 逐点对比分析（核心）
## 4. 证据与可信度评估
## 5. 最终结论（明确可执行）
## 6. 执行建议（分阶段）
## 7. 风险清单与规避策略
## 8. 信息缺口与下一步验证计划

写作风格：先结论后论证，语言清晰，避免空话。`
    }

    if (round === 1) {
      return `你是一位专业的AI助手。请仔细思考用户的问题，给出详细、准确、有见地的回答。
注意：如果涉及代码，请提供完整可运行的示例；如果涉及分析，请列出关键点和依据；如果有不确定的地方，请明确说明。`
    }

    return `你是一位专业的AI助手，正在参与多轮辩论。
在这一轮中，你需要：
1. 审视其他AI助手的回答，指出其中的错误、遗漏或不足
2. 完善和改进你自己的回答
3. 如果发现自己之前的错误，请坦诚承认并修正
保持专业、客观，专注于提供最准确、最有价值的信息。`
  }

  buildPrompt(params: BuildPromptParams): Message[] {
    const messages: Message[] = []
    const {
      round,
      originalQuery,
      previousRounds,
      fileContext,
      userIntervention,
      isVerdict,
      reportDetailLevel,
    } = params

    messages.push({
      id: uuidv4(),
      role: 'system',
      content: this.buildSystemPrompt(round, isVerdict, reportDetailLevel),
      timestamp: Date.now(),
    })

    if (fileContext && fileContext.length > 0) {
      const fileContent = this.formatFileContext(fileContext)
      messages.push({
        id: uuidv4(),
        role: 'user',
        content: fileContent,
        timestamp: Date.now(),
      })
    }

    messages.push({
      id: uuidv4(),
      role: 'user',
      content: originalQuery,
      timestamp: Date.now(),
    })

    if (round > 1 && previousRounds.length > 0) {
      const peerReviewContent = this.formatPeerReview(previousRounds, !!isVerdict)
      messages.push({
        id: uuidv4(),
        role: 'user',
        content: peerReviewContent,
        timestamp: Date.now(),
      })
    }

    if (userIntervention) {
      messages.push({
        id: uuidv4(),
        role: 'user',
        content: `[USER INTERVENTION]\n${userIntervention}\n[/USER INTERVENTION]`,
        timestamp: Date.now(),
      })
    }

    if (!isVerdict && round > 1) {
      messages.push({
        id: uuidv4(),
        role: 'user',
        content: this.buildRoundInstruction(round),
        timestamp: Date.now(),
      })
    }

    return messages
  }

  buildRoundPrompts(
    models: ModelConfig[],
    params: Omit<BuildPromptParams, 'isVerdict'>
  ): Map<string, Message[]> {
    const prompts = new Map<string, Message[]>()
    for (const model of models) {
      prompts.set(model.id, this.buildPrompt({ ...params, isVerdict: false }))
    }
    return prompts
  }

  buildVerdictPrompt(
    params: Omit<BuildPromptParams, 'round' | 'isVerdict'>
  ): Message[] {
    return this.buildPrompt({
      ...params,
      round: params.previousRounds.length + 1,
      isVerdict: true,
      reportDetailLevel: params.reportDetailLevel || 'standard',
    })
  }

  private formatFileContext(files: FileAttachment[]): string {
    const parts: string[] = ['以下是用户提供的参考文件：\n']
    for (const file of files) {
      parts.push(`[FILE: ${file.name}]`)
      if (this.isCodeFile(file.name)) {
        const lang = this.getLanguageFromFilename(file.name)
        parts.push(`\`\`\`${lang}\n${file.content}\n\`\`\``)
      } else {
        parts.push(file.content)
      }
      parts.push(`[/FILE: ${file.name}]\n`)
    }
    return parts.join('\n')
  }

  private formatPeerReview(rounds: RoundHistory[], isVerdict: boolean): string {
    const parts: string[] = []
    parts.push(
      isVerdict
        ? '以下是各AI助手在整个辩论过程中的回答：\n'
        : '以下是其他AI助手的回答，请审视并改进你的观点：\n'
    )
    for (const round of rounds) {
      parts.push(`--- 第 ${round.round} 轮 ${round.compressed ? '(已压缩)' : ''} ---\n`)
      for (const [modelId, response] of Array.from(round.responses)) {
        parts.push(`【${modelId}】`)
        parts.push(response)
        parts.push('')
      }
    }
    return parts.join('\n')
  }

  private buildRoundInstruction(round: number): string {
    return `这是第 ${round} 轮辩论。请：
1. 仔细阅读上面其他AI助手的回答
2. 指出你发现的任何错误、遗漏或可以改进的地方
3. 提供你更新后的、更完善的回答
如果你认为某个观点是正确的，也请明确表示认同。`
  }

  private isCodeFile(filename: string): boolean {
    const codeExtensions = [
      '.js', '.ts', '.jsx', '.tsx', '.py', '.java', '.cpp', '.c',
      '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.cs', '.vue',
      '.html', '.css', '.scss', '.json', '.yaml', '.yml', '.xml',
      '.sql', '.sh', '.bash', '.zsh', '.md', '.markdown',
    ]
    return codeExtensions.some((ext) => filename.toLowerCase().endsWith(ext))
  }

  private getLanguageFromFilename(filename: string): string {
    const ext = filename.split('.').pop()?.toLowerCase() || ''
    const langMap: Record<string, string> = {
      js: 'javascript',
      ts: 'typescript',
      jsx: 'jsx',
      tsx: 'tsx',
      py: 'python',
      java: 'java',
      cpp: 'cpp',
      c: 'c',
      go: 'go',
      rs: 'rust',
      rb: 'ruby',
      php: 'php',
      swift: 'swift',
      kt: 'kotlin',
      cs: 'csharp',
      vue: 'vue',
      html: 'html',
      css: 'css',
      scss: 'scss',
      json: 'json',
      yaml: 'yaml',
      yml: 'yaml',
      xml: 'xml',
      sql: 'sql',
      sh: 'bash',
      bash: 'bash',
      md: 'markdown',
    }
    return langMap[ext] || ext
  }
}

export const promptFactory = new PromptFactory()
