import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'

export function getOmniMcpUrl(): string {
  const base = process.env.OMNI_KE_URL || 'http://localhost:8002'
  return `${base.replace(/\/$/, '')}/mcp`
}

export interface McpConfig {
  mcpServers: Record<string, { type: 'http' | 'stdio'; url?: string; command?: string; args?: string[] }>
}

export function buildMcpConfig(): McpConfig {
  return {
    mcpServers: {
      omni: {
        type: 'http',
        url: getOmniMcpUrl(),
      },
    },
  }
}

/**
 * 写一份临时 mcp-config.json 到 ~/.claude/.tmp/，返回路径
 * 老板 spawn claude code 时通过 --mcp-config <path> 加载
 */
export async function writeTempMcpConfig(sessionId: string): Promise<string> {
  const dir = path.join(os.homedir(), '.claude', '.tmp')
  await fs.mkdir(dir, { recursive: true })
  const file = path.join(dir, `mcp-${sessionId}.json`)
  await fs.writeFile(file, JSON.stringify(buildMcpConfig(), null, 2), 'utf8')
  return file
}

export async function cleanupTempMcpConfig(sessionId: string): Promise<void> {
  const file = path.join(os.homedir(), '.claude', '.tmp', `mcp-${sessionId}.json`)
  await fs.unlink(file).catch(() => undefined)
}
