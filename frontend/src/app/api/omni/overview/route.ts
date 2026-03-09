import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface HealthResp {
  status: string
  service: string
}

interface KnowledgeStatsResp {
  code: number
  message: string
  data: {
    knowledge_bases: number
    documents: number
    tasks_by_status: Record<string, number>
  }
}

interface KnowledgeBasesResp {
  code: number
  message: string
  data: Array<{ id: string }>
}

async function readHealth(url: string): Promise<'healthy' | 'down'> {
  try {
    const result = await fetchJson<HealthResp>(`${url}/health`)
    return result.status === 'healthy' ? 'healthy' : 'down'
  } catch {
    return 'down'
  }
}

export async function GET() {
  try {
    const base = serviceBase()
    const [identity, aiHub, knowledge, statsResp, kbResp] = await Promise.all([
      readHealth(base.identity),
      readHealth(base.aiHub),
      readHealth(base.knowledge),
      fetchJson<KnowledgeStatsResp>(`${base.knowledge}/api/v1/knowledge/stats`).catch(() => null),
      fetchJson<KnowledgeBasesResp>(`${base.knowledge}/api/v1/knowledge/bases`).catch(() => null),
    ])

    const stats = statsResp?.data
    const health = { identity, aiHub, knowledge }

    const totalServices = Object.keys(health).length
    const healthyServices = Object.values(health).filter((x) => x === 'healthy').length
    const infraUptime = totalServices > 0 ? Number(((healthyServices / totalServices) * 100).toFixed(1)) : 0

    const docCount = stats?.documents ?? 0
    const kbCount = stats?.knowledge_bases ?? kbResp?.data?.length ?? 0
    const runningTasks =
      (stats?.tasks_by_status.running || 0) +
      (stats?.tasks_by_status.processing || 0) +
      (stats?.tasks_by_status.queued || 0)

    return Response.json({
      success: true,
      data: {
        health,
        metrics: {
          identityUsers: 0,
          aiTokenToday: 0,
          knowledgeDocuments: docCount,
          infraUptime,
          knowledgeBases: kbCount,
          runningTasks,
        },
      },
    })
  } catch (error) {
    return Response.json({ success: false, error: String(error) }, { status: 500 })
  }
}
