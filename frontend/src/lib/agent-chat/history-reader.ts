import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import readline from 'node:readline'
import { createReadStream } from 'node:fs'
import type { ChatMessage, ChatAttachment } from './types'

/**
 * Claude Code 把项目目录 mangled 成扁平字符串。例：
 * E:\agent\omni -> E--agent-omni
 * /home/user -> -home-user
 *
 * 替换规则：所有路径分隔符 / 冒号 / 反斜杠 -> '-'
 */
export function encodeProjectDir(absPath: string): string {
  return absPath.replace(/[\\/:]/g, '-')
}

export function getSessionsDir(projectAbsPath: string = process.cwd()): string {
  return path.join(os.homedir(), '.claude', 'projects', encodeProjectDir(projectAbsPath))
}

interface ClaudeJsonlLine {
  type: 'user' | 'assistant' | 'system'
  message?: {
    id?: string
    role: 'user' | 'assistant'
    content: Array<
      | { type: 'text'; text: string }
      | { type: 'thinking'; thinking: string }
      | { type: 'tool_use'; id: string; name: string; input: Record<string, unknown> }
      | { type: 'tool_result'; tool_use_id: string; content: unknown; is_error?: boolean }
    >
    usage?: { input_tokens: number; output_tokens: number }
  }
  session_id?: string
  timestamp?: string
}

export async function readSessionHistory(jsonlPath: string): Promise<ChatMessage[]> {
  try {
    await fs.access(jsonlPath)
  } catch {
    return []
  }
  const messages: ChatMessage[] = []
  const rl = readline.createInterface({
    input: createReadStream(jsonlPath, { encoding: 'utf8' }),
    crlfDelay: Infinity,
  })
  for await (const line of rl) {
    if (!line.trim()) continue
    let parsed: ClaudeJsonlLine
    try {
      parsed = JSON.parse(line)
    } catch {
      continue
    }
    const msg = parsed.message
    if (!msg) continue
    const sessionId = parsed.session_id || ''
    const createdAt = parsed.timestamp || new Date().toISOString()
    for (const block of msg.content) {
      if (block.type === 'text') {
        messages.push({
          id: `${msg.id || crypto.randomUUID()}-${messages.length}`,
          session_id: sessionId,
          role: msg.role === 'user' ? 'user' : 'assistant',
          text: block.text,
          created_at: createdAt,
        })
      } else if (block.type === 'tool_use') {
        messages.push({
          id: `${block.id}-call`,
          session_id: sessionId,
          role: 'tool_call',
          tool_name: block.name,
          tool_args: block.input,
          tool_use_id: block.id,
          tool_status: 'completed',
          created_at: createdAt,
        })
      } else if (block.type === 'tool_result') {
        messages.push({
          id: `${block.tool_use_id}-result`,
          session_id: sessionId,
          role: 'tool_result',
          tool_use_id: block.tool_use_id,
          raw_result: block.content,
          attachments: extractAttachments(block.content),
          created_at: createdAt,
        })
      }
    }
  }
  return messages
}

function extractAttachments(content: unknown): ChatAttachment[] {
  if (typeof content !== 'string') return []
  let parsed: unknown
  try {
    parsed = JSON.parse(content)
  } catch {
    return []
  }
  if (typeof parsed !== 'object' || parsed === null) return []
  const obj = parsed as Record<string, unknown>
  const attachments: ChatAttachment[] = []
  const collectUrls = (val: unknown, type: 'image' | 'video') => {
    if (typeof val === 'string') attachments.push({ type, url: val })
    else if (Array.isArray(val)) {
      for (const v of val) {
        if (typeof v === 'string') attachments.push({ type, url: v })
        else if (typeof v === 'object' && v !== null && 'url' in v && typeof (v as { url: unknown }).url === 'string') {
          attachments.push({ type, url: (v as { url: string }).url })
        }
      }
    }
  }
  if ('image_url' in obj) collectUrls(obj.image_url, 'image')
  if ('image_urls' in obj) collectUrls(obj.image_urls, 'image')
  if ('video_url' in obj) collectUrls(obj.video_url, 'video')
  if ('video_urls' in obj) collectUrls(obj.video_urls, 'video')
  if ('markdown' in obj && typeof obj.markdown === 'string') {
    attachments.push({ type: 'markdown', markdown: obj.markdown })
  }
  if ('script_md' in obj && typeof obj.script_md === 'string') {
    attachments.push({ type: 'markdown', markdown: obj.script_md })
  }
  return attachments
}
