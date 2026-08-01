export interface NodeTypeDefinition {
  label: string
  color: string
  description: string
}

const FALLBACK: NodeTypeDefinition = {
  label: '其他模块',
  color: '#64748b',
  description: '尚未登记专用渲染器，按通用事实节点展示。',
}

export const NODE_TYPE_REGISTRY: Record<string, NodeTypeDefinition> = {
  feature: { label: '功能', color: '#7c3aed', description: '由 FeatureDefinition 声明的用户功能。' },
  page: { label: '页面', color: '#2563eb', description: '用户可进入的前端页面。' },
  bff_route: { label: 'BFF', color: '#0891b2', description: '同源边界与鉴权代理。' },
  api_route: { label: 'API', color: '#059669', description: '后端 HTTP 接口。' },
  mcp_tool: { label: 'MCP Tool', color: '#d97706', description: '可审计、可编排的工具能力。' },
  service: { label: '服务', color: '#4f46e5', description: '承载运行能力的服务。' },
  migration: { label: '迁移', color: '#9333ea', description: '数据库结构演进事实。' },
  table: { label: '数据表', color: '#be123c', description: '持久化数据实体。' },
  workflow: { label: '工作流', color: '#ea580c', description: '跨模块业务链路。' },
  evidence: { label: '证据', color: '#475569', description: '验证或交付证据。' },
}

export function nodeTypeDefinition(kind: string): NodeTypeDefinition {
  return NODE_TYPE_REGISTRY[kind] || { ...FALLBACK, label: kind || FALLBACK.label }
}
