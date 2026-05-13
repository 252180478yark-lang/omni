'use client'

import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Loader2, Sparkles, ChevronDown, ChevronRight, Copy, Download, Users, Target, Film, Network, Image as ImageIcon } from 'lucide-react'
import LineageTree, { type PickableNode } from './LineageTree'

interface SkuRow {
  id: string
  name: string
  status: string
  platform_status: string | null
  growth_class: string | null
  in_focus_pool: boolean
  push_tier: string | null
  price_min: number | null
  price_max: number | null
}

interface TraceShape {
  model_provider: string
  model: string
  final_prompt: string
  params: Record<string, any>
  cost_estimate: string
}

interface MatrixResp {
  ok: boolean
  result?: {
    matrix_md: string
    sku_id: string
    matrix_run_id?: string | null
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

interface AudienceRecordSummary {
  id: string | null
  ordinal: number
  name: string
  kb_doc: string | null
  kb_section: string | null
  layer_tags: string[]
  match_reason_count: number
}

interface AudienceResp {
  ok: boolean
  result?: {
    audience_md: string
    sku_id: string
    matrix_run_id?: string | null
    audience_run_id?: string | null
    records?: AudienceRecordSummary[]
    recall_meta?: {
      mode: string
      queries: string[]
      chunk_count: number
    }
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

interface RecordDetail {
  id: string
  name: string
  kb_doc: string | null
  kb_section: string | null
  kb_chunk_text: string | null
  match_reasons: string[]
  layer_tags: string[]
  raw_md_segment: string
  status: string
  selected_for_pack: boolean
}

interface AudienceRunSummary {
  id: string
  matrix_run_id: string | null
  sku_id: string
  version: number
  status: string
  record_count: number
  model_provider: string | null
  model: string | null
  created_at: string
}

interface AudiencePackResp {
  ok: boolean
  result?: {
    pack_md: string
    audience_pack_id: string | null
    audience_record_id: string
    audience_run_id: string | null
    matrix_run_id: string | null
    sku_id: string
    audience_name: string | null
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

interface KeywordPackResp {
  ok: boolean
  result?: {
    keyword_text: string
    keyword_count: number
    target_count: number
    keyword_pack_id: string | null
    sku_id: string
    audience_record_id: string | null
    audience_pack_id: string | null
    warnings: string[]
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

type CreativeKind =
  | 'video_soft_ad'
  | 'video_planting'
  | 'video_harvest'
  | 'graphic_harvest'
  | 'product_main_image'
  | 'product_detail_page'

const CREATIVE_KIND_LIST: { kind: CreativeKind; label: string; group: string; hint: string }[] = [
  { kind: 'video_soft_ad', label: '视频 · 软广', group: '视频', hint: 'A2 触动层 / 软植入 / 内容娱乐化 / 30s 内' },
  { kind: 'video_planting', label: '视频 · 种草', group: '视频', hint: 'A3 共鸣层 / 痛点+卖点 / 30-45s' },
  { kind: 'video_harvest', label: '视频 · 收割', group: '视频', hint: 'A4 行动层 / 强 CTA + 限时 / 15-25s' },
  { kind: 'graphic_harvest', label: '图文 · 收割', group: '图文', hint: '抖店/小红书图文 / 标题 + 5 段 + 配图 brief' },
  { kind: 'product_main_image', label: '主图', group: '商品视觉', hint: '5-9 张主图设计 brief / 大字 + 卖点叠加' },
  { kind: 'product_detail_page', label: '详情页', group: '商品视觉', hint: '8-12 段叙事长图 brief / 卖点闭环 + 信任锚' },
]

interface CreativePackResp {
  ok: boolean
  result?: {
    script_md: string
    script_id: string | null
    kind: CreativeKind
    kind_label: string
    sku_id: string
    audience_record_id: string | null
    audience_pack_id: string | null
    matrix_run_id: string | null
    metrics?: Record<string, unknown> | null
    validation_warnings?: string[]
  }
  trace?: TraceShape
  error?: string
  hint?: string
}

// ── 故事板提示词导出 util（W4-B 14.4 phase D step 6 增强 2026-05-11） ─────────
// 把 step 5 写的 image_prompt 里的 character_sheet[role_id] 占位符
// 展开成 inline 5 官描述（外部模型如 Midjourney / 即梦 / 可灵 / 豆包等读懂的纯文本 prompt）。
// 不调任何 LLM —— 纯字符串拼接 + 查 character_sheets meta 替换。
function buildStandalonePrompt(
  imagePromptRaw: string,
  characterSheets: Array<{
    role_id: string
    age?: string
    gender?: string
    appearance_keywords?: string
    aura?: string
  }>,
): string {
  let prompt = imagePromptRaw
  const reCharRef = /character_sheet\s*\[\s*([a-z_][a-z0-9_]*)\s*\]/gi
  prompt = prompt.replace(reCharRef, (match, roleId: string) => {
    const cs = characterSheets.find(c => c.role_id === roleId)
    if (!cs) return match // 找不到保留原占位符
    const genderEn = cs.gender === '女' ? 'woman' : cs.gender === '男' ? 'man' : 'person'
    const age = (cs.age || '').trim()
    const apk = (cs.appearance_keywords || '').trim()
    const aura = (cs.aura || '').trim()
    // inline 描述：a 60-65 岁 woman with neat short graying hair... ; A seasoned family cook...
    const parts: string[] = []
    parts.push(`a ${age ? age + ' ' : ''}${genderEn}`)
    if (apk) parts.push(`with ${apk}`)
    if (aura) parts.push(aura)
    return parts.join(', ')
  })
  return prompt
}

export default function SkuPipelinePage() {
  const [activeTab, setActiveTab] = useState<string>('step2')
  const [skus, setSkus] = useState<SkuRow[]>([])
  const [skuId, setSkuId] = useState<string>('')
  const [error, setError] = useState<string | null>(null)

  // Step 2 state
  const [userInitialPoints, setUserInitialPoints] = useState('')
  const [userReviews, setUserReviews] = useState('')
  const [kbContext, setKbContext] = useState('')
  const [extraContext2, setExtraContext2] = useState('')
  const [running2, setRunning2] = useState(false)
  const [resp2, setResp2] = useState<MatrixResp | null>(null)
  const [showPrompt2, setShowPrompt2] = useState(true)

  // Step 3 state
  const [matrixMd3, setMatrixMd3] = useState('')
  const [extraContext3, setExtraContext3] = useState('')
  const [kbRecallOverride, setKbRecallOverride] = useState('')
  const [showOverride, setShowOverride] = useState(false)
  const [running3, setRunning3] = useState(false)
  const [resp3, setResp3] = useState<AudienceResp | null>(null)
  const [showPrompt3, setShowPrompt3] = useState(true)
  const [showQueries, setShowQueries] = useState(false)
  // Step 3 phase A：N 个人群卡片相关
  const [adoptedRecordIds, setAdoptedRecordIds] = useState<Set<string>>(new Set())
  const [adopting, setAdopting] = useState<string | null>(null)
  const [expandedRecord, setExpandedRecord] = useState<string | null>(null)
  const [recordDetails, setRecordDetails] = useState<Record<string, RecordDetail>>({})
  const [loadingDetail, setLoadingDetail] = useState<string | null>(null)
  // Step 4 / Step 5 / 未来 step：确认绑入血缘（status='draft' → 'adopted'）
  // 跑完即落 draft（已实现），老板手动点"确认绑入血缘"才走下游 + 进 v_asset_full_lineage
  const [adoptingPack, setAdoptingPack] = useState<string | null>(null)
  const [adoptedPackIds, setAdoptedPackIds] = useState<Set<string>>(new Set())
  const [adoptingScript, setAdoptingScript] = useState<string | null>(null)
  const [adoptedScriptIds, setAdoptedScriptIds] = useState<Set<string>>(new Set())
  // 血缘图 pick 模态（step 5 / phase D 输入区调起，从血缘图选上游）
  const [pickModalOpen, setPickModalOpen] = useState(false)

  // ── Step 6：分镜图生成（W4-B 切片 14.4 phase D） ─────────
  // SKU 下所有 adopted 脚本（拉来选 1 条出分镜图）
  const [scriptsForSku6, setScriptsForSku6] = useState<Array<{
    id: string
    kind: string
    version: number
    status: string
    created_at: string
    audience_record_id: string | null
    audience_pack_id: string | null
  }> | null>(null)
  const [loadingScripts6, setLoadingScripts6] = useState(false)
  const [script6Id, setScript6Id] = useState<string>('')
  const [script6Detail, setScript6Detail] = useState<{
    id: string
    kind: string
    sku_id: string
    version: number
    status: string
    scenes: Array<{
      scene_no: number
      name?: string
      time_range?: string
      visual?: string
      shot?: string
      dialog?: string
      image_prompt?: string
      characters_in_scene?: string[]
      product_appearance?: boolean
    }>
    character_sheets?: Array<{
      role_id: string
      name?: string
      age?: string
      gender?: string
      appearance_keywords?: string
      aura?: string
    }>
  } | null>(null)
  const [loadingScript6Detail, setLoadingScript6Detail] = useState(false)
  const [faceRefs6, setFaceRefs6] = useState('')
  const [productRefs6, setProductRefs6] = useState('')
  const [aspect6, setAspect6] = useState('9:16')
  const [extraSuffix6, setExtraSuffix6] = useState('')
  const [deidentifyFaces6, setDeidentifyFaces6] = useState(false)
  const [running6, setRunning6] = useState(false)
  const [resp6, setResp6] = useState<{
    ok: boolean
    result?: {
      script_id: string
      kind: string
      sku_id: string
      scenes_total: number
      success_count: number
      error_count: number
      results: Array<{
        scene_no: number
        asset_id?: string
        file_url?: string
        prompt?: string
        error?: string
        face_refs_used?: string[]
        product_refs_used?: string[]
        characters_in_scene?: string[]
        product_appearance?: boolean
      }>
    }
    trace?: TraceShape
    error?: string
    hint?: string
  } | null>(null)
  // 哪些 scene 选中重跑（默认全跑；prefix 用 -1 表示全跑）
  const [selectedScenes6, setSelectedScenes6] = useState<Set<number>>(new Set())
  // 已采纳 asset id 集合（step 6 / 6.5 共用：分镜图 + 角色定妆图都进 pipeline.assets）
  const [adoptedAssetIds, setAdoptedAssetIds] = useState<Set<string>>(new Set())
  const [adoptingAsset, setAdoptingAsset] = useState<string | null>(null)
  // 血缘图刷新触发器 — character_sheets / storyboard / adopt 跑完 +1，LineageTree key remount 重 fetch
  const [lineageKey, setLineageKey] = useState(0)
  const bumpLineage = () => setLineageKey(k => k + 1)
  // step 6.5 角色定妆白底像
  const [runningCharSheets, setRunningCharSheets] = useState(false)
  const [charSheetsResp, setCharSheetsResp] = useState<{
    ok: boolean
    result?: {
      script_id: string
      roles_total: number
      success_count: number
      error_count: number
      results: Array<{
        role_id: string
        name?: string
        asset_id?: string
        file_url?: string
        prompt?: string
        error?: string
      }>
    }
    error?: string
    hint?: string
  } | null>(null)

  // ── Step 7.1：i2v 视频段生成（分镜图→视频） ─────────────────────
  const [imageAssets7, setImageAssets7] = useState<Array<{
    id: string
    scene_no: number | null
    file_url: string | null
    status: string
  }> | null>(null)
  const [loadingImageAssets7, setLoadingImageAssets7] = useState(false)
  const [selectedScenes7, setSelectedScenes7] = useState<Set<number>>(new Set())
  const [duration7i, setDuration7i] = useState<number>(8)
  const [aspect7i, setAspect7i] = useState('9:16')
  const [extraSuffix7i, setExtraSuffix7i] = useState('')
  const [running7i, setRunning7i] = useState(false)

  type VideoSegResp = {
    ok: boolean
    result?: {
      script_id: string
      kind: string
      sku_id: string
      scenes_total: number
      success_count: number
      error_count: number
      results: Array<{
        scene_no: number
        asset_id?: string
        video_url?: string
        prompt?: string
        error?: string
        error_category?: string
        error_detail?: string
        hint?: string
        first_frame_used?: string
        last_frame_used?: string | null
        face_refs_used?: string[]
        product_refs_used?: string[]
        refs_blocked_reason?: string | null
        characters_in_scene?: string[]
        product_appearance?: boolean
        duration_s?: number
        scene_time_range?: string | null
        task_id?: string | null
        dry_run?: boolean
        t2v_mode?: boolean
      }>
    }
    trace?: TraceShape
    error?: string
    hint?: string
    scene_nums_missing_image?: number[]
  }

  const [resp7i, setResp7i] = useState<VideoSegResp | null>(null)

  // ── Step 7.2：t2v 视频段生成（文字→视频） ─────────────────────────
  const [selectedScenes7t, setSelectedScenes7t] = useState<Set<number>>(new Set())
  const [duration7t, setDuration7t] = useState<number>(8)
  const [aspect7t, setAspect7t] = useState('9:16')
  const [characterAnchor7t, setCharacterAnchor7t] = useState('')
  const [generatingAnchor7t, setGeneratingAnchor7t] = useState(false)
  const [extraSuffix7t, setExtraSuffix7t] = useState('')
  const [running7t, setRunning7t] = useState(false)
  const [resp7t, setResp7t] = useState<VideoSegResp | null>(null)

  // SKU 已收藏人群池（跨多次 audience_run 的 status=adopted 累积）
  const [poolRecords, setPoolRecords] = useState<AudienceRecordSummary[] | null>(null)
  const [poolLoading, setPoolLoading] = useState(false)
  const [showPool, setShowPool] = useState(false)
  // SKU 的 step 3 历史跑次（A.5：让老板下次启动能挑历史 audience_run 加载回 UI）
  const [historyRuns, setHistoryRuns] = useState<AudienceRunSummary[] | null>(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null)

  // Step 4 圈包 SOP（phase B）
  const [record4Id, setRecord4Id] = useState<string>('')
  const [record4Detail, setRecord4Detail] = useState<RecordDetail | null>(null)
  const [loadingRecord4, setLoadingRecord4] = useState(false)
  const [showRecord4Detail, setShowRecord4Detail] = useState(false)
  const [extraContext4, setExtraContext4] = useState('')
  const [running4, setRunning4] = useState(false)
  const [resp4, setResp4] = useState<AudiencePackResp | null>(null)
  const [showPrompt4, setShowPrompt4] = useState(true)
  // Step 4 关键词扩展（phase B+）
  const [seedKw, setSeedKw] = useState('')
  const [targetCountKw, setTargetCountKw] = useState(500)
  const [runningKw, setRunningKw] = useState(false)
  const [respKw, setRespKw] = useState<KeywordPackResp | null>(null)
  const [copiedKw, setCopiedKw] = useState(false)

  // Step 5 创意素材（phase C）
  const [kind5, setKind5] = useState<CreativeKind>('video_planting')
  const [srcMode5, setSrcMode5] = useState<'record' | 'pack' | 'sku'>('record')
  const [record5Id, setRecord5Id] = useState<string>('')
  const [pack5Id, setPack5Id] = useState<string>('')
  const [pack5Detail, setPack5Detail] = useState<{
    id: string
    sku_id: string
    audience_record_id: string
    audience_run_id: string
    matrix_run_id: string
    pack_md: string
    version: number
    status: string
    created_at: string
  } | null>(null)
  const [loadingPack5, setLoadingPack5] = useState(false)
  const [showPack5Md, setShowPack5Md] = useState(false)
  const [packListForSku, setPackListForSku] = useState<Array<{ id: string; sku_id: string; version: number; status: string; created_at: string }> | null>(null)
  const [packListLoading, setPackListLoading] = useState(false)
  const [extraContext5, setExtraContext5] = useState('')
  const [running5, setRunning5] = useState(false)
  const [resp5, setResp5] = useState<CreativePackResp | null>(null)
  const [showPrompt5, setShowPrompt5] = useState(true)

  useEffect(() => {
    fetch('/api/omni/scout/skus?status=active')
      .then(r => r.json())
      .then(data => {
        const arr: SkuRow[] = Array.isArray(data) ? data : (data.data || data.skus || [])
        setSkus(arr)
        if (arr.length > 0 && !skuId) setSkuId(arr[0].id)
      })
      .catch(e => setError(`SKU 列表加载失败: ${String(e)}`))
  }, [])

  // step 2 跑完 → 自动同步 matrix_md 到 step 3 输入（老板可手改）
  useEffect(() => {
    if (resp2?.result?.matrix_md) {
      setMatrixMd3(resp2.result.matrix_md)
    }
  }, [resp2?.result?.matrix_md])

  const selectedSku = skus.find(s => s.id === skuId)

  const runStep2 = async () => {
    setRunning2(true)
    setResp2(null)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/selling-points-matrix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sku_id: skuId,
          user_initial_points: userInitialPoints,
          user_reviews: userReviews,
          kb_context: kbContext || null,
          extra_context: extraContext2 || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp2(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning2(false)
    }
  }

  const runStep3 = async () => {
    setRunning3(true)
    setResp3(null)
    setError(null)
    setAdoptedRecordIds(new Set())
    setExpandedRecord(null)
    setRecordDetails({})
    try {
      const res = await fetch('/api/omni/sku-pipeline/audience-match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sku_id: skuId,
          matrix_md: matrixMd3,
          extra_context: extraContext3 || null,
          kb_recall_override: kbRecallOverride || null,
          // 自动带上 step 2 拿到的 matrix_run_id（如果有），让链路血缘连起来
          matrix_run_id: resp2?.result?.matrix_run_id || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp3(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning3(false)
    }
  }

  // 收藏某个 audience_record 到 SKU 人群池（status=adopted，**不**动 selected_for_pack）。
  // selected_for_pack 留给 phase B step 4 圈包"挑 1 个出发"那一刻设——勾选 ≠ 即刻挂下游。
  const adoptAudienceRecord = async (recordId: string) => {
    if (!recordId || adopting) return
    setAdopting(recordId)
    try {
      const res = await fetch('/api/omni/sku-pipeline/adopt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          table: 'audience_records',
          run_id: recordId,
          set_selected: false,
        }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setAdoptedRecordIds(prev => {
          const next = new Set(prev)
          next.add(recordId)
          return next
        })
        // 收藏成功 → 让 SKU 人群池下次打开/已展开时自动 refetch
        setPoolRecords(null)
      } else {
        setError(`收藏失败：${json.data?.error || json.error || '未知错误'}`)
      }
    } catch (e) {
      setError(`收藏异常：${String(e)}`)
    } finally {
      setAdopting(null)
    }
  }

  // 把某个 audience_pack 从 status='draft' 改 'adopted'（确认绑入血缘）。
  // 不动 audience_record selected_for_pack — pack adopt 只是"老板觉得这版圈包 OK"的标记。
  // 多版本并存：同 record 重跑得多版 pack，老板可逐个采纳，下游手挑。
  const adoptAudiencePack = async (packId: string) => {
    if (!packId || adoptingPack) return
    setAdoptingPack(packId)
    try {
      const res = await fetch('/api/omni/sku-pipeline/adopt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          table: 'audience_packs',
          run_id: packId,
        }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setAdoptedPackIds(prev => {
          const next = new Set(prev)
          next.add(packId)
          return next
        })
        bumpLineage()
      } else {
        setError(`圈包采纳失败：${json.data?.error || json.error || '未知错误'}`)
      }
    } catch (e) {
      setError(`圈包采纳异常：${String(e)}`)
    } finally {
      setAdoptingPack(null)
    }
  }

  // 把某条 creative script（pipeline.scripts）从 'draft' 改 'adopted'。
  // 同 sku+kind 多版可并存采纳；下游 phase D 生成时按 sku+kind 列出 adopted 让老板挑。
  const adoptCreativeScript = async (scriptId: string) => {
    if (!scriptId || adoptingScript) return
    setAdoptingScript(scriptId)
    try {
      const res = await fetch('/api/omni/sku-pipeline/adopt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          table: 'scripts',
          run_id: scriptId,
        }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setAdoptedScriptIds(prev => {
          const next = new Set(prev)
          next.add(scriptId)
          return next
        })
        bumpLineage()
      } else {
        setError(`脚本采纳失败：${json.data?.error || json.error || '未知错误'}`)
      }
    } catch (e) {
      setError(`脚本采纳异常：${String(e)}`)
    } finally {
      setAdoptingScript(null)
    }
  }

  // 拉 SKU 已收藏池（跨多次 audience_run）—— 老板要确认"留着以后用"是真留下了
  const loadPool = async () => {
    if (!skuId) return
    setPoolLoading(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/list-audience-records', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku_id: skuId, selected_only: false, limit: 100 }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        // 只看 status=adopted 的（人群池）
        const adopted = (json.data.records || []).filter((r: any) => r.status === 'adopted')
        setPoolRecords(adopted)
      } else {
        setPoolRecords([])
      }
    } catch (e) {
      console.error('loadPool failed', e)
      setPoolRecords([])
    } finally {
      setPoolLoading(false)
    }
  }

  // 脚本详情变化时自动全选所有 scene（不依赖 selectScript6 内部 timing）
  useEffect(() => {
    if (script6Detail?.scenes && script6Detail.scenes.length > 0) {
      const all = new Set<number>(
        script6Detail.scenes.map(s => s.scene_no).filter((n): n is number => typeof n === 'number')
      )
      setSelectedScenes6(all)
    } else {
      setSelectedScenes6(new Set())
    }
  }, [script6Detail])

  // SKU 变化时清空 pool / history / 已采纳 Set / step 6 脚本缓存 / step 5 pack/record 选中（让老板切 SKU 时不串）
  useEffect(() => {
    setPoolRecords(null)
    setShowPool(false)
    setHistoryRuns(null)
    setShowHistory(false)
    setAdoptedPackIds(new Set())
    setAdoptedScriptIds(new Set())
    setScriptsForSku6(null)
    setScript6Id('')
    setScript6Detail(null)
    setResp6(null)
    setSelectedScenes6(new Set())
    setCharSheetsResp(null)
    setRecord5Id('')
    setPack5Id('')
    setPack5Detail(null)
    setShowPack5Md(false)
  }, [skuId])

  // pack 模式：拉选中 pack 的 pack_md / 关联 ids（让老板预览选对没）
  const loadPack5Detail = async (packId: string) => {
    if (!packId) {
      setPack5Detail(null)
      return
    }
    setLoadingPack5(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/get-pack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pack_id: packId }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok && json.data.pack) {
        setPack5Detail(json.data.pack)
      } else {
        setPack5Detail(null)
      }
    } catch (e) {
      console.error('loadPack5Detail failed', e)
      setPack5Detail(null)
    } finally {
      setLoadingPack5(false)
    }
  }

  // ── Step 6 函数：拉脚本列表 / 选脚本拉 scenes / 跑分镜图 ──
  const loadScriptsForStep6 = async () => {
    if (!skuId) return
    setLoadingScripts6(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/list-scripts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku_id: skuId, limit: 50 }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setScriptsForSku6(json.data.scripts || [])
      } else {
        setScriptsForSku6([])
        setError(`加载脚本失败：${json.data?.error || json.error || '未知'}`)
      }
    } catch (e) {
      setError(`加载脚本异常：${String(e)}`)
      setScriptsForSku6([])
    } finally {
      setLoadingScripts6(false)
    }
  }

  const selectScript6 = async (scriptId: string) => {
    setScript6Id(scriptId)
    setScript6Detail(null)
    setSelectedScenes6(new Set())
    setCharSheetsResp(null)
    if (!scriptId) return
    setLoadingScript6Detail(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/get-script', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script_id: scriptId }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok && json.data.script) {
        setScript6Detail(json.data.script)
        // 默认全选
        const all = new Set<number>(
          (json.data.script.scenes || []).map((s: any) => s.scene_no as number)
        )
        setSelectedScenes6(all)
      }
    } catch (e) {
      console.error('selectScript6 failed', e)
    } finally {
      setLoadingScript6Detail(false)
    }
  }

  const runStep6Storyboard = async (sceneNumsOverride?: number[]) => {
    if (!script6Id || running6) return
    const scene_nums = sceneNumsOverride !== undefined
      ? sceneNumsOverride
      : (selectedScenes6.size > 0 && selectedScenes6.size < (script6Detail?.scenes?.length || 0)
          ? Array.from(selectedScenes6)
          : null)  // null = 全跑
    const face_refs = faceRefs6.split(/\n/).map(s => s.trim()).filter(Boolean)
    const product_refs = productRefs6.split(/\n/).map(s => s.trim()).filter(Boolean)
    setRunning6(true)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/storyboard-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          script_id: script6Id,
          scene_nums,
          face_refs: face_refs.length ? face_refs : null,
          product_refs: product_refs.length ? product_refs : null,
          aspect_ratio: aspect6,
          extra_prompt_suffix: extraSuffix6.trim() || null,
          deidentify_faces: deidentifyFaces6,
        }),
      })
      const json = await res.json()
      if (json.success) {
        setResp6(json.data)
        bumpLineage()  // 触发 LineageTree refetch（新出的分镜 asset 已落 db）
      } else {
        setError(`分镜图生成失败：${json.error || '未知'}`)
      }
    } catch (e) {
      setError(`分镜图生成异常：${String(e)}`)
    } finally {
      setRunning6(false)
    }
  }

  // step 6.5：跑 character_sheets 角色定妆白底像（同 script_id 全角色或某几个）
  const runCharacterSheets = async (roleIds?: string[]) => {
    if (!script6Id || runningCharSheets) return
    setRunningCharSheets(true)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/character-sheets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          script_id: script6Id,
          role_ids: roleIds || null,
          aspect_ratio: '1:1',
        }),
      })
      const json = await res.json()
      if (json.success) {
        setCharSheetsResp(json.data)
        bumpLineage()  // 触发 LineageTree refetch（character_sheet asset 已落 db，让血缘图能立刻看到）
      } else {
        setError(`角色定妆失败：${json.error || '未知'}`)
      }
    } catch (e) {
      setError(`角色定妆异常：${String(e)}`)
    } finally {
      setRunningCharSheets(false)
    }
  }

  // ✓ 采纳 asset（落 status='draft' → 'adopted'，下游/血缘图可挂）
  const adoptAsset = async (assetId: string) => {
    if (!assetId || adoptingAsset) return
    setAdoptingAsset(assetId)
    try {
      const res = await fetch('/api/omni/sku-pipeline/adopt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table: 'assets', run_id: assetId }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setAdoptedAssetIds(prev => {
          const next = new Set(prev)
          next.add(assetId)
          return next
        })
        bumpLineage()  // 血缘图同步刷新（asset status 变绿）
      } else {
        setError(`资产采纳失败：${json.data?.error || json.error || '未知'}`)
      }
    } catch (e) {
      setError(`资产采纳异常：${String(e)}`)
    } finally {
      setAdoptingAsset(null)
    }
  }

  // ⬇ 下载图（base64 data URL 或 http url 都支持，直接触发浏览器下载）
  const downloadAsset = (url: string, filename: string) => {
    if (!url) return
    try {
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } catch (e) {
      setError(`下载失败：${String(e)}`)
    }
  }

  const toggleScene6 = (sceneNo: number) => {
    setSelectedScenes6(prev => {
      const next = new Set(prev)
      if (next.has(sceneNo)) next.delete(sceneNo)
      else next.add(sceneNo)
      return next
    })
  }

  // ── Step 7 handlers ─────────
  // 拉同 script_id 的 image asset（哪几段已出图能跑视频）
  const loadImageAssets7 = async () => {
    if (!script6Id) return
    setLoadingImageAssets7(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/list-assets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script_id: script6Id, asset_type: 'image', limit: 200 }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        // 按 scene_no 去重：同一段多次重跑只保留 1 张（优先 adopted，fallback 第一张/最新）
        // 后端 list_assets 已按 scene_no + created_at DESC 排过序
        const raw = (json.data.assets || []) as Array<{
          id: string; scene_no: number | null; file_url: string | null; status: string
        }>
        const bySn = new Map<number, typeof raw[number]>()
        for (const a of raw) {
          if (typeof a.scene_no !== 'number') continue
          const existing = bySn.get(a.scene_no)
          if (!existing) {
            bySn.set(a.scene_no, a)
          } else if (a.status === 'adopted' && existing.status !== 'adopted') {
            bySn.set(a.scene_no, a)  // adopted 优先替换
          }
        }
        const deduped = Array.from(bySn.values()).sort((a, b) => (a.scene_no ?? 0) - (b.scene_no ?? 0))
        setImageAssets7(deduped)
      } else {
        setError(`拉分镜图列表失败：${json.data?.error || json.error || '未知'}`)
        setImageAssets7([])
      }
    } catch (e) {
      setError(`拉分镜图列表异常：${String(e)}`)
      setImageAssets7([])
    } finally {
      setLoadingImageAssets7(false)
    }
  }

  // ── Step 7.1 i2v 函数 ───────────────────────────────────────────────
  const runStep7iVideo = async (dryRun = false) => {
    if (!script6Id || running7i) return
    setRunning7i(true)
    setError(null)
    try {
      const scene_nums =
        selectedScenes7.size === 0 || selectedScenes7.size === (imageAssets7?.length || 0)
          ? undefined
          : Array.from(selectedScenes7)
      const res = await fetch('/api/omni/sku-pipeline/video-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          script_id: script6Id,
          scene_nums,
          aspect_ratio: aspect7i,
          duration_s: duration7i,
          extra_prompt_suffix: extraSuffix7i || null,
          dry_run: dryRun,
        }),
      })
      const json = await res.json()
      if (json.success) {
        setResp7i(json.data)
        if (!dryRun) bumpLineage()
      } else {
        setError(`${dryRun ? '提示词预览' : 'i2v 生成'}失败：${json.error || '未知'}`)
      }
    } catch (e) {
      setError(`i2v 生成异常：${String(e)}`)
    } finally {
      setRunning7i(false)
    }
  }

  const rerunOneScene7i = (sceneNo: number) => {
    setSelectedScenes7(new Set([sceneNo]))
    setTimeout(() => void runStep7iVideo(), 0)
  }

  // ── Step 7.2 t2v 函数 ───────────────────────────────────────────────
  const generateAnchor7t = async () => {
    if (!script6Id || generatingAnchor7t) return
    setGeneratingAnchor7t(true)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/video-anchor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script_id: script6Id }),
      })
      const json = await res.json()
      if (json.success && json.data?.result?.anchor) {
        setCharacterAnchor7t(json.data.result.anchor)
      } else {
        setError(`生成角色锚点失败：${json.error || json.data?.error || '未知'}`)
      }
    } catch (e) {
      setError(`生成角色锚点异常：${String(e)}`)
    } finally {
      setGeneratingAnchor7t(false)
    }
  }

  const runStep7tVideo = async (dryRun = false) => {
    if (!script6Id || running7t) return
    setRunning7t(true)
    setError(null)
    try {
      const totalScenes = script6Detail?.scenes?.length || 0
      const scene_nums =
        selectedScenes7t.size === 0 || selectedScenes7t.size === totalScenes
          ? undefined
          : Array.from(selectedScenes7t)
      const res = await fetch('/api/omni/sku-pipeline/video-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          script_id: script6Id,
          scene_nums,
          aspect_ratio: aspect7t,
          duration_s: duration7t,
          force_t2v: true,
          character_anchor: characterAnchor7t.trim() || null,
          extra_prompt_suffix: extraSuffix7t || null,
          dry_run: dryRun,
        }),
      })
      const json = await res.json()
      if (json.success) {
        setResp7t(json.data)
        if (!dryRun) bumpLineage()
      } else {
        setError(`${dryRun ? '提示词预览' : 't2v 生成'}失败：${json.error || '未知'}`)
      }
    } catch (e) {
      setError(`t2v 生成异常：${String(e)}`)
    } finally {
      setRunning7t(false)
    }
  }

  const rerunOneScene7t = (sceneNo: number) => {
    setSelectedScenes7t(new Set([sceneNo]))
    setTimeout(() => void runStep7tVideo(), 0)
  }

  // 老板切到 step 7.1 时自动拉 image asset 列表（如果还没拉过）
  useEffect(() => {
    if (script6Id && imageAssets7 === null && !loadingImageAssets7) {
      loadImageAssets7()
    }
  }, [script6Id])  // eslint-disable-line react-hooks/exhaustive-deps

  // 切换 script6Id 时清空 step 7.1 state
  useEffect(() => {
    setImageAssets7(null)
    setSelectedScenes7(new Set())
    setResp7i(null)
  }, [script6Id])

  // step 7.1：默认全选有图的 scene
  useEffect(() => {
    if (imageAssets7 && imageAssets7.length > 0) {
      const validNos = imageAssets7
        .map(a => a.scene_no)
        .filter((n): n is number => typeof n === 'number')
      setSelectedScenes7(new Set(validNos))
    }
  }, [imageAssets7])

  // 切换 script6Id 时清空 step 7.2 state
  useEffect(() => {
    setSelectedScenes7t(new Set())
    setResp7t(null)
    setCharacterAnchor7t('')
  }, [script6Id])

  // step 7.2：默认全选脚本所有 scene
  useEffect(() => {
    if (script6Detail?.scenes && script6Detail.scenes.length > 0) {
      const nos = script6Detail.scenes
        .map((s: { scene_no?: number }) => s.scene_no)
        .filter((n): n is number => typeof n === 'number')
      setSelectedScenes7t(new Set(nos))
    }
  }, [script6Detail])

  // 老板点了"看人群池"或者本次新收藏一条 → 自动 refresh pool（保证池数据是最新的）
  useEffect(() => {
    if (showPool && poolRecords === null && !poolLoading) {
      loadPool()
    }
  }, [showPool, poolRecords, poolLoading])

  // 老板点了"看历史" → lazy load 该 SKU 跑过的所有 audience_run
  const loadHistory = async () => {
    if (!skuId) return
    setHistoryLoading(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/list-audience-runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku_id: skuId, limit: 30 }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setHistoryRuns(json.data.runs || [])
      } else {
        setHistoryRuns([])
      }
    } catch (e) {
      console.error('loadHistory failed', e)
      setHistoryRuns([])
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => {
    if (showHistory && historyRuns === null && !historyLoading) {
      loadHistory()
    }
  }, [showHistory, historyRuns, historyLoading])

  // 加载某次历史 audience_run 全量回 UI（含整段 markdown / N 条 records / 已勾选状态）
  const loadAudienceRun = async (runId: string) => {
    setLoadingRunId(runId)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/get-audience-run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audience_run_id: runId }),
      })
      const json = await res.json()
      if (!json.success || !json.data?.ok) {
        setError(`加载失败：${json.data?.error || json.error || '未知错误'}`)
        return
      }
      const { run, records } = json.data as {
        run: any
        records: Array<{
          id: string
          ordinal: number
          name: string
          kb_doc: string | null
          kb_section: string | null
          layer_tags: string[]
          match_reasons: string[]
          status: string
          selected_for_pack: boolean
        }>
      }
      // 把 audience_run 灌回 resp3 state（让 UI 渲染跟刚跑完一致）
      const summaries: AudienceRecordSummary[] = records.map(r => ({
        id: r.id,
        ordinal: r.ordinal,
        name: r.name,
        kb_doc: r.kb_doc,
        kb_section: r.kb_section,
        layer_tags: r.layer_tags || [],
        match_reason_count: (r.match_reasons || []).length,
      }))
      setResp3({
        ok: true,
        result: {
          audience_md: run.audience_md,
          sku_id: run.sku_id,
          matrix_run_id: run.matrix_run_id,
          audience_run_id: run.id,
          recall_meta: run.recall_meta || { mode: '', queries: [], chunk_count: 0 },
          records: summaries,
        },
        trace: undefined,  // 历史加载不带 trace（重跑才有）
      } as any)
      // 同步勾选集合：把 status='adopted' 的所有 record 标为已收藏
      const adopted = new Set<string>()
      for (const r of records) {
        if (r.status === 'adopted' && r.id) adopted.add(r.id)
      }
      setAdoptedRecordIds(adopted)
      setExpandedRecord(null)
      setRecordDetails({})
      setShowHistory(false)  // 加载完关闭历史下拉，让老板看到刚加载的卡片列表
    } catch (e) {
      setError(`加载异常：${String(e)}`)
    } finally {
      setLoadingRunId(null)
    }
  }

  // === Step 4: 选 audience_record + 跑圈包 ===
  const selectRecord4 = async (recordId: string) => {
    setRecord4Id(recordId)
    setRecord4Detail(null)
    setShowRecord4Detail(false)
    setResp4(null)
    if (!recordId) return
    // 复用已缓存的 detail（如果有）
    if (recordDetails[recordId]) {
      setRecord4Detail(recordDetails[recordId])
      return
    }
    setLoadingRecord4(true)
    try {
      const res = await fetch('/api/omni/sku-pipeline/get-audience-record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ record_id: recordId }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok && json.data?.record) {
        const detail = json.data.record as RecordDetail
        setRecord4Detail(detail)
        setRecordDetails(prev => ({ ...prev, [recordId]: detail }))
      }
    } catch (e) {
      console.error('selectRecord4 failed', e)
    } finally {
      setLoadingRecord4(false)
    }
  }

  const runStep4 = async () => {
    if (!record4Id) return
    setRunning4(true)
    setResp4(null)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/audience-pack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          audience_record_id: record4Id,
          extra_context: extraContext4 || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp4(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning4(false)
    }
  }

  // === Step 5: 创意素材（6 类）===
  const runStep5 = async () => {
    if (srcMode5 === 'record' && !record5Id) {
      setError('record 模式必须先选 1 条人群')
      return
    }
    if (srcMode5 === 'sku' && !skuId) {
      setError('sku 模式必须先选 SKU')
      return
    }
    setRunning5(true)
    setResp5(null)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        kind: kind5,
        extra_context: extraContext5 || null,
      }
      if (srcMode5 === 'record') {
        body.audience_record_id = record5Id
      } else if (srcMode5 === 'sku') {
        body.sku_id = skuId
      } else if (srcMode5 === 'pack') {
        body.audience_pack_id = pack5Id
      }
      const res = await fetch('/api/omni/sku-pipeline/creative-pack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setResp5(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunning5(false)
    }
  }

  // SKU 切换时清空 step 4 状态
  useEffect(() => {
    setRecord4Id('')
    setRecord4Detail(null)
    setResp4(null)
    setExtraContext4('')
    setSeedKw('')
    setRespKw(null)
  }, [skuId])

  // 从 resp4.pack_md 第 4 部分抽推荐种子词（auto-fill 到种子词输入框）
  const extractSeedFromPackMd = (md: string): string => {
    if (!md) return ''
    // 找"第 4 部分"之后到"---"之前的段
    const m = md.match(/第\s*4\s*部分[^\n]*\n([\s\S]+?)(?:\n---|\n###|\Z)/)
    if (!m) return ''
    const block = m[1]
    // 抓 bullet (- xxx 或 * xxx) 或 顿号/逗号分隔的清单
    const items: string[] = []
    const bullet = /^[\-\*]\s*([^\n]+)/gm
    let bm: RegExpExecArray | null
    while ((bm = bullet.exec(block)) !== null) {
      const raw = bm[1].trim().replace(/^[「\["'`]|[」\]"'`，。、；;.]+$/g, '')
      // 去掉里面的"等"字尾 / 解释括号
      const cleaned = raw.replace(/[（(].*?[)）]/g, '').trim()
      if (cleaned && cleaned.length >= 2 && cleaned.length <= 20) {
        items.push(cleaned)
      }
    }
    // 如果 bullet 没抓到，尝试逗号/顿号分隔
    if (items.length === 0) {
      const parts = block.split(/[、，,；;]/).map(s => s.trim()).filter(s => s.length >= 2 && s.length <= 20)
      items.push(...parts.slice(0, 10))
    }
    return items.slice(0, 12).join('\n')
  }

  // resp4 跑完 → 自动从 pack_md 第 4 部分抽种子词预填到输入框
  useEffect(() => {
    if (resp4?.result?.pack_md && !seedKw) {
      const auto = extractSeedFromPackMd(resp4.result.pack_md)
      if (auto) setSeedKw(auto)
    }
  }, [resp4?.result?.pack_md])

  const runKeywordPack = async () => {
    if (!seedKw.trim()) return
    setRunningKw(true)
    setRespKw(null)
    setError(null)
    setCopiedKw(false)
    try {
      const res = await fetch('/api/omni/sku-pipeline/keyword-pack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          seed_keywords: seedKw,
          target_count: targetCountKw,
          // 自动挂上 step 4 的链路（如果有）
          audience_record_id: resp4?.result?.audience_record_id || record4Id || null,
          audience_pack_id: resp4?.result?.audience_pack_id || null,
          sku_id: skuId || null,
        }),
      })
      const json = await res.json()
      if (!json.success) {
        setError(json.error || '调用失败')
      } else {
        setRespKw(json.data)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setRunningKw(false)
    }
  }

  const copyKeywordText = async () => {
    if (!respKw?.result?.keyword_text) return
    await navigator.clipboard.writeText(respKw.result.keyword_text)
    setCopiedKw(true)
    setTimeout(() => setCopiedKw(false), 2000)
  }

  const downloadKeywordTxt = () => {
    if (!respKw?.result?.keyword_text) return
    const blob = new Blob([respKw.result.keyword_text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const skuShort = (skuId || 'unknown').replace(/^SKU-/, '')
    const recordShort = (record4Id || 'norecord').slice(0, 8)
    const count = respKw.result.keyword_count
    a.href = url
    a.download = `keywords_${skuShort}_${recordShort}_${count}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  // 展开某个 record，按需 lazy load 完整字段（kb_chunk_text + match_reasons + raw_md_segment）
  const toggleExpandRecord = async (recordId: string) => {
    if (expandedRecord === recordId) {
      setExpandedRecord(null)
      return
    }
    setExpandedRecord(recordId)
    if (recordDetails[recordId]) return  // 已缓存
    setLoadingDetail(recordId)
    try {
      const res = await fetch('/api/omni/sku-pipeline/get-audience-record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ record_id: recordId }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok && json.data?.record) {
        setRecordDetails(prev => ({ ...prev, [recordId]: json.data.record }))
      }
    } catch (e) {
      // 详情拉不到不阻塞主流程，仅 console
      console.error('load record detail failed', e)
    } finally {
      setLoadingDetail(null)
    }
  }

  const copyText = (text: string | undefined) => {
    if (text) navigator.clipboard.writeText(text)
  }
  const downloadMd = (text: string | undefined, filename: string) => {
    if (!text) return
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  // SKU 选择器（两个 step 共享）
  const SkuPicker = (
    <div>
      <label className="text-sm font-medium mb-1 block">SKU（共 {skus.length} 个 active）</label>
      <select
        className="w-full border rounded px-2 py-2 text-sm bg-background"
        value={skuId}
        onChange={e => setSkuId(e.target.value)}
      >
        {skus.map(s => (
          <option key={s.id} value={s.id}>
            {s.id} — {s.name.substring(0, 30)} {s.in_focus_pool ? '⭐' : ''}
            {s.platform_status === 'on_sale' ? '' : ` [${s.platform_status}]`}
          </option>
        ))}
      </select>
      {selectedSku && (
        <div className="text-xs text-muted-foreground mt-1 space-x-2">
          <Badge variant="outline">{selectedSku.platform_status || 'unknown'}</Badge>
          {selectedSku.growth_class && (
            <Badge variant="outline">{selectedSku.growth_class}</Badge>
          )}
          {selectedSku.price_min !== null && (
            <span>¥{selectedSku.price_min}{selectedSku.price_max && selectedSku.price_max !== selectedSku.price_min ? ` - ¥${selectedSku.price_max}` : ''}</span>
          )}
        </div>
      )}
    </div>
  )

  return (
    <div className="mx-auto p-6 max-w-[1800px]">
      <div className="mb-6">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Sparkles className="w-6 h-6" /> SKU Pipeline 测试
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          单步测试通道。每步可独立跑（不强制走完整链路）；step 2 跑完后 matrix_md 会自动喂到 step 3。
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} orientation="vertical" className="w-full gap-4 items-start">
        <TabsList variant="line" className="w-40 shrink-0 h-fit p-2 sticky top-4">
          <TabsTrigger value="step2" className="text-sm font-medium w-full justify-start py-2">
            <Sparkles className="w-4 h-4 mr-1.5" /> Step 2 · 卖点矩阵
          </TabsTrigger>
          <TabsTrigger value="step3" className="text-sm font-medium w-full justify-start py-2">
            <Users className="w-4 h-4 mr-1.5" /> Step 3 · 人群匹配
          </TabsTrigger>
          <TabsTrigger value="step4" className="text-sm font-medium w-full justify-start py-2">
            <Target className="w-4 h-4 mr-1.5" /> Step 4 · 圈包
          </TabsTrigger>
          <TabsTrigger value="step5" className="text-sm font-medium w-full justify-start py-2">
            <Film className="w-4 h-4 mr-1.5" /> Step 5 · 创意素材
          </TabsTrigger>
          <TabsTrigger value="step6" className="text-sm font-medium w-full justify-start py-2">
            <ImageIcon className="w-4 h-4 mr-1.5" /> Step 6 · 分镜图
          </TabsTrigger>
          <TabsTrigger value="step7i" className="text-sm font-medium w-full justify-start py-2">
            <Film className="w-4 h-4 mr-1.5" /> 7.1 · i2v 视频
          </TabsTrigger>
          <TabsTrigger value="step7t" className="text-sm font-medium w-full justify-start py-2">
            <Sparkles className="w-4 h-4 mr-1.5" /> 7.2 · t2v 视频
          </TabsTrigger>
          <TabsTrigger value="lineage" className="text-sm font-medium w-full justify-start py-2">
            <Network className="w-4 h-4 mr-1.5" /> 血缘图
          </TabsTrigger>
        </TabsList>

        {/* ============== STEP 2: 卖点矩阵 ============== */}
        <TabsContent value="step2" className="mt-0 flex-1 min-w-0">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">输入</CardTitle>
                <CardDescription>
                  调味品行业专家 prompt — 5 部分输出（产品档案 / 三层卖点地图 / 五心智维度 /
                  结构化标签汇总 / 信息补全建议）
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    ④ 自己观察到的显性卖点（user_initial_points）
                  </label>
                  <Textarea
                    placeholder="例：日式风味、有机、零添加、180 天发酵、玻璃瓶包装、33 年源头工厂..."
                    value={userInitialPoints}
                    onChange={e => setUserInitialPoints(e.target.value)}
                    rows={5}
                    className="text-sm"
                  />
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    ③ 用户评价（user_reviews）
                  </label>
                  <Textarea
                    placeholder="好评关键词 / 差评关键词 / 客服反馈 / 私域反馈，例：「鲜味浓不咸」「玻璃瓶有质感」「滴几滴提鲜」「价格偏贵」「物流泡沫薄」..."
                    value={userReviews}
                    onChange={e => setUserReviews(e.target.value)}
                    rows={4}
                    className="text-sm"
                  />
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    可选补充（kb_context — 竞品 / 品牌故事 / 工艺细节 / 历史血统）
                  </label>
                  <Textarea
                    placeholder="（可空）建议先 search_kb 拿同品类爆款拆解 / 品牌资产再贴这里"
                    value={kbContext}
                    onChange={e => setKbContext(e.target.value)}
                    rows={5}
                    className="text-sm"
                  />
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    额外要求（extra_context）
                  </label>
                  <Textarea
                    placeholder="（可空）例：「这次主推送礼场景」「重点挖儿童辅食角度」"
                    value={extraContext2}
                    onChange={e => setExtraContext2(e.target.value)}
                    rows={4}
                    className="text-sm"
                  />
                </div>

                <Button
                  onClick={runStep2}
                  disabled={running2 || !skuId}
                  className="w-full"
                >
                  {running2 ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（约 60-120s，pro 模型推理慢）</> : '跑卖点矩阵'}
                </Button>

                {error && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">输出</CardTitle>
                  {resp2?.trace && (
                    <CardDescription className="text-xs">
                      {resp2.trace.model_provider}/{resp2.trace.model} · {resp2.trace.cost_estimate}
                    </CardDescription>
                  )}
                </div>
                {resp2?.result?.matrix_md && (
                  <div className="space-x-1">
                    <Button size="sm" variant="outline" onClick={() => copyText(resp2.result?.matrix_md)}>
                      <Copy className="w-3 h-3 mr-1" /> 复制
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => downloadMd(resp2.result?.matrix_md, `${skuId}_selling-points-matrix.md`)}>
                      <Download className="w-3 h-3 mr-1" /> 下载 .md
                    </Button>
                  </div>
                )}
              </CardHeader>
              <CardContent>
                {!resp2 && !running2 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左边填资料后点"跑卖点矩阵"，结果会显示在这里。
                  </div>
                )}
                {running2 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                    LLM 正在生成 5 部分报告...
                  </div>
                )}
                {resp2?.result?.matrix_md && (
                  <>
                    {resp2.result.matrix_run_id && (
                      <div className="mb-3 flex items-center gap-2 text-xs">
                        <Badge variant="outline" className="text-xs">已落库</Badge>
                        <span className="text-muted-foreground">
                          matrix_run_id: <code className="text-[10px]">{resp2.result.matrix_run_id.slice(0, 8)}…</code>
                          <span className="ml-2">step 3 会自动挂这个 id</span>
                        </span>
                      </div>
                    )}
                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {resp2.result.matrix_md}
                      </ReactMarkdown>
                    </div>

                    {resp2.trace?.final_prompt && (
                      <div className="mt-6 border-t pt-4">
                        <button
                          className="text-sm font-medium flex items-center gap-1"
                          onClick={() => setShowPrompt2(s => !s)}
                        >
                          {showPrompt2 ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          Final Prompt
                        </button>
                        {showPrompt2 && (
                          <pre className="mt-2 p-3 bg-muted text-xs rounded whitespace-pre-wrap">
                            {resp2.trace.final_prompt}
                          </pre>
                        )}
                      </div>
                    )}
                  </>
                )}
                {resp2 && !resp2.ok && (
                  <div className="text-sm text-red-500">
                    <div>Error: {resp2.error}</div>
                    {resp2.hint && <div className="text-xs text-muted-foreground mt-1">{resp2.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ============== STEP 3: 人群匹配 ============== */}
        <TabsContent value="step3" className="mt-0 flex-1 min-w-0">
          {/* SKU 状态卡（人群池 + 历史跑次）*/}
          {skuId && (
            <Card className="mb-4">
              <CardContent className="pt-4 space-y-3">
                {/* 已收藏人群池 */}
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2 text-sm">
                    <span>📌</span>
                    <span className="font-medium">{skuId}</span>
                    <span className="text-muted-foreground">已收藏的人群池</span>
                    {poolRecords !== null && (
                      <Badge variant="secondary">{poolRecords.length} 条</Badge>
                    )}
                    {poolRecords === null && !poolLoading && (
                      <span className="text-xs text-muted-foreground">（未加载）</span>
                    )}
                    {poolLoading && (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    )}
                  </div>
                  <div className="space-x-1">
                    <Button
                      size="sm"
                      variant={showPool ? 'default' : 'outline'}
                      onClick={() => setShowPool(s => !s)}
                    >
                      {showPool ? <ChevronDown className="w-3 h-3 mr-1" /> : <ChevronRight className="w-3 h-3 mr-1" />}
                      {showPool ? '收起' : '查看池子'}
                    </Button>
                    {showPool && (
                      <Button size="sm" variant="ghost" onClick={loadPool} disabled={poolLoading}>
                        刷新
                      </Button>
                    )}
                  </div>
                </div>
                {showPool && poolRecords !== null && poolRecords.length === 0 && (
                  <div className="text-xs text-muted-foreground py-3 text-center border border-dashed rounded">
                    池子是空的。在下方跑过 step 3 后，挑你认可的人群点 ⭐ 加入人群池。
                  </div>
                )}
                {showPool && poolRecords !== null && poolRecords.length > 0 && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {poolRecords.map(r => (
                      <div key={r.id || r.ordinal} className="border rounded p-2 text-xs bg-emerald-50/30 dark:bg-emerald-950/20">
                        <div className="flex items-center gap-1 flex-wrap">
                          <span className="font-medium">{r.name}</span>
                          {(r.layer_tags || []).slice(0, 3).map((t, i) => (
                            <Badge key={i} variant="outline" className="text-[9px]">{t}</Badge>
                          ))}
                        </div>
                        {r.kb_doc && (
                          <div className="text-muted-foreground mt-1 truncate">
                            {r.kb_doc}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                <div className="text-[11px] text-muted-foreground">
                  人群池 = SKU 跨多次 step 3 跑过的所有「老板已勾选」人群。后续跑 step 4 圈包时，从这池子里选 1 个出发。
                </div>

                {/* 历史 step 3 跑次（A.5：恢复上次跑过的 audience_run）*/}
                <div className="border-t pt-3">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2 text-sm">
                      <span>📜</span>
                      <span className="text-muted-foreground">历史 step 3 跑次</span>
                      {historyRuns !== null && (
                        <Badge variant="secondary">{historyRuns.length} 次</Badge>
                      )}
                      {historyRuns === null && !historyLoading && (
                        <span className="text-xs text-muted-foreground">（未加载）</span>
                      )}
                      {historyLoading && <Loader2 className="w-3 h-3 animate-spin" />}
                    </div>
                    <div className="space-x-1">
                      <Button
                        size="sm"
                        variant={showHistory ? 'default' : 'outline'}
                        onClick={() => setShowHistory(s => !s)}
                      >
                        {showHistory ? <ChevronDown className="w-3 h-3 mr-1" /> : <ChevronRight className="w-3 h-3 mr-1" />}
                        {showHistory ? '收起' : '查看历史'}
                      </Button>
                      {showHistory && (
                        <Button size="sm" variant="ghost" onClick={loadHistory} disabled={historyLoading}>
                          刷新
                        </Button>
                      )}
                    </div>
                  </div>
                  {showHistory && historyRuns !== null && historyRuns.length === 0 && (
                    <div className="mt-2 text-xs text-muted-foreground py-3 text-center border border-dashed rounded">
                      该 SKU 还没跑过 step 3。下方跑一次后会出现在这里。
                    </div>
                  )}
                  {showHistory && historyRuns !== null && historyRuns.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {historyRuns.map(run => (
                        <div
                          key={run.id}
                          className="flex items-center justify-between gap-2 p-2 border rounded text-xs hover:bg-muted/50"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <Badge variant="outline" className="text-[10px]">v{run.version}</Badge>
                            <Badge
                              variant={run.status === 'adopted' ? 'default' : 'outline'}
                              className="text-[10px]"
                            >
                              {run.status}
                            </Badge>
                            <span className="text-muted-foreground">
                              {run.record_count} 条人群
                            </span>
                            <span className="text-muted-foreground truncate">
                              {new Date(run.created_at).toLocaleString('zh-CN', { hour12: false })}
                            </span>
                            <code className="text-[9px] text-muted-foreground">{run.id.slice(0, 8)}…</code>
                          </div>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={loadingRunId === run.id}
                            onClick={() => loadAudienceRun(run.id)}
                            className="shrink-0"
                          >
                            {loadingRunId === run.id
                              ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 加载中</>
                              : '加载这次'}
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="text-[11px] text-muted-foreground mt-2">
                    每次跑 step 3 = 一行历史。点"加载这次" → N 条候选卡片 + 整段 markdown 全部恢复到下方输出区，已勾选状态会一起带回来。
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">输入</CardTitle>
                <CardDescription>
                  反向匹配 = 拿卖点+场景+心智去 KB 全部 chunks 里实打实挑对口人群。
                  2 部分输出（KB 匹配人群 ≥15 / 跨 ≥10 doc / 标签 ≥30）。KB 共 46 doc，全 KB 多 query 扩散召回。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    matrix_md（step 2 输出 — 必填）
                    {resp2?.result?.matrix_md && (
                      <Badge variant="outline" className="ml-2 text-xs">已自动同步 step 2 结果</Badge>
                    )}
                  </label>
                  <Textarea
                    placeholder="粘贴 step 2 的卖点矩阵 markdown（含三层卖点 + 5 心智 + 标签），或先去 step 2 跑一次自动同步"
                    value={matrixMd3}
                    onChange={e => setMatrixMd3(e.target.value)}
                    rows={10}
                    className="text-sm font-mono"
                  />
                  <div className="text-xs text-muted-foreground mt-1">
                    {matrixMd3.length} 字
                  </div>
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    额外要求（extra_context）
                  </label>
                  <Textarea
                    placeholder="（可空）例：「重点挖跨圈层」「假设里多列银发人群」「对标 X 品牌的人群路径」"
                    value={extraContext3}
                    onChange={e => setExtraContext3(e.target.value)}
                    rows={4}
                    className="text-sm"
                  />
                </div>

                <div>
                  <button
                    className="text-xs text-muted-foreground flex items-center gap-1"
                    onClick={() => setShowOverride(s => !s)}
                  >
                    {showOverride ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    高级：手动覆盖 KB 召回（极少用）
                  </button>
                  {showOverride && (
                    <Textarea
                      placeholder="（可空）老板想跳过自动多 query 召回，直接喂自定义 KB chunks 时贴这里。给了这个，tool 不再调 search_kb"
                      value={kbRecallOverride}
                      onChange={e => setKbRecallOverride(e.target.value)}
                      rows={4}
                      className="text-sm mt-2"
                    />
                  )}
                </div>

                <Button
                  onClick={runStep3}
                  disabled={running3 || !skuId || !matrixMd3.trim()}
                  className="w-full"
                >
                  {running3 ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（多 query 召回 + pro 推理 ~120s）</> : '跑人群匹配'}
                </Button>

                {error && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">输出</CardTitle>
                  {resp3?.trace && (
                    <CardDescription className="text-xs">
                      {resp3.trace.model_provider}/{resp3.trace.model} · {resp3.trace.cost_estimate}
                    </CardDescription>
                  )}
                </div>
                {resp3?.result?.audience_md && (
                  <div className="space-x-1">
                    <Button size="sm" variant="outline" onClick={() => copyText(resp3.result?.audience_md)}>
                      <Copy className="w-3 h-3 mr-1" /> 复制
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => downloadMd(resp3.result?.audience_md, `${skuId}_audience-match.md`)}>
                      <Download className="w-3 h-3 mr-1" /> 下载 .md
                    </Button>
                  </div>
                )}
              </CardHeader>
              <CardContent>
                {!resp3 && !running3 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左边贴 matrix_md 后点"跑人群匹配"，结果会显示在这里。
                  </div>
                )}
                {running3 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                    全 KB 多 query 召回（跨 46 doc）→ pro 模型反向匹配 → 资料诊断 + ≥15 个匹配人群 + 标签汇总...
                  </div>
                )}
                {resp3?.result?.audience_md && (
                  <>
                    {resp3.result.recall_meta && (
                      <div className="mb-4 p-3 bg-muted/50 rounded text-xs space-y-1">
                        <div className="flex items-center justify-between">
                          <div>
                            <span className="font-medium">召回模式：</span>
                            <Badge variant="outline" className="ml-1">
                              {resp3.result.recall_meta.mode === 'multi_query' ? '多 query 自动召回' : '手动覆盖'}
                            </Badge>
                            <span className="ml-3">
                              <span className="font-medium">queries:</span> {resp3.result.recall_meta.queries.length}
                            </span>
                            <span className="ml-3">
                              <span className="font-medium">chunks:</span> {resp3.result.recall_meta.chunk_count}
                            </span>
                          </div>
                          {resp3.result.recall_meta.queries.length > 0 && (
                            <button
                              className="flex items-center gap-1"
                              onClick={() => setShowQueries(s => !s)}
                            >
                              {showQueries ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                              展开 query 清单
                            </button>
                          )}
                        </div>
                        {showQueries && resp3.result.recall_meta.queries.length > 0 && (
                          <ul className="mt-2 list-disc list-inside text-muted-foreground">
                            {resp3.result.recall_meta.queries.map((q, i) => (
                              <li key={i}>{q}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}

                    {/* 落库摘要 + N 个人群卡片（phase A 新） */}
                    {resp3.result.audience_run_id && (
                      <div className="mb-4 p-3 border rounded bg-blue-50/40 dark:bg-blue-950/20 text-xs">
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge variant="outline">已落库</Badge>
                          <span>
                            audience_run_id: <code className="text-[10px]">{resp3.result.audience_run_id.slice(0, 8)}…</code>
                          </span>
                          <span className="ml-2">
                            <strong>{resp3.result.records?.length ?? 0}</strong> 条候选人群
                          </span>
                          {adoptedRecordIds.size > 0 && (
                            <Badge variant="secondary" className="text-[10px]">
                              本次已收藏 {adoptedRecordIds.size}
                            </Badge>
                          )}
                          {resp3.result.matrix_run_id && (
                            <span className="ml-2 text-muted-foreground">
                              ← matrix_run_id: <code className="text-[10px]">{resp3.result.matrix_run_id.slice(0, 8)}…</code>
                            </span>
                          )}
                        </div>
                        <div className="text-muted-foreground mt-1">
                          ⭐ 勾选 = 把这条加进 SKU 的人群池（持久化收藏）。**不会**立刻跑下游 step 4 圈包；以后跑圈包时从池子里选 1 个出发即可。
                        </div>
                      </div>
                    )}

                    {(resp3.result.records?.length ?? 0) > 0 && (
                      <div className="space-y-3 mb-4">
                        {resp3.result.records!.map(r => {
                          const adopted = r.id ? adoptedRecordIds.has(r.id) : false
                          const expanded = expandedRecord === r.id
                          const detail = r.id ? recordDetails[r.id] : undefined
                          return (
                            <div
                              key={r.id || r.ordinal}
                              className={`border rounded-lg p-4 transition ${adopted ? 'bg-emerald-50/40 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800' : 'bg-card hover:bg-muted/30'}`}
                            >
                              <div className="flex items-start justify-between gap-2 mb-2">
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-xs text-muted-foreground">#{r.ordinal}</span>
                                    <h4 className="font-medium text-sm">{r.name}</h4>
                                    {(r.layer_tags || []).map((t, i) => (
                                      <Badge key={i} variant="secondary" className="text-[10px]">{t}</Badge>
                                    ))}
                                  </div>
                                  {r.kb_doc && (
                                    <div className="text-xs text-muted-foreground mt-1 truncate">
                                      KB 来源：{r.kb_doc}{r.kb_section ? ` · ${r.kb_section}` : ''}
                                    </div>
                                  )}
                                  <div className="text-xs text-muted-foreground mt-1">
                                    匹配理由 {r.match_reason_count} 条
                                  </div>
                                </div>
                                <Button
                                  size="sm"
                                  variant={adopted ? 'default' : 'outline'}
                                  disabled={!r.id || adopting === r.id || adopted}
                                  onClick={() => r.id && adoptAudienceRecord(r.id)}
                                  className="shrink-0"
                                  title={adopted ? '已加入 SKU 人群池，以后跑 step 4 圈包从池里选' : '把这条人群收藏到 SKU 人群池'}
                                >
                                  {adopting === r.id
                                    ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 收藏中</>
                                    : adopted
                                      ? <>✓ 已收藏</>
                                      : <>⭐ 加入人群池</>}
                                </Button>
                              </div>
                              {r.id && (
                                <button
                                  className="text-xs text-muted-foreground flex items-center gap-1"
                                  onClick={() => toggleExpandRecord(r.id!)}
                                >
                                  {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                                  {loadingDetail === r.id ? '加载中...' : '展开 KB 原文 + 匹配理由'}
                                </button>
                              )}
                              {expanded && detail && (
                                <div className="mt-3 prose prose-sm max-w-none dark:prose-invert border-t pt-3">
                                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                    {detail.raw_md_segment}
                                  </ReactMarkdown>
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}

                    {/* 完整原始报告（折叠 — 老板想看 LLM 原始整段时翻这里） */}
                    <details className="mt-4 border-t pt-4" open>
                      <summary className="text-sm font-medium cursor-pointer select-none">
                        完整原始报告（含第 2 部分标签汇总；含 LLM 原始 markdown）
                      </summary>
                      <div className="mt-3 prose prose-sm max-w-none dark:prose-invert">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {resp3.result.audience_md}
                        </ReactMarkdown>
                      </div>
                    </details>

                    {resp3.trace?.final_prompt && (
                      <div className="mt-6 border-t pt-4">
                        <button
                          className="text-sm font-medium flex items-center gap-1"
                          onClick={() => setShowPrompt3(s => !s)}
                        >
                          {showPrompt3 ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          Final Prompt（含 KB 召回原文）
                        </button>
                        {showPrompt3 && (
                          <pre className="mt-2 p-3 bg-muted text-xs rounded whitespace-pre-wrap">
                            {resp3.trace.final_prompt}
                          </pre>
                        )}
                      </div>
                    )}
                  </>
                )}
                {resp3 && !resp3.ok && (
                  <div className="text-sm text-red-500">
                    <div>Error: {resp3.error}</div>
                    {resp3.hint && <div className="text-xs text-muted-foreground mt-1">{resp3.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ============== STEP 4: 圈包 SOP ============== */}
        <TabsContent value="step4" className="mt-0 flex-1 min-w-0">
          {/* SKU 状态卡（已收藏池 — 复用 step 3 的池子）*/}
          {skuId && (
            <Card className="mb-4">
              <CardContent className="pt-4">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="flex items-center gap-2 text-sm">
                    <span>📌</span>
                    <span className="font-medium">{skuId}</span>
                    <span className="text-muted-foreground">已收藏的人群池（step 4 候选）</span>
                    {poolRecords !== null && (
                      <Badge variant="secondary">{poolRecords.length} 条可选</Badge>
                    )}
                    {poolRecords === null && !poolLoading && (
                      <span className="text-xs text-muted-foreground">（点右侧加载）</span>
                    )}
                    {poolLoading && <Loader2 className="w-3 h-3 animate-spin" />}
                  </div>
                  <Button size="sm" variant="outline" onClick={loadPool} disabled={poolLoading}>
                    {poolRecords !== null ? '刷新' : '加载人群池'}
                  </Button>
                </div>
                {poolRecords !== null && poolRecords.length === 0 && (
                  <div className="mt-3 text-xs text-muted-foreground py-3 text-center border border-dashed rounded">
                    池子是空的。先去 step 3 跑一次人群匹配，挑认可的点 ⭐ 加入人群池，再回 step 4。
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">输入</CardTitle>
                <CardDescription>
                  从已收藏人群池选 1 个 → 翻译成巨量云图 8 大维度可勾选标签 + P 优先级 + 引用理由 + 预算两阶段 + A/B 矩阵。flash 模型，约 30-60s。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    选 1 个 audience_record（来自已收藏池）
                  </label>
                  {!poolRecords && (
                    <div className="text-xs text-muted-foreground p-3 border border-dashed rounded">
                      先点上方"加载人群池"拉候选。
                    </div>
                  )}
                  {poolRecords && poolRecords.length > 0 && (
                    <select
                      className="w-full border rounded px-2 py-2 text-sm bg-background"
                      value={record4Id}
                      onChange={e => selectRecord4(e.target.value)}
                    >
                      <option value="">— 请选择 —</option>
                      {poolRecords.map(r => (
                        <option key={r.id || r.ordinal} value={r.id || ''}>
                          #{r.ordinal} {r.name} · {(r.layer_tags || []).slice(0, 3).join('/')}
                        </option>
                      ))}
                    </select>
                  )}
                  {loadingRecord4 && (
                    <div className="text-xs text-muted-foreground mt-1">
                      <Loader2 className="w-3 h-3 inline animate-spin mr-1" />加载选中人群详情...
                    </div>
                  )}
                </div>

                {record4Detail && (
                  <div className="border rounded p-3 bg-muted/30 text-xs space-y-2">
                    <div>
                      <span className="font-medium">人群：</span>{record4Detail.name}
                    </div>
                    {record4Detail.kb_doc && (
                      <div>
                        <span className="font-medium">KB 来源：</span>
                        <span className="text-muted-foreground">{record4Detail.kb_doc}</span>
                      </div>
                    )}
                    <div className="flex gap-1 flex-wrap">
                      {(record4Detail.layer_tags || []).map((t, i) => (
                        <Badge key={i} variant="outline" className="text-[10px]">{t}</Badge>
                      ))}
                    </div>
                    <div>
                      <span className="font-medium">5 条匹配理由：</span>
                      <ol className="mt-1 list-decimal list-inside text-muted-foreground space-y-1">
                        {(record4Detail.match_reasons || []).slice(0, 5).map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ol>
                    </div>
                    <button
                      className="text-xs flex items-center gap-1"
                      onClick={() => setShowRecord4Detail(s => !s)}
                    >
                      {showRecord4Detail ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      展开 KB chunk 原文
                    </button>
                    {showRecord4Detail && (
                      <pre className="mt-2 p-2 bg-background border rounded text-xs whitespace-pre-wrap">
                        {record4Detail.kb_chunk_text || '（KB chunk 缺失）'}
                      </pre>
                    )}
                  </div>
                )}

                <div>
                  <label className="text-sm font-medium mb-1 block">
                    额外要求（extra_context）
                  </label>
                  <Textarea
                    placeholder="（可空）例：「测试期预算紧，最多 ¥800/天」「主推送礼场景」「这版圈包要避开同行已饱和标签」"
                    value={extraContext4}
                    onChange={e => setExtraContext4(e.target.value)}
                    rows={4}
                    className="text-sm"
                  />
                </div>

                <Button
                  onClick={runStep4}
                  disabled={running4 || !record4Id}
                  className="w-full"
                >
                  {running4 ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（约 30-60s）</> : '跑圈包 SOP'}
                </Button>

                {error && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">输出</CardTitle>
                  {resp4?.trace && (
                    <CardDescription className="text-xs">
                      {resp4.trace.model_provider}/{resp4.trace.model} · {resp4.trace.cost_estimate}
                    </CardDescription>
                  )}
                </div>
                {resp4?.result?.pack_md && (
                  <div className="space-x-1">
                    <Button size="sm" variant="outline" onClick={() => copyText(resp4.result?.pack_md)}>
                      <Copy className="w-3 h-3 mr-1" /> 复制
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => downloadMd(resp4.result?.pack_md, `${skuId}_audience-pack_${(resp4.result?.audience_pack_id || '').slice(0, 8)}.md`)}>
                      <Download className="w-3 h-3 mr-1" /> 下载 .md
                    </Button>
                  </div>
                )}
              </CardHeader>
              <CardContent>
                {!resp4 && !running4 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左边选 1 个人群后点"跑圈包 SOP"，结果会显示在这里。
                  </div>
                )}
                {running4 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                    LLM 翻译人群 → 巨量云图 8 大维度标签清单 + 预算 + A/B 矩阵...
                  </div>
                )}
                {resp4?.result?.pack_md && (
                  <>
                    {resp4.result.audience_pack_id && (() => {
                      const pId = resp4.result.audience_pack_id
                      const isAdopted = adoptedPackIds.has(pId)
                      const isAdoptingThis = adoptingPack === pId
                      return (
                        <div className={`mb-4 p-3 border rounded text-xs transition ${isAdopted ? 'bg-emerald-50/40 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800' : 'bg-blue-50/40 dark:bg-blue-950/20'}`}>
                          <div className="flex items-center justify-between gap-3 flex-wrap">
                            <div className="flex items-center gap-2 flex-wrap min-w-0">
                              <Badge variant={isAdopted ? 'default' : 'outline'}>
                                {isAdopted ? '✅ 已绑入血缘' : '已落库 · draft'}
                              </Badge>
                              <span>
                                audience_pack_id: <code className="text-[10px]">{pId.slice(0, 8)}…</code>
                              </span>
                              <span className="ml-2 text-muted-foreground">
                                ← record_id: <code className="text-[10px]">{resp4.result.audience_record_id.slice(0, 8)}…</code>
                              </span>
                            </div>
                            <Button
                              size="sm"
                              variant={isAdopted ? 'default' : 'outline'}
                              disabled={isAdoptingThis || isAdopted}
                              onClick={() => adoptAudiencePack(pId)}
                              className="shrink-0"
                              title={isAdopted ? '已绑入血缘 — 下游 step 5/6 可挂这一版' : '老板审完 OK 后点这里：把这版圈包标 adopted，绑入血缘，下游可挂'}
                            >
                              {isAdoptingThis
                                ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 绑入中</>
                                : isAdopted
                                  ? <>✅ 已绑入血缘</>
                                  : <>✓ 确认绑入血缘</>}
                            </Button>
                          </div>
                          <div className="text-muted-foreground mt-2">
                            {isAdopted
                              ? '已绑入。后续 step 5/6 跑脚本会自动挂这个 audience_pack_id；血缘反查（v_asset_full_lineage）也只跟 adopted 走。'
                              : '审完觉得这版 OK 再点"确认绑入血缘"。不点也能往下走，但血缘反查不会跟这版（draft 状态可重跑覆盖）。'}
                          </div>
                        </div>
                      )
                    })()}

                    <div className="prose prose-sm max-w-none dark:prose-invert">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {resp4.result.pack_md}
                      </ReactMarkdown>
                    </div>

                    {resp4.trace?.final_prompt && (
                      <div className="mt-6 border-t pt-4">
                        <button
                          className="text-sm font-medium flex items-center gap-1"
                          onClick={() => setShowPrompt4(s => !s)}
                        >
                          {showPrompt4 ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          Final Prompt（含 KB 原文 + matrix）
                        </button>
                        {showPrompt4 && (
                          <pre className="mt-2 p-3 bg-muted text-xs rounded whitespace-pre-wrap">
                            {resp4.trace.final_prompt}
                          </pre>
                        )}
                      </div>
                    )}
                  </>
                )}
                {resp4 && !resp4.ok && (
                  <div className="text-sm text-red-500">
                    <div>Error: {resp4.error}</div>
                    {resp4.hint && <div className="text-xs text-muted-foreground mt-1">{resp4.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Step 4 配套：500 词关键词扩展（phase B+） */}
          {resp4?.result?.pack_md && (
            <Card className="mt-4 border-dashed">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  🔑 500 词关键词扩展（云图数据工厂关键词夹用）
                </CardTitle>
                <CardDescription className="text-xs">
                  上面 step 4 第 4 部分的种子词已自动预填到下方（可改）。点"跑扩展" → 出 N 个一行一词无标点的纯文本，下载 .txt 后导入「云图 → 数据工厂 → 关键词夹 → 新建关键词包」。再到标签工厂转成人群标签 → 回自定义人群引用 → 推千川。<strong>不是直接进千川计划关键词定向</strong>。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="md:col-span-2">
                    <label className="text-sm font-medium mb-1 block">
                      种子关键词（每行 1 个；自动从 step 4 第 4 部分预填，可改）
                    </label>
                    <Textarea
                      placeholder="例：&#10;有机酱油&#10;无糖生抽&#10;赛博朋克&#10;寿喜锅底料&#10;减脂餐调味"
                      value={seedKw}
                      onChange={e => setSeedKw(e.target.value)}
                      rows={6}
                      className="text-sm font-mono"
                    />
                    <div className="text-xs text-muted-foreground mt-1">
                      {seedKw.split(/\n/).filter(s => s.trim()).length} 个种子词
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <label className="text-sm font-medium mb-1 block">
                        目标词数
                      </label>
                      <select
                        className="w-full border rounded px-2 py-2 text-sm bg-background"
                        value={targetCountKw}
                        onChange={e => setTargetCountKw(parseInt(e.target.value, 10))}
                      >
                        <option value={100}>100 词（快测）</option>
                        <option value={300}>300 词</option>
                        <option value={500}>500 词（推荐）</option>
                        <option value={1000}>1000 词（最大）</option>
                      </select>
                    </div>
                    <div className="text-xs text-muted-foreground space-y-1 p-2 bg-muted/30 rounded">
                      <div>挂上下文：</div>
                      <div>• SKU: <code className="text-[10px]">{skuId || '—'}</code></div>
                      <div>• audience_record: <code className="text-[10px]">{(resp4.result?.audience_record_id || record4Id || '—').slice(0, 8)}…</code></div>
                      <div>• audience_pack: <code className="text-[10px]">{(resp4.result?.audience_pack_id || '—').slice(0, 8)}…</code></div>
                    </div>
                    <Button
                      onClick={runKeywordPack}
                      disabled={runningKw || !seedKw.trim()}
                      className="w-full"
                    >
                      {runningKw ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中（约 30-60s）</> : `跑 ${targetCountKw} 词扩展`}
                    </Button>
                  </div>
                </div>

                {respKw?.result?.keyword_text && (
                  <div className="border rounded p-3 bg-emerald-50/30 dark:bg-emerald-950/20 space-y-2">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="flex items-center gap-2 text-xs">
                        <Badge variant="outline">已落库</Badge>
                        <span>
                          实际清洗后 <strong>{respKw.result.keyword_count}</strong> 词 / 目标 {respKw.result.target_count}
                        </span>
                        {respKw.result.keyword_pack_id && (
                          <span className="text-muted-foreground">
                            keyword_pack_id: <code className="text-[10px]">{respKw.result.keyword_pack_id.slice(0, 8)}…</code>
                          </span>
                        )}
                      </div>
                      <div className="space-x-1">
                        <Button size="sm" variant="outline" onClick={copyKeywordText}>
                          <Copy className="w-3 h-3 mr-1" /> {copiedKw ? '✓ 已复制' : '复制全部'}
                        </Button>
                        <Button size="sm" variant="default" onClick={downloadKeywordTxt}>
                          <Download className="w-3 h-3 mr-1" /> 下载 .txt
                        </Button>
                      </div>
                    </div>

                    {(respKw.result.warnings || []).length > 0 && (
                      <div className="text-xs text-amber-700 dark:text-amber-400 p-2 border border-amber-200 dark:border-amber-900 rounded bg-amber-50 dark:bg-amber-950/40">
                        ⚠ {respKw.result.warnings.join(' · ')}
                      </div>
                    )}

                    <Textarea
                      value={respKw.result.keyword_text}
                      readOnly
                      rows={14}
                      className="text-xs font-mono bg-background"
                      onClick={e => (e.target as HTMLTextAreaElement).select()}
                    />
                    <div className="text-[11px] text-muted-foreground">
                      格式：每行 1 词、无标点、无数字、长度 2-15 字。下载后用记事本打开，全选复制 → 导入「云图 → 数据工厂 → 关键词夹 → 新建关键词包」。
                    </div>
                  </div>
                )}

                {runningKw && !respKw && (
                  <div className="text-sm text-muted-foreground py-6 text-center">
                    <Loader2 className="w-5 h-5 mx-auto animate-spin mb-2" />
                    LLM 扩词 → 后处理清洗（去标点 / 去数字 / 去重 / 长度过滤）...
                  </div>
                )}

                {respKw && !respKw.ok && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    Error: {respKw.error}
                    {respKw.hint && <div className="text-xs mt-1">{respKw.hint}</div>}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ============== STEP 5: 创意素材（6 类） ============== */}
        <TabsContent value="step5" className="mt-0 flex-1 min-w-0">
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            {/* 左：模式 + 输入 */}
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Film className="w-4 h-4" /> 输入
                </CardTitle>
                <CardDescription>
                  6 类素材 1 个 tool 6 套 prompt；选挂哪一层链路 + 选素材类型 → 跑
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                {/* 当前选中 summary（一眼看明白现在选了啥） */}
                <div className="rounded border border-dashed p-2 text-xs space-y-1 bg-muted/30">
                  <div className="font-medium text-muted-foreground">当前选中</div>
                  <div>
                    <span className="text-muted-foreground">模式：</span>
                    <Badge variant="secondary">
                      {srcMode5 === 'record' ? 'record 候选人群'
                        : srcMode5 === 'pack' ? 'pack 圈包（最完整链路）'
                        : 'sku 单 SKU 直跑'}
                    </Badge>
                  </div>
                  {srcMode5 === 'record' && (
                    <div>
                      <span className="text-muted-foreground">人群：</span>
                      {record5Id ? (
                        <Badge>
                          {(poolRecords?.find(r => r.id === record5Id)?.name) || record5Id.slice(0, 8)}
                        </Badge>
                      ) : (
                        <span className="text-orange-500">未选（点下面"从 SKU 人群池选"展开后挑 1 条）</span>
                      )}
                    </div>
                  )}
                  {srcMode5 === 'pack' && (
                    <div>
                      <span className="text-muted-foreground">圈包：</span>
                      {pack5Id ? (
                        <span className="inline-flex items-center gap-1">
                          <Badge>
                            圈包 第 {pack5Detail?.version || '?'} 版 · <code className="text-[10px]">{pack5Id.slice(0, 8)}</code>
                          </Badge>
                          {loadingPack5 && <Loader2 className="w-3 h-3 animate-spin" />}
                          <button
                            type="button"
                            className="text-[10px] text-muted-foreground hover:text-red-500"
                            onClick={() => {
                              setPack5Id('')
                              setPack5Detail(null)
                              setShowPack5Md(false)
                            }}
                            title="清除选中圈包"
                          >
                            ✕ 清除
                          </button>
                        </span>
                      ) : (
                        <span className="text-orange-500">未选（点下方"从血缘图选上游"挑一个圈包节点）</span>
                      )}
                    </div>
                  )}
                  <div>
                    <span className="text-muted-foreground">素材类型：</span>
                    <Badge>{CREATIVE_KIND_LIST.find(x => x.kind === kind5)?.label || kind5}</Badge>
                  </div>
                </div>

                <div>
                  <label className="text-sm font-medium mb-2 block">挂链路（弹性挂 · 完整度 pack &gt; record &gt; sku）</label>
                  <div className="flex gap-2 flex-wrap">
                    <button
                      type="button"
                      className={`text-xs px-3 py-1.5 rounded border-2 font-medium transition-colors ${srcMode5 === 'record' ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background text-muted-foreground hover:bg-muted'}`}
                      onClick={() => setSrcMode5('record')}
                    >
                      {srcMode5 === 'record' ? '✓ ' : ''}record（候选人群）
                    </button>
                    <button
                      type="button"
                      className={`text-xs px-3 py-1.5 rounded border-2 font-medium transition-colors ${srcMode5 === 'pack' ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background text-muted-foreground hover:bg-muted'}`}
                      onClick={() => {
                        setSrcMode5('pack')
                        // pack 没有独立"池子"UI（人群池 ≠ 圈包池），点了直接弹血缘图选
                        if (!pack5Id) setPickModalOpen(true)
                      }}
                    >
                      {srcMode5 === 'pack' ? '✓ ' : ''}pack（圈包）
                    </button>
                    <button
                      type="button"
                      className={`text-xs px-3 py-1.5 rounded border-2 font-medium transition-colors ${srcMode5 === 'sku' ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background text-muted-foreground hover:bg-muted'}`}
                      onClick={() => setSrcMode5('sku')}
                    >
                      {srcMode5 === 'sku' ? '✓ ' : ''}sku（单 SKU 直跑）
                    </button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="text-xs h-auto py-1.5"
                      disabled={!skuId}
                      onClick={() => setPickModalOpen(true)}
                      title={skuId ? '从血缘图选 record / pack 节点回填' : '先选 SKU'}
                    >
                      <Network className="w-3 h-3 mr-1" /> 从血缘图选上游
                    </Button>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    <strong>pack 模式</strong>：拉圈包 + 关联 record + matrix 全链路（最完整）；<strong>record 模式</strong>：人群 KB 画像 + matrix 卖点；<strong>sku 模式</strong>：通用画像，适合先试主图/详情页。
                  </div>
                </div>

                {srcMode5 === 'record' && (
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-sm font-medium">从 SKU 人群池选</label>
                      <button
                        type="button"
                        className="text-xs text-primary hover:underline"
                        onClick={() => {
                          setShowPool(prev => !prev)
                          if (poolRecords === null) loadPool()
                        }}
                      >
                        {showPool ? '收起' : '展开'}
                      </button>
                    </div>
                    {showPool && poolLoading && <div className="text-xs text-muted-foreground">加载中...</div>}
                    {showPool && !poolLoading && poolRecords !== null && poolRecords.length === 0 && (
                      <div className="text-xs text-muted-foreground py-2">
                        当前 SKU 还没人群池。先去 step 3 跑一次匹配，挑认可的点 ⭐ 加入池子。
                      </div>
                    )}
                    {showPool && !poolLoading && poolRecords !== null && poolRecords.length > 0 && (
                      <div className="space-y-1 max-h-64 overflow-y-auto">
                        {poolRecords.map(r => {
                          const selected = record5Id === r.id
                          return (
                            <button
                              key={r.id}
                              type="button"
                              className={`w-full text-left text-xs px-2 py-1.5 rounded border-2 transition-colors ${selected ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background hover:bg-muted'}`}
                              onClick={() => setRecord5Id(r.id || '')}
                            >
                              <div className="font-medium flex items-center gap-1">
                                {selected && <span>✓</span>}
                                {r.name}
                              </div>
                              <div className={`text-[10px] ${selected ? 'text-primary-foreground/80' : 'text-muted-foreground'}`}>
                                {r.kb_doc || '（无 doc）'} · {(r.layer_tags || []).join(' / ')}
                              </div>
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* pack 模式：选中圈包详情卡（pack_md 预览，老板确认选对没） */}
                {srcMode5 === 'pack' && pack5Id && (
                  <div className="border rounded p-3 bg-pink-50/40 dark:bg-pink-950/10 text-xs space-y-2 border-pink-200 dark:border-pink-900">
                    {loadingPack5 && (
                      <div className="text-muted-foreground">
                        <Loader2 className="w-3 h-3 inline animate-spin mr-1" /> 拉圈包详情...
                      </div>
                    )}
                    {pack5Detail && (
                      <>
                        <div className="flex items-center gap-2 flex-wrap">
                          <Badge className="text-[10px]">圈包第 {pack5Detail.version} 版</Badge>
                          <Badge
                            variant={pack5Detail.status === 'adopted' ? 'default' : 'outline'}
                            className="text-[10px]"
                          >
                            {pack5Detail.status === 'adopted' ? '✅ 已采纳' : '草稿'}
                          </Badge>
                          <span className="text-muted-foreground">
                            上游候选人群 <code className="text-[10px]">{pack5Detail.audience_record_id?.slice(0, 8)}</code>
                          </span>
                          <span className="text-muted-foreground">
                            · 卖点矩阵 <code className="text-[10px]">{pack5Detail.matrix_run_id?.slice(0, 8)}</code>
                          </span>
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                          创建于 {pack5Detail.created_at?.slice(0, 16).replace('T', ' ')}
                        </div>
                        <div className="border-t border-pink-200/60 dark:border-pink-900/60 pt-2">
                          <button
                            type="button"
                            className="text-xs flex items-center gap-1 text-primary hover:underline"
                            onClick={() => setShowPack5Md(s => !s)}
                          >
                            {showPack5Md ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                            {showPack5Md ? '收起' : '展开'} pack_md 全文（{pack5Detail.pack_md?.length || 0} 字）
                          </button>
                          {!showPack5Md && pack5Detail.pack_md && (
                            <div className="text-[11px] text-muted-foreground mt-1 line-clamp-3 italic">
                              {pack5Detail.pack_md.slice(0, 240)}...
                            </div>
                          )}
                          {showPack5Md && pack5Detail.pack_md && (
                            <div className="prose prose-sm max-w-none dark:prose-invert mt-2 text-sm p-3 bg-background border rounded">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {pack5Detail.pack_md}
                              </ReactMarkdown>
                            </div>
                          )}
                        </div>
                      </>
                    )}
                    {!loadingPack5 && !pack5Detail && (
                      <div className="text-muted-foreground">
                        ⚠ 圈包详情拉不到（id 可能失效）。点 ✕ 清除重选。
                      </div>
                    )}
                  </div>
                )}

                <div>
                  <label className="text-sm font-medium mb-2 block">素材类型（6 选 1）</label>
                  <div className="grid grid-cols-2 gap-2">
                    {CREATIVE_KIND_LIST.map(item => {
                      const selected = kind5 === item.kind
                      return (
                        <button
                          key={item.kind}
                          type="button"
                          className={`text-xs text-left px-2 py-2 rounded border-2 transition-colors ${selected ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background hover:bg-muted'}`}
                          onClick={() => setKind5(item.kind)}
                          title={item.hint}
                        >
                          <div className="font-medium flex items-center gap-1">
                            {selected && <span>✓</span>}
                            {item.label}
                          </div>
                          <div className={`text-[10px] mt-0.5 ${selected ? 'text-primary-foreground/80' : 'text-muted-foreground'}`}>
                            {item.hint}
                          </div>
                        </button>
                      )
                    })}
                  </div>
                </div>

                <div>
                  <label className="text-sm font-medium mb-1 block">extra_context（可空）</label>
                  <Textarea
                    placeholder="例：「这版主推送礼场景」「避开同行已饱和卖点」「老板自给优惠：下单立减 10 元」"
                    value={extraContext5}
                    onChange={e => setExtraContext5(e.target.value)}
                    rows={5}
                  />
                </div>

                <Button onClick={runStep5} disabled={running5} className="w-full">
                  {running5 ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> 跑中...（约 30-90s）</> : '跑创意素材'}
                </Button>
              </CardContent>
            </Card>

            {/* 右：输出 */}
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle className="text-base">输出</CardTitle>
                <CardDescription>
                  v1 骨架 — prompt 调试中。任何不对的地方，告诉我改 prompt（不用改代码）
                </CardDescription>
              </CardHeader>
              <CardContent>
                {!resp5 && !running5 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左侧选 record / sku + 选素材类型 → 点"跑创意素材"，结果显示在这里。
                  </div>
                )}

                {running5 && !resp5 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-5 h-5 mx-auto animate-spin mb-2" />
                    LLM 出稿中（gemini-3.1-pro-preview）...
                  </div>
                )}

                {resp5 && !resp5.ok && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    Error: {resp5.error}
                    {resp5.hint && <div className="text-xs mt-1">{resp5.hint}</div>}
                  </div>
                )}

                {resp5 && resp5.ok && resp5.result && (
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap">
                      <Badge variant="secondary">{resp5.result.kind_label}</Badge>
                      {resp5.result.script_id && (
                        <span title="pipeline.scripts.id">script_id: {resp5.result.script_id.slice(0, 8)}</span>
                      )}
                      {resp5.result.audience_record_id && (
                        <span>record: {resp5.result.audience_record_id.slice(0, 8)}</span>
                      )}
                      {resp5.result.matrix_run_id && (
                        <span>matrix: {resp5.result.matrix_run_id.slice(0, 8)}</span>
                      )}
                      <button
                        className="ml-auto text-primary hover:underline"
                        onClick={() => {
                          if (resp5.result?.script_md) {
                            navigator.clipboard.writeText(resp5.result.script_md)
                          }
                        }}
                      >
                        <Copy className="w-3 h-3 inline mr-1" /> 复制
                      </button>
                      <button
                        className="text-primary hover:underline"
                        onClick={() => {
                          if (!resp5.result?.script_md) return
                          const blob = new Blob([resp5.result.script_md], { type: 'text/markdown' })
                          const url = URL.createObjectURL(blob)
                          const a = document.createElement('a')
                          a.href = url
                          a.download = `${resp5.result.kind}-${(resp5.result.script_id || 'creative').slice(0, 8)}.md`
                          a.click()
                          URL.revokeObjectURL(url)
                        }}
                      >
                        <Download className="w-3 h-3 inline mr-1" /> 下载 .md
                      </button>
                    </div>

                    {/* 确认绑入血缘（status='draft' → 'adopted'）—— 老板审完点 */}
                    {resp5.result.script_id && (() => {
                      const sId = resp5.result.script_id
                      const isAdopted = adoptedScriptIds.has(sId)
                      const isAdoptingThis = adoptingScript === sId
                      const hasWarnings = (resp5.result.validation_warnings || []).length > 0
                      return (
                        <div className={`p-3 border rounded text-xs transition ${isAdopted ? 'bg-emerald-50/40 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800' : 'bg-blue-50/40 dark:bg-blue-950/20'}`}>
                          <div className="flex items-center justify-between gap-3 flex-wrap">
                            <div className="flex items-center gap-2 flex-wrap min-w-0">
                              <Badge variant={isAdopted ? 'default' : 'outline'}>
                                {isAdopted ? '✅ 已绑入血缘' : '已落库 · draft'}
                              </Badge>
                              <span className="text-muted-foreground">
                                kind: <code className="text-[10px]">{resp5.result.kind}</code>
                              </span>
                              <span className="text-muted-foreground">
                                script_id: <code className="text-[10px]">{sId.slice(0, 8)}…</code>
                              </span>
                            </div>
                            <Button
                              size="sm"
                              variant={isAdopted ? 'default' : 'outline'}
                              disabled={isAdoptingThis || isAdopted}
                              onClick={() => adoptCreativeScript(sId)}
                              className="shrink-0"
                              title={isAdopted ? '已绑入血缘 — 下游 phase D 生成图/视频可挂这版' : '审完 OK 后点这里：标 adopted 进血缘，下游可挂'}
                            >
                              {isAdoptingThis
                                ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 绑入中</>
                                : isAdopted
                                  ? <>✅ 已绑入血缘</>
                                  : <>✓ 确认绑入血缘</>}
                            </Button>
                          </div>
                          <div className="text-muted-foreground mt-2">
                            {isAdopted
                              ? '已绑入。phase D 起拉分镜图 / 视频生成时按 sku+kind 列 adopted 让你挑这版。血缘反查也只跟 adopted 走。'
                              : hasWarnings
                                ? '⚠ 上方校验有警告。建议改 prompt / 重跑修复后再绑；硬要绑也可以（多版本并存，draft 老板按需重跑覆盖）。'
                                : '审完觉得这版 OK 再点"确认绑入血缘"。不点也能继续跑别的，但 phase D 生成时不会列 draft 版本。'}
                          </div>
                        </div>
                      )
                    })()}

                    {/* 后端硬约束校验结果（反 LLM 自检装饰） */}
                    {resp5.result.validation_warnings && resp5.result.validation_warnings.length > 0 && (
                      <div className="border-2 border-orange-300 rounded p-3 bg-orange-50 space-y-2">
                        <div className="text-sm font-semibold text-orange-800">
                          ⚠ 后端硬约束校验：{resp5.result.validation_warnings.length} 项不通过
                        </div>
                        <ul className="text-xs text-orange-900 space-y-1 list-disc pl-5">
                          {resp5.result.validation_warnings.map((w, i) => (
                            <li key={i}>{w}</li>
                          ))}
                        </ul>
                        <div className="text-[10px] text-orange-700 mt-1">
                          这是 LLM 自报 metrics_json 后跑的代码校验，不是 LLM 自打钩。改 prompt 或重跑修。
                        </div>
                      </div>
                    )}
                    {resp5.result.validation_warnings && resp5.result.validation_warnings.length === 0 && resp5.result.metrics && (
                      <div className="border-2 border-green-300 rounded p-2 bg-green-50 text-xs text-green-800">
                        ✓ 后端硬约束校验全过（地板 8 条 + 选定方向硬约束）
                      </div>
                    )}

                    {/* metrics_json 数据（折叠显示） */}
                    {resp5.result.metrics && (
                      <details className="border rounded p-2 bg-muted/20" open>
                        <summary className="text-xs cursor-pointer text-muted-foreground">
                          metrics_json（LLM 自报指标，后端校验依据）
                        </summary>
                        <pre className="text-[10px] mt-2 whitespace-pre-wrap">
                          {JSON.stringify(resp5.result.metrics, null, 2)}
                        </pre>
                      </details>
                    )}

                    <div className="prose prose-sm max-w-none border rounded p-4 bg-muted/30">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{resp5.result.script_md}</ReactMarkdown>
                    </div>

                    {resp5.trace && (
                      <div className="border rounded">
                        <button
                          className="w-full flex items-center justify-between px-3 py-2 text-xs text-muted-foreground hover:bg-muted"
                          onClick={() => setShowPrompt5(!showPrompt5)}
                        >
                          <span>
                            {showPrompt5 ? <ChevronDown className="w-3 h-3 inline" /> : <ChevronRight className="w-3 h-3 inline" />}
                            {' '}prompt + trace（{resp5.trace.model_provider}/{resp5.trace.model}）
                          </span>
                        </button>
                        {showPrompt5 && (
                          <pre className="text-xs p-3 bg-muted/50 whitespace-pre-wrap">
                            {resp5.trace.final_prompt}
                          </pre>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ============== STEP 6: 分镜图生成（W4-B 14.4 phase D） ============== */}
        <TabsContent value="step6" className="mt-0 flex-1 min-w-0">
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            {/* 左：选脚本 + 输入 */}
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <ImageIcon className="w-4 h-4" /> 输入
                </CardTitle>
                <CardDescription>
                  选已采纳脚本 → 自动拆分镜清单 → 选哪几段 + 参考图 → 并发出图（每张 30-60s）落入血缘
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                <div className="flex items-center justify-between gap-2">
                  <label className="text-sm font-medium">脚本</label>
                  <Button size="sm" variant="outline" onClick={loadScriptsForStep6} disabled={!skuId || loadingScripts6}>
                    {loadingScripts6 ? <Loader2 className="w-3 h-3 animate-spin" /> : (scriptsForSku6 !== null ? '刷新' : '加载脚本')}
                  </Button>
                </div>
                {scriptsForSku6 === null && (
                  <div className="text-xs text-muted-foreground p-3 border border-dashed rounded">
                    点上方"加载脚本"拉这个 SKU 跑过的所有脚本（按时间倒序）。
                  </div>
                )}
                {scriptsForSku6 && scriptsForSku6.length === 0 && (
                  <div className="text-xs text-muted-foreground p-3 border border-dashed rounded">
                    这个 SKU 还没跑过 step 5 创意脚本。
                  </div>
                )}
                {scriptsForSku6 && scriptsForSku6.length > 0 && (
                  <select
                    className="w-full border rounded px-2 py-2 text-sm bg-background"
                    value={script6Id}
                    onChange={e => selectScript6(e.target.value)}
                  >
                    <option value="">— 请选择脚本 —</option>
                    {scriptsForSku6.map(s => (
                      <option key={s.id} value={s.id}>
                        [{s.status === 'adopted' ? '✅' : '·'}] {s.kind} v{s.version} · {s.id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                )}

                {loadingScript6Detail && (
                  <div className="text-xs text-muted-foreground">
                    <Loader2 className="w-3 h-3 inline animate-spin mr-1" /> 拉脚本详情...
                  </div>
                )}

                {script6Detail && (
                  <div className="border rounded p-2 bg-muted/30 text-xs space-y-1">
                    <div>
                      <Badge variant="secondary" className="text-[10px]">{script6Detail.kind}</Badge>
                      <Badge variant="outline" className="text-[10px] ml-1">第 {script6Detail.version} 版</Badge>
                      <Badge
                        variant={script6Detail.status === 'adopted' ? 'default' : 'outline'}
                        className="text-[10px] ml-1"
                      >
                        {script6Detail.status === 'adopted' ? '已采纳' : '草稿'}
                      </Badge>
                    </div>
                    <div className="text-muted-foreground">
                      共 <strong>{script6Detail.scenes?.length || 0}</strong> 段分镜
                      {(script6Detail.character_sheets?.length || 0) > 0 && (
                        <span> · <strong>{script6Detail.character_sheets!.length}</strong> 个固定角色</span>
                      )}
                      {(script6Detail.scenes?.length || 0) === 0 && (
                        <span className="text-orange-500 ml-1">
                          ⚠ scenes 为空，先调"回填分镜"按钮
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* ═════ 主操作按钮（置顶，老板一眼能看见） ═════ */}
                {script6Detail && (script6Detail.scenes?.length || 0) > 0 && (
                  <div className="border-2 border-primary/50 rounded-lg p-3 bg-primary/5 space-y-2">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="text-sm font-medium">
                        ▶ 出图：已选 <strong className="text-primary">{selectedScenes6.size}</strong> / {script6Detail.scenes!.length} 段
                      </div>
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          onClick={() => setSelectedScenes6(new Set([script6Detail.scenes![0].scene_no]))}
                          title="只跑第 1 段（先小范围测）"
                        >
                          只第 1 段
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          onClick={() => setSelectedScenes6(new Set(script6Detail.scenes!.map(s => s.scene_no)))}
                        >
                          全选 {script6Detail.scenes!.length}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          onClick={() => setSelectedScenes6(new Set())}
                        >
                          全清
                        </Button>
                      </div>
                    </div>
                    <Button
                      onClick={() => runStep6Storyboard()}
                      disabled={running6 || selectedScenes6.size === 0}
                      className="w-full text-base h-11"
                      size="lg"
                    >
                      {running6 ? (
                        <><Loader2 className="w-5 h-5 mr-2 animate-spin" /> 跑中（{selectedScenes6.size} 张并发，约 30-60s）</>
                      ) : selectedScenes6.size === 0 ? (
                        '先选要跑的段'
                      ) : (
                        `★ 出 ${selectedScenes6.size} 张分镜图（${selectedScenes6.size > 1 ? '并发 ' : ''}gpt-image-1.5）`
                      )}
                    </Button>
                    <div className="text-[11px] text-muted-foreground">
                      下方可调画幅 / 角色定妆 / 参考图等细节后再跑。
                    </div>
                  </div>
                )}

                {/* Step 6.5：角色定妆白底像（chatgpt-image-2 锁脸） */}
                {script6Detail && (script6Detail.character_sheets?.length || 0) > 0 && (
                  <div className="border rounded p-3 bg-purple-50/30 dark:bg-purple-950/10 text-sm space-y-2 border-purple-200 dark:border-purple-900">
                    <div className="flex items-center justify-between">
                      <div className="font-medium flex items-center gap-2">
                        <span className="text-purple-700 dark:text-purple-400">★ Step 6.5</span>
                        <span>角色定妆（锁脸）</span>
                      </div>
                      <Button
                        size="sm"
                        variant={charSheetsResp?.result?.success_count ? 'default' : 'outline'}
                        disabled={runningCharSheets || !script6Id}
                        onClick={() => runCharacterSheets()}
                      >
                        {runningCharSheets
                          ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 跑中</>
                          : charSheetsResp?.result?.success_count
                            ? `✓ 已出 ${charSheetsResp.result.success_count} 张 · 重跑`
                            : `出 ${script6Detail.character_sheets!.length} 张白底像（约 30s）`}
                      </Button>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      跑完后 step 6 分镜图自动按每段 <code>characters_in_scene</code> 找对应角色当 face_refs，全篇锁脸。
                    </div>
                    <div className="space-y-1.5">
                      {script6Detail.character_sheets!.map(s => {
                        const got = charSheetsResp?.result?.results?.find(r => r.role_id === s.role_id)
                        return (
                          <div key={s.role_id} className="flex items-start gap-2 text-xs p-2 rounded bg-background/60 border">
                            {got?.file_url ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={got.file_url}
                                alt={s.role_id}
                                className="w-16 h-16 object-cover rounded border shrink-0"
                              />
                            ) : (
                              <div className="w-16 h-16 rounded border border-dashed flex items-center justify-center bg-muted text-muted-foreground text-[10px] shrink-0">
                                {got?.error ? '❌' : 'pending'}
                              </div>
                            )}
                            <div className="flex-1 min-w-0">
                              <div className="font-medium">
                                <code>{s.role_id}</code> · {s.name || '?'}
                                {got?.asset_id && (
                                  <Badge variant="default" className="text-[10px] ml-2">已落血缘</Badge>
                                )}
                              </div>
                              <div className="text-[11px] text-muted-foreground">
                                {s.age} · {s.gender} · {s.appearance_keywords?.slice(0, 60)}
                                {(s.appearance_keywords?.length || 0) > 60 && '...'}
                              </div>
                              {got?.error && (
                                <div className="text-[11px] text-red-500 mt-1">{got.error}</div>
                              )}
                              {got?.file_url && (
                                <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    disabled={runningCharSheets}
                                    onClick={() => runCharacterSheets([s.role_id])}
                                    className="text-[10px] h-6 px-2"
                                  >
                                    🔄 重跑
                                  </Button>
                                  {got.asset_id && (() => {
                                    const isAdopted = adoptedAssetIds.has(got.asset_id!)
                                    const isAdoptingThis = adoptingAsset === got.asset_id
                                    return (
                                      <Button
                                        size="sm"
                                        variant={isAdopted ? 'default' : 'outline'}
                                        disabled={isAdoptingThis || isAdopted}
                                        onClick={() => adoptAsset(got.asset_id!)}
                                        className="text-[10px] h-6 px-2"
                                      >
                                        {isAdoptingThis
                                          ? <Loader2 className="w-3 h-3 animate-spin" />
                                          : isAdopted ? '✅ 已绑' : '✓ 绑血缘'}
                                      </Button>
                                    )
                                  })()}
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => {
                                      const fname = `${script6Detail?.sku_id || 'sku'}_${s.role_id}.png`
                                      downloadAsset(got.file_url!, fname)
                                    }}
                                    className="text-[10px] h-6 px-2"
                                  >
                                    ⬇ 下载
                                  </Button>
                                  <a
                                    href={got.file_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="text-[11px] text-primary hover:underline ml-auto"
                                  >
                                    原图 ↗
                                  </a>
                                </div>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {script6Detail && (script6Detail.character_sheets?.length || 0) === 0 && (
                  <div className="text-xs text-muted-foreground p-2 border border-dashed rounded">
                    ⚠ 这个脚本没角色清单（v10 老格式无第 3.5 部分）。step 6 分镜图照常跑，但无 face_refs 锁脸。
                    建议重跑 step 5 出 v11+ 新格式脚本。
                  </div>
                )}

                {script6Detail && (script6Detail.scenes?.length || 0) > 0 && (
                  <div>
                    <label className="text-sm font-medium mb-2 block text-muted-foreground">
                      ▼ 多选段详情（点卡片切换；当前选 {selectedScenes6.size} / {script6Detail.scenes!.length}）
                    </label>
                    <div className="space-y-1.5 max-h-80 overflow-y-auto pr-1">
                      {script6Detail.scenes.map(s => {
                        const sel = selectedScenes6.has(s.scene_no)
                        // 故事板 prompt 数据准备（独立于 step 6 跑没跑过）
                        const rawIp = s.image_prompt || ''
                        const sheets = script6Detail.character_sheets || []
                        const standalonePrompt = rawIp ? buildStandalonePrompt(rawIp, sheets) : ''
                        // character_sheet asset url（来自 step 6.5 跑结果）— role_id → file_url
                        const charAssetUrls: Record<string, string> = {}
                        ;(charSheetsResp?.result?.results || []).forEach(rr => {
                          if (rr.role_id && rr.file_url) charAssetUrls[rr.role_id] = rr.file_url
                        })
                        const sceneFaceUrls = (s.characters_in_scene || [])
                          .map(roleId => charAssetUrls[roleId])
                          .filter((x): x is string => Boolean(x))
                        const manualFaceUrls = faceRefs6.split(/\n/).map(x => x.trim()).filter(Boolean)
                        const allFaceUrls = [...manualFaceUrls, ...sceneFaceUrls]
                        const productUrls = s.product_appearance !== false
                          ? productRefs6.split(/\n/).map(x => x.trim()).filter(Boolean)
                          : []
                        const refLines: string[] = []
                        allFaceUrls.forEach((u, i) => refLines.push(`- 人脸参考 ${i + 1}: ${u}`))
                        productUrls.forEach((u, i) => refLines.push(`- 产品参考 ${i + 1}: ${u}`))
                        const sbFullText = refLines.length > 0
                          ? `${standalonePrompt}\n\nReference images (strictly preserve the people and products shown):\n${refLines.join('\n')}`
                          : standalonePrompt
                        return (
                          <div
                            key={s.scene_no}
                            className={`p-2 border rounded transition ${sel ? 'border-primary bg-primary/5' : 'border-border bg-background hover:bg-muted/30'}`}
                          >
                            <div
                              className="flex items-center gap-2 text-xs cursor-pointer"
                              onClick={() => toggleScene6(s.scene_no)}
                            >
                              <span className="font-medium">第 {s.scene_no} 段</span>
                              {s.name && <span className="text-muted-foreground truncate">· {s.name}</span>}
                              {s.time_range && <Badge variant="outline" className="text-[10px]">{s.time_range}</Badge>}
                              {(s.characters_in_scene?.length || 0) > 0 && (
                                <Badge variant="outline" className="text-[10px]">
                                  👤 {s.characters_in_scene!.join('/')} ({sceneFaceUrls.length})
                                </Badge>
                              )}
                              {s.product_appearance === true && (
                                <Badge variant="outline" className="text-[10px]">📦 ({productUrls.length})</Badge>
                              )}
                              {sel && <span className="ml-auto text-primary text-[10px]">✓ 跑</span>}
                            </div>
                            {s.visual && (
                              <div
                                className="text-[11px] text-muted-foreground mt-1 line-clamp-2 cursor-pointer"
                                onClick={() => toggleScene6(s.scene_no)}
                              >
                                {s.visual}
                              </div>
                            )}
                            {rawIp && (
                              <details
                                className="mt-1 text-[11px]"
                                onClick={e => e.stopPropagation()}
                              >
                                <summary className="cursor-pointer text-primary font-medium">
                                  📋 故事板提示词（外部模型用 · 含人脸/产品描述 + 参考图 url）
                                </summary>
                                <div className="mt-1 space-y-2" onClick={e => e.stopPropagation()}>
                                  <textarea
                                    readOnly
                                    value={sbFullText}
                                    rows={Math.min(14, sbFullText.split('\n').length + 2)}
                                    className="w-full text-[10px] font-mono p-2 border rounded bg-muted/30"
                                    onClick={e => {
                                      e.stopPropagation();
                                      (e.target as HTMLTextAreaElement).select()
                                    }}
                                  />
                                  {(allFaceUrls.length > 0 || productUrls.length > 0) && (
                                    <div className="space-y-1">
                                      <div className="text-[10px] text-muted-foreground">
                                        参考图（点缩略图打开原图，方便下载贴外部模型）：
                                      </div>
                                      <div className="flex flex-wrap gap-2">
                                        {allFaceUrls.map((u, i) => (
                                          <a key={`f${i}`} href={u} target="_blank" rel="noreferrer" title={`人脸 ${i + 1}`} onClick={e => e.stopPropagation()}>
                                            {/* eslint-disable-next-line @next/next/no-img-element */}
                                            <img src={u} alt={`face${i}`} className="w-12 h-12 object-cover rounded border" />
                                          </a>
                                        ))}
                                        {productUrls.map((u, i) => (
                                          <a key={`p${i}`} href={u} target="_blank" rel="noreferrer" title={`产品 ${i + 1}`} onClick={e => e.stopPropagation()}>
                                            {/* eslint-disable-next-line @next/next/no-img-element */}
                                            <img src={u} alt={`product${i}`} className="w-12 h-12 object-cover rounded border" />
                                          </a>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                  {(s.characters_in_scene?.length || 0) > 0 && sceneFaceUrls.length === 0 && (
                                    <div className="text-[10px] text-orange-500">
                                      ⚠ 本段角色 {s.characters_in_scene!.join('/')} 还没出定妆照（step 6.5），prompt 里只有文字描述、无参考图 url。先跑 step 6.5 定妆照后再来这里拿 url
                                    </div>
                                  )}
                                  <Button
                                    size="sm"
                                    variant="default"
                                    className="text-xs h-7"
                                    onClick={e => {
                                      e.stopPropagation()
                                      navigator.clipboard.writeText(sbFullText)
                                    }}
                                  >
                                    📋 复制全文（prompt + 参考图 url）
                                  </Button>
                                </div>
                              </details>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                <div>
                  <label className="text-sm font-medium mb-1 block">人脸参考图（face_refs，每行 1 url）</label>
                  <Textarea
                    placeholder="（可空）每行 1 个 url"
                    value={faceRefs6}
                    onChange={e => setFaceRefs6(e.target.value)}
                    rows={4}
                    className="text-xs font-mono"
                  />
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-sm font-medium">产品参考图（product_refs · 严格参考产品外观）</label>
                    <label className="text-xs text-primary hover:underline cursor-pointer">
                      ⬆ 上传白底图
                      <input
                        type="file"
                        multiple
                        accept="image/png,image/jpeg,image/webp"
                        className="hidden"
                        onChange={async e => {
                          const files = Array.from(e.target.files || [])
                          if (!files.length) return
                          const dataUrls: string[] = []
                          for (const f of files) {
                            try {
                              const dataUrl = await new Promise<string>((resolve, reject) => {
                                const reader = new FileReader()
                                reader.onload = () => resolve(reader.result as string)
                                reader.onerror = () => reject(reader.error)
                                reader.readAsDataURL(f)
                              })
                              dataUrls.push(dataUrl)
                            } catch (err) {
                              console.error('upload failed', f.name, err)
                            }
                          }
                          if (dataUrls.length) {
                            const existing = productRefs6.trim()
                            setProductRefs6(existing ? `${existing}\n${dataUrls.join('\n')}` : dataUrls.join('\n'))
                          }
                          // 重置 input 让同一个文件可再选
                          e.target.value = ''
                        }}
                      />
                    </label>
                  </div>
                  <Textarea
                    placeholder="（可空）每行 1 个 url 或 base64 data URL；点上方「⬆ 上传白底图」直接上传文件"
                    value={productRefs6}
                    onChange={e => setProductRefs6(e.target.value)}
                    rows={4}
                    className="text-xs font-mono"
                  />
                  {/* 已上传/输入的图片缩略图列表（含 1 键删除） */}
                  {(() => {
                    const lines = productRefs6.split('\n').map(s => s.trim()).filter(Boolean)
                    if (!lines.length) return null
                    return (
                      <div className="mt-2 grid grid-cols-4 sm:grid-cols-5 gap-2">
                        {lines.map((url, i) => (
                          <div key={i} className="relative group border rounded overflow-hidden bg-muted/30">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={url}
                              alt={`ref ${i + 1}`}
                              className="w-full h-20 object-contain bg-white"
                              onError={e => {
                                (e.target as HTMLImageElement).style.opacity = '0.3'
                              }}
                            />
                            <button
                              type="button"
                              className="absolute top-0.5 right-0.5 bg-red-500 text-white rounded text-[10px] px-1.5 py-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                              onClick={() => {
                                const next = lines.filter((_, idx) => idx !== i).join('\n')
                                setProductRefs6(next)
                              }}
                              title="删除"
                            >
                              ✕
                            </button>
                            <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[10px] px-1 py-0.5 truncate">
                              #{i + 1} {url.startsWith('data:') ? '(上传)' : url.slice(0, 30)}
                            </div>
                          </div>
                        ))}
                      </div>
                    )
                  })()}
                  <div className="text-[11px] text-muted-foreground mt-1">
                    {productRefs6.split('\n').filter(s => s.trim()).length} 张产品参考图。
                    上传后会跟 character_sheet 一起作为 reference image 传给 chatgpt-image，OpenAI 严格参考画。
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-sm font-medium mb-1 block">画幅</label>
                    <select
                      className="w-full border rounded px-2 py-2 text-sm bg-background"
                      value={aspect6}
                      onChange={e => setAspect6(e.target.value)}
                    >
                      <option value="9:16">9:16（抖音竖版）</option>
                      <option value="1:1">1:1（方版）</option>
                      <option value="16:9">16:9（横版）</option>
                      <option value="3:4">3:4（小红书）</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1 block">风格 hint（可空）</label>
                    <input
                      type="text"
                      className="w-full border rounded px-2 py-2 text-sm bg-background"
                      placeholder="如 photo-realistic, warm tone"
                      value={extraSuffix6}
                      onChange={e => setExtraSuffix6(e.target.value)}
                    />
                  </div>
                  <label className="flex items-center gap-2 text-xs cursor-pointer">
                    <input
                      type="checkbox"
                      checked={deidentifyFaces6}
                      onChange={e => setDeidentifyFaces6(e.target.checked)}
                    />
                    <span>去识别化（含人物的分镜自动加：局部遮挡 / 侧背角度 / 脸部虚焦 / 产品为主体），降低 step 7 首帧过审概率</span>
                  </label>
                </div>

                <div className="text-xs text-muted-foreground border-t pt-2 mt-2">
                  💡 历史脚本 scenes 为空？
                  <button
                    className="text-primary underline ml-1"
                    onClick={async () => {
                      try {
                        const res = await fetch('/api/omni/sku-pipeline/backfill-scenes', { method: 'POST' })
                        const json = await res.json()
                        if (json.success && json.data?.ok) {
                          alert(`回填完成：扫 ${json.data.scanned} 条、更新 ${json.data.scripts_updated} 条、解析 ${json.data.scenes_parsed_total} 段。\n刷新脚本列表重选。`)
                          if (script6Id) await selectScript6(script6Id)
                        } else {
                          alert(`回填失败：${json.data?.error || json.error}`)
                        }
                      } catch (e) {
                        alert(`回填异常：${String(e)}`)
                      }
                    }}
                  >
                    一键回填全库 scenes
                  </button>
                  （扫所有 video_* 脚本，按 markdown 分镜段重解析）
                </div>

                {error && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* 右：输出 grid */}
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle className="text-base">输出</CardTitle>
                <CardDescription className="text-xs">
                  {resp6?.result
                    ? `成功 ${resp6.result.success_count} / ${resp6.result.scenes_total}，失败 ${resp6.result.error_count}。每张图自动落 pipeline.assets（status=draft）。`
                    : 'left 输入完毕跑出 → 右侧 grid 显示。每张图卡可单独采纳/重跑/挂血缘。'}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {!resp6 && !running6 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    左侧选脚本 + 选段 → 点出图。
                  </div>
                )}
                {running6 && !resp6 && (
                  <div className="text-sm text-muted-foreground py-12 text-center">
                    <Loader2 className="w-6 h-6 mx-auto animate-spin mb-2" />
                    {selectedScenes6.size} 张分镜并发出图...
                  </div>
                )}
                {resp6 && !resp6.ok && (
                  <div className="text-sm text-red-500 p-2 border border-red-200 rounded bg-red-50">
                    Error: {resp6.error}
                    {resp6.hint && <div className="text-xs mt-1">{resp6.hint}</div>}
                  </div>
                )}
                {resp6?.result && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
                    {resp6.result.results.map(r => (
                      <div
                        key={r.scene_no}
                        className={`border rounded p-2 ${r.error ? 'border-red-300 bg-red-50/30' : 'border-emerald-200 bg-emerald-50/20'}`}
                      >
                        <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
                          <div className="flex items-center gap-1 flex-wrap">
                            <Badge variant="secondary" className="text-[10px]">第 {r.scene_no} 段</Badge>
                            {(r.characters_in_scene?.length || 0) > 0 && (
                              <Badge variant="outline" className="text-[10px]" title="本段角色 / face_refs 数">
                                👤 {r.characters_in_scene!.join('/')} ({r.face_refs_used?.length || 0})
                              </Badge>
                            )}
                            {r.product_appearance === true && (
                              <Badge variant="outline" className="text-[10px]" title="产品出场">
                                📦 ({r.product_refs_used?.length || 0})
                              </Badge>
                            )}
                          </div>
                          {r.asset_id && (
                            <span className="text-[10px] text-muted-foreground">
                              <code>{r.asset_id.slice(0, 8)}</code>
                            </span>
                          )}
                        </div>
                        {r.file_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={r.file_url}
                            alt={`scene ${r.scene_no}`}
                            className="w-full rounded border"
                            style={{ maxHeight: 360, objectFit: 'contain' }}
                          />
                        ) : (
                          <div className="text-xs text-red-500 p-3 border border-red-200 rounded bg-red-50/40">
                            ❌ {r.error}
                          </div>
                        )}
                        {r.prompt && (
                          <details className="mt-2 text-[11px]">
                            <summary className="cursor-pointer text-muted-foreground">prompt (omni 内部，带 character_sheet[] 占位)</summary>
                            <pre className="whitespace-pre-wrap bg-muted/40 p-2 rounded mt-1 text-[10px]">{r.prompt}</pre>
                          </details>
                        )}
                        {(() => {
                          // 故事板提示词（外部模型用）— 展开 character_sheet[] 占位 + 列出参考图 url
                          const scene = script6Detail?.scenes?.find(s => s.scene_no === r.scene_no)
                          const rawIp = scene?.image_prompt || ''
                          if (!rawIp) return null
                          const sheets = script6Detail?.character_sheets || []
                          const standalone = buildStandalonePrompt(rawIp, sheets)
                          const faceUrls = r.face_refs_used || []
                          const productUrls = r.product_refs_used || []
                          const refLines: string[] = []
                          faceUrls.forEach((u, i) => refLines.push(`- 人脸参考 ${i + 1}: ${u}`))
                          productUrls.forEach((u, i) => refLines.push(`- 产品参考 ${i + 1}: ${u}`))
                          const fullText = refLines.length > 0
                            ? `${standalone}\n\nReference images (use as visual reference, strictly preserve the people and products shown):\n${refLines.join('\n')}`
                            : standalone
                          return (
                            <details className="mt-2 text-[11px]">
                              <summary className="cursor-pointer text-primary font-medium">
                                📋 故事板提示词（外部模型用 · 含人脸/产品描述+参考图 url）
                              </summary>
                              <div className="mt-1 space-y-2">
                                <textarea
                                  readOnly
                                  value={fullText}
                                  rows={Math.min(14, fullText.split('\n').length + 2)}
                                  className="w-full text-[10px] font-mono p-2 border rounded bg-muted/30"
                                  onClick={e => (e.target as HTMLTextAreaElement).select()}
                                />
                                {(faceUrls.length > 0 || productUrls.length > 0) && (
                                  <div className="space-y-1">
                                    <div className="text-[10px] text-muted-foreground">参考图（点缩略图打开原图，方便下载贴外部模型）：</div>
                                    <div className="flex flex-wrap gap-2">
                                      {faceUrls.map((u, i) => (
                                        <a key={`f${i}`} href={u} target="_blank" rel="noreferrer" title={`人脸 ${i + 1}`}>
                                          {/* eslint-disable-next-line @next/next/no-img-element */}
                                          <img src={u} alt={`face${i}`} className="w-14 h-14 object-cover rounded border" />
                                        </a>
                                      ))}
                                      {productUrls.map((u, i) => (
                                        <a key={`p${i}`} href={u} target="_blank" rel="noreferrer" title={`产品 ${i + 1}`}>
                                          {/* eslint-disable-next-line @next/next/no-img-element */}
                                          <img src={u} alt={`product${i}`} className="w-14 h-14 object-cover rounded border" />
                                        </a>
                                      ))}
                                    </div>
                                  </div>
                                )}
                                <Button
                                  size="sm"
                                  variant="default"
                                  className="text-xs h-7"
                                  onClick={() => {
                                    navigator.clipboard.writeText(fullText)
                                  }}
                                >
                                  📋 复制全文（prompt + 参考图 url）
                                </Button>
                              </div>
                            </details>
                          )
                        })()}
                        <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={running6}
                            onClick={() => runStep6Storyboard([r.scene_no])}
                            className="text-xs h-7"
                          >
                            {running6 ? <Loader2 className="w-3 h-3 animate-spin" /> : '🔄 重跑'}
                          </Button>
                          {r.asset_id && (() => {
                            const isAdopted = adoptedAssetIds.has(r.asset_id!)
                            const isAdoptingThis = adoptingAsset === r.asset_id
                            return (
                              <Button
                                size="sm"
                                variant={isAdopted ? 'default' : 'outline'}
                                disabled={isAdoptingThis || isAdopted}
                                onClick={() => adoptAsset(r.asset_id!)}
                                className="text-xs h-7"
                                title={isAdopted ? '已绑入血缘 — 下游可挂' : '审完 OK 后点这里：标 adopted 进血缘'}
                              >
                                {isAdoptingThis
                                  ? <Loader2 className="w-3 h-3 animate-spin" />
                                  : isAdopted
                                    ? '✅ 已绑'
                                    : '✓ 绑血缘'}
                              </Button>
                            )
                          })()}
                          {r.file_url && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                const fname = `${resp6?.result?.sku_id || 'sku'}_${resp6?.result?.kind || 'asset'}_scene${r.scene_no}.png`
                                downloadAsset(r.file_url!, fname)
                              }}
                              className="text-xs h-7"
                            >
                              ⬇ 下载
                            </Button>
                          )}
                          {r.file_url && (
                            <a
                              href={r.file_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs text-primary hover:underline ml-auto"
                            >
                              原图 ↗
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {resp6?.trace && (
                  <div className="mt-4 text-[11px] text-muted-foreground border-t pt-2">
                    {resp6.trace.model_provider}/{resp6.trace.model} · {resp6.trace.cost_estimate}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ============== STEP 7.1：i2v 视频段生成（分镜图→视频） ============== */}
        <TabsContent value="step7i" className="mt-0 flex-1 min-w-0">
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Film className="w-4 h-4" /> Step 7.1 · i2v 输入
                </CardTitle>
                <CardDescription>
                  分镜图（step 6）→ first_frame → Veo 3.1 按图运镜出每段视频。
                  需先跑 step 6；每段约 60-120s，并发跑总时间约等于单段。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                {/* step 7 独立脚本选择器（共享 script6Id / scriptsForSku6 / selectScript6） */}
                <div className="flex items-center justify-between gap-2">
                  <label className="text-sm font-medium">脚本（kind 须为 video_*）</label>
                  <Button size="sm" variant="outline" onClick={loadScriptsForStep6} disabled={!skuId || loadingScripts6}>
                    {loadingScripts6 ? <Loader2 className="w-3 h-3 animate-spin" /> : (scriptsForSku6 !== null ? '刷新' : '加载脚本')}
                  </Button>
                </div>
                {scriptsForSku6 === null && (
                  <div className="text-xs text-muted-foreground p-3 border border-dashed rounded">
                    点上方"加载脚本"拉这个 SKU 跑过的所有脚本（按时间倒序）。或到 <strong>血缘图</strong> tab 点 video_* 脚本节点直接跳到这里。
                  </div>
                )}
                {scriptsForSku6 && scriptsForSku6.length === 0 && (
                  <div className="text-xs text-muted-foreground p-3 border border-dashed rounded">
                    这个 SKU 还没跑过 step 5 创意脚本。
                  </div>
                )}
                {scriptsForSku6 && scriptsForSku6.length > 0 && (() => {
                  const videoScripts = scriptsForSku6.filter(s => s.kind.startsWith('video_'))
                  return (
                    <>
                      <select
                        className="w-full border rounded px-2 py-2 text-sm bg-background"
                        value={script6Id}
                        onChange={e => selectScript6(e.target.value)}
                      >
                        <option value="">— 请选择脚本 —</option>
                        {videoScripts.map(s => (
                          <option key={s.id} value={s.id}>
                            [{s.status === 'adopted' ? '✅' : '·'}] {s.kind} v{s.version} · {s.id.slice(0, 8)}
                          </option>
                        ))}
                      </select>
                      {videoScripts.length === 0 && (
                        <div className="text-xs text-orange-500 -mt-1">
                          ⚠ 此 SKU 跑过 {scriptsForSku6.length} 个脚本但都是非 video 类型（如 graphic_harvest / product_main_image），step 7 只能跑 video_*。先到 step 5 出一个 video_soft_ad / video_planting / video_harvest 脚本。
                        </div>
                      )}
                    </>
                  )
                })()}

                {loadingScript6Detail && (
                  <div className="text-xs text-muted-foreground">
                    <Loader2 className="w-3 h-3 inline animate-spin mr-1" /> 拉脚本详情...
                  </div>
                )}
                {script6Id && script6Detail && !script6Detail.kind.startsWith('video_') && (
                  <div className="border border-dashed border-orange-300 dark:border-orange-700 rounded p-3 text-xs bg-orange-50/30 dark:bg-orange-950/10">
                    ⚠ 当前脚本 kind=<code>{script6Detail.kind}</code>，不是视频脚本。
                    上面下拉换个 <code>video_*</code> 脚本（soft_ad / planting / harvest）。
                  </div>
                )}
                {script6Detail && script6Detail.kind.startsWith('video_') && (
                  <div className="border rounded p-2 bg-muted/30 text-xs space-y-1">
                    <div>
                      <Badge variant="secondary" className="text-[10px]">{script6Detail.kind}</Badge>
                      <Badge variant="outline" className="text-[10px] ml-1">第 {script6Detail.version} 版</Badge>
                      <Badge
                        variant={script6Detail.status === 'adopted' ? 'default' : 'outline'}
                        className="text-[10px] ml-1"
                      >
                        {script6Detail.status === 'adopted' ? '已采纳' : '草稿'}
                      </Badge>
                    </div>
                    <div className="text-muted-foreground">
                      共 <strong>{script6Detail.scenes?.length || 0}</strong> 段分镜
                      {(script6Detail.character_sheets?.length || 0) > 0 && (
                        <span> · <strong>{script6Detail.character_sheets!.length}</strong> 个固定角色</span>
                      )}
                    </div>
                  </div>
                )}

                {/* 拉已出分镜图列表（哪几段能跑视频） */}
                {script6Id && script6Detail?.kind?.startsWith('video_') && (
                  <div className="border rounded p-3 space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <label className="text-sm font-medium">已出分镜图（step 6）</label>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={loadImageAssets7}
                        disabled={loadingImageAssets7}
                      >
                        {loadingImageAssets7 ? <Loader2 className="w-3 h-3 animate-spin" /> : '刷新'}
                      </Button>
                    </div>
                    {imageAssets7 === null && (
                      <div className="text-xs text-muted-foreground">点刷新拉这个脚本已落库的分镜图（asset_type=image）。</div>
                    )}
                    {imageAssets7 && imageAssets7.length === 0 && (
                      <div className="text-xs text-orange-500">
                        ⚠ 还没跑分镜图。先到 step 6 跑 <code>generate_storyboard_images</code> 再回来跑视频。
                      </div>
                    )}
                    {imageAssets7 && imageAssets7.length > 0 && (
                      <div className="text-xs text-muted-foreground space-y-1">
                        <div>已出 <strong className="text-foreground">{imageAssets7.length}</strong> 张分镜图（按 scene_no 自动当 first_frame）。</div>
                        {script6Detail && (script6Detail.scenes?.length || 0) > imageAssets7.length && (
                          <div className="text-orange-500">
                            ⚠ 脚本有 {script6Detail.scenes!.length} 段但只有 {imageAssets7.length} 张图；
                            缺图的段会返 missing_storyboard_images，先到 step 6 补齐。
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* 主操作按钮（置顶） */}
                {script6Id && imageAssets7 && imageAssets7.length > 0 && (
                  <div className="border-2 border-primary/50 rounded-lg p-3 bg-primary/5 space-y-2">
                    <div className="flex items-center justify-between gap-2 flex-wrap">
                      <div className="text-sm font-medium">
                        ▶ 出视频：已选 <strong className="text-primary">{selectedScenes7.size}</strong> / {imageAssets7.length} 段
                      </div>
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          onClick={() => {
                            const first = imageAssets7
                              .map(a => a.scene_no)
                              .filter((n): n is number => typeof n === 'number')[0]
                            if (typeof first === 'number') setSelectedScenes7(new Set([first]))
                          }}
                          title="只跑第 1 段（先小范围测，省钱）"
                        >
                          只第 1 段
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          onClick={() => {
                            const all = imageAssets7
                              .map(a => a.scene_no)
                              .filter((n): n is number => typeof n === 'number')
                            setSelectedScenes7(new Set(all))
                          }}
                        >
                          全选 {imageAssets7.length}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          onClick={() => setSelectedScenes7(new Set())}
                        >
                          全清
                        </Button>
                      </div>
                    </div>
                    <Button
                      onClick={() => runStep7iVideo(false)}
                      disabled={running7i || selectedScenes7.size === 0}
                      className="w-full text-base h-11"
                      size="lg"
                    >
                      {running7i ? (
                        <><Loader2 className="w-5 h-5 mr-2 animate-spin" /> 跑中（{selectedScenes7.size} 段并发，~{selectedScenes7.size * 1.5} min）</>
                      ) : selectedScenes7.size === 0 ? (
                        '先选要跑的段'
                      ) : (
                        `★ i2v 出 ${selectedScenes7.size} 段视频（分镜图→Veo 3.1）`
                      )}
                    </Button>
                    <Button
                      onClick={() => runStep7iVideo(true)}
                      disabled={running7i || selectedScenes7.size === 0}
                      className="w-full h-9 text-xs"
                      variant="outline"
                    >
                      🔍 仅预览提示词（零费用，调 prompt 用）
                    </Button>
                    <div className="text-[11px] text-muted-foreground">
                      分镜图自动当 first_frame · 约 60-120s/段 · Veo 3.1 via GEMINI_API_KEY
                    </div>
                  </div>
                )}

                {/* 段选清单 */}
                {imageAssets7 && imageAssets7.length > 0 && (
                  <details className="text-sm" open>
                    <summary className="cursor-pointer text-sm font-medium text-muted-foreground">
                      ▼ 多选段（当前选 {selectedScenes7.size} / {imageAssets7.length}）
                    </summary>
                    <div className="grid grid-cols-2 gap-2 mt-2">
                      {imageAssets7.map(a => {
                        if (typeof a.scene_no !== 'number') return null
                        const sn = a.scene_no
                        const checked = selectedScenes7.has(sn)
                        const scene = script6Detail?.scenes?.find(s => s.scene_no === sn)
                        return (
                          <label
                            key={a.id}
                            className={`border rounded p-2 cursor-pointer transition flex gap-2 ${
                              checked ? 'border-primary bg-primary/5' : 'border-muted hover:border-muted-foreground/50'
                            }`}
                          >
                            <input
                              type="checkbox"
                              className="mt-0.5"
                              checked={checked}
                              onChange={() => {
                                setSelectedScenes7(prev => {
                                  const next = new Set(prev)
                                  if (next.has(sn)) next.delete(sn)
                                  else next.add(sn)
                                  return next
                                })
                              }}
                            />
                            {a.file_url && (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={a.file_url}
                                alt={`scene ${sn}`}
                                className="w-12 h-12 object-cover rounded border shrink-0"
                              />
                            )}
                            <div className="flex-1 min-w-0">
                              <div className="text-xs font-medium">第 {sn} 段</div>
                              <div className="text-[10px] text-muted-foreground truncate">
                                {scene?.name || scene?.visual?.slice(0, 40) || '—'}
                              </div>
                              {scene && (
                                <div className="flex flex-wrap gap-1 mt-0.5">
                                  {(scene.characters_in_scene?.length || 0) > 0 && (
                                    <Badge variant="outline" className="text-[9px] px-1 py-0">
                                      👤 {scene.characters_in_scene!.join('/')}
                                    </Badge>
                                  )}
                                  {scene.product_appearance && (
                                    <Badge variant="outline" className="text-[9px] px-1 py-0">📦</Badge>
                                  )}
                                </div>
                              )}
                            </div>
                          </label>
                        )
                      })}
                    </div>
                  </details>
                )}

                {/* i2v 参数 */}
                {script6Id && (
                  <details className="text-sm" open>
                    <summary className="cursor-pointer text-sm font-medium text-muted-foreground">▼ 视频参数</summary>
                    <div className="mt-2 space-y-3">
                      <div>
                        <label className="text-xs font-medium">画幅（Veo 3.1 仅支持竖屏 / 横屏）</label>
                        <select className="w-full border rounded px-2 py-1.5 text-sm bg-background mt-1" value={aspect7i} onChange={e => setAspect7i(e.target.value)}>
                          {['9:16', '16:9'].map(r => <option key={r} value={r}>{r}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="text-xs font-medium">回退默认时长（秒）</label>
                        <div className="text-[10px] text-muted-foreground mb-1">优先 scene.time_range；无则用此值兜底。Veo 3.1 仅支持 4 / 6 / 8s，其他值自动 clamp。</div>
                        <select className="w-full border rounded px-2 py-1.5 text-sm bg-background" value={duration7i} onChange={e => setDuration7i(Number(e.target.value))}>
                          {[4, 6, 8].map(d => <option key={d} value={d}>{d}s{d === 8 ? ' (默认)' : ''}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="text-xs font-medium">额外 prompt 后缀（运镜 hint，全段共用）</label>
                        <Textarea value={extraSuffix7i} onChange={e => setExtraSuffix7i(e.target.value)} rows={2} className="text-xs mt-1" placeholder="如：slow handheld motion, warm cinematic lighting" />
                      </div>
                    </div>
                  </details>
                )}

              </CardContent>
            </Card>

            {/* 右：输出 grid */}
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Film className="w-4 h-4" /> i2v 输出（视频段）
                </CardTitle>
                <CardDescription>
                  每段单独 video element；点 ✓ 绑血缘 / ⬇ 下载 / 🔄 单段重跑。
                </CardDescription>
              </CardHeader>
              <CardContent>
                {!resp7i && (
                  <div className="text-sm text-muted-foreground p-4 border border-dashed rounded">
                    左侧选段 + 跑后这里显示视频 grid。
                  </div>
                )}
                {resp7i?.error && (
                  <div className="text-sm p-3 border border-red-300 rounded bg-red-50 dark:bg-red-950/20 space-y-1">
                    <div className="text-red-600 font-medium">❌ {resp7i.error}</div>
                    {resp7i.hint && <div className="text-xs text-muted-foreground">{resp7i.hint}</div>}
                    {resp7i.scene_nums_missing_image && (
                      <div className="text-xs">
                        缺图的段：{resp7i.scene_nums_missing_image.join(', ')}（先到 step 6 跑这几段）
                      </div>
                    )}
                  </div>
                )}
                {resp7i?.result && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm">
                      <Badge variant="default">
                        ✓ {resp7i.result.success_count} / {resp7i.result.scenes_total} 段成功
                      </Badge>
                      {resp7i.result.error_count > 0 && (
                        <Badge variant="destructive">
                          ❌ {resp7i.result.error_count} 段失败
                        </Badge>
                      )}
                    </div>

                    {resp7i.result.success_count > 0 && (() => {
                      const downloadableVideos = resp7i.result!.results
                        .filter(r => r.video_url)
                        .map(r => ({
                          url: r.video_url!,
                          filename: `${resp7i?.result?.sku_id || 'sku'}_${resp7i?.result?.kind || 'video'}_i2v_scene${r.scene_no}.mp4`,
                        }))
                      if (downloadableVideos.length === 0) return null
                      const downloadAll = () => {
                        downloadableVideos.forEach((v, i) => {
                          setTimeout(() => downloadAsset(v.url, v.filename), i * 400)
                        })
                      }
                      return (
                        <div className="border rounded-lg p-3 space-y-2">
                          <div className="text-xs text-muted-foreground">
                            视频已落盘，可随时下载。浏览器可能弹"允许多文件下载"提示，点允许。
                          </div>
                          <Button
                            size="lg"
                            variant="default"
                            className="w-full h-10 text-sm"
                            onClick={downloadAll}
                          >
                            ⬇ 一键下载全部 {downloadableVideos.length} 段视频
                          </Button>
                        </div>
                      )
                    })()}

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {resp7i.result.results.map(r => (
                        <div key={r.scene_no} className="border rounded p-2 space-y-2 bg-card">
                          <div className="flex items-center justify-between gap-1 flex-wrap">
                            <div className="text-sm font-medium">
                              第 {r.scene_no} 段 · {r.duration_s}s
                              {r.scene_time_range && (
                                <span className="text-[10px] text-muted-foreground ml-1">[{r.scene_time_range}]</span>
                              )}
                            </div>
                            <div className="flex flex-wrap gap-1">
                              {(r.characters_in_scene?.length || 0) > 0 && (
                                <Badge variant="outline" className="text-[10px]">
                                  👤 {r.characters_in_scene!.join('/')} ({(r.face_refs_used?.length || 0)})
                                </Badge>
                              )}
                              {(r.product_refs_used?.length || 0) > 0 && (
                                <Badge variant="outline" className="text-[10px]">
                                  📦 ({r.product_refs_used!.length})
                                </Badge>
                              )}
                              {r.refs_blocked_reason && (
                                <Badge variant="secondary" className="text-[10px]" title={r.refs_blocked_reason}>
                                  ⓘ refs 已绕开
                                </Badge>
                              )}
                            </div>
                          </div>
                          {r.error ? (
                            <div className="text-xs p-2 border border-red-300 rounded bg-red-50 dark:bg-red-950/20 text-red-700 dark:text-red-300 space-y-1">
                              <div className="font-medium">{r.error}</div>
                              {r.hint && <div className="text-[11px]">💡 {r.hint}</div>}
                              {r.error_detail && (
                                <details className="text-[10px]">
                                  <summary className="cursor-pointer opacity-70">▼ 原始 detail</summary>
                                  <pre className="mt-1 whitespace-pre-wrap break-words">{r.error_detail}</pre>
                                </details>
                              )}
                            </div>
                          ) : r.video_url ? (
                            <video
                              src={r.video_url}
                              controls
                              className="w-full rounded border"
                              preload="metadata"
                            />
                          ) : r.dry_run ? (
                            <div className="text-xs p-2 border border-blue-300 rounded bg-blue-50 dark:bg-blue-950/20 text-blue-700 dark:text-blue-300">
                              🔍 预览模式（干跑，未调 Veo）· 仅展示 prompt 用于调试 · 时长 {r.duration_s || '?'}s
                            </div>
                          ) : (
                            <div className="text-xs text-muted-foreground italic">无视频 url</div>
                          )}
                          {r.prompt && (
                            <details className="text-xs" open={!!r.dry_run}>
                              <summary className="cursor-pointer text-muted-foreground">
                                ▼ 实际喂 Veo 3.1 的 prompt（i2v 模式）
                              </summary>
                              <pre className="mt-1 p-2 bg-muted/50 rounded whitespace-pre-wrap text-[10px]">{r.prompt}</pre>
                            </details>
                          )}
                          {(() => {
                            // 故事板提示词（外部视频模型用：即梦/可灵/Sora/Veo 等）
                            const scene = script6Detail?.scenes?.find(s => s.scene_no === r.scene_no)
                            const rawIp = scene?.image_prompt || ''
                            if (!rawIp) return null
                            const sheets = script6Detail?.character_sheets || []
                            const standalone = buildStandalonePrompt(rawIp, sheets)
                            // step 7 face_refs 可能被 i2v 互斥清空，回退 step 6 出图同 scene 拿
                            let faceUrls = r.face_refs_used || []
                            const productUrls = r.product_refs_used || []
                            if (faceUrls.length === 0 && r.refs_blocked_reason) {
                              // 回查 step 6 此段出图（如有跑过）拿到 face/product refs（中间桥接）
                              const sb6 = resp6?.result?.results?.find(x => x.scene_no === r.scene_no)
                              if (sb6) {
                                faceUrls = sb6.face_refs_used || []
                              }
                            }
                            const refLines: string[] = []
                            if (r.first_frame_used) refLines.push(`- 起手帧 (step 6 分镜图): ${r.first_frame_used}`)
                            faceUrls.forEach((u, i) => refLines.push(`- 人脸参考 ${i + 1}: ${u}`))
                            productUrls.forEach((u, i) => refLines.push(`- 产品参考 ${i + 1}: ${u}`))
                            const durationHint = r.duration_s ? `\n\nVideo duration: ${r.duration_s}s.` : ''
                            const fullText = refLines.length > 0
                              ? `${standalone}${durationHint}\n\nReference media:\n${refLines.join('\n')}`
                              : standalone + durationHint
                            return (
                              <details className="text-xs">
                                <summary className="cursor-pointer text-primary font-medium">
                                  📋 故事板提示词（外部视频模型用 · 含人脸/产品+起手帧 url）
                                </summary>
                                <div className="mt-1 space-y-2">
                                  <textarea
                                    readOnly
                                    value={fullText}
                                    rows={Math.min(14, fullText.split('\n').length + 2)}
                                    className="w-full text-[10px] font-mono p-2 border rounded bg-muted/30"
                                    onClick={e => (e.target as HTMLTextAreaElement).select()}
                                  />
                                  {(faceUrls.length > 0 || productUrls.length > 0 || r.first_frame_used) && (
                                    <div className="space-y-1">
                                      <div className="text-[10px] text-muted-foreground">参考媒体（点缩略图打开原图）：</div>
                                      <div className="flex flex-wrap gap-2">
                                        {r.first_frame_used && (
                                          <a href={r.first_frame_used} target="_blank" rel="noreferrer" title="起手帧（step 6 分镜图）">
                                            {/* eslint-disable-next-line @next/next/no-img-element */}
                                            <img src={r.first_frame_used} alt="first_frame" className="w-14 h-14 object-cover rounded border border-blue-400" />
                                          </a>
                                        )}
                                        {faceUrls.map((u, i) => (
                                          <a key={`f${i}`} href={u} target="_blank" rel="noreferrer" title={`人脸 ${i + 1}`}>
                                            {/* eslint-disable-next-line @next/next/no-img-element */}
                                            <img src={u} alt={`face${i}`} className="w-14 h-14 object-cover rounded border" />
                                          </a>
                                        ))}
                                        {productUrls.map((u, i) => (
                                          <a key={`p${i}`} href={u} target="_blank" rel="noreferrer" title={`产品 ${i + 1}`}>
                                            {/* eslint-disable-next-line @next/next/no-img-element */}
                                            <img src={u} alt={`product${i}`} className="w-14 h-14 object-cover rounded border" />
                                          </a>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                  <Button
                                    size="sm"
                                    variant="default"
                                    className="text-xs h-7"
                                    onClick={() => navigator.clipboard.writeText(fullText)}
                                  >
                                    📋 复制全文（prompt + 媒体 url）
                                  </Button>
                                </div>
                              </details>
                            )
                          })()}
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={running7i}
                              onClick={() => rerunOneScene7i(r.scene_no)}
                              className="text-[10px] h-7 px-2"
                            >
                              🔄 重跑此段
                            </Button>
                            {r.asset_id && (
                              <Button
                                size="sm"
                                variant={adoptedAssetIds.has(r.asset_id) ? 'default' : 'outline'}
                                disabled={!r.asset_id || adoptingAsset === r.asset_id}
                                onClick={() => adoptAsset(r.asset_id!)}
                                className="text-[10px] h-7 px-2"
                              >
                                {adoptingAsset === r.asset_id ? (
                                  <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 采纳中</>
                                ) : adoptedAssetIds.has(r.asset_id) ? (
                                  '✅ 已绑'
                                ) : (
                                  '✓ 绑血缘'
                                )}
                              </Button>
                            )}
                            {r.video_url && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  const fname = `${resp7i?.result?.sku_id || 'sku'}_${resp7i?.result?.kind || 'video'}_i2v_scene${r.scene_no}.mp4`
                                  downloadAsset(r.video_url!, fname)
                                }}
                                className="text-[10px] h-7 px-2"
                              >
                                <Download className="w-3 h-3 mr-1" /> 下载
                              </Button>
                            )}
                            {r.video_url && (
                              <a
                                href={r.video_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[10px] text-blue-600 hover:underline px-1"
                              >
                                原视频 ↗
                              </a>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {resp7i?.trace && (
                  <div className="mt-4 text-[11px] text-muted-foreground border-t pt-2">
                    {resp7i.trace.model_provider}/{resp7i.trace.model} · {resp7i.trace.cost_estimate}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ============== STEP 7.2：t2v 视频段生成（文字→视频） ============== */}
        <TabsContent value="step7t" className="mt-0 flex-1 min-w-0">
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
            {/* 左：脚本选择 + 角色锚点 + 参数 + 主操作 */}
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Sparkles className="w-4 h-4" /> Step 7.2 · t2v 输入
                </CardTitle>
                <CardDescription>
                  跳过 step 6 分镜图，Veo 3.1 纯按文字生成画面。
                  character_anchor 前置注入每段 prompt，维持跨镜人物一致性。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {SkuPicker}

                {/* 脚本选择（共享 script6Id） */}
                <div className="flex items-center justify-between gap-2">
                  <label className="text-sm font-medium">脚本（video_* kind）</label>
                  <Button size="sm" variant="outline" onClick={loadScriptsForStep6} disabled={!skuId || loadingScripts6}>
                    {loadingScripts6 ? <Loader2 className="w-3 h-3 animate-spin" /> : (scriptsForSku6 !== null ? '刷新' : '加载脚本')}
                  </Button>
                </div>
                {scriptsForSku6 === null && (
                  <div className="text-xs text-muted-foreground p-3 border border-dashed rounded">
                    点"加载脚本"拉这个 SKU 跑过的所有脚本。
                  </div>
                )}
                {scriptsForSku6 && scriptsForSku6.length > 0 && (() => {
                  const videoScripts = scriptsForSku6.filter(s => s.kind.startsWith('video_'))
                  return (
                    <select
                      className="w-full border rounded px-2 py-2 text-sm bg-background"
                      value={script6Id}
                      onChange={e => selectScript6(e.target.value)}
                    >
                      <option value="">— 请选择脚本 —</option>
                      {videoScripts.map(s => (
                        <option key={s.id} value={s.id}>
                          [{s.status === 'adopted' ? '✅' : '·'}] {s.kind} v{s.version} · {s.id.slice(0, 8)}
                        </option>
                      ))}
                    </select>
                  )
                })()}

                {script6Detail && script6Detail.kind.startsWith('video_') && (
                  <div className="border rounded p-2 bg-muted/30 text-xs space-y-1">
                    <div>
                      <Badge variant="secondary" className="text-[10px]">{script6Detail.kind}</Badge>
                      <Badge variant="outline" className="text-[10px] ml-1">v{script6Detail.version}</Badge>
                    </div>
                    <div className="text-muted-foreground">
                      共 <strong>{script6Detail.scenes?.length || 0}</strong> 段分镜
                    </div>
                  </div>
                )}

                {/* 角色锚点（t2v 核心） */}
                {script6Id && (
                  <div className="border-2 border-primary/30 rounded-lg p-3 space-y-2 bg-primary/5">
                    <div className="flex items-center justify-between">
                      <label className="text-sm font-medium">角色 + 场景锚点 <span className="text-red-500">*</span></label>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs"
                        onClick={generateAnchor7t}
                        disabled={!script6Id || generatingAnchor7t}
                      >
                        {generatingAnchor7t ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" />生成中</> : '✨ 一键生成'}
                      </Button>
                    </div>
                    <Textarea
                      value={characterAnchor7t}
                      onChange={e => setCharacterAnchor7t(e.target.value)}
                      rows={4}
                      className="text-xs"
                      placeholder="如：40岁日本主妇，齐肩黑发，米色棉麻围裙，温柔笑容，温馨木质厨房，暖黄吊灯，柔和胶片色调"
                    />
                    <p className="text-[11px] text-muted-foreground">
                      根据血缘链路（人群画像+卖点矩阵+脚本场景）自动生成；可手动改。
                      前置注入每段 prompt 开头，维持跨镜角色一致性。
                    </p>
                  </div>
                )}

                {/* t2v 段选清单（从 script scenes 拉，不依赖分镜图） */}
                {script6Detail?.scenes && script6Detail.scenes.length > 0 && (
                  <details className="text-sm" open>
                    <summary className="cursor-pointer text-sm font-medium text-muted-foreground">
                      ▼ 选段（当前选 {selectedScenes7t.size} / {script6Detail.scenes.length}）
                    </summary>
                    <div className="flex gap-1 mt-2 mb-2">
                      <Button size="sm" variant="outline" className="h-6 text-xs"
                        onClick={() => {
                          const first = script6Detail.scenes![0]?.scene_no
                          if (typeof first === 'number') setSelectedScenes7t(new Set([first]))
                        }}>只第 1 段</Button>
                      <Button size="sm" variant="outline" className="h-6 text-xs"
                        onClick={() => {
                          const all = script6Detail.scenes!.map((s: { scene_no?: number }) => s.scene_no).filter((n): n is number => typeof n === 'number')
                          setSelectedScenes7t(new Set(all))
                        }}>全选</Button>
                      <Button size="sm" variant="outline" className="h-6 text-xs"
                        onClick={() => setSelectedScenes7t(new Set())}>全清</Button>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      {script6Detail.scenes.map((scene: { scene_no?: number; name?: string; visual?: string; characters_in_scene?: string[]; product_appearance?: boolean; time_range?: string }) => {
                        const sn = scene.scene_no
                        if (typeof sn !== 'number') return null
                        const checked = selectedScenes7t.has(sn)
                        return (
                          <label
                            key={sn}
                            className={`border rounded p-2 cursor-pointer transition flex gap-2 ${
                              checked ? 'border-primary bg-primary/5' : 'border-muted hover:border-muted-foreground/50'
                            }`}
                          >
                            <input
                              type="checkbox"
                              className="mt-0.5"
                              checked={checked}
                              onChange={() => {
                                setSelectedScenes7t(prev => {
                                  const next = new Set(prev)
                                  if (next.has(sn)) next.delete(sn)
                                  else next.add(sn)
                                  return next
                                })
                              }}
                            />
                            <div className="flex-1 min-w-0">
                              <div className="text-xs font-medium">第 {sn} 段 {scene.time_range && <span className="text-muted-foreground text-[10px]">[{scene.time_range}]</span>}</div>
                              <div className="text-[10px] text-muted-foreground truncate">
                                {scene.name || scene.visual?.slice(0, 50) || '—'}
                              </div>
                              <div className="flex flex-wrap gap-1 mt-0.5">
                                {(scene.characters_in_scene?.length || 0) > 0 && (
                                  <Badge variant="outline" className="text-[9px] px-1 py-0">
                                    👤 {scene.characters_in_scene!.join('/')}
                                  </Badge>
                                )}
                                {scene.product_appearance && (
                                  <Badge variant="outline" className="text-[9px] px-1 py-0">📦</Badge>
                                )}
                              </div>
                            </div>
                          </label>
                        )
                      })}
                    </div>
                  </details>
                )}

                {/* t2v 主操作按钮 */}
                {script6Id && script6Detail?.kind?.startsWith('video_') && (
                  <div className="border-2 border-primary/50 rounded-lg p-3 bg-primary/5 space-y-2">
                    <div className="text-sm font-medium">
                      ▶ t2v 出视频：已选 <strong className="text-primary">{selectedScenes7t.size}</strong> / {script6Detail.scenes?.length || 0} 段
                    </div>
                    <Button
                      onClick={() => runStep7tVideo(false)}
                      disabled={running7t || selectedScenes7t.size === 0}
                      className="w-full text-base h-11"
                      size="lg"
                    >
                      {running7t ? (
                        <><Loader2 className="w-5 h-5 mr-2 animate-spin" /> 跑中（{selectedScenes7t.size} 段并发，~{selectedScenes7t.size * 1.5} min）</>
                      ) : selectedScenes7t.size === 0 ? (
                        '先选要跑的段'
                      ) : (
                        `★ t2v 出 ${selectedScenes7t.size} 段视频（Veo 3.1 纯文字生成）`
                      )}
                    </Button>
                    <Button
                      onClick={() => runStep7tVideo(true)}
                      disabled={running7t || selectedScenes7t.size === 0}
                      className="w-full h-9 text-xs"
                      variant="outline"
                    >
                      🔍 仅预览提示词（零费用，调 prompt 用）
                    </Button>
                    <div className="text-[11px] text-muted-foreground">
                      无需 step 6 分镜图 · character_anchor 锁跨镜角色 · 约 60-120s/段
                    </div>
                  </div>
                )}

                {/* t2v 参数 */}
                {script6Id && (
                  <details className="text-sm">
                    <summary className="cursor-pointer text-sm font-medium text-muted-foreground">▼ 视频参数</summary>
                    <div className="mt-2 space-y-3">
                      <div>
                        <label className="text-xs font-medium">画幅（Veo 3.1 仅支持竖屏 / 横屏）</label>
                        <select className="w-full border rounded px-2 py-1.5 text-sm bg-background mt-1" value={aspect7t} onChange={e => setAspect7t(e.target.value)}>
                          {['9:16', '16:9'].map(r => <option key={r} value={r}>{r}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="text-xs font-medium">回退默认时长（秒）</label>
                        <div className="text-[10px] text-muted-foreground mb-1">优先 scene.time_range；无则用此值兜底。Veo 3.1 仅支持 4 / 6 / 8s，其他值自动 clamp。</div>
                        <select className="w-full border rounded px-2 py-1.5 text-sm bg-background" value={duration7t} onChange={e => setDuration7t(Number(e.target.value))}>
                          {[4, 6, 8].map(d => <option key={d} value={d}>{d}s{d === 8 ? ' (默认)' : ''}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="text-xs font-medium">额外 prompt 后缀（全段共用）</label>
                        <Textarea value={extraSuffix7t} onChange={e => setExtraSuffix7t(e.target.value)} rows={2} className="text-xs mt-1" placeholder="如：slow handheld motion, warm cinematic tone" />
                      </div>
                    </div>
                  </details>
                )}
              </CardContent>
            </Card>

            {/* 右：t2v 输出 */}
            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <Sparkles className="w-4 h-4" /> t2v 输出（视频段）
                </CardTitle>
                <CardDescription>
                  每段单独 video element；点 ✓ 绑血缘 / ⬇ 下载 / 🔄 单段重跑。
                </CardDescription>
              </CardHeader>
              <CardContent>
                {!resp7t && (
                  <div className="text-sm text-muted-foreground p-4 border border-dashed rounded">
                    左侧填角色锚点 → 选段 → 跑后这里显示视频 grid。
                  </div>
                )}
                {resp7t?.error && (
                  <div className="text-sm p-3 border border-red-300 rounded bg-red-50 dark:bg-red-950/20 space-y-1">
                    <div className="text-red-600 font-medium">❌ {resp7t.error}</div>
                    {resp7t.hint && <div className="text-xs text-muted-foreground">💡 {resp7t.hint}</div>}
                  </div>
                )}
                {resp7t?.result && (
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm">
                      <Badge variant="default">
                        ✓ {resp7t.result.success_count} / {resp7t.result.scenes_total} 段成功
                      </Badge>
                      {resp7t.result.error_count > 0 && (
                        <Badge variant="destructive">
                          ❌ {resp7t.result.error_count} 段失败
                        </Badge>
                      )}
                    </div>

                    {resp7t.result.success_count > 0 && (() => {
                      const vids = resp7t.result!.results.filter(r => r.video_url).map(r => ({
                        url: r.video_url!,
                        filename: `${resp7t?.result?.sku_id || 'sku'}_${resp7t?.result?.kind || 'video'}_t2v_scene${r.scene_no}.mp4`,
                      }))
                      if (vids.length === 0) return null
                      return (
                        <div className="border rounded-lg p-3 space-y-2">
                          <div className="text-xs text-muted-foreground">
                            视频已落盘，可随时下载。浏览器可能弹"允许多文件下载"提示，点允许。
                          </div>
                          <Button size="lg" variant="default" className="w-full h-10 text-sm"
                            onClick={() => vids.forEach((v, i) => setTimeout(() => downloadAsset(v.url, v.filename), i * 400))}>
                            ⬇ 一键下载全部 {vids.length} 段 t2v 视频
                          </Button>
                        </div>
                      )
                    })()}

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {resp7t.result.results.map(r => (
                        <div key={r.scene_no} className="border rounded p-2 space-y-2 bg-card">
                          <div className="flex items-center justify-between gap-1 flex-wrap">
                            <div className="text-sm font-medium">
                              第 {r.scene_no} 段 · {r.duration_s}s
                              {r.scene_time_range && (
                                <span className="text-[10px] text-muted-foreground ml-1">[{r.scene_time_range}]</span>
                              )}
                              <Badge variant="outline" className="text-[9px] ml-1 px-1">t2v</Badge>
                            </div>
                          </div>
                          {r.error ? (
                            <div className="text-xs p-2 border border-red-300 rounded bg-red-50 dark:bg-red-950/20 text-red-700 dark:text-red-300 space-y-1">
                              <div className="font-medium">{r.error}</div>
                              {r.hint && <div className="text-[11px]">💡 {r.hint}</div>}
                              {r.error_detail && (
                                <details className="text-[10px]">
                                  <summary className="cursor-pointer opacity-70">▼ 原始 detail</summary>
                                  <pre className="mt-1 whitespace-pre-wrap break-words">{r.error_detail}</pre>
                                </details>
                              )}
                            </div>
                          ) : r.video_url ? (
                            <video src={r.video_url} controls className="w-full rounded border" preload="metadata" />
                          ) : r.dry_run ? (
                            <div className="text-xs p-2 border border-blue-300 rounded bg-blue-50 dark:bg-blue-950/20 text-blue-700 dark:text-blue-300">
                              🔍 预览模式（干跑，未调 Veo）· 时长 {r.duration_s || '?'}s
                            </div>
                          ) : (
                            <div className="text-xs text-muted-foreground italic">无视频 url</div>
                          )}
                          {r.prompt && (
                            <details className="text-xs" open={!!r.dry_run}>
                              <summary className="cursor-pointer text-muted-foreground">
                                ▼ 实际喂 Veo 3.1 的 prompt（t2v 模式）
                              </summary>
                              <pre className="mt-1 p-2 bg-muted/50 rounded whitespace-pre-wrap text-[10px]">{r.prompt}</pre>
                            </details>
                          )}
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <Button
                              size="sm" variant="outline" disabled={running7t}
                              onClick={() => rerunOneScene7t(r.scene_no)}
                              className="text-[10px] h-7 px-2"
                            >
                              🔄 重跑此段
                            </Button>
                            {r.asset_id && (
                              <Button
                                size="sm"
                                variant={adoptedAssetIds.has(r.asset_id) ? 'default' : 'outline'}
                                disabled={!r.asset_id || adoptingAsset === r.asset_id}
                                onClick={() => adoptAsset(r.asset_id!)}
                                className="text-[10px] h-7 px-2"
                              >
                                {adoptingAsset === r.asset_id ? (
                                  <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 采纳中</>
                                ) : adoptedAssetIds.has(r.asset_id) ? '✅ 已绑' : '✓ 绑血缘'}
                              </Button>
                            )}
                            {r.video_url && (
                              <Button size="sm" variant="outline"
                                onClick={() => downloadAsset(r.video_url!, `${resp7t?.result?.sku_id || 'sku'}_t2v_scene${r.scene_no}.mp4`)}
                                className="text-[10px] h-7 px-2">
                                <Download className="w-3 h-3 mr-1" /> 下载
                              </Button>
                            )}
                            {r.video_url && (
                              <a href={r.video_url} target="_blank" rel="noopener noreferrer"
                                className="text-[10px] text-blue-600 hover:underline px-1">原视频 ↗</a>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {resp7t?.trace && (
                  <div className="mt-4 text-[11px] text-muted-foreground border-t pt-2">
                    {resp7t.trace.model_provider}/{resp7t.trace.model} · {resp7t.trace.cost_estimate}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ============== 血缘图（全局浏览 + 节点采纳 / 详情） ============== */}
        <TabsContent value="lineage" className="mt-0 flex-1 min-w-0">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Network className="w-4 h-4" /> SKU 血缘图
              </CardTitle>
              <CardDescription>
                整条链路一图看清：matrix → audience_run → record → pack → script → asset。
                draft 灰 / adopted 绿 / published 蓝。可在节点上直接采纳（draft → adopted）。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {SkuPicker}

              {!skuId ? (
                <div className="text-sm text-muted-foreground py-12 text-center border border-dashed rounded">
                  上方先选个 SKU。
                </div>
              ) : (
                <>
                  <div className="text-[11px] text-muted-foreground mb-2 p-2 rounded bg-muted/30 border border-dashed">
                    💡 点 <strong>video_*</strong> 脚本节点的 "← 用作 step 7" 按钮，可直接把此脚本绑到 step 7 跑视频。
                  </div>
                  <LineageTree
                    key={`${skuId}-${lineageKey}`}
                    skuId={skuId}
                    height="65vh"
                    pickKinds={['script']}
                    onPick={node => {
                      if (node.kind !== 'script') return
                      // 校验脚本 kind 必须是 video_*（无法在 LineageTree 内直接知，让 page 这边校验 + 提示）
                      if (!node.label.includes('视频')) {
                        alert('step 7 只能跑 video_* 脚本（视频软广 / 种草 / 收割）；该脚本不是视频类型，无法在 step 7 跑。')
                        return
                      }
                      setScript6Id(node.id)
                      selectScript6(node.id)  // 同步拉脚本详情
                      if (scriptsForSku6 === null) {
                        loadScriptsForStep6()  // 也加载列表方便下拉
                      }
                      setActiveTab('step7')
                    }}
                  />
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* 血缘图 pick 模态层（step 5 / phase D 输入区可调起） */}
      {pickModalOpen && skuId && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onClick={() => setPickModalOpen(false)}
        >
          <div
            className="bg-background border rounded-lg shadow-xl max-w-5xl w-full max-h-[90vh] overflow-hidden flex flex-col"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b">
              <h3 className="font-semibold flex items-center gap-2">
                <Network className="w-4 h-4" /> 从血缘图选上游
              </h3>
              <button
                onClick={() => setPickModalOpen(false)}
                className="text-muted-foreground hover:text-foreground text-lg leading-none px-2"
              >
                ✕
              </button>
            </div>
            <div className="p-4 overflow-y-auto flex-1">
              <LineageTree
                key={`${skuId}-${lineageKey}`}
                skuId={skuId}
                height="60vh"
                onPick={node => {
                  // record / pack 都能回填 step 5
                  if (node.kind === 'audience_record') {
                    setSrcMode5('record')
                    setRecord5Id(node.id)
                    selectRecord4(node.id)  // 复用 step 4 的 detail 拉取（选用同款详情卡）
                    setPickModalOpen(false)
                  } else if (node.kind === 'audience_pack') {
                    // pack 模式：拉圈包 + 关联 record/matrix 全链路（最完整）
                    setSrcMode5('pack')
                    setPack5Id(node.id)
                    loadPack5Detail(node.id)  // 同步拉 pack_md 预览
                    setPickModalOpen(false)
                  } else if (node.kind === 'script') {
                    alert('脚本节点是 step 5 输出，不是输入。phase D 起 step 6 分镜图会从这里选脚本。')
                  } else {
                    alert(`${node.kind} 节点不能作为 step 5 输入。请选 候选人群 / 圈包 节点。`)
                  }
                }}
                onClose={() => setPickModalOpen(false)}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
