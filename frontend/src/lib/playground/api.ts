/**
 * playground 调试场 API helpers
 *
 * - 拉 KE 暴露的 MCP tool 列表(KE 没现成 REST endpoint, 先 hard-code 来自 doctor.py 的清单作 fallback,
 *   将来可补 GET /api/v1/mcp/tools/list 走 ListToolsResult 协议)
 * - 创建 sandbox session(走 /api/agent-chat/sessions POST 加 sandbox: true)
 */

// 来源: services/knowledge-engine/app/mcp/doctor.py wanted set
// W1+W2+W3a+W3b+W3c+W4-A+W4-B 切片 5/8/9/14.* + realman + video_anchor = 52 tool
// 按业务分类排列, 方便老板"全开 / 仅这一类"勾选
export const TOOL_GROUPS: Array<{ label: string; tools: string[] }> = [
  {
    label: 'W1 查询基础',
    tools: ['list_skus', 'get_sku', 'search_kb', 'list_kbs', 'list_briefs'],
  },
  {
    label: 'W2 算账 + 生成',
    tools: [
      'query_costs',
      'compute_margin',
      'generate_brief',
      'generate_image',
      'generate_video',
    ],
  },
  {
    label: 'W3a 成本写入 + brief grounding',
    tools: ['record_cost', 'disable_cost_item', 'gather_brief_context'],
  },
  {
    label: 'W3b 抓数 + KB 写入',
    tools: [
      'fetch_compass_store_daily',
      'fetch_compass_sku_detail',
      'fetch_compass_search_traffic',
      'fetch_yuntu_5a',
      'fetch_yuntu_brand_mind',
      'kb_upload_doc',
      'kb_set_role',
    ],
  },
  {
    label: 'W3c 通用 LLM',
    tools: ['summarize_text', 'parse_long_doc_with_gemini', 'query_template_chunks'],
  },
  {
    label: 'W4-A Agent 进化',
    tools: [
      'rate_tool_call',
      'agent_self_review',
      'codify_pattern_to_skill',
      'refresh_project_context',
    ],
  },
  {
    label: 'W4-B 决策 + 通知',
    tools: [
      'save_decision',
      'schedule_observation',
      'generate_image_compare',
      'send_wecom_message',
      'dy_publish_creative',
    ],
  },
  {
    label: 'W4-B 字典查询',
    tools: ['list_product_prices', 'list_channel_fees'],
  },
  {
    label: 'sku-pipeline LLM',
    tools: [
      'generate_selling_points_matrix',
      'generate_audience_match',
      'generate_audience_pack',
      'generate_keyword_pack',
      'generate_creative_pack',
      'generate_storyboard_images',
      'generate_character_sheets',
      'generate_video_segments',
    ],
  },
  {
    label: 'pipeline lineage',
    tools: [
      'pipeline_list_matrix_runs',
      'pipeline_get_matrix_run',
      'pipeline_list_audience_runs',
      'pipeline_get_audience_run',
      'pipeline_list_audience_records',
      'pipeline_get_audience_record',
      'pipeline_adopt',
    ],
  },
  {
    label: '真人视频 + t2v 锚点',
    tools: ['realman_create_avatar', 'realman_generate_portrait_video', 'generate_video_anchor'],
  },
  {
    label: '反推故事板(W7 新)',
    tools: ['reverse_storyboard_video'],
  },
]

/** 平铺所有 tool 名(去重 — 防 doctor 名单后续微调有重复) */
export function allToolNames(): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const g of TOOL_GROUPS) {
    for (const t of g.tools) {
      if (!seen.has(t)) {
        seen.add(t)
        out.push(t)
      }
    }
  }
  return out
}

/** 试着拉 KE 的真实 tool list(JSON-RPC tools/list);失败 fallback hard-code 清单 */
export async function fetchToolList(): Promise<{ tools: string[]; fromKe: boolean }> {
  try {
    const r = await fetch('/api/playground/tools', { cache: 'no-store' })
    if (!r.ok) throw new Error('not_ok')
    const j = (await r.json()) as { ok?: boolean; tools?: string[] }
    if (j?.ok && Array.isArray(j.tools) && j.tools.length > 0) {
      // MCP 自带 tool 还会含 fastmcp 内部的, 去掉非 omni tool — 这里简单过滤掉以下划线开头的
      const cleaned = j.tools.filter((t) => !t.startsWith('_'))
      return { tools: cleaned, fromKe: true }
    }
  } catch {
    /* fallback */
  }
  return { tools: allToolNames(), fromKe: false }
}

/** 创建 sandbox session(playground 专用 — 后端写库时打 sandbox=true) */
export async function createSandboxSession(title?: string): Promise<{ id: string }> {
  const r = await fetch('/api/agent-chat/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title || 'playground sandbox', sandbox: true }),
  })
  const j = await r.json()
  if (!j.success) throw new Error(j.error || 'create_session_failed')
  return { id: j.data.id as string }
}

/** 把 playground UI model key 映射成 claude.cmd --model 接受的字符串 */
export function modelToCliFlag(model: 'sonnet' | 'opus' | 'haiku'): string {
  if (model === 'opus') return 'claude-opus-4-7'
  if (model === 'haiku') return 'claude-haiku-4-5'
  return 'claude-sonnet-4-6'
}
