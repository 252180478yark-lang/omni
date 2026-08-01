import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

export function getOmniMcpUrl(): string {
  const base = process.env.OMNI_KE_URL || 'http://localhost:8002'
  return `${base.replace(/\/$/, '')}/mcp`
}

export interface McpConfig {
  mcpServers: Record<string, { type: 'http' | 'stdio'; url?: string; command?: string; args?: string[]; headers?: Record<string, string> }>
}

export interface McpTraceContext {
  traceId: string
  executionId: string
  parentSpanId: string
  sessionId: string
  correlationId?: string
  gateId?: string
}

export function traceHeaders(context: McpTraceContext): Record<string, string> {
  return {
    'X-Omni-Trace-Id': context.traceId,
    'X-Omni-Execution-Id': context.executionId,
    'X-Omni-Parent-Span-Id': context.parentSpanId,
    'X-Omni-Session-Id': context.sessionId,
    ...(context.correlationId ? { 'X-Omni-Correlation-Id': context.correlationId } : {}),
    ...(context.gateId ? { 'X-Omni-Gate-Id': context.gateId } : {}),
  }
}

export function buildMcpConfig(context?: McpTraceContext): McpConfig {
  return {
    mcpServers: {
      omni: {
        type: 'http',
        url: getOmniMcpUrl(),
        ...(context ? { headers: traceHeaders(context) } : {}),
      },
    },
  }
}

/**
 * 写一份临时 mcp-config.json 到 ~/.claude/.tmp/，返回路径
 * 老板 spawn claude code 时通过 --mcp-config <path> 加载
 */
export async function writeTempMcpConfig(sessionId: string, context?: McpTraceContext): Promise<string> {
  const dir = path.join(os.homedir(), '.claude', '.tmp')
  await fs.mkdir(dir, { recursive: true })
  const file = path.join(dir, `mcp-${sessionId}.json`)
  await fs.writeFile(file, JSON.stringify(buildMcpConfig(context), null, 2), 'utf8')
  return file
}

export async function cleanupTempMcpConfig(sessionId: string): Promise<void> {
  const file = path.join(os.homedir(), '.claude', '.tmp', `mcp-${sessionId}.json`)
  await fs.unlink(file).catch(() => undefined)
}
