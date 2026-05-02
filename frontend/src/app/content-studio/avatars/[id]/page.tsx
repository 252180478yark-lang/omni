'use client'

import Image from 'next/image'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { useContentStudioStore, type DigitalHuman, type Pipeline } from '@/stores/contentStudioStore'

export default function AvatarDetailPage() {
  const params = useParams<{ id: string }>()
  const avatarId = params?.id ?? ''
  const router = useRouter()
  const {
    promoteDigitalHuman,
    archiveDigitalHuman,
    fetchAvatarPipelines,
  } = useContentStudioStore()

  const [avatar, setAvatar] = useState<DigitalHuman | null>(null)
  const [pipelines, setPipelines] = useState<Pipeline[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 编辑器
  const [name, setName] = useState('')
  const [gender, setGender] = useState('')
  const [ageRange, setAgeRange] = useState('')
  const [identityAnchor, setIdentityAnchor] = useState('')
  const [styleTagsText, setStyleTagsText] = useState('')
  const [faceUrlsText, setFaceUrlsText] = useState('')

  useEffect(() => {
    if (!avatarId) return
    let cancelled = false
    void (async () => {
      setLoading(true)
      try {
        const r = await fetch(`/api/omni/content-studio/digital-humans/${avatarId}`, { cache: 'no-store' })
        if (!r.ok) throw new Error(`${r.status}`)
        const data = (await r.json()) as DigitalHuman
        if (cancelled) return
        setAvatar(data)
        setName(data.name || '')
        setGender(data.gender || '')
        setAgeRange(data.age_range || '')
        setIdentityAnchor(data.identity_anchor || '')
        setStyleTagsText((data.style_tags ?? []).join(','))
        setFaceUrlsText((data.face_urls ?? []).join('\n'))

        const ps = await fetchAvatarPipelines(avatarId)
        if (cancelled) return
        setPipelines(ps)
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [avatarId, fetchAvatarPipelines])

  const onSave = async () => {
    if (!avatar) return
    setSaving(true)
    setError(null)
    try {
      const faceUrls = faceUrlsText.split('\n').map((s) => s.trim()).filter(Boolean)
      const styleTags = styleTagsText.split(',').map((s) => s.trim()).filter(Boolean)
      const r = await fetch(`/api/omni/content-studio/digital-humans/${avatar.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          gender: gender || null,
          age_range: ageRange || null,
          identity_anchor: identityAnchor || null,
          style_tags: styleTags,
          face_urls: faceUrls,
          seed_face_url: faceUrls[0] || avatar.seed_face_url,
        }),
      })
      if (!r.ok) throw new Error(`${r.status}`)
      const updated = (await r.json()) as DigitalHuman
      setAvatar(updated)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const onArchive = async () => {
    if (!avatar) return
    if (!window.confirm(`归档「${avatar.name}」？归档后投放飞轮停止累计`)) return
    const next = await archiveDigitalHuman(avatar.id)
    setAvatar(next)
  }

  if (loading) return <div className="p-6 text-sm text-gray-500">加载中…</div>
  if (!avatar) return <div className="p-6 text-sm text-rose-500">数字人不存在</div>

  const ctr = (avatar.ctr_avg ?? 0) * 100
  const cvr = (avatar.cvr_avg ?? 0) * 100

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <Link href="/content-studio/avatars" className="text-xs text-gray-500 hover:underline">
            ← 返回数字人脸库
          </Link>
          <h1 className="text-2xl font-semibold mt-1">{avatar.name}</h1>
          <div className="text-xs text-gray-500 mt-1 flex items-center gap-2">
            {avatar.status && (
              <span className="bg-gray-100 px-1.5 rounded">{avatar.status}</span>
            )}
            {avatar.gender && <span>{avatar.gender}</span>}
            {avatar.age_range && <span>{avatar.age_range}</span>}
            <span>用过 {avatar.usage_count ?? 0} 次</span>
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <button
            type="button"
            className="text-xs px-3 py-1.5 rounded border border-emerald-300 text-emerald-700 hover:bg-emerald-50"
            onClick={async () => {
              const next = await promoteDigitalHuman(avatar.id, 'testing')
              setAvatar(next)
            }}
            disabled={avatar.status === 'archived'}
          >
            → testing
          </button>
          <button
            type="button"
            className="text-xs px-3 py-1.5 rounded border border-emerald-400 bg-emerald-50 text-emerald-800 hover:bg-emerald-100"
            onClick={async () => {
              const next = await promoteDigitalHuman(avatar.id, 'approved')
              setAvatar(next)
            }}
            disabled={avatar.status === 'archived'}
          >
            → approved
          </button>
          <button
            type="button"
            className="text-xs px-3 py-1.5 rounded border border-gray-300 hover:bg-gray-50"
            onClick={onArchive}
            disabled={avatar.status === 'archived'}
          >
            归档
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm text-rose-600 border border-rose-200 bg-rose-50 rounded p-2">{error}</div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <section className="lg:col-span-2 space-y-4">
          <div className="border rounded-lg p-4 space-y-3">
            <h2 className="font-medium">多角度底图（{(avatar.face_urls ?? []).length} 张）</h2>
            <div className="flex flex-wrap gap-2">
              {(avatar.face_urls ?? []).map((url, i) => (
                <div key={`${url}-${i}`} className="w-32 h-32 rounded border overflow-hidden relative bg-gray-100">
                  {url ? (
                    <Image src={url} alt={avatar.name} fill sizes="128px" className="object-cover" unoptimized />
                  ) : null}
                </div>
              ))}
            </div>
            <textarea
              className="w-full text-xs font-mono border rounded px-3 py-2 min-h-32"
              placeholder="一行一个 URL"
              value={faceUrlsText}
              onChange={(e) => setFaceUrlsText(e.target.value)}
            />
            <p className="text-[11px] text-gray-500">第一张作为 seed_face_url（生成时主参考）。</p>
          </div>

          <div className="border rounded-lg p-4 space-y-3">
            <h2 className="font-medium">基础信息</h2>
            <input
              className="w-full border rounded px-3 py-2 text-sm"
              placeholder="名称"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <div className="grid grid-cols-2 gap-3">
              <input
                className="border rounded px-3 py-2 text-sm"
                placeholder="性别 male/female"
                value={gender}
                onChange={(e) => setGender(e.target.value)}
              />
              <input
                className="border rounded px-3 py-2 text-sm"
                placeholder="年龄段（25-30）"
                value={ageRange}
                onChange={(e) => setAgeRange(e.target.value)}
              />
            </div>
            <input
              className="w-full border rounded px-3 py-2 text-sm"
              placeholder="风格标签（逗号分隔）"
              value={styleTagsText}
              onChange={(e) => setStyleTagsText(e.target.value)}
            />
            <textarea
              className="w-full border rounded px-3 py-2 text-sm min-h-24"
              placeholder="identity_anchor：固定外观的提示词锚（关键，越具体越一致）"
              value={identityAnchor}
              onChange={(e) => setIdentityAnchor(e.target.value)}
            />
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              className="px-4 py-2 rounded bg-violet-600 text-white text-sm disabled:opacity-60"
              disabled={saving}
              onClick={onSave}
            >
              {saving ? '保存中…' : '保存'}
            </button>
            <button
              type="button"
              className="px-4 py-2 rounded border border-gray-300 text-sm"
              onClick={() => router.push('/content-studio/avatars')}
            >
              取消
            </button>
          </div>
        </section>

        <aside className="space-y-4">
          <div className="border rounded-lg p-4">
            <h2 className="font-medium mb-2">投放飞轮指标</h2>
            <Stat label="平均 CTR" value={`${ctr.toFixed(2)}%`} />
            <Stat label="平均 CVR" value={`${cvr.toFixed(2)}%`} />
            <Stat label="质量分" value={(avatar.quality_score ?? 0).toFixed(2)} />
            <Stat label="累计样本" value={String(avatar.usage_count ?? 0)} />
            {((avatar.extra as { consecutive_low?: number } | undefined)?.consecutive_low ?? 0) > 0 && (
              <div className="text-xs text-amber-600 mt-2">
                连续 {(avatar.extra as { consecutive_low?: number }).consecutive_low} 次低 CTR，接近自动归档阈值
              </div>
            )}
          </div>

          <div className="border rounded-lg p-4">
            <h2 className="font-medium mb-2">出现过的流水线（{pipelines.length}）</h2>
            {pipelines.length === 0 ? (
              <div className="text-xs text-gray-400">暂未在任何流水线中使用</div>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {pipelines.map((p) => (
                  <li key={p.id}>
                    <Link
                      href={`/content-studio?id=${p.id}`}
                      className="text-violet-700 hover:underline"
                    >
                      {p.title}
                    </Link>
                    <span className="ml-2 text-[10px] text-gray-500">{p.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}


function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-sm py-0.5">
      <span className="text-gray-600">{label}</span>
      <span className="font-medium text-gray-800">{value}</span>
    </div>
  )
}
