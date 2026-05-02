'use client'

import { useEffect, useState } from 'react'
import Image from 'next/image'
import Link from 'next/link'

import { useContentStudioStore, type DigitalHuman } from '@/stores/contentStudioStore'
import { ContentStudioHubNav } from '@/components/content-studio-hub-nav'

function isUrl(s: string): boolean {
  return /^https?:\/\//i.test(s.trim())
}

export default function AvatarLibraryPage() {
  const {
    digitalHumans,
    fetchDigitalHumans,
    createDigitalHuman,
    generateDigitalHuman,
    promoteDigitalHuman,
    archiveDigitalHuman,
    error,
  } = useContentStudioStore()

  // 一键生成（基于参考图）
  const [genName, setGenName] = useState('')
  const [genDesc, setGenDesc] = useState('')
  const [genRef, setGenRef] = useState('')
  const [genRefs, setGenRefs] = useState<string[]>([])
  const [genGender, setGenGender] = useState('')
  const [genAge, setGenAge] = useState('')
  const [genLoading, setGenLoading] = useState(false)
  const [genError, setGenError] = useState<string | null>(null)

  // 手动新建
  const [name, setName] = useState('')
  const [seedFaceUrl, setSeedFaceUrl] = useState('')

  useEffect(() => {
    void fetchDigitalHumans()
  }, [fetchDigitalHumans])

  const onAddRef = () => {
    const v = genRef.trim()
    if (!v || !isUrl(v)) {
      setGenError('参考图必须是完整 http(s) URL')
      return
    }
    setGenError(null)
    setGenRefs([...genRefs, v])
    setGenRef('')
  }

  const onGenerate = async () => {
    if (!genName.trim() || (!genDesc.trim() && genRefs.length === 0)) {
      setGenError('需要填写人设描述或上传至少 1 张参考图')
      return
    }
    setGenLoading(true)
    setGenError(null)
    try {
      await generateDigitalHuman({
        name: genName,
        appearance_desc: genDesc,
        reference_images: genRefs,
        gender: genGender || undefined,
        age_range: genAge || undefined,
      })
      setGenName('')
      setGenDesc('')
      setGenRefs([])
      setGenGender('')
      setGenAge('')
    } catch (e) {
      setGenError((e as Error).message)
    } finally {
      setGenLoading(false)
    }
  }

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <ContentStudioHubNav />
      <div>
        <h1 className="text-2xl font-semibold">数字人脸库</h1>
        <p className="text-sm text-gray-500">
          沉淀可复用的数字人头像，支持跨流水线复用、按 CTR 排序、自动晋级/归档。
        </p>
      </div>

      {/* 一键生成 */}
      <section className="border-2 border-violet-200 bg-violet-50/40 rounded-lg p-4 space-y-3">
        <h2 className="font-medium text-violet-800">⚡ 基于参考图一键生成多角度底图</h2>
        <div className="grid grid-cols-2 gap-3">
          <input
            className="border rounded px-3 py-2 text-sm bg-white"
            placeholder="数字人名称"
            value={genName}
            onChange={(e) => setGenName(e.target.value)}
          />
          <input
            className="border rounded px-3 py-2 text-sm bg-white"
            placeholder="性别（可选 male/female）"
            value={genGender}
            onChange={(e) => setGenGender(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <input
            className="border rounded px-3 py-2 text-sm bg-white"
            placeholder="年龄段（可选 25-30）"
            value={genAge}
            onChange={(e) => setGenAge(e.target.value)}
          />
          <div />
        </div>
        <textarea
          className="w-full border rounded px-3 py-2 text-sm min-h-20 bg-white"
          placeholder="人设外貌描述（瓜子脸、长发、笑容温柔...）"
          value={genDesc}
          onChange={(e) => setGenDesc(e.target.value)}
        />
        <div className="flex gap-2">
          <input
            className="flex-1 border rounded px-3 py-2 text-sm bg-white"
            placeholder="参考图 URL（可加多张）"
            value={genRef}
            onChange={(e) => setGenRef(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onAddRef()}
          />
          <button
            type="button"
            className="px-3 py-2 rounded bg-gray-900 text-white text-xs"
            onClick={onAddRef}
          >
            追加
          </button>
        </div>
        {genRefs.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {genRefs.map((url, i) => (
              <div key={`${url}-${i}`} className="relative w-16 h-16 rounded border overflow-hidden bg-white">
                <Image src={url} alt="" fill sizes="64px" className="object-cover" unoptimized />
                <button
                  type="button"
                  className="absolute -top-1 -right-1 w-4 h-4 bg-rose-500 text-white text-[10px] rounded-full"
                  onClick={() => setGenRefs(genRefs.filter((u) => u !== url))}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}
        {genError && <div className="text-sm text-rose-600">{genError}</div>}
        <button
          type="button"
          className="px-4 py-2 rounded bg-violet-600 text-white text-sm disabled:opacity-60"
          disabled={genLoading}
          onClick={onGenerate}
        >
          {genLoading ? '生成中（约 30s）…' : '生成 4 张多角度底图'}
        </button>
      </section>

      {/* 手动新建 */}
      <section className="border rounded-lg p-4 space-y-3">
        <h2 className="font-medium">手动新建（已有底图）</h2>
        <input
          className="w-full border rounded px-3 py-2 text-sm"
          placeholder="名称"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className="w-full border rounded px-3 py-2 text-sm"
          placeholder="种子脸 URL"
          value={seedFaceUrl}
          onChange={(e) => setSeedFaceUrl(e.target.value)}
        />
        <button
          type="button"
          className="px-4 py-2 rounded bg-gray-900 text-white text-sm"
          onClick={async () => {
            if (!name || !seedFaceUrl) return
            await createDigitalHuman({ name, seed_face_url: seedFaceUrl, face_urls: [seedFaceUrl] })
            setName('')
            setSeedFaceUrl('')
          }}
        >
          创建
        </button>
      </section>

      {error && <div className="text-sm text-rose-600">{error}</div>}

      <section className="space-y-3">
        <h2 className="font-medium text-gray-700">已有数字人（{digitalHumans.length}，按 CTR 排序）</h2>
        {digitalHumans.map((avatar) => (
          <AvatarCard
            key={avatar.id}
            avatar={avatar}
            onPromote={() => void promoteDigitalHuman(avatar.id)}
            onArchive={() => {
              if (window.confirm(`归档「${avatar.name}」？`)) void archiveDigitalHuman(avatar.id)
            }}
          />
        ))}
      </section>
    </div>
  )
}


function AvatarCard({
  avatar,
  onPromote,
  onArchive,
}: {
  avatar: DigitalHuman
  onPromote: () => void
  onArchive: () => void
}) {
  const ctr = (avatar.ctr_avg ?? 0) * 100
  const cvr = (avatar.cvr_avg ?? 0) * 100
  const isArchived = avatar.status === 'archived'
  return (
    <div className={`border rounded-lg p-4 flex items-start gap-4 bg-white ${isArchived ? 'opacity-60' : ''}`}>
      <div className="flex flex-wrap gap-1 shrink-0">
        {(avatar.face_urls?.length ? avatar.face_urls : [avatar.seed_face_url]).slice(0, 4).map((url, i) => (
          <div key={`${url}-${i}`} className="w-16 h-16 rounded border overflow-hidden relative bg-gray-100">
            {url ? (
              <Image src={url} alt={avatar.name} fill sizes="64px" className="object-cover" unoptimized />
            ) : null}
          </div>
        ))}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Link href={`/content-studio/avatars/${avatar.id}`} className="font-medium hover:underline">
            {avatar.name}
          </Link>
          {avatar.status && (
            <span className={`text-[10px] px-1.5 rounded ${
              avatar.status === 'approved' || avatar.status === 'promoted'
                ? 'bg-emerald-100 text-emerald-700'
                : avatar.status === 'archived'
                  ? 'bg-gray-200 text-gray-600'
                  : 'bg-amber-100 text-amber-700'
            }`}>
              {avatar.status}
            </span>
          )}
          {avatar.gender && <span className="text-[10px] text-gray-500">{avatar.gender}</span>}
          {avatar.age_range && <span className="text-[10px] text-gray-500">{avatar.age_range}</span>}
        </div>

        <div className="text-xs text-gray-500 mt-1 grid grid-cols-3 gap-2">
          <div>样本：{avatar.usage_count ?? 0}</div>
          <div>CTR：{ctr.toFixed(2)}%</div>
          <div>CVR：{cvr.toFixed(2)}%</div>
        </div>

        {avatar.identity_anchor && (
          <div className="text-xs text-gray-600 mt-2 line-clamp-2">{avatar.identity_anchor}</div>
        )}
      </div>

      <div className="flex flex-col gap-1.5 shrink-0">
        <button
          type="button"
          className="text-xs px-2.5 py-1 rounded border border-emerald-300 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
          onClick={onPromote}
          disabled={isArchived}
        >
          晋级
        </button>
        <button
          type="button"
          className="text-xs px-2.5 py-1 rounded border border-gray-300 hover:bg-gray-50 disabled:opacity-50"
          onClick={onArchive}
          disabled={isArchived}
        >
          归档
        </button>
      </div>
    </div>
  )
}
