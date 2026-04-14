const BFF = '/api/omni/ad-review'

async function parseJson<T>(res: Response): Promise<T> {
  const text = await res.text()
  if (!res.ok) {
    try {
      const j = JSON.parse(text) as { detail?: string; message?: string }
      throw new Error(j.detail || j.message || text || res.statusText)
    } catch {
      throw new Error(text || res.statusText)
    }
  }
  return text ? (JSON.parse(text) as T) : ({} as T)
}

export async function arFetch(path: string, init?: RequestInit): Promise<Response> {
  const url = `${BFF}/${path.replace(/^\//, '')}`
  return fetch(url, { ...init, cache: 'no-store' })
}

export type CampaignListItem = Record<string, unknown> & {
  id: string
  name: string
  product_name?: string
  start_date?: string
  end_date?: string
  total_cost?: number | null
  status?: string
  audience_count?: number
  material_count?: number
  best_ctr?: number | null
}

export async function listCampaigns(qs?: string): Promise<{ items: CampaignListItem[] }> {
  const res = await arFetch(`campaigns${qs ? `?${qs}` : ''}`)
  return parseJson(res)
}

export async function listProducts(): Promise<{ items: { id: string; name: string }[] }> {
  const res = await arFetch('products')
  return parseJson(res)
}

export async function createCampaign(body: unknown): Promise<{ id: string }> {
  const res = await arFetch('campaigns', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJson(res)
}

export async function getCampaignDetail(id: string): Promise<{
  campaign: Record<string, unknown>
  audiences: Record<string, unknown>[]
  materials: Record<string, unknown>[]
  groups: Record<string, unknown>[]
  review_log: Record<string, unknown> | null
}> {
  const res = await arFetch(`campaigns/${id}`)
  return parseJson(res)
}

export async function updateCampaign(id: string, body: unknown): Promise<{ ok: boolean }> {
  const res = await arFetch(`campaigns/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJson(res)
}

export async function deleteCampaign(id: string): Promise<{ ok: boolean }> {
  const res = await arFetch(`campaigns/${id}`, { method: 'DELETE' })
  return parseJson(res)
}

export async function createAudience(campaignId: string, body: unknown): Promise<{ id: string }> {
  const res = await arFetch(`campaigns/${campaignId}/audiences`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJson(res)
}

export async function deleteAudience(audienceId: string): Promise<{ ok: boolean }> {
  const res = await arFetch(`audiences/${audienceId}`, { method: 'DELETE' })
  return parseJson(res)
}

export async function updateAudience(
  audienceId: string,
  body: Record<string, unknown>,
): Promise<{ ok: boolean }> {
  const res = await arFetch(`audiences/${audienceId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJson(res)
}

export async function uploadAudienceProfile(audienceId: string, file: File): Promise<{ path: string; filename: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await arFetch(`audiences/${audienceId}/upload-profile`, { method: 'POST', body: fd })
  return parseJson(res)
}

export async function uploadAudienceTargeting(audienceId: string, file: File): Promise<{ path: string; filename: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await arFetch(`audiences/${audienceId}/upload-targeting`, { method: 'POST', body: fd })
  return parseJson(res)
}

export async function getIterationChain(materialId: string): Promise<{ chain: Record<string, unknown>[] }> {
  const res = await arFetch(`materials/${materialId}/iteration-chain`)
  return parseJson(res)
}

export async function previewCsv(audienceId: string, file: File): Promise<unknown> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('preview', 'true')
  const res = await arFetch(`audiences/${audienceId}/import-csv`, { method: 'POST', body: fd })
  return parseJson(res)
}

export async function importCsv(audienceId: string, file: File): Promise<{ imported: number; items: unknown[] }> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('preview', 'false')
  const res = await arFetch(`audiences/${audienceId}/import-csv`, { method: 'POST', body: fd })
  return parseJson(res)
}

export async function deleteMaterial(materialId: string): Promise<{ ok: boolean }> {
  const res = await arFetch(`materials/${materialId}`, { method: 'DELETE' })
  return parseJson(res)
}

export async function updateMaterial(materialId: string, body: Record<string, unknown>): Promise<{ ok: boolean }> {
  const res = await arFetch(`materials/${materialId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJson(res)
}

export async function linkVideo(materialId: string, videoAnalysisId: string | null): Promise<{ ok: boolean }> {
  const res = await arFetch(`materials/${materialId}/link-video`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_analysis_id: videoAnalysisId }),
  })
  return parseJson(res)
}

export async function linkParent(
  materialId: string,
  parentId: string,
  note: string,
  changeTags: string[] = [],
): Promise<{ ok: boolean }> {
  const res = await arFetch(`materials/${materialId}/link-parent`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ parent_material_id: parentId, iteration_note: note, change_tags: changeTags }),
  })
  return parseJson(res)
}

export async function createGroup(audienceId: string, body: { style_label: string; video_purpose?: string; description?: string }): Promise<{ id: string }> {
  const res = await arFetch(`audiences/${audienceId}/groups`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJson(res)
}

export async function updateGroup(groupId: string, body: { style_label?: string; description?: string }): Promise<{ ok: boolean }> {
  const res = await arFetch(`groups/${groupId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJson(res)
}

export async function deleteGroup(groupId: string): Promise<{ ok: boolean }> {
  const res = await arFetch(`groups/${groupId}`, { method: 'DELETE' })
  return parseJson(res)
}

export async function batchGroupMaterials(materialIds: string[], groupId: string | null): Promise<{ ok: boolean }> {
  const res = await arFetch('materials/batch-group', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ material_ids: materialIds, group_id: groupId }),
  })
  return parseJson(res)
}

export async function listVideos(): Promise<Record<string, unknown>[]> {
  const res = await fetch('/api/omni/video-analysis/videos', { cache: 'no-store' })
  const data = await res.json()
  return Array.isArray(data) ? data : []
}

export async function uploadVideoForAnalysis(file: File): Promise<{ id: string; status?: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch('/api/omni/video-analysis/videos', {
    method: 'POST',
    body: fd,
    cache: 'no-store',
  })
  return parseJson(res)
}

/** SP6 视频详情（含 report.scores.overall） */
export async function getVideoDetail(videoId: string): Promise<{
  report?: { scores?: { overall?: number } }
  video?: Record<string, unknown>
}> {
  const res = await fetch(`/api/omni/video-analysis/videos/${encodeURIComponent(videoId)}`, { cache: 'no-store' })
  if (!res.ok) return {}
  return res.json() as Promise<{ report?: { scores?: { overall?: number } }; video?: Record<string, unknown> }>
}

export type SsePayload = { type: string; content?: string; review_log_id?: string }

export function parseSseDataLines(buffer: string): { events: SsePayload[]; rest: string } {
  const parts = buffer.split('\n\n')
  const rest = parts.pop() ?? ''
  const events: SsePayload[] = []
  for (const block of parts) {
    for (const line of block.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data:')) continue
      const raw = trimmed.slice(5).trim()
      if (!raw) continue
      try {
        events.push(JSON.parse(raw) as SsePayload)
      } catch {
        /* skip */
      }
    }
  }
  return { events, rest }
}

export async function streamGenerateReview(
  campaignId: string,
  replace: boolean,
  onEvent: (e: SsePayload) => void,
  kbIds?: string[],
): Promise<void> {
  const params = new URLSearchParams({ replace: replace ? 'true' : 'false' })
  if (kbIds && kbIds.length > 0) params.set('kb_ids', kbIds.join(','))
  const res = await arFetch(`campaigns/${campaignId}/generate-review?${params}`, {
    method: 'POST',
  })
  if (!res.ok || !res.body) {
    throw new Error(await res.text())
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const { events, rest } = parseSseDataLines(buf)
    buf = rest
    for (const e of events) onEvent(e)
  }
  const { events } = parseSseDataLines(buf + '\n\n')
  for (const e of events) onEvent(e)
}

export async function getReview(campaignId: string): Promise<{ review_log: Record<string, unknown> | null }> {
  const res = await arFetch(`campaigns/${campaignId}/review`)
  return parseJson(res)
}

export async function saveReview(
  campaignId: string,
  content_md: string,
  experience_tags: string[],
): Promise<{ ok: boolean }> {
  const res = await arFetch(`campaigns/${campaignId}/review`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content_md, experience_tags }),
  })
  return parseJson(res)
}

export async function syncKb(campaignId: string): Promise<{ ok: boolean; kb_id?: string; document_id?: string | null }> {
  const res = await arFetch(`campaigns/${campaignId}/review/sync-kb`, { method: 'POST' })
  return parseJson(res)
}

export async function listKnowledgeBases(): Promise<{ id: string; name: string }[]> {
  const res = await fetch('/api/omni/knowledge/bases', { cache: 'no-store' })
  if (!res.ok) return []
  const data = await res.json()
  const items = data?.data || data?.items || (Array.isArray(data) ? data : [])
  return items.map((kb: Record<string, unknown>) => ({ id: String(kb.id), name: String(kb.name) }))
}

export async function productTrend(productId: string): Promise<{ points: Record<string, unknown>[] }> {
  const res = await arFetch(`analytics/product-trend?product_id=${encodeURIComponent(productId)}`)
  return parseJson(res)
}

export async function audienceCompare(cid: string): Promise<{ rows: Record<string, unknown>[] }> {
  const res = await arFetch(`analytics/audience-compare?cid=${encodeURIComponent(cid)}`)
  return parseJson(res)
}
