import { NextResponse } from 'next/server'

export const runtime = 'nodejs'

/**
 * 拉 KE MCP server 的 tool 列表.
 *
 * KE 没暴露轻 REST endpoint(/api/v1/mcp/tools), 只有 /mcp/ JSON-RPC MCP 协议口.
 * 这里尝试 JSON-RPC tools/list — FastMCP 通常要求先 initialize 再 tools/list,
 * 不行就 ok=false 让前端 fallback 到 hard-code 清单(api.ts allToolNames).
 *
 * 即使这个接口跑通也只是给 UI 显示用; 实际 tool 能否被调走 spawn args 的
 * --allowedTools, KE 真实注册情况靠 doctor.py 自检.
 */
export async function GET() {
  const base = process.env.OMNI_KE_URL || 'http://localhost:8002'
  const url = `${base.replace(/\/$/, '')}/mcp/`
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'tools/list',
        params: {},
      }),
    })
    if (!resp.ok) {
      return NextResponse.json({ ok: false, error: `ke_${resp.status}` }, { status: 200 })
    }
    const text = await resp.text()
    // MCP HTTP 默认 SSE 编码: 找第一个 "data: " 行 parse JSON
    let payload: unknown = null
    if (text.startsWith('{')) {
      payload = JSON.parse(text)
    } else {
      const dataLine = text.split(/\r?\n/).find((l) => l.startsWith('data:'))
      if (dataLine) {
        payload = JSON.parse(dataLine.slice(5).trim())
      }
    }
    if (typeof payload !== 'object' || payload === null) {
      return NextResponse.json({ ok: false, error: 'bad_payload' })
    }
    const result = (payload as { result?: { tools?: Array<{ name: string }> } }).result
    if (!result?.tools || !Array.isArray(result.tools)) {
      return NextResponse.json({ ok: false, error: 'no_tools_in_result' })
    }
    const names = result.tools.map((t) => t.name).filter((n): n is string => typeof n === 'string')
    return NextResponse.json({ ok: true, tools: names, count: names.length })
  } catch (e) {
    return NextResponse.json({ ok: false, error: 'fetch_failed', detail: (e as Error).message })
  }
}
