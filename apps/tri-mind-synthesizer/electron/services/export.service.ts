import { ChatNode, Session } from '../../src/lib/types'
import * as dbService from './db.service'

/**
 * 导出服务
 * 
 * 支持将辩论记录导出为 Markdown 或 JSON 格式
 */

/**
 * 导出为 Markdown 格式
 */
export function exportToMarkdown(sessionId: string): string {
  const session = dbService.getSession(sessionId)
  const nodes = dbService.getSessionNodes(sessionId)

  if (!session) {
    return '# 导出失败\n\n会话不存在'
  }

  const lines: string[] = []

  // 标题
  lines.push(`# ${session.title}`)
  lines.push('')
  lines.push(`> 导出时间: ${new Date().toLocaleString('zh-CN')}`)
  lines.push(`> 创建时间: ${new Date(session.createdAt).toLocaleString('zh-CN')}`)
  lines.push('')
  lines.push('---')
  lines.push('')

  // 按轮次分组消息
  const userMessages = nodes.filter(n => n.role === 'user')
  const assistantMessages = nodes.filter(n => n.role === 'assistant')
  const verdictMessages = nodes.filter(n => n.role === 'verdict')

  // 用户问题
  if (userMessages.length > 0) {
    lines.push('## 用户问题')
    lines.push('')
    userMessages.forEach(msg => {
      lines.push(msg.content)
      lines.push('')
    })
    lines.push('---')
    lines.push('')
  }

  // 按轮次输出模型回答
  const rounds = new Set(assistantMessages.map(m => m.round).filter(r => r !== undefined))
  
  for (const round of Array.from(rounds).sort()) {
    lines.push(`## 第 ${round} 轮辩论`)
    lines.push('')

    const roundMessages = assistantMessages.filter(m => m.round === round)
    for (const msg of roundMessages) {
      lines.push(`### ${msg.modelId || '模型'}`)
      lines.push('')
      lines.push(msg.content)
      lines.push('')
      
      if (msg.tokenInput || msg.tokenOutput) {
        lines.push(`> Token: ${msg.tokenInput} 输入 / ${msg.tokenOutput} 输出`)
        lines.push('')
      }
    }

    lines.push('---')
    lines.push('')
  }

  // 最终裁决
  if (verdictMessages.length > 0) {
    lines.push('## 最终裁决')
    lines.push('')
    verdictMessages.forEach(msg => {
      lines.push(msg.content)
      lines.push('')
    })
  }

  // 统计信息
  lines.push('---')
  lines.push('')
  lines.push('## 统计信息')
  lines.push('')
  
  const totalInputTokens = nodes.reduce((sum, n) => sum + (n.tokenInput || 0), 0)
  const totalOutputTokens = nodes.reduce((sum, n) => sum + (n.tokenOutput || 0), 0)
  
  lines.push(`- 辩论轮数: ${rounds.size}`)
  lines.push(`- 参与模型数: ${new Set(assistantMessages.map(m => m.modelId)).size}`)
  lines.push(`- 总输入 Token: ${totalInputTokens}`)
  lines.push(`- 总输出 Token: ${totalOutputTokens}`)
  lines.push('')

  return lines.join('\n')
}

/**
 * 导出为 JSON 格式
 */
export function exportToJSON(sessionId: string): string {
  const session = dbService.getSession(sessionId)
  const nodes = dbService.getSessionNodes(sessionId)

  if (!session) {
    return JSON.stringify({ error: '会话不存在' }, null, 2)
  }

  const exportData = {
    version: '1.0',
    exportedAt: new Date().toISOString(),
    session: {
      id: session.id,
      title: session.title,
      createdAt: session.createdAt,
      updatedAt: session.updatedAt,
      config: session.config,
    },
    nodes: nodes.map(node => ({
      id: node.id,
      role: node.role,
      modelId: node.modelId,
      content: node.content,
      round: node.round,
      tokenInput: node.tokenInput,
      tokenOutput: node.tokenOutput,
      createdAt: node.createdAt,
    })),
    statistics: {
      totalRounds: Math.max(...nodes.filter(n => n.round).map(n => n.round!), 0),
      modelsCount: new Set(nodes.filter(n => n.modelId).map(n => n.modelId)).size,
      totalInputTokens: nodes.reduce((sum, n) => sum + (n.tokenInput || 0), 0),
      totalOutputTokens: nodes.reduce((sum, n) => sum + (n.tokenOutput || 0), 0),
    },
  }

  return JSON.stringify(exportData, null, 2)
}

/**
 * 生成导出文件名
 */
export function generateExportFilename(session: Session | null, format: 'md' | 'json'): string {
  const title = session?.title || '辩论记录'
  const safeTitle = title.replace(/[<>:"/\\|?*]/g, '_').substring(0, 50)
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').substring(0, 19)
  
  return `${safeTitle}_${timestamp}.${format}`
}
