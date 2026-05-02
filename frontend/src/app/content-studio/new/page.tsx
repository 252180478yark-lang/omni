'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import Image from 'next/image'

import { useContentStudioStore, type DigitalHuman, type Brief } from '@/stores/contentStudioStore'
import { ContentStudioHubNav } from '@/components/content-studio-hub-nav'

type RefItem = { url: string; type: 'character' | 'product'; weight?: number }

function isUrl(s: string): boolean {
  return /^https?:\/\//i.test(s.trim())
}

export default function NewPipelinePage() {
  const router = useRouter()
  const {
    briefs,
    digitalHumans,
    fetchBriefs,
    fetchDigitalHumans,
    createPipeline,
    setExtraReferenceImages,
  } = useContentStudioStore()

  const [title, setTitle] = useState('')
  const [briefId, setBriefId] = useState('')
  const [digitalHumanId, setDigitalHumanId] = useState('')

  // 临时上传/手填的参考图：URL 字符串，前端按类型组织
  const [characterUrls, setCharacterUrls] = useState<string[]>([])
  const [productUrls, setProductUrls] = useState<string[]>([])

  // input 暂存
  const [charInput, setCharInput] = useState('')
  const [prodInput, setProdInput] = useState('')

  // 文件上传：提交前暂存，创建 pipeline 后再上传到后端。
  const [pendingChar, setPendingChar] = useState<File[]>([])
  const [pendingProd, setPendingProd] = useState<File[]>([])

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showAllAvatars, setShowAllAvatars] = useState(false)

  useEffect(() => {
    void fetchBriefs()
    void fetchDigitalHumans()
  }, [fetchBriefs, fetchDigitalHumans])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const b = params.get('brief_id')
    const a = params.get('digital_human_id')
    if (b) setBriefId(b)
    if (a) setDigitalHumanId(a)
  }, [])

  const selectedBrief: Brief | undefined = useMemo(
    () => briefs.find((b) => b.id === briefId),
    [briefs, briefId],
  )
  const selectedAvatar: DigitalHuman | undefined = useMemo(
    () => digitalHumans.find((d) => d.id === digitalHumanId),
    [digitalHumans, digitalHumanId],
  )

  // 自动从 Avatar 带入 face_urls 作为人脸参考
  const avatarFaces = useMemo(() => selectedAvatar?.face_urls ?? [], [selectedAvatar])

  const allCharRefs = useMemo(
    () => Array.from(new Set([...avatarFaces, ...characterUrls])).filter(Boolean),
    [avatarFaces, characterUrls],
  )

  const charOk = allCharRefs.length + pendingChar.length > 0
  const productOk = productUrls.length + pendingProd.length > 0
  const briefOk = !!briefId
  const avatarOk = !!digitalHumanId
  const stepOk = title.trim().length > 0 && briefOk && avatarOk
  const missingItems = [
    !title.trim() && '流水线名称',
    !briefOk && 'Brief（用于投放复盘回灌）',
    !avatarOk && 'Avatar（用于同一人识别与回灌）',
  ].filter(Boolean)

  const onAddChar = () => {
    const v = charInput.trim()
    if (!v || !isUrl(v)) {
      setError('人脸参考图请输入完整 http(s) URL')
      return
    }
    setError(null)
    setCharacterUrls([...characterUrls, v])
    setCharInput('')
  }

  const onAddProd = () => {
    const v = prodInput.trim()
    if (!v || !isUrl(v)) {
      setError('产品参考图请输入完整 http(s) URL')
      return
    }
    setError(null)
    setProductUrls([...productUrls, v])
    setProdInput('')
  }

  const onSubmit = async () => {
    if (!stepOk) return
    setSubmitting(true)
    setError(null)
    try {
      const extraRefs: RefItem[] = [
        ...characterUrls.map((url) => ({ url, type: 'character' as const, weight: 0.8 })),
        ...productUrls.map((url) => ({ url, type: 'product' as const, weight: 1.0 })),
      ]
      const pipe = await createPipeline(
        title,
        '',
        {},
        {
          briefId: briefId || undefined,
          digitalHumanId: digitalHumanId || undefined,
        },
      )
      if (extraRefs.length > 0) {
        await setExtraReferenceImages(pipe.id, extraRefs)
      }
      if (productUrls.length > 0) {
        await fetch(`/api/omni/content-studio/pipeline/${pipe.id}/product-images`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image_urls: productUrls }),
        }).catch(() => null)
      }
      router.push(`/content-studio?id=${pipe.id}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const onPickCharFiles = (files: FileList | null) => {
    if (!files) return
    setPendingChar([...pendingChar, ...Array.from(files)])
  }
  const onPickProdFiles = (files: FileList | null) => {
    if (!files) return
    setPendingProd([...pendingProd, ...Array.from(files)])
  }

  const onSubmitWithFiles = async () => {
    if (!title.trim()) return
    if (!briefId || !digitalHumanId) {
      setError('请先选择 Brief 和数字人 Avatar，确保投放复盘能回灌指标')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const pipe = await createPipeline(
        title,
        '',
        {},
        {
          briefId: briefId || undefined,
          digitalHumanId: digitalHumanId || undefined,
        },
      )

      // 上传 character 文件
      for (const f of pendingChar) {
        const fd = new FormData()
        fd.append('file', f)
        await fetch(
          `/api/omni/content-studio/pipeline/${pipe.id}/extra-refs/upload?ref_type=character`,
          { method: 'POST', body: fd },
        )
      }
      // 上传 product 文件
      const uploadedProd: string[] = []
      for (const f of pendingProd) {
        const fd = new FormData()
        fd.append('file', f)
        const r = await fetch(
          `/api/omni/content-studio/pipeline/${pipe.id}/extra-refs/upload?ref_type=product`,
          { method: 'POST', body: fd },
        )
        if (r.ok) {
          const data = (await r.json()) as { url: string }
          uploadedProd.push(data.url)
        }
      }

      // URL 形式追加（不会覆盖刚 upload 的）
      const urlRefs: RefItem[] = [
        ...characterUrls.map((url) => ({ url, type: 'character' as const, weight: 0.8 })),
        ...productUrls.map((url) => ({ url, type: 'product' as const, weight: 1.0 })),
      ]
      if (urlRefs.length > 0) {
        // 读当前已存在的（含 upload 的），合并去重
        const r = await fetch(`/api/omni/content-studio/pipeline/${pipe.id}`)
        const cur = (await r.json()) as { extra_reference_images?: RefItem[] }
        const merged: RefItem[] = []
        const seen = new Set<string>()
        for (const x of [...(cur.extra_reference_images ?? []), ...urlRefs]) {
          if (x.url && !seen.has(x.url)) {
            seen.add(x.url)
            merged.push(x)
          }
        }
        await setExtraReferenceImages(pipe.id, merged)
      }

      const allProd = [...productUrls, ...uploadedProd]
      if (allProd.length > 0) {
        await fetch(`/api/omni/content-studio/pipeline/${pipe.id}/product-images`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image_urls: allProd }),
        }).catch(() => null)
      }

      router.push(`/content-studio?id=${pipe.id}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <ContentStudioHubNav />
      <div>
        <h1 className="text-2xl font-semibold">新建流水线</h1>
        <p className="text-sm text-gray-500">
          建 Brief → 建 Avatar → 新建 Pipeline → 生成 → 下载 → 投放 → 复盘
        </p>
      </div>

      <section className="rounded-lg border border-violet-200 bg-violet-50/50 p-3 text-xs text-violet-900">
        <div className="font-medium">闭环检查</div>
        <div className="mt-1 flex flex-wrap gap-2">
          {['建 Brief', '建 Avatar', '新建 Pipeline', '生成', '下载', '投放', '复盘'].map((label, idx) => (
            <span key={label} className={`rounded-full px-2 py-0.5 ${idx < 2 ? 'bg-white text-violet-700' : 'bg-violet-100 text-violet-600'}`}>
              {idx + 1}. {label}
            </span>
          ))}
        </div>
        {missingItems.length > 0 && (
          <div className="mt-2 text-amber-700">
            当前还缺：{missingItems.join('、')}。
            <Link href="/content-studio/briefs" className="ml-2 underline">去建 Brief</Link>
            <Link href="/content-studio/avatars" className="ml-2 underline">去建 Avatar</Link>
          </div>
        )}
        {missingItems.length === 0 && (!charOk || !productOk) && (
          <div className="mt-2 text-amber-700">
            当前未上传{!charOk ? '人脸参考图' : ''}{!charOk && !productOk ? '、' : ''}{!productOk ? '产品参考图' : ''}；
            可以继续生成，但人物/产品一致性会弱一些。上传后系统会严格参考这些图片。
          </div>
        )}
      </section>

      {/* Step 1：基本信息 */}
      <section className="border rounded-lg p-4 space-y-3">
        <h2 className="font-medium">① 基本信息</h2>
        <input
          className="w-full border rounded px-3 py-2 text-sm"
          placeholder="流水线名称（必填）"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />

        <div className="grid grid-cols-2 gap-3">
          <select
            className="border rounded px-3 py-2 text-sm"
            value={briefId}
            onChange={(e) => setBriefId(e.target.value)}
          >
            <option value="">请选择 Brief（必选，回灌用）</option>
            {briefs.map((b) => (
              <option key={b.id} value={b.id}>
                {b.title}
                {b.product_name ? ` · ${b.product_name}` : ''}
              </option>
            ))}
          </select>

          <div>
            <select
              className="border rounded px-3 py-2 text-sm w-full"
              value={digitalHumanId}
              onChange={(e) => setDigitalHumanId(e.target.value)}
            >
              <option value="">请选择数字人 Avatar（必选）</option>
              {digitalHumans
                .filter((d) => {
                  if (showAllAvatars) return true
                  const s = (d.status || '').toLowerCase()
                  return s === 'approved' || s === 'promoted' || s === 'active'
                })
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                    {d.status ? ` (${d.status})` : ''}
                  </option>
                ))}
            </select>
            <label className="flex items-center gap-1 mt-1 text-[11px] text-gray-500">
              <input
                type="checkbox"
                checked={showAllAvatars}
                onChange={(e) => setShowAllAvatars(e.target.checked)}
              />
              显示全部（含 draft / testing / archived）
            </label>
          </div>
        </div>

        {selectedBrief && (
          <div className="text-xs text-gray-600 bg-violet-50/50 rounded p-2">
            已选 Brief：<b>{selectedBrief.title}</b>
            <div className="mt-1 line-clamp-2">USP：{selectedBrief.usp}</div>
          </div>
        )}
      </section>

      {/* Step 2：双路参考图 */}
      <section className="border rounded-lg p-4 space-y-4">
        <h2 className="font-medium">② 参考图（可选，上传后会严格遵守）</h2>
        <p className="text-xs text-gray-500">
          有人物或产品一致性要求时建议上传；如果这条内容不需要人脸或产品固定，也可以不上传，直接进入后续生成。
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* 左：人脸参考 */}
          <div className={`border rounded-lg p-3 space-y-2 ${charOk ? 'border-emerald-300 bg-emerald-50/30' : 'border-gray-200 bg-gray-50/30'}`}>
            <div className="flex items-center justify-between">
              <h3 className="font-medium">👤 人脸参考{!charOk && <span className="text-gray-400 text-xs ml-2">可选</span>}</h3>
              {selectedAvatar && (
                <span className="text-[11px] text-emerald-700">已从 Avatar 「{selectedAvatar.name}」带入 {avatarFaces.length} 张</span>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              {allCharRefs.map((url, i) => (
                <div key={`${url}-${i}`} className="relative w-16 h-16 rounded border overflow-hidden bg-white">
                  <Image src={url} alt="" fill sizes="64px" className="object-cover" unoptimized />
                  {!avatarFaces.includes(url) && (
                    <button
                      type="button"
                      className="absolute -top-1 -right-1 w-4 h-4 bg-rose-500 text-white text-[10px] rounded-full"
                      onClick={() => setCharacterUrls(characterUrls.filter((u) => u !== url))}
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
            </div>

            <div className="flex gap-2">
              <input
                className="flex-1 border rounded px-2 py-1.5 text-xs"
                placeholder="粘贴人脸参考图 URL（http://...）"
                value={charInput}
                onChange={(e) => setCharInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && onAddChar()}
              />
              <button
                type="button"
                className="px-3 py-1.5 rounded bg-gray-900 text-white text-xs"
                onClick={onAddChar}
              >
                追加 URL
              </button>
            </div>

            <label className="flex items-center gap-2 text-[11px] text-violet-700 cursor-pointer">
              <input
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(e) => onPickCharFiles(e.target.files)}
              />
              <span className="px-2 py-1 border border-violet-300 rounded hover:bg-violet-50">
                + 上传本地文件
              </span>
              <span className="text-gray-500">
                {pendingChar.length > 0 ? `已选 ${pendingChar.length} 个文件，提交时上传` : '可选，PNG/JPG'}
              </span>
            </label>

            <div className="text-[11px] text-gray-500">
              建议：需要固定人物时，从「数字人脸库」选择已有 Avatar 自动带入；或临时补 1~3 张同一个人物的多角度图。
            </div>
          </div>

          {/* 右：产品参考 */}
          <div className={`border rounded-lg p-3 space-y-2 ${productOk ? 'border-emerald-300 bg-emerald-50/30' : 'border-gray-200 bg-gray-50/30'}`}>
            <div className="flex items-center justify-between">
              <h3 className="font-medium">📦 产品参考{!productOk && <span className="text-gray-400 text-xs ml-2">可选</span>}</h3>
            </div>

            <div className="flex flex-wrap gap-2">
              {productUrls.map((url, i) => (
                <div key={`${url}-${i}`} className="relative w-16 h-16 rounded border overflow-hidden bg-white">
                  <Image src={url} alt="" fill sizes="64px" className="object-cover" unoptimized />
                  <button
                    type="button"
                    className="absolute -top-1 -right-1 w-4 h-4 bg-rose-500 text-white text-[10px] rounded-full"
                    onClick={() => setProductUrls(productUrls.filter((u) => u !== url))}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>

            <div className="flex gap-2">
              <input
                className="flex-1 border rounded px-2 py-1.5 text-xs"
                placeholder="粘贴产品白底/精修图 URL（http://...）"
                value={prodInput}
                onChange={(e) => setProdInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && onAddProd()}
              />
              <button
                type="button"
                className="px-3 py-1.5 rounded bg-gray-900 text-white text-xs"
                onClick={onAddProd}
              >
                追加 URL
              </button>
            </div>

            <label className="flex items-center gap-2 text-[11px] text-violet-700 cursor-pointer">
              <input
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(e) => onPickProdFiles(e.target.files)}
              />
              <span className="px-2 py-1 border border-violet-300 rounded hover:bg-violet-50">
                + 上传本地文件
              </span>
              <span className="text-gray-500">
                {pendingProd.length > 0 ? `已选 ${pendingProd.length} 个文件，提交时上传` : '可选，PNG/JPG'}
              </span>
            </label>

            <div className="text-[11px] text-gray-500">
              建议：需要固定产品外观时，上传 1~3 张同一 SKU 的不同角度图，确保模型不变形。
            </div>
          </div>
        </div>
      </section>

      {/* Step 3：确认与运行 */}
      <section className="border rounded-lg p-4 space-y-3">
        <h2 className="font-medium">③ 确认并创建</h2>
        {error && <div className="text-sm text-rose-600">{error}</div>}
        {!stepOk && (
          <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
            请完成：{missingItems.join('；')}。参考图不是必填，但上传后会被后续生成严格使用。
          </div>
        )}
        {stepOk && (!charOk || !productOk) && (
          <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
            你没有上传完整参考图，仍可继续。后续会按文案和场景描述生成；如需同一人/同一产品稳定识别，请返回补充参考图。
          </div>
        )}
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="px-4 py-2 rounded bg-violet-600 text-white text-sm disabled:opacity-50"
            disabled={!stepOk || submitting}
            onClick={() => {
              if (pendingChar.length > 0 || pendingProd.length > 0) {
                void onSubmitWithFiles()
              } else {
                void onSubmit()
              }
            }}
          >
            {submitting ? '创建中（上传 + 入库）…' : '创建并进入流水线'}
          </button>
          <span className="text-xs text-gray-500">
            创建后自动跳转到 /content-studio，按步执行 copy → script → storyboard → video。
          </span>
        </div>
      </section>
    </div>
  )
}
