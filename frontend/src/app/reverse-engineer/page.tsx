'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'

type TabType = 'video' | 'detail-page' | 'main-image'

interface KbItem {
  id: string
  name: string
}

interface Material {
  id: string
  material_type: string
  title: string
  status: string
  progress: number
  progress_message: string
  created_at: string
}

interface MaterialUnit {
  unit_index: number
  unit_type: string
  start_sec?: number
  end_sec?: number
  image_index?: number
  fields: Record<string, unknown>
  prompt_pack: Record<string, string>
}

interface MaterialDetail {
  material: Material & Record<string, unknown>
  units: MaterialUnit[]
}

export default function ReverseEngineerPage() {
  const [tab, setTab] = useState<TabType>('video')
  const [kbs, setKbs] = useState<KbItem[]>([])
  const [kbId, setKbId] = useState('')
  const [files, setFiles] = useState<FileList | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [list, setList] = useState<Material[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState<MaterialDetail | null>(null)

  const accept = useMemo(() => {
    if (tab === 'video') return '.mp4,.mov'
    return '.jpg,.jpeg,.png'
  }, [tab])

  const multiple = tab !== 'video'

  async function refreshList() {
    const res = await fetch('/api/omni/reverse-engineer', { cache: 'no-store' })
    if (!res.ok) throw new Error(await res.text())
    const data = (await res.json()) as { items: Material[] }
    setList(data.items || [])
    if (!selectedId && data.items?.length) {
      setSelectedId(data.items[0].id)
    }
  }

  async function loadDetail(id: string) {
    const res = await fetch(`/api/omni/reverse-engineer/${id}`, { cache: 'no-store' })
    if (!res.ok) throw new Error(await res.text())
    const data = (await res.json()) as MaterialDetail
    setDetail(data)
  }

  useEffect(() => {
    const init = async () => {
      const kbRes = await fetch('/api/omni/knowledge/bases', { cache: 'no-store' })
      const kbJson = (await kbRes.json()) as { success: boolean; data?: KbItem[] }
      if (kbJson.success) {
        setKbs(kbJson.data || [])
      }
      await refreshList()
    }
    void init().catch((e) => setMessage(String(e)))
  }, [])

  useEffect(() => {
    if (!selectedId) return
    void loadDetail(selectedId).catch((e) => setMessage(String(e)))
  }, [selectedId])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshList().catch(() => null)
      if (selectedId) {
        void loadDetail(selectedId).catch(() => null)
      }
    }, 2500)
    return () => window.clearInterval(timer)
  }, [selectedId])

  async function submit() {
    if (!kbId) {
      setMessage('请先选择目标知识库')
      return
    }
    if (!files || files.length === 0) {
      setMessage('请先选择文件')
      return
    }
    setLoading(true)
    setMessage('')
    try {
      if (tab === 'video' && files[0].size > 500 * 1024 * 1024) {
        throw new Error('视频超过 500MB 限制')
      }
      const form = new FormData()
      form.append('kb_id', kbId)
      if (tab === 'video') {
        form.append('file', files[0])
      } else {
        Array.from(files).forEach((f) => form.append('files', f))
      }
      const endpoint =
        tab === 'video'
          ? '/api/omni/reverse-engineer?mode=video'
          : tab === 'detail-page'
            ? '/api/omni/reverse-engineer?mode=detail-page'
            : '/api/omni/reverse-engineer?mode=main-image'
      const res = await fetch(endpoint, { method: 'POST', body: form })
      if (!res.ok) throw new Error(await res.text())
      const json = (await res.json()) as { material_id: string }
      setSelectedId(json.material_id)
      await refreshList()
      setMessage('任务已提交，正在拆解')
    } catch (e) {
      setMessage(String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <Link href="/" className="text-gray-500 hover:text-gray-900">← 返回控制台</Link>
          <div className="font-semibold text-gray-900">爆款素材反向拆解</div>
          <Link href="/video-analysis" className="text-sm text-blue-600 hover:underline">回到短视频分析</Link>
        </div>
      </nav>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8 space-y-4">
        <div className="rounded-xl bg-white p-4 shadow-sm border border-gray-100 space-y-4">
          <div className="flex gap-2">
            {[
              { key: 'video', label: '视频拆解' },
              { key: 'detail-page', label: '详情页拆解' },
              { key: 'main-image', label: '主图拆解' },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setTab(item.key as TabType)}
                className={`px-3 py-2 text-sm rounded-md ${tab === item.key ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700'}`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="grid md:grid-cols-3 gap-3 items-end">
            <div>
              <div className="text-xs text-gray-500 mb-1">目标知识库（必选）</div>
              <select value={kbId} onChange={(e) => setKbId(e.target.value)} className="h-10 rounded-md border px-3 w-full">
                <option value="">请选择知识库</option>
                {kbs.map((kb) => (
                  <option key={kb.id} value={kb.id}>{kb.name}</option>
                ))}
              </select>
            </div>
            <div>
              <div className="text-xs text-gray-500 mb-1">{tab === 'video' ? '上传视频（单文件）' : '上传图片（多文件）'}</div>
              <input
                type="file"
                accept={accept}
                multiple={multiple}
                onChange={(e) => setFiles(e.target.files)}
                className="h-10 text-sm w-full"
              />
            </div>
            <button
              type="button"
              onClick={() => void submit()}
              disabled={loading || !kbId}
              className="h-10 rounded-md bg-blue-600 text-white text-sm disabled:opacity-50"
            >
              {loading ? '提交中...' : '开始拆解'}
            </button>
          </div>
        </div>

        <div className="grid lg:grid-cols-3 gap-4">
          <div className="rounded-xl bg-white p-4 shadow-sm border border-gray-100">
            <div className="text-sm font-medium mb-3">任务列表</div>
            <div className="space-y-2 max-h-[560px] overflow-auto">
              {list.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setSelectedId(m.id)}
                  className={`w-full text-left p-3 rounded-lg border ${selectedId === m.id ? 'border-blue-500 bg-blue-50' : 'border-gray-100'}`}
                >
                  <div className="text-sm font-medium truncate">{m.title || m.id}</div>
                  <div className="text-xs text-gray-500 mt-1">{m.material_type} · {m.status}</div>
                  <div className="text-xs text-gray-400 mt-1">{m.progress_message || ''}</div>
                </button>
              ))}
            </div>
          </div>
          <div className="lg:col-span-2 rounded-xl bg-white p-4 shadow-sm border border-gray-100 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium">拆解详情</div>
              {detail?.material?.status ? (
                <div className="text-xs text-gray-500">
                  {String(detail.material.status)} · {String(detail.material.phase || '')} · {Math.round(Number(detail.material.progress || 0) * 100)}%
                </div>
              ) : null}
            </div>
            {!detail ? <div className="text-sm text-gray-400">请选择任务</div> : null}
            {detail?.units?.map((u) => (
              <div key={`${u.unit_index}-${u.unit_type}`} className="rounded-lg border border-gray-100 p-3 space-y-2">
                <div className="text-sm font-medium">Unit {u.unit_index} · {u.unit_type}</div>
                <div className="text-xs text-gray-500">
                  {typeof u.start_sec === 'number' ? `${u.start_sec}s - ${u.end_sec}s` : `image_index: ${String(u.image_index ?? '-')}`}
                </div>
                <div className="text-xs text-gray-700">{String(u.fields?.visual_description || '')}</div>
                <div className="grid md:grid-cols-2 gap-2">
                  <textarea readOnly value={u.prompt_pack?.image_prompt_zh || ''} className="h-20 text-xs border rounded p-2" />
                  <textarea readOnly value={u.prompt_pack?.image_prompt_en || ''} className="h-20 text-xs border rounded p-2" />
                  {u.prompt_pack?.video_prompt_zh ? (
                    <textarea readOnly value={u.prompt_pack?.video_prompt_zh || ''} className="h-20 text-xs border rounded p-2" />
                  ) : null}
                  {u.prompt_pack?.video_prompt_en ? (
                    <textarea readOnly value={u.prompt_pack?.video_prompt_en || ''} className="h-20 text-xs border rounded p-2" />
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
        {message ? <div className="text-sm rounded-md border bg-white px-4 py-3">{message}</div> : null}
      </main>
    </div>
  )
}
