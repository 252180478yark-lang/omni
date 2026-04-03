import { fetchJson, serviceBase } from '../_shared'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

interface ActivityItem {
  id: string
  title: string
  status: string
  time: string
  source: 'knowledge' | 'news' | 'video' | 'livestream'
}

interface KnowledgeTask {
  id: string
  title: string
  status: string
  updated_at: string
  created_at: string
}

interface NewsJob {
  job_id: string
  status: string
  total_fetched: number
  started_at: string
  finished_at: string | null
}

interface VideoRecord {
  id: string
  original_name: string
  status: string
  created_at: string
  updated_at?: string
}

export async function GET() {
  const base = serviceBase()
  const items: ActivityItem[] = []

  const [knowledgeTasks, newsJobs, videos] = await Promise.allSettled([
    fetchJson<{ code: number; data: KnowledgeTask[] }>(
      `${base.knowledge}/api/v1/knowledge/tasks?limit=5`
    ),
    fetchJson<{ jobs: NewsJob[] }>(
      `${base.newsAggregator}/api/v1/news/fetch?limit=5`
    ),
    fetchJson<{ videos: VideoRecord[] }>(
      `${base.videoAnalysis}/api/v1/video-analysis/videos`
    ),
  ])

  if (knowledgeTasks.status === 'fulfilled') {
    for (const t of (knowledgeTasks.value.data ?? []).slice(0, 5)) {
      items.push({
        id: t.id,
        title: `知识入库: ${t.title || t.id.slice(0, 8)}`,
        status: t.status,
        time: t.updated_at || t.created_at,
        source: 'knowledge',
      })
    }
  }

  if (newsJobs.status === 'fulfilled') {
    for (const j of (newsJobs.value.jobs ?? []).slice(0, 5)) {
      items.push({
        id: String(j.job_id),
        title: `新闻抓取 (${j.total_fetched} 篇)`,
        status: j.status,
        time: j.finished_at || j.started_at,
        source: 'news',
      })
    }
  }

  if (videos.status === 'fulfilled') {
    const list = Array.isArray(videos.value)
      ? (videos.value as VideoRecord[])
      : (videos.value as { videos: VideoRecord[] }).videos ?? []
    for (const v of list.slice(0, 5)) {
      items.push({
        id: v.id,
        title: `视频分析: ${v.original_name}`,
        status: v.status,
        time: v.updated_at || v.created_at,
        source: 'video',
      })
    }
  }

  items.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())

  return Response.json({ success: true, data: items.slice(0, 10) })
}
