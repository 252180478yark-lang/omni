'use client'

import Link from 'next/link'
import { createPortal } from 'react-dom'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronDown, ChevronRight, Upload, Plus, Trash2, LinkIcon, GitBranch,
  MoreHorizontal, FileText, X, ArrowRight, Check, Layers, RefreshCw,
  Pencil, ArrowDown, Play, Eye,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import {
  batchGroupMaterials, createAudience, createGroup, deleteAudience, deleteGroup,
  deleteMaterial, getCampaignDetail, getVideoDetail, importCsv, linkParent, linkVideo, listVideos,
  previewCsv, updateAudience, updateCampaign, updateMaterial,
  uploadVideoForAnalysis,
  uploadAudienceProfile, uploadAudienceTargeting,
} from '@/lib/ad-review-api'

type Row = Record<string, unknown>
type CsvPreviewState = {
  columns: string[]
  sample_rows: unknown[][]
  mapped_columns: Record<string, string>
}

const STATUS_CFG: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'bg-gray-100 text-gray-600' },
  data_uploaded: { label: '数据已上传', color: 'bg-blue-50 text-blue-700' },
  reviewed: { label: '已复盘', color: 'bg-green-50 text-green-700' },
  archived: { label: '已归档', color: 'bg-gray-50 text-gray-400' },
}

const CHANGE_TAG_OPTIONS = ['改钩子', '改BGM', '改文案', '改画面', '缩短时长', '换演员', '换场景', '改字幕']

const PURPOSE_CFG: Record<string, { label: string; color: string }> = {
  organic: { label: '自然流量', color: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  seeding: { label: '种草', color: 'bg-amber-50 text-amber-700 border-amber-200' },
  conversion: { label: '转化', color: 'bg-rose-50 text-rose-700 border-rose-200' },
}

/* ── Collapsible Section ── */
function Section({ title, badge, defaultOpen = true, actions, children }: {
  title: string; badge?: string; defaultOpen?: boolean; actions?: React.ReactNode; children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50/50"
        onClick={() => setOpen(!open)}
      >
        <span className="flex items-center gap-2 font-semibold text-sm text-gray-800">
          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          {title}
          {badge && <span className="text-xs font-normal text-gray-400">{badge}</span>}
        </span>
        {actions && <span onClick={(e) => e.stopPropagation()}>{actions}</span>}
      </button>
      {open && <div className="px-4 pb-4 border-t border-gray-100">{children}</div>}
    </div>
  )
}

/* ── Format helpers ── */
function fmtCtr(v: unknown) {
  if (v == null) return '—'
  const n = Number(v)
  return `${(n * 100).toFixed(2)}%`
}
function fmtPct(v: unknown) {
  if (v == null) return '—'
  return `${(Number(v) * 100).toFixed(1)}%`
}
function fmtCost(v: unknown) {
  if (v == null) return '—'
  return `¥${Number(v).toLocaleString()}`
}
function delta(cur: unknown, prev: unknown): { text: string; cls: string } | null {
  if (cur == null || prev == null) return null
  const c = Number(cur), p = Number(prev)
  if (p === 0) return null
  const d = ((c - p) / p) * 100
  const sign = d > 0 ? '+' : ''
  return { text: `${sign}${d.toFixed(1)}%`, cls: d > 0 ? 'text-green-600' : d < 0 ? 'text-red-500' : 'text-gray-400' }
}

/* ── Build iteration chains from materials within a group ── */
function buildChains(mats: Row[]): Row[][] {
  const byId = new Map(mats.map((m) => [String(m.id), m]))
  const childMap = new Map<string, Row[]>()
  const roots: Row[] = []
  for (const m of mats) {
    const pid = m.parent_material_id ? String(m.parent_material_id) : null
    if (pid && byId.has(pid)) {
      if (!childMap.has(pid)) childMap.set(pid, [])
      childMap.get(pid)!.push(m)
    } else {
      roots.push(m)
    }
  }
  // Sort children by version
  Array.from(childMap.values()).forEach((children) => {
    children.sort((a, b) => (Number(a.version) || 0) - (Number(b.version) || 0))
  })
  // Build chains from each root
  const chains: Row[][] = []
  for (const root of roots) {
    const chain: Row[] = [root]
    const queue = [root]
    while (queue.length) {
      const cur = queue.shift()!
      const kids = childMap.get(String(cur.id)) || []
      for (const kid of kids) {
        chain.push(kid)
        queue.push(kid)
      }
    }
    chains.push(chain)
  }
  return chains
}

export default function AdReviewCampaignDetailPage() {
  const params = useParams()
  const router = useRouter()
  const id = String(params.id || '')

  const [campaign, setCampaign] = useState<Row | null>(null)
  const [audiences, setAudiences] = useState<Row[]>([])
  const [materials, setMaterials] = useState<Row[]>([])
  const [groups, setGroups] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tip, setTip] = useState('')

  // Audience form
  const [audForm, setAudForm] = useState({ name: '', description: '', tags: '' })

  // CSV import
  const [csvAudience, setCsvAudience] = useState('')
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [csvPreview, setCsvPreview] = useState<CsvPreviewState | null>(null)
  const [importing, setImporting] = useState(false)

  // Dialogs
  const [videoOpen, setVideoOpen] = useState(false)
  const [videoPickMat, setVideoPickMat] = useState<string | null>(null)
  const [videos, setVideos] = useState<Row[]>([])
  const [videoMeta, setVideoMeta] = useState<Record<string, { overall: number | null }>>({})
  const [videoRefreshing, setVideoRefreshing] = useState(false)
  const [videoUploading, setVideoUploading] = useState(false)
  const [parentOpen, setParentOpen] = useState(false)
  const [parentMat, setParentMat] = useState<string | null>(null)
  const [parentPick, setParentPick] = useState('')
  const [parentNote, setParentNote] = useState('')
  const [parentTags, setParentTags] = useState<string[]>([])

  // Group creation
  const [newGroupAud, setNewGroupAud] = useState<string | null>(null)
  const [newGroupLabel, setNewGroupLabel] = useState('')
  const [newGroupPurpose, setNewGroupPurpose] = useState('seeding')

  // Batch selection for grouping
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [batchTarget, setBatchTarget] = useState('')

  // Audience text drafts
  const [audienceDrafts, setAudienceDrafts] = useState<Record<string, { targeting: string; profileText: string }>>({})

  // Material action menus
  const [matMenu, setMatMenu] = useState<string | null>(null)
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 })

  // Feature 1: CSV video upload wizard
  const [wizardOpen, setWizardOpen] = useState(false)
  const [wizardMats, setWizardMats] = useState<Row[]>([])
  const [wizardIdx, setWizardIdx] = useState(0)
  const [wizardUploading, setWizardUploading] = useState(false)
  const [wizardVideoIds, setWizardVideoIds] = useState<Record<string, string>>({})
  const pollingRef = useRef<Record<string, string>>({})

  // Feature 2: Material detail dialog
  const [detailMat, setDetailMat] = useState<Row | null>(null)
  const [detailReport, setDetailReport] = useState<Record<string, unknown> | null | undefined>(undefined)
  const [detailTab, setDetailTab] = useState('scores')

  // Feature 3: Full-screen iteration tree
  const [treeChain, setTreeChain] = useState<Row[] | null>(null)

  // Feature 4: Editable material name (parent-level to survive re-renders)
  const [editingMatId, setEditingMatId] = useState<string | null>(null)
  const [editingMatName, setEditingMatName] = useState('')

  // Feature 5: review log + parent hint from AI suggestions
  const [reviewLog, setReviewLog] = useState<Row | null>(null)
  const [parentHint, setParentHint] = useState('')
  const [parentEvidenceFields, setParentEvidenceFields] = useState<string[]>([])

  const showTip = (msg: string) => {
    setTip(msg)
    setTimeout(() => setTip(''), 3000)
  }

  const renderObj = (obj: unknown): React.ReactNode => {
    if (obj == null) return '—'
    if (typeof obj === 'string' || typeof obj === 'number' || typeof obj === 'boolean') return String(obj)
    if (Array.isArray(obj)) return obj.map((item, i) => <div key={i}>{renderObj(item)}</div>)
    if (typeof obj === 'object') return Object.entries(obj as Record<string, unknown>).map(([k, v]) => (
      <div key={k} className="flex gap-2"><span className="text-gray-500 shrink-0">{k}:</span><span>{typeof v === 'object' ? JSON.stringify(v) : String(v ?? '')}</span></div>
    ))
    return String(obj)
  }

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const d = await getCampaignDetail(id)
      setCampaign(d.campaign)
      setAudiences(d.audiences || [])
      setMaterials(d.materials || [])
      setGroups(d.groups || [])
      setReviewLog(d.review_log || null)
      setCsvAudience((prev) => prev || ((d.audiences || [])[0]?.id ? String((d.audiences as Row[])[0].id) : ''))
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    const d: Record<string, { targeting: string; profileText: string }> = {}
    for (const a of audiences) {
      d[String(a.id)] = {
        targeting: String(a.targeting_method_text || ''),
        profileText: String(a.audience_profile_text || ''),
      }
    }
    setAudienceDrafts(d)
  }, [audiences])

  useEffect(() => {
    if (!matMenu) return
    const handler = () => setMatMenu(null)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [matMenu])

  useEffect(() => {
    if (!detailMat?.video_analysis_id) { setDetailReport(undefined); return }
    setDetailReport(null)
    getVideoDetail(String(detailMat.video_analysis_id)).then((d) => {
      setDetailReport(d.report as Record<string, unknown> || undefined)
    }).catch(() => setDetailReport(undefined))
  }, [detailMat])

  // Video polling for wizard-uploaded videos
  useEffect(() => {
    const timer = setInterval(async () => {
      const entries = Object.entries(pollingRef.current)
      if (entries.length === 0) return
      for (const [mid, vid] of entries) {
        try {
          const d = await getVideoDetail(vid)
          if (String((d.video as Row | undefined)?.status || '') === 'done') {
            await linkVideo(mid, vid)
            delete pollingRef.current[mid]
            void load()
          }
        } catch { /* retry next tick */ }
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [load])

  // Auto-suggest from ai_suggestions when parent is selected
  useEffect(() => {
    if (!parentPick || !reviewLog) { setParentHint(''); setParentEvidenceFields([]); return }
    const suggestions = Array.isArray(reviewLog.ai_suggestions) ? (reviewLog.ai_suggestions as Row[]) : []
    const parent = materials.find((m) => String(m.id) === parentPick)
    if (!parent) return
    const entry = suggestions.find((s) => String(s.material_name) === String(parent.name))
    if (entry) {
      const tags = Array.isArray(entry.suggestions) ? (entry.suggestions as string[]) : []
      if (tags.length > 0) setParentTags(tags)
      setParentHint(String(entry.detail || ''))
      const ev = Array.isArray(entry.evidence_fields)
        ? (entry.evidence_fields as unknown[]).map((v) => String(v)).filter(Boolean)
        : []
      setParentEvidenceFields(ev)
    } else {
      setParentHint('')
      setParentEvidenceFields([])
    }
  }, [parentPick, reviewLog, materials])

  const audienceOptions = useMemo(() => audiences, [audiences])

  /* ── Grouped materials structure ── */
  const matsByAudience = useMemo(() => {
    const map: Record<string, Row[]> = {}
    for (const m of materials) {
      const aid = String(m.audience_pack_id)
      if (!map[aid]) map[aid] = []
      map[aid].push(m)
    }
    return map
  }, [materials])

  const groupsByAudience = useMemo(() => {
    const map: Record<string, Row[]> = {}
    for (const g of groups) {
      const aid = String(g.audience_pack_id)
      if (!map[aid]) map[aid] = []
      map[aid].push(g)
    }
    return map
  }, [groups])

  /* ── Actions ── */
  const saveBasic = async () => {
    if (!campaign) return
    try {
      await updateCampaign(id, { name: campaign.name, start_date: campaign.start_date, end_date: campaign.end_date, total_budget: campaign.total_budget })
      showTip('基础信息已保存')
      void load()
    } catch (e) { setError(String(e)) }
  }

  const addAudience = async () => {
    if (!audForm.name.trim()) { setError('请输入人群包名称'); return }
    try {
      const tags = audForm.tags.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      await createAudience(id, { name: audForm.name, description: audForm.description, tags })
      setAudForm({ name: '', description: '', tags: '' })
      showTip('人群包已添加')
      void load()
    } catch (e) { setError(String(e)) }
  }

  const removeAudience = async (aid: string) => {
    if (!confirm('删除人群包将同时删除其下所有素材，确定？')) return
    try { await deleteAudience(aid); void load() }
    catch (e) { setError(String(e)) }
  }

  const saveAudienceText = async (aid: string) => {
    const dr = audienceDrafts[aid]
    if (!dr) return
    try {
      await updateAudience(aid, { targeting_method_text: dr.targeting, audience_profile_text: dr.profileText })
      showTip('已保存')
      void load()
    } catch (e) { setError(String(e)) }
  }

  const runPreview = async () => {
    if (!csvAudience || !csvFile) { setError('请选择人群包并上传千川数据文件'); return }
    setError('')
    try {
      const p = await previewCsv(csvAudience, csvFile) as {
        columns?: string[]
        sample_rows?: unknown[][]
        mapped_columns?: Record<string, string>
        preview?: Array<Record<string, unknown>>
        column_mapping?: Record<string, string>
      }

      const mapped = p.mapped_columns || p.column_mapping || {}
      const columnsFromResp = Array.isArray(p.columns) ? p.columns : []
      const sampleRowsFromResp = Array.isArray(p.sample_rows) ? p.sample_rows : []
      const objectRows = Array.isArray(p.preview)
        ? p.preview.filter((r): r is Record<string, unknown> => !!r && typeof r === 'object')
        : []
      const normalizedColumns = columnsFromResp.length > 0
        ? columnsFromResp
        : (objectRows[0] ? Object.keys(objectRows[0]) : [])
      const normalizedRows = sampleRowsFromResp.length > 0
        ? sampleRowsFromResp
        : objectRows.map((r) => normalizedColumns.map((col) => r[col] ?? ''))

      setCsvPreview({ columns: normalizedColumns, sample_rows: normalizedRows, mapped_columns: mapped })
    } catch (e) { setError(String(e)) }
  }

  const runImport = async () => {
    if (!csvAudience || !csvFile) return
    setImporting(true); setError('')
    try {
      const existingIds = new Set(materials.map((m) => String(m.id)))
      await importCsv(csvAudience, csvFile)
      setCsvPreview(null); setCsvFile(null)
      showTip('CSV 导入成功')
      const d = await getCampaignDetail(id)
      setCampaign(d.campaign); setAudiences(d.audiences || [])
      setMaterials(d.materials || []); setGroups(d.groups || [])
      setReviewLog(d.review_log || null)
      const imported = (d.materials || []).filter((m) => !existingIds.has(String(m.id)))
      if (imported.length > 0) {
        setWizardMats(imported); setWizardIdx(0); setWizardVideoIds({}); setWizardOpen(true)
      }
    } catch (e) { setError(String(e)) }
    finally { setImporting(false) }
  }

  const wizardUpload = async (file: File) => {
    const mat = wizardMats[wizardIdx]
    if (!mat) return
    setWizardUploading(true)
    try {
      const res = await uploadVideoForAnalysis(file)
      setWizardVideoIds((prev) => ({ ...prev, [String(mat.id)]: String(res.id) }))
    } catch (e) { setError(String(e)) }
    finally { setWizardUploading(false) }
  }

  const closeWizard = () => {
    setWizardOpen(false)
    Object.assign(pollingRef.current, wizardVideoIds)
  }

  const refreshVideos = useCallback(async () => {
    setVideoRefreshing(true)
    try {
      const raw = await listVideos()
      setVideos(raw)
      const meta: Record<string, { overall: number | null }> = {}
      await Promise.all(raw.slice(0, 30).map(async (v) => {
        const vid = String(v.id)
        if (String(v.status) !== 'done') { meta[vid] = { overall: null }; return }
        try {
          const d = await getVideoDetail(vid)
          meta[vid] = { overall: typeof d.report?.scores?.overall === 'number' ? d.report.scores.overall : null }
        } catch { meta[vid] = { overall: null } }
      }))
      setVideoMeta(meta)
    } catch (e) { setError(String(e)) }
    finally { setVideoRefreshing(false) }
  }, [])

  const openVideo = async (mid: string) => {
    setVideoPickMat(mid); setVideoOpen(true); setVideoMeta({}); setMatMenu(null)
    await refreshVideos()
  }

  const onUploadVideo = async (file: File | null) => {
    if (!file) return
    setVideoUploading(true)
    try {
      await uploadVideoForAnalysis(file)
      showTip('视频已提交分析，完成后可在此列表直接关联')
      await refreshVideos()
    } catch (e) {
      setError(String(e))
    } finally {
      setVideoUploading(false)
    }
  }

  const confirmVideo = async (vid: string | null) => {
    if (!videoPickMat) return
    try { await linkVideo(videoPickMat, vid); setVideoOpen(false); void load() }
    catch (e) { setError(String(e)) }
  }

  const unlinkVideo = async (mid: string) => {
    setMatMenu(null)
    try { await linkVideo(mid, null); void load() }
    catch (e) { setError(String(e)) }
  }

  const openParent = (mid: string) => {
    setParentMat(mid); setParentPick(''); setParentNote(''); setParentTags([]); setParentHint(''); setParentEvidenceFields([]); setParentOpen(true); setMatMenu(null)
  }

  const confirmParent = async () => {
    if (!parentMat || !parentPick) return
    try { await linkParent(parentMat, parentPick, parentNote, parentTags); setParentOpen(false); void load() }
    catch (e) { setError(String(e)) }
  }

  const doCreateGroup = async () => {
    if (!newGroupAud || !newGroupLabel.trim()) return
    try {
      await createGroup(newGroupAud, { style_label: newGroupLabel.trim(), video_purpose: newGroupPurpose })
      setNewGroupAud(null); setNewGroupLabel(''); setNewGroupPurpose('seeding')
      showTip('风格组已创建')
      void load()
    } catch (e) { setError(String(e)) }
  }

  const doDeleteGroup = async (gid: string) => {
    if (!confirm('删除风格组？（素材不会被删除，只是变为未分组）')) return
    try { await deleteGroup(gid); void load() }
    catch (e) { setError(String(e)) }
  }

  const doBatchGroup = async () => {
    if (selected.size === 0 || !batchTarget) return
    try {
      await batchGroupMaterials(Array.from(selected), batchTarget)
      setSelected(new Set()); setBatchTarget('')
      showTip(`已将 ${selected.size} 条素材移入风格组`)
      void load()
    } catch (e) { setError(String(e)) }
  }

  const toggleSelect = (mid: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(mid)) next.delete(mid); else next.add(mid)
      return next
    })
  }

  if (!id) return null
  const st = STATUS_CFG[String(campaign?.status || '')] || { label: '—', color: '' }

  /* ── Material row component ── */
  const MatRow = ({ m, prev, showCheckbox, purpose }: { m: Row; prev?: Row; showCheckbox?: boolean; purpose?: string }) => {
    const mid = String(m.id)
    const scores = m.video_analysis_scores as { overall?: number } | null | undefined
    const overall = scores && typeof scores === 'object' && typeof scores.overall === 'number' ? scores.overall : null
    const ctrDelta = prev ? delta(m.ctr, prev.ctr) : null
    const tags = Array.isArray(m.change_tags) ? (m.change_tags as string[]) : []
    const isEditing = editingMatId === mid

    // Type-specific metrics
    const metricsLine = () => {
      const cpm = m.cpm != null ? `CPM ¥${Number(m.cpm).toFixed(1)}` : null
      if (purpose === 'organic') {
        return (
          <>
            <span>完播 {fmtPct(m.completion_rate)}</span>
            <span>3秒率 {fmtPct(m.play_3s_rate)}</span>
            <span>互动率 {fmtPct(m.interaction_rate)}</span>
            <span>播放 {m.plays != null ? Number(m.plays).toLocaleString() : '—'}</span>
          </>
        )
      }
      if (purpose === 'conversion') {
        const cvr = m.conversion_rate != null ? fmtPct(m.conversion_rate) : '—'
        const cpmVal = Number(m.cpm || 0)
        const ctrVal = Number(m.ctr || 0)
        const cvrVal = Number(m.conversion_rate || 0)
        let convCostStr = '—'
        let convCostClass = ''
        if (cpmVal > 0 && ctrVal > 0 && cvrVal > 0) {
          const cc = cpmVal / (ctrVal * 1000) / cvrVal
          convCostStr = `¥${cc.toFixed(2)}`
          const pp = Number(campaign?.product_price || 0)
          const mr = Number(campaign?.product_margin_rate || 0)
          if (pp && mr) {
            convCostClass = cc <= pp * mr ? 'text-green-600 font-medium' : 'text-red-500 font-medium'
          }
        }
        return (
          <>
            {cpm && <span>{cpm}</span>}
            <span>CTR <span className={Number(m.ctr || 0) > 0.03 ? 'text-green-600 font-medium' : ''}>{fmtCtr(m.ctr)}</span>
              {ctrDelta && <span className={`ml-1 font-medium ${ctrDelta.cls}`}>{ctrDelta.text}</span>}
            </span>
            <span>CVR {cvr}</span>
            <span className={convCostClass}>转化成本 {convCostStr}</span>
          </>
        )
      }
      // seeding (default)
      return (
        <>
          {cpm && <span>{cpm}</span>}
          <span>CTR <span className={Number(m.ctr || 0) > 0.03 ? 'text-green-600 font-medium' : ''}>{fmtCtr(m.ctr)}</span>
            {ctrDelta && <span className={`ml-1 font-medium ${ctrDelta.cls}`}>{ctrDelta.text}</span>}
          </span>
          <span>转化率 {fmtPct(m.conversion_rate)}</span>
          {m.cost_per_result != null && <span>转化成本 ¥{Number(m.cost_per_result).toFixed(2)}</span>}
        </>
      )
    }

    return (
      <div className="flex items-start gap-2 py-1.5 group">
        {showCheckbox && (
          <input type="checkbox" checked={selected.has(mid)} onChange={() => toggleSelect(mid)}
            className="mt-1.5 rounded border-gray-300" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {isEditing ? (
              <input className="text-sm font-medium text-gray-800 border-b border-indigo-400 outline-none bg-transparent w-40"
                value={editingMatName} autoFocus
                onChange={(e) => setEditingMatName(e.target.value)}
                onKeyDown={async (e) => {
                  if (e.key === 'Enter') { await updateMaterial(mid, { name: editingMatName }); setEditingMatId(null); void load() }
                  if (e.key === 'Escape') setEditingMatId(null)
                }}
                onBlur={async () => { if (editingMatName.trim()) { await updateMaterial(mid, { name: editingMatName }); setEditingMatId(null); void load() } }}
              />
            ) : (
              <>
                <span className="text-sm font-medium text-gray-800 truncate cursor-pointer hover:text-indigo-600"
                  onClick={() => setDetailMat(m)}>{String(m.name)}</span>
                <button className="opacity-0 group-hover:opacity-100 p-0.5" onClick={() => { setEditingMatId(mid); setEditingMatName(String(m.name)) }}>
                  <Pencil className="w-3 h-3 text-gray-400" />
                </button>
              </>
            )}
            {Number(m.version || 1) > 1 && (
              <span className="text-[10px] bg-amber-50 text-amber-700 px-1.5 py-0.5 rounded font-medium">v{String(m.version)}</span>
            )}
            {tags.length > 0 && tags.map((t, i) => (
              <span key={i} className="text-[10px] bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded">{t}</span>
            ))}
            {!!m.video_analysis_id && (
              <span className="text-[10px] bg-purple-50 text-purple-700 px-1.5 py-0.5 rounded">
                {overall != null ? `${overall}/10` : '视频已关联'}
              </span>
            )}
          </div>
          <div className="flex gap-4 text-xs text-gray-500 mt-0.5">
            <span>{fmtCost(m.cost)}</span>
            {metricsLine()}
            {!!m.iteration_note && <span className="text-gray-400 italic">&ldquo;{String(m.iteration_note)}&rdquo;</span>}
          </div>
        </div>
        <div className="relative shrink-0 flex items-center gap-1">
          <button className="text-[11px] px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50"
            onClick={() => openParent(mid)}>设置父节点</button>
          {!m.video_analysis_id ? (
            <button className="text-[11px] px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50"
              onClick={() => void openVideo(mid)}>关联视频</button>
          ) : (
            <button className="text-[11px] px-2 py-1 rounded border border-red-200 text-red-500 hover:bg-red-50"
              onClick={() => { if (confirm('确定解除该素材的视频关联？')) void unlinkVideo(mid) }}>
              <X className="w-3 h-3 inline -mt-0.5 mr-0.5" />解除视频
            </button>
          )}
          <button
            ref={(el) => { if (el && matMenu === mid) el.dataset.menuAnchor = 'true' }}
            className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600 opacity-0 group-hover:opacity-100 transition-opacity"
            onClick={(e) => {
              e.stopPropagation()
              const btn = e.currentTarget
              const rect = btn.getBoundingClientRect()
              setMenuPos({ top: rect.bottom + 4, left: rect.right - 160 })
              setMatMenu(matMenu === mid ? null : mid)
            }}>
            <MoreHorizontal className="w-4 h-4" />
          </button>
          {matMenu === mid && typeof document !== 'undefined' && createPortal(
            <div
              className="fixed z-[9999] w-40 bg-white border rounded-lg shadow-xl py-1 text-xs"
              style={{ top: menuPos.top, left: Math.max(8, menuPos.left) }}
              onClick={(e) => e.stopPropagation()}
            >
              <button className="w-full text-left px-3 py-1.5 hover:bg-gray-50 flex items-center gap-2"
                onClick={() => void openVideo(mid)}>
                <LinkIcon className="w-3 h-3" /> {m.video_analysis_id ? '更换视频' : '关联视频'}
              </button>
              <button className="w-full text-left px-3 py-1.5 hover:bg-gray-50 flex items-center gap-2"
                onClick={() => openParent(mid)}>
                <GitBranch className="w-3 h-3" /> 标记迭代
              </button>
              {!!m.video_analysis_id && (
                <button className="w-full text-left px-3 py-1.5 hover:bg-red-50 text-red-600 flex items-center gap-2"
                  onClick={() => void unlinkVideo(mid)}>
                  <X className="w-3 h-3" /> 解除视频
                </button>
              )}
              <div className="border-t border-gray-100 my-0.5" />
              <button className="w-full text-left px-3 py-1.5 hover:bg-red-50 text-red-600 flex items-center gap-2"
                onClick={async () => {
                  if (!confirm('确定删除该素材及其投放数据？')) return
                  setMatMenu(null)
                  try { await deleteMaterial(mid); void load() }
                  catch (e) { setError(String(e)) }
                }}>
                <Trash2 className="w-3 h-3" /> 删除素材
              </button>
            </div>,
            document.body,
          )}
        </div>
      </div>
    )
  }

  /* ── Iteration chain component (compact, used inside groups) ── */
  const ChainView = ({ chain, purpose }: { chain: Row[]; purpose?: string }) => {
    if (chain.length === 1) {
      return <MatRow m={chain[0]} purpose={purpose} />
    }
    return (
      <div className="space-y-0">
        {chain.map((m, idx) => (
          <div key={String(m.id)}>
            {idx > 0 && (
              <div className="flex items-center gap-1.5 pl-4 py-0.5 text-[10px] text-gray-400">
                <ArrowRight className="w-3 h-3" />
                {Array.isArray(m.change_tags) && (m.change_tags as string[]).length > 0
                  ? (m.change_tags as string[]).join(', ')
                  : '迭代'}
              </div>
            )}
            <MatRow m={m} prev={idx > 0 ? chain[idx - 1] : undefined} purpose={purpose} />
          </div>
        ))}
      </div>
    )
  }

  /* ── Iteration Relation Graph (visual card-based chain) ── */
  const IterationGraph = ({ chain }: { chain: Row[] }) => {
    if (chain.length < 2) return null
    return (
      <div className="flex items-start gap-0 overflow-x-auto pb-2">
        {chain.map((m, idx) => {
          const prev = idx > 0 ? chain[idx - 1] : null
          const tags = Array.isArray(m.change_tags) ? (m.change_tags as string[]) : []
          const scores = m.video_analysis_scores as { overall?: number } | null | undefined
          const overall = scores && typeof scores === 'object' && typeof scores.overall === 'number' ? scores.overall : null
          const ctrD = prev ? delta(m.ctr, prev.ctr) : null
          const crD = prev ? delta(m.completion_rate, prev.completion_rate) : null
          const costD = prev ? delta(m.cost, prev.cost) : null
          const cvrD = prev ? delta(m.conversion_rate, prev.conversion_rate) : null
          const cpmD = prev ? delta(m.cpm, prev.cpm) : null

          return (
            <div key={String(m.id)} className="flex items-start shrink-0">
              {idx > 0 && (
                <div className="flex flex-col items-center justify-center px-1 pt-6 shrink-0">
                  <div className="w-8 h-px bg-gray-300" />
                  <ArrowRight className="w-3.5 h-3.5 text-gray-400 -mt-[9px]" />
                  {tags.length > 0 && (
                    <div className="flex flex-col items-center gap-0.5 mt-1">
                      {tags.map((t, i) => (
                        <span key={i} className="text-[9px] bg-indigo-50 text-indigo-600 px-1 py-0.5 rounded whitespace-nowrap">{t}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <div className={`w-56 rounded-lg border p-3 shrink-0 cursor-pointer hover:shadow-md transition-shadow ${
                idx === 0 ? 'border-gray-200 bg-white' : idx === chain.length - 1 ? 'border-green-200 bg-green-50/30' : 'border-amber-200 bg-amber-50/30'
              }`} onClick={() => setDetailMat(m)}>
                <div className="flex items-center gap-1.5 mb-2">
                  <span className="text-xs font-semibold text-gray-800 truncate">{String(m.name)}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 ${
                    idx === 0 ? 'bg-gray-100 text-gray-600' : 'bg-amber-100 text-amber-700'
                  }`}>v{String(m.version || 1)}</span>
                </div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                  <div className="text-gray-500">消耗</div>
                  <div className="font-medium text-gray-800 text-right">
                    {fmtCost(m.cost)}
                    {costD && <span className={`ml-1 ${costD.cls}`}>{costD.text}</span>}
                  </div>
                  <div className="text-gray-500">CPM</div>
                  <div className="font-medium text-gray-800 text-right">
                    {m.cpm != null ? `¥${Number(m.cpm).toFixed(1)}` : '—'}
                    {cpmD && <span className={`ml-1 ${cpmD.cls}`}>{cpmD.text}</span>}
                  </div>
                  <div className="text-gray-500">点击率</div>
                  <div className="font-medium text-gray-800 text-right">
                    {fmtCtr(m.ctr)}
                    {ctrD && <span className={`ml-1 ${ctrD.cls}`}>{ctrD.text}</span>}
                  </div>
                  <div className="text-gray-500">转化率</div>
                  <div className="font-medium text-gray-800 text-right">
                    {fmtPct(m.conversion_rate)}
                    {cvrD && <span className={`ml-1 ${cvrD.cls}`}>{cvrD.text}</span>}
                  </div>
                  <div className="text-gray-500">完播率</div>
                  <div className="font-medium text-gray-800 text-right">
                    {fmtPct(m.completion_rate)}
                    {crD && <span className={`ml-1 ${crD.cls}`}>{crD.text}</span>}
                  </div>
                  <div className="text-gray-500">3秒率</div>
                  <div className="font-medium text-gray-800 text-right">{fmtPct(m.play_3s_rate)}</div>
                  {m.cost_per_result != null && (
                    <>
                      <div className="text-gray-500">转化成本</div>
                      <div className="font-medium text-gray-800 text-right">¥{Number(m.cost_per_result).toFixed(2)}</div>
                    </>
                  )}
                  {overall != null && (
                    <>
                      <div className="text-gray-500">视频评分</div>
                      <div className="font-medium text-purple-700 text-right">{overall}/10</div>
                    </>
                  )}
                </div>
                {!!m.iteration_note && (
                  <div className="mt-2 text-[10px] text-gray-400 italic border-t border-gray-100 pt-1">
                    &ldquo;{String(m.iteration_note)}&rdquo;
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  /* ── Group insight (auto-computed) ── */
  const GroupInsight = ({ chains }: { chains: Row[][] }) => {
    const allMats = chains.flat()
    if (allMats.length < 2) return null

    // Find effective/ineffective strategies from change_tags + CTR delta
    const effective: string[] = []
    const ineffective: string[] = []
    for (const chain of chains) {
      for (let i = 1; i < chain.length; i++) {
        const cur = chain[i], prev = chain[i - 1]
        const tags = Array.isArray(cur.change_tags) ? (cur.change_tags as string[]) : []
        if (!tags.length || cur.ctr == null || prev.ctr == null) continue
        const d = Number(cur.ctr) - Number(prev.ctr)
        for (const t of tags) {
          if (d > 0) { if (!effective.includes(t)) effective.push(t) }
          else if (d < 0) { if (!ineffective.includes(t)) ineffective.push(t) }
        }
      }
    }

    // Best material
    const best = allMats.reduce((a, b) => (Number(a.ctr || 0) > Number(b.ctr || 0) ? a : b))

    if (!effective.length && !ineffective.length) return null

    return (
      <div className="mt-2 px-3 py-2 rounded-lg bg-gray-50 text-xs text-gray-600 space-y-0.5">
        <div className="font-medium text-gray-700">组洞察</div>
        {best.ctr != null && (
          <div>最优素材：{String(best.name)} (CTR {fmtCtr(best.ctr)})</div>
        )}
        {effective.length > 0 && (
          <div className="text-green-600">有效策略：{effective.join(', ')}</div>
        )}
        {ineffective.length > 0 && (
          <div className="text-red-500">无效策略：{ineffective.join(', ')}</div>
        )}
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-24">
      {/* Header */}
      <header className="border-b bg-white/90 backdrop-blur sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 py-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-3 min-w-0">
            <Link href="/ad-review" className="text-sm text-gray-500 shrink-0">← 列表</Link>
            <h1 className="text-lg font-semibold truncate">{(campaign?.name as string) || '批次详情'}</h1>
            {campaign && <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${st.color}`}>{st.label}</span>}
            {!!campaign?.product_name && (
              <span className="text-xs text-gray-500">
                {String(campaign.product_name)}
                {campaign.product_price ? ` · ¥${Number(campaign.product_price).toFixed(2)}` : ''}
                {campaign.product_margin_rate ? ` · 毛利${(Number(campaign.product_margin_rate) * 100).toFixed(0)}%` : ''}
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-5 space-y-4">
        {/* Notifications */}
        {tip && <div className="rounded-lg bg-green-50 border border-green-200 text-green-700 px-3 py-2 text-sm flex items-center justify-between">
          {tip} <button onClick={() => setTip('')}><X className="w-3.5 h-3.5" /></button>
        </div>}
        {error && <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-3 py-2 text-sm flex items-center justify-between">
          {error} <button onClick={() => setError('')}><X className="w-3.5 h-3.5" /></button>
        </div>}

        {loading || !campaign ? (
          <p className="text-gray-500 text-sm py-8 text-center">加载中…</p>
        ) : (
          <>
            {/* ─── Section 1: Basic Info ─── */}
            <Section title="基础信息" defaultOpen={false}>
              <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-3">
                <div>
                  <span className="text-xs text-gray-500">批次名称</span>
                  <Input value={String(campaign.name || '')} onChange={(e) => setCampaign({ ...campaign, name: e.target.value })} />
                </div>
                <div>
                  <span className="text-xs text-gray-500">开始日期</span>
                  <Input type="date" value={String(campaign.start_date || '').slice(0, 10)} onChange={(e) => setCampaign({ ...campaign, start_date: e.target.value })} />
                </div>
                <div>
                  <span className="text-xs text-gray-500">结束日期</span>
                  <Input type="date" value={String(campaign.end_date || '').slice(0, 10)} onChange={(e) => setCampaign({ ...campaign, end_date: e.target.value })} />
                </div>
                <div>
                  <span className="text-xs text-gray-500">总消耗（自动汇总）</span>
                  <Input disabled value={campaign.total_cost != null ? `¥${Number(campaign.total_cost).toLocaleString()}` : '—'} />
                </div>
              </div>
              <Button size="sm" className="mt-3" onClick={() => void saveBasic()}>保存修改</Button>
            </Section>

            {/* ─── Section 2: Audiences ─── */}
            <Section title="人群包" badge={`${audiences.length} 个`}>
              <div className="pt-3 space-y-3">
                {audiences.map((a) => {
                  const aid = String(a.id)
                  const dr = audienceDrafts[aid] || { targeting: '', profileText: '' }
                  return (
                    <div key={aid} className="rounded-lg border border-gray-100 p-3 space-y-2">
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="font-medium text-sm">{String(a.name)}</span>
                          {a.description ? <span className="text-xs text-gray-400 ml-2">{String(a.description)}</span> : null}
                          {Array.isArray(a.tags) && (a.tags as string[]).length > 0 && (
                            <div className="flex gap-1 mt-1">
                              {(a.tags as string[]).map((t, i) => (
                                <span key={i} className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{t}</span>
                              ))}
                            </div>
                          )}
                        </div>
                        <Button variant="ghost" size="sm" className="text-red-500 h-7 text-xs" onClick={() => void removeAudience(aid)}>
                          <Trash2 className="w-3 h-3 mr-1" /> 删除
                        </Button>
                      </div>
                      <div className="grid sm:grid-cols-2 gap-2">
                        <div>
                          <span className="text-[10px] text-gray-400">圈包手法</span>
                          <Textarea rows={2} className="text-xs" value={dr.targeting} placeholder="定向描述…"
                            onChange={(e) => setAudienceDrafts((prev) => ({ ...prev, [aid]: { ...dr, targeting: e.target.value } }))} />
                        </div>
                        <div>
                          <span className="text-[10px] text-gray-400">人群画像</span>
                          <Textarea rows={2} className="text-xs" value={dr.profileText} placeholder="人群画像摘要…"
                            onChange={(e) => setAudienceDrafts((prev) => ({ ...prev, [aid]: { ...dr, profileText: e.target.value } }))} />
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2 items-center">
                        <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => void saveAudienceText(aid)}>保存文本</Button>
                        <label className="text-[11px] cursor-pointer border rounded px-2 py-1 hover:bg-gray-50 flex items-center gap-1">
                          <Upload className="w-3 h-3" /> 上传画像文件
                          <input type="file" accept=".xlsx,.xls,.csv,.doc,.docx,.pdf,.txt" className="hidden" onChange={async (e) => {
                            const f = e.target.files?.[0]; e.target.value = ''
                            if (!f) return
                            try { await uploadAudienceProfile(aid, f); showTip('画像文件已上传'); void load() }
                            catch (err) { setError(String(err)) }
                          }} />
                        </label>
                        <label className="text-[11px] cursor-pointer border rounded px-2 py-1 hover:bg-gray-50 flex items-center gap-1">
                          <Upload className="w-3 h-3" /> 上传圈包手法
                          <input type="file" accept=".xlsx,.xls,.csv,.doc,.docx,.pdf,.txt" className="hidden" onChange={async (e) => {
                            const f = e.target.files?.[0]; e.target.value = ''
                            if (!f) return
                            try { await uploadAudienceTargeting(aid, f); showTip('圈包文件已上传'); void load() }
                            catch (err) { setError(String(err)) }
                          }} />
                        </label>
                        {(a.audience_profile_file || a.targeting_method_file) ? (
                          <span className="text-[10px] text-gray-400">
                            附件: {String(a.audience_profile_file || '—')} / {String(a.targeting_method_file || '—')}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  )
                })}
                {/* Add audience */}
                <div className="rounded-lg border border-dashed border-gray-200 p-3">
                  <div className="flex flex-wrap gap-2 items-end">
                    <div className="flex-1 min-w-[140px]">
                      <span className="text-[10px] text-gray-400">名称</span>
                      <Input className="h-8 text-sm" value={audForm.name} onChange={(e) => setAudForm((f) => ({ ...f, name: e.target.value }))} placeholder="人群包名称" />
                    </div>
                    <div className="flex-1 min-w-[140px]">
                      <span className="text-[10px] text-gray-400">描述</span>
                      <Input className="h-8 text-sm" value={audForm.description} onChange={(e) => setAudForm((f) => ({ ...f, description: e.target.value }))} placeholder="可选" />
                    </div>
                    <div className="flex-1 min-w-[140px]">
                      <span className="text-[10px] text-gray-400">标签（逗号分隔）</span>
                      <Input className="h-8 text-sm" value={audForm.tags} onChange={(e) => setAudForm((f) => ({ ...f, tags: e.target.value }))} placeholder="如：年轻女性,高消费" />
                    </div>
                    <Button size="sm" className="h-8 gap-1" onClick={() => void addAudience()}>
                      <Plus className="w-3 h-3" /> 添加
                    </Button>
                  </div>
                </div>
              </div>
            </Section>

            {/* ─── Section 3: CSV Import ─── */}
            <Section title="导入数据" defaultOpen={materials.length === 0}>
              <div className="pt-3">
                <div className="rounded-lg border border-blue-100 bg-blue-50/30 p-3 space-y-3">
                  <div className="text-xs font-medium text-blue-800">导入千川 CSV</div>
                  <div className="flex flex-wrap gap-2 items-center">
                    <select className="h-8 rounded-md border px-2 text-xs min-w-[140px]" value={csvAudience} onChange={(e) => setCsvAudience(e.target.value)}>
                      <option value="">选择目标人群包</option>
                      {audienceOptions.map((a) => <option key={String(a.id)} value={String(a.id)}>{String(a.name)}</option>)}
                    </select>
                    <label className="h-8 px-3 rounded-md border bg-white text-xs flex items-center gap-1 cursor-pointer hover:bg-gray-50">
                      <Upload className="w-3 h-3" /> {csvFile ? csvFile.name : '选择千川文件'}
                      <input type="file" accept=".csv,.xlsx,.xlsm,.CSV,.XLSX,.XLSM" className="hidden" onChange={(e) => { setCsvFile(e.target.files?.[0] || null); setCsvPreview(null) }} />
                    </label>
                    <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => void runPreview()} disabled={!csvFile || !csvAudience}>预览</Button>
                    {csvPreview && (
                      <Button size="sm" className="h-8 text-xs" onClick={() => void runImport()} disabled={importing}>
                        {importing ? '导入中…' : '确认导入'}
                      </Button>
                    )}
                  </div>
                  {csvPreview && (
                    <div className="overflow-x-auto">
                      <div className="text-[10px] text-gray-500 mb-1">
                        识别到 {csvPreview.columns.length} 列，预览前 {csvPreview.sample_rows.length} 行
                        {Object.keys(csvPreview.mapped_columns).length > 0 && (
                          <span className="ml-2 text-green-600">
                            已映射: {Object.entries(csvPreview.mapped_columns).map(([k, v]) => `${k}→${v}`).join(', ')}
                          </span>
                        )}
                      </div>
                      <table className="w-full text-[11px] border-collapse">
                        <thead><tr className="bg-gray-100">
                          {csvPreview.columns.map((col, i) => (
                            <th key={i} className="border border-gray-200 px-2 py-1 text-left font-medium whitespace-nowrap">{col}</th>
                          ))}
                        </tr></thead>
                        <tbody>
                          {csvPreview.sample_rows.map((row, ri) => (
                            <tr key={ri} className="hover:bg-gray-50">
                              {(row as unknown[]).map((cell, ci) => (
                                <td key={ci} className="border border-gray-200 px-2 py-1 whitespace-nowrap max-w-[200px] truncate">{String(cell ?? '')}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            </Section>

            {/* ─── Section 4: Materials (grouped by audience → style group → chain) ─── */}
            {audiences.map((aud) => {
              const aid = String(aud.id)
              const audMats = matsByAudience[aid] || []
              const audGroups = groupsByAudience[aid] || []

              if (audMats.length === 0 && audGroups.length === 0) return null

              const groupedMats = audMats.filter((m) => m.group_id)
              const ungroupedMats = audMats.filter((m) => !m.group_id)

              return (
                <Section key={aid} title={`${String(aud.name)} 素材`} badge={`${audMats.length} 条`}
                  actions={
                    <Button size="sm" variant="ghost" className="h-7 text-xs gap-1"
                      onClick={(e) => { e.stopPropagation(); setNewGroupAud(aid); setNewGroupLabel('') }}>
                      <Layers className="w-3 h-3" /> 新建风格组
                    </Button>
                  }
                >
                  <div className="pt-3 space-y-4">
                    {/* Style groups */}
                    {audGroups.map((g) => {
                      const gid = String(g.id)
                      const gMats = groupedMats.filter((m) => String(m.group_id) === gid)
                      const chains = buildChains(gMats)
                      return (
                        <div key={gid} className="rounded-lg border border-indigo-100 bg-indigo-50/20 overflow-hidden">
                          <div className="flex items-center justify-between px-3 py-2 border-b border-indigo-100">
                            <div className="flex items-center gap-2">
                              <Layers className="w-3.5 h-3.5 text-indigo-500" />
                              <span className="text-sm font-semibold text-indigo-900">{String(g.style_label)}</span>
                              {(() => {
                                const p = PURPOSE_CFG[String(g.video_purpose || 'seeding')]
                                return p ? <span className={`text-[10px] px-1.5 py-0.5 rounded border ${p.color}`}>{p.label}</span> : null
                              })()}
                              <span className="text-[10px] text-indigo-400">{gMats.length} 条 · {chains.length} 个变种</span>
                            </div>
                            <button className="text-[10px] text-red-400 hover:text-red-600 px-1" onClick={() => void doDeleteGroup(gid)}>
                              删除组
                            </button>
                          </div>
                          <div className="px-3 py-2 space-y-3">
                            {chains.length === 0 && (
                              <div className="text-xs text-gray-400 py-2 text-center">暂无素材，从「未分组」中选择素材移入</div>
                            )}
                            {chains.map((chain, ci) => (
                              <div key={ci} className={ci > 0 ? 'border-t border-indigo-100/50 pt-2' : ''}>
                                <ChainView chain={chain} purpose={String(g.video_purpose || 'seeding')} />
                              </div>
                            ))}
                            <GroupInsight chains={chains} />
                          </div>
                        </div>
                      )
                    })}

                    {/* Ungrouped */}
                    {ungroupedMats.length > 0 && (
                      <div className="rounded-lg border border-dashed border-gray-200 overflow-hidden">
                        <div className="flex items-center justify-between px-3 py-2 bg-gray-50/50 border-b border-gray-100">
                          <span className="text-xs font-medium text-gray-500">未分组（{ungroupedMats.length} 条）</span>
                          {selected.size > 0 && audGroups.length > 0 && (
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] text-gray-500">已选 {selected.size} 条 →</span>
                              <select className="h-7 rounded border px-1.5 text-xs" value={batchTarget} onChange={(e) => setBatchTarget(e.target.value)}>
                                <option value="">选择风格组</option>
                                {audGroups.map((g) => <option key={String(g.id)} value={String(g.id)}>{String(g.style_label)}</option>)}
                              </select>
                              <Button size="sm" variant="outline" className="h-7 text-xs gap-1" onClick={() => void doBatchGroup()} disabled={!batchTarget}>
                                <Check className="w-3 h-3" /> 移入
                              </Button>
                            </div>
                          )}
                        </div>
                        <div className="px-3 py-2 divide-y divide-gray-50">
                          {ungroupedMats.map((m) => (
                            <MatRow key={String(m.id)} m={m} showCheckbox={audGroups.length > 0} />
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Inline new group */}
                    {newGroupAud === aid && (
                      <div className="flex gap-2 items-end flex-wrap">
                        <div className="flex-1 min-w-[120px]">
                          <span className="text-[10px] text-gray-400">风格组名称</span>
                          <Input className="h-8 text-sm" value={newGroupLabel} onChange={(e) => setNewGroupLabel(e.target.value)}
                            placeholder="如：种草类、剧情类、口播类" autoFocus />
                        </div>
                        <div className="w-[110px]">
                          <span className="text-[10px] text-gray-400">投放目的</span>
                          <select className="w-full h-8 text-sm border rounded px-2 bg-white"
                            value={newGroupPurpose} onChange={(e) => setNewGroupPurpose(e.target.value)}>
                            <option value="organic">自然流量</option>
                            <option value="seeding">种草</option>
                            <option value="conversion">转化</option>
                          </select>
                        </div>
                        <Button size="sm" className="h-8" onClick={() => void doCreateGroup()}>创建</Button>
                        <Button size="sm" variant="ghost" className="h-8" onClick={() => setNewGroupAud(null)}>取消</Button>
                      </div>
                    )}
                  </div>
                </Section>
              )
            })}

            {/* ─── Section: Iteration Relation Graph ─── */}
            {(() => {
              const allChains = buildChains(materials).filter((c) => c.length >= 2)
              if (allChains.length === 0) return null
              const audMap: Record<string, string> = {}
              for (const a of audiences) audMap[String(a.id)] = String(a.name)
              return (
                <Section title="迭代关系图" badge={`${allChains.length} 条迭代链`}>
                  <div className="pt-3 space-y-5">
                    {allChains.map((chain, ci) => {
                      const rootAud = audMap[String(chain[0].audience_pack_id)] || ''
                      return (
                        <div key={ci}>
                          <div className="flex items-center gap-2 mb-2">
                            <GitBranch className="w-3.5 h-3.5 text-amber-600" />
                            <span className="text-xs font-semibold text-gray-700">
                              {String(chain[0].name)} → {chain.length} 个版本
                            </span>
                            {rootAud && <span className="text-[10px] text-gray-400">({rootAud})</span>}
                            <Button variant="ghost" size="sm" className="h-6 text-[10px] gap-1" onClick={() => setTreeChain(chain)}>
                              <Eye className="w-3 h-3" /> 查看迭代树
                            </Button>
                          </div>
                          <IterationGraph chain={chain} />
                        </div>
                      )
                    })}
                  </div>
                </Section>
              )
            })()}

            {/* ─── Bottom CTA ─── */}
            <div className="flex justify-center pt-4">
              <Button size="lg" className="gap-2 px-8" onClick={() => router.push(`/ad-review/${id}/review`)}>
                <FileText className="w-4 h-4" />
                生成复盘报告
              </Button>
            </div>
          </>
        )}
      </main>

      {/* ── Video Picker Dialog ── */}
      <Dialog open={videoOpen} onOpenChange={setVideoOpen}>
        <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
          <DialogHeader><DialogTitle>上传并选择视频分析结果</DialogTitle></DialogHeader>
          <div className="flex items-center justify-between gap-2 pb-1">
            <label className="text-xs cursor-pointer border rounded px-2.5 py-1.5 hover:bg-gray-50 flex items-center gap-1.5">
              <Upload className="w-3 h-3" />
              {videoUploading ? '上传中…' : '上传短视频'}
              <input
                type="file"
                accept="video/*,.mp4,.mov,.avi,.mkv,.MP4,.MOV,.AVI,.MKV"
                className="hidden"
                onChange={async (e) => {
                  const f = e.target.files?.[0] || null
                  e.target.value = ''
                  await onUploadVideo(f)
                }}
              />
            </label>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 text-xs gap-1"
              onClick={() => void refreshVideos()}
              disabled={videoRefreshing}
            >
              <RefreshCw className={`w-3 h-3 ${videoRefreshing ? 'animate-spin' : ''}`} />
              刷新状态
            </Button>
          </div>
          <div className="space-y-1">
            {videos.length === 0 && <p className="text-sm text-gray-400 py-4 text-center">暂无视频分析记录</p>}
            {videos.map((v) => {
              const vid = String(v.id)
              const meta = videoMeta[vid]
              const status = String(v.status || '')
              const selectable = status === 'done'
              return (
                <button key={vid} type="button"
                  className={`w-full text-left border rounded-lg p-2.5 text-sm flex items-center justify-between ${
                    selectable ? 'hover:bg-gray-50' : 'opacity-70 cursor-not-allowed'
                  }`}
                  disabled={!selectable}
                  onClick={() => void confirmVideo(vid)}>
                  <div>
                    <div className="font-medium">{String(v.original_name || v.id)}</div>
                    <div className="text-xs text-gray-400">
                      {status === 'done' ? '分析完成，可关联' : status === 'failed' ? '分析失败' : '分析中，请稍后刷新'}
                    </div>
                  </div>
                  {meta?.overall != null && (
                    <span className="text-xs bg-purple-50 text-purple-700 px-2 py-0.5 rounded">{meta.overall}/10</span>
                  )}
                </button>
              )
            })}
          </div>
        </DialogContent>
      </Dialog>

      {/* ── CSV Video Upload Wizard (Feature 1) ── */}
      <Dialog open={wizardOpen} onOpenChange={(o) => { if (!o) closeWizard() }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>为素材上传对应视频 ({wizardIdx + 1}/{wizardMats.length})</DialogTitle>
          </DialogHeader>
          {(() => {
            const mat = wizardMats[wizardIdx]
            if (!mat) return null
            const vid = wizardVideoIds[String(mat.id)]
            return (
              <div className="space-y-3">
                <div className="text-sm font-medium">{String(mat.name)}</div>
                <div className="flex gap-4 text-xs text-gray-500">
                  <span>{fmtCost(mat.cost)}</span>
                  <span>CTR {fmtCtr(mat.ctr)}</span>
                </div>
                {vid ? (
                  <div className="text-xs text-amber-600 py-3 text-center">分析中…</div>
                ) : (
                  <label className="block text-xs border rounded-lg p-4 text-center cursor-pointer hover:bg-gray-50">
                    <Upload className="w-5 h-5 mx-auto mb-1 text-gray-400" />
                    {wizardUploading ? '上传中…' : '选择视频文件'}
                    <input type="file" accept="video/*" className="hidden" disabled={wizardUploading}
                      onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void wizardUpload(f) }} />
                  </label>
                )}
                <div className="flex justify-between pt-2">
                  <Button variant="ghost" size="sm"
                    onClick={() => { if (wizardIdx < wizardMats.length - 1) setWizardIdx((i) => i + 1); else closeWizard() }}>
                    跳过
                  </Button>
                  <div className="flex gap-2">
                    {wizardIdx < wizardMats.length - 1 && (
                      <Button variant="outline" size="sm" onClick={() => setWizardIdx((i) => i + 1)}>下一条</Button>
                    )}
                    <Button size="sm" onClick={closeWizard}>全部完成</Button>
                  </div>
                </div>
              </div>
            )
          })()}
        </DialogContent>
      </Dialog>

      {/* ── Material Detail Dialog (Feature 2) ── */}
      <Dialog open={!!detailMat} onOpenChange={(o) => { if (!o) { setDetailMat(null); setDetailReport(null); setDetailTab('scores') } }}>
        <DialogContent className="max-w-[95vw] w-[95vw] h-[92vh] flex flex-col overflow-hidden">
          <DialogHeader><DialogTitle>素材详情 — {String(detailMat?.name)}</DialogTitle></DialogHeader>
          {detailMat && (() => {
            const hasVideo = !!detailMat.video_analysis_id
            const parent = detailMat.parent_material_id
              ? materials.find((mm) => String(mm.id) === String(detailMat.parent_material_id)) : null

            const report = detailReport
            const rScores = report ? (report.scores || {}) as Record<string, unknown> : null
            const rDims = rScores ? (rScores.dimensions || {}) as Record<string, unknown> : {}
            const dimLabels: Record<string, string> = {
              hook_power: '钩子力', content_value: '内容价值',
              visual_quality: '画面质量', editing_rhythm: '剪辑节奏',
              audio_bgm: '音频BGM', copy_script: '文案脚本',
              interaction_design: '互动设计', algorithm_friendliness: '算法友好',
              commercial_potential: '商业潜力',
            }
            const scoreColor = (s: number) => s >= 8 ? 'bg-green-500' : s >= 6 ? 'bg-blue-500' : s >= 4 ? 'bg-amber-500' : 'bg-red-500'
            const urgencyBadge = (u: unknown) => {
              const s = String(u ?? '').toLowerCase()
              if (s.includes('high') || s.includes('高')) return 'bg-red-100 text-red-700 border-red-200'
              if (s.includes('medium') || s.includes('中')) return 'bg-amber-100 text-amber-700 border-amber-200'
              return 'bg-green-100 text-green-700 border-green-200'
            }

            const tabs = [
              { key: 'scores', label: '评分总览' },
              { key: 'summary', label: '视频概述' },
              { key: 'visual', label: '画面分析' },
              { key: 'bgm_audio', label: '音频BGM' },
              { key: 'editing_rhythm', label: '剪辑节奏' },
              { key: 'copy_logic', label: '文案脚本' },
              { key: 'interaction_algo', label: '互动算法' },
              { key: 'business_strategy', label: '商业策略' },
              { key: 'douyin_specific', label: '抖音分析' },
              { key: 'improvements', label: '改进建议' },
            ]

            return (
              <div className="space-y-4">
                {/* Row 1: Video + Data cards */}
                <div className="grid md:grid-cols-2 gap-4">
                  <div>
                    {hasVideo ? (
                      <video controls className="w-full rounded-lg bg-black"
                        src={`/api/omni/video-analysis/videos/${detailMat.video_analysis_id}/original`} />
                    ) : (
                      <div className="w-full aspect-video bg-gray-100 rounded-lg flex items-center justify-center text-sm text-gray-400">
                        <Play className="w-5 h-5 mr-1" />无关联视频
                      </div>
                    )}
                    {parent && (
                      <div className="mt-2 text-xs border rounded p-2 text-gray-500">
                        父素材：{String(parent.name)} v{String(parent.version || 1)}
                        <span className="ml-2">CTR {fmtCtr(parent.ctr)}</span>
                        {delta(detailMat.ctr, parent.ctr) && (
                          <span className={`ml-1 ${delta(detailMat.ctr, parent.ctr)!.cls}`}>{delta(detailMat.ctr, parent.ctr)!.text}</span>
                        )}
                        <span className="ml-2">转化率 {fmtPct(parent.conversion_rate)}</span>
                        {delta(detailMat.conversion_rate, parent.conversion_rate) && (
                          <span className={`ml-1 ${delta(detailMat.conversion_rate, parent.conversion_rate)!.cls}`}>{delta(detailMat.conversion_rate, parent.conversion_rate)!.text}</span>
                        )}
                      </div>
                    )}
                  </div>
                  <div>
                    <div className="text-xs font-medium text-gray-600 mb-2">千川投放数据</div>
                    <div className="grid grid-cols-5 gap-1.5 text-xs">
                      {([
                        ['消耗', detailMat.cost, 'cost'],
                        ['展示次数', detailMat.impressions, 'int'],
                        ['点击次数', detailMat.clicks, 'int'],
                        ['CPM', detailMat.cpm, 'money'],
                        ['CPC', detailMat.cpc, 'money'],
                        ['点击率', detailMat.ctr, 'pct'],
                        ['转化数', detailMat.conversions, 'int'],
                        ['转化率', detailMat.conversion_rate, 'pct'],
                        ['转化成本', detailMat.cost_per_result, 'money'],
                        ['播放次数', detailMat.plays, 'int'],
                        ['完播率', detailMat.completion_rate, 'pct'],
                        ['3秒播放率', detailMat.play_3s_rate, 'pct'],
                        ['3秒播放数', detailMat.play_3s, 'int'],
                        ['25%进度播放率', detailMat.play_25pct_rate, 'pct'],
                        ['50%进度播放率', detailMat.play_50pct_rate, 'pct'],
                        ['75%进度播放率', detailMat.play_75pct_rate, 'pct'],
                        ['25%进度播放数', detailMat.play_25pct, 'int'],
                        ['50%进度播放数', detailMat.play_50pct, 'int'],
                        ['75%进度播放数', detailMat.play_75pct, 'int'],
                        ['评论次数', detailMat.comments, 'int'],
                        ['分享次数', detailMat.shares_7d, 'int'],
                        ['新增关注', detailMat.new_followers, 'int'],
                        ['成交额', detailMat.direct_pay_amount, 'money'],
                        ['ROI', detailMat.direct_pay_roi, 'decimal'],
                        ['7日新增A3', detailMat.new_a3, 'int'],
                        ['A3成本', detailMat.a3_cost, 'money'],
                        ['A3率', detailMat.a3_ratio, 'pct'],
                        ['前展', detailMat.front_impressions, 'int'],
                        ['互动率', detailMat.interaction_rate, 'pct'],
                      ] as [string, unknown, string][])
                        .filter(([, v]) => v != null)
                        .map(([label, val, fmt]) => {
                          let display = '—'
                          if (val != null) {
                            if (fmt === 'cost' || fmt === 'money') display = `¥${Number(val).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                            else if (fmt === 'pct') display = `${(Number(val) * 100).toFixed(2)}%`
                            else if (fmt === 'int') display = Number(val).toLocaleString()
                            else if (fmt === 'decimal') display = Number(val).toFixed(2)
                            else display = String(val)
                          }
                          return (
                            <div key={label} className="border rounded px-2 py-1.5">
                              <div className="text-gray-400 text-[10px]">{label}</div>
                              <div className="font-semibold text-gray-800">{display}</div>
                            </div>
                          )
                        })}
                    </div>
                  </div>
                </div>

                {/* Row 2: Tabbed report sections */}
                {hasVideo && (
                  <div className="border rounded-lg overflow-hidden">
                    {detailReport === null ? (
                      <div className="text-xs text-gray-400 py-6 text-center">报告加载中…</div>
                    ) : detailReport === undefined ? (
                      <div className="text-xs text-gray-400 py-6 text-center">无视频分析报告</div>
                    ) : (
                      <>
                        <div className="flex border-b overflow-x-auto bg-gray-50">
                          {tabs.map((t) => (
                            <button key={t.key}
                              className={`shrink-0 px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
                                detailTab === t.key
                                  ? 'border-indigo-600 text-indigo-700 bg-white'
                                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-100'
                              }`}
                              onClick={() => setDetailTab(t.key)}>
                              {t.label}
                            </button>
                          ))}
                        </div>

                        <div className="p-4 text-xs space-y-3">
                          {/* Tab: 评分总览 */}
                          {detailTab === 'scores' && (() => {
                            const overall = Number(rScores?.overall ?? 0)
                            const dimEntries = Object.entries(rDims) as [string, unknown][]
                            return (
                              <div className="space-y-4">
                                <div className="flex items-center gap-4">
                                  <div className="flex flex-col items-center justify-center w-24 h-24 rounded-full border-4 border-purple-200 bg-purple-50">
                                    <span className="text-2xl font-bold text-purple-700">{overall || '—'}</span>
                                    <span className="text-[10px] text-purple-500">/ 10</span>
                                  </div>
                                  <div className="text-sm text-gray-600">综合评分</div>
                                </div>
                                <div className="space-y-2">
                                  {dimEntries.map(([key, raw]) => {
                                    const d = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
                                    const s = Number(d.score ?? 0)
                                    return (
                                      <div key={key} className="space-y-0.5">
                                        <div className="flex justify-between items-center">
                                          <span className="text-gray-700 font-medium">{dimLabels[key] || key}</span>
                                          <span className="font-semibold">{s}/10</span>
                                        </div>
                                        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                                          <div className={`h-full rounded-full transition-all ${scoreColor(s)}`} style={{ width: `${s * 10}%` }} />
                                        </div>
                                        {!!d.brief && <div className="text-[10px] text-gray-400">{String(d.brief)}</div>}
                                      </div>
                                    )
                                  })}
                                </div>
                              </div>
                            )
                          })()}

                          {/* Tab: 视频概述 */}
                          {detailTab === 'summary' && (
                            <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                              {String(report?.summary ?? '暂无概述')}
                            </div>
                          )}

                          {/* Tab: 画面分析 */}
                          {detailTab === 'visual' && (
                            <div className="space-y-1">{renderObj(report?.visual)}</div>
                          )}

                          {/* Tab: 音频BGM */}
                          {detailTab === 'bgm_audio' && (
                            <div className="space-y-1">{renderObj(report?.bgm_audio)}</div>
                          )}

                          {/* Tab: 剪辑节奏 */}
                          {detailTab === 'editing_rhythm' && (
                            <div className="space-y-1">{renderObj(report?.editing_rhythm)}</div>
                          )}

                          {/* Tab: 文案脚本 */}
                          {detailTab === 'copy_logic' && (
                            <div className="space-y-1">{renderObj(report?.copy_logic)}</div>
                          )}

                          {/* Tab: 互动算法 */}
                          {detailTab === 'interaction_algo' && (
                            <div className="space-y-1">{renderObj(report?.interaction_algo)}</div>
                          )}

                          {/* Tab: 商业策略 */}
                          {detailTab === 'business_strategy' && (
                            <div className="space-y-1">{renderObj(report?.business_strategy)}</div>
                          )}

                          {/* Tab: 抖音分析 */}
                          {detailTab === 'douyin_specific' && (
                            <div className="space-y-1">{renderObj(report?.douyin_specific)}</div>
                          )}

                          {/* Tab: 改进建议 */}
                          {detailTab === 'improvements' && (() => {
                            const imp = (report?.improvement_suggestions || {}) as Record<string, unknown>
                            const actions = Array.isArray(imp.priority_actions) ? (imp.priority_actions as Record<string, unknown>[]) : []
                            const copyRewrite = (imp.copy_rewrite || {}) as Record<string, unknown>
                            const sugTitles = Array.isArray(copyRewrite.suggested_titles) ? (copyRewrite.suggested_titles as unknown[]) : []
                            const editSugs = Array.isArray(imp.editing_suggestions)
                              ? ([...(imp.editing_suggestions as Record<string, unknown>[])].sort((a, b) => Number(a.timestamp_sec ?? 0) - Number(b.timestamp_sec ?? 0)))
                              : []
                            const algoOpt = Array.isArray(imp.algorithm_optimization) ? (imp.algorithm_optimization as unknown[]) : []
                            const abTests = Array.isArray(imp.a_b_test_suggestions) ? (imp.a_b_test_suggestions as Record<string, unknown>[]) : []

                            return (
                              <div className="space-y-4">
                                {actions.length > 0 && (
                                  <div>
                                    <div className="font-medium text-gray-700 mb-2">优先行动</div>
                                    <div className="space-y-1.5">
                                      {actions.map((a, i) => (
                                        <div key={i} className="flex items-start gap-2 border rounded p-2">
                                          <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded border font-medium ${urgencyBadge(a.urgency)}`}>
                                            {String(a.urgency ?? '—')}
                                          </span>
                                          <div className="min-w-0">
                                            {!!a.category && <span className="font-medium text-gray-700 mr-1">[{String(a.category)}]</span>}
                                            {!!a.current_issue && <div className="text-gray-500">问题：{String(a.current_issue)}</div>}
                                            {!!a.suggestion && <div className="text-gray-800">{String(a.suggestion)}</div>}
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {(!!copyRewrite.original_title || sugTitles.length > 0) && (
                                  <div>
                                    <div className="font-medium text-gray-700 mb-2">文案改写</div>
                                    {!!copyRewrite.original_title && (
                                      <div className="text-gray-500 mb-1">原标题：{String(copyRewrite.original_title)}</div>
                                    )}
                                    {sugTitles.length > 0 && (
                                      <div className="space-y-0.5">
                                        {sugTitles.map((t, i) => (
                                          <div key={i} className="flex items-center gap-2">
                                            <span className="text-[10px] text-indigo-500 shrink-0">建议{i + 1}</span>
                                            <span className="text-gray-800">{String(t)}</span>
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )}

                                {editSugs.length > 0 && (
                                  <div>
                                    <div className="font-medium text-gray-700 mb-2">剪辑建议</div>
                                    <div className="space-y-1">
                                      {editSugs.map((e, i) => (
                                        <div key={i} className="flex gap-2 border rounded p-2">
                                          <span className="shrink-0 font-mono text-[10px] bg-gray-100 rounded px-1.5 py-0.5">
                                            {Number(e.timestamp_sec ?? 0).toFixed(1)}s
                                          </span>
                                          <span className="text-gray-800">{String(e.suggestion ?? '')}</span>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}

                                {algoOpt.length > 0 && (
                                  <div>
                                    <div className="font-medium text-gray-700 mb-2">算法优化建议</div>
                                    <ul className="list-disc ml-4 space-y-0.5">
                                      {algoOpt.map((tip, i) => <li key={i} className="text-gray-800">{String(tip)}</li>)}
                                    </ul>
                                  </div>
                                )}

                                {abTests.length > 0 && (
                                  <div>
                                    <div className="font-medium text-gray-700 mb-2">A/B 测试建议</div>
                                    <table className="w-full border-collapse text-xs">
                                      <thead>
                                        <tr className="bg-gray-50">
                                          <th className="border px-2 py-1 text-left font-medium">变量</th>
                                          <th className="border px-2 py-1 text-left font-medium">版本 A</th>
                                          <th className="border px-2 py-1 text-left font-medium">版本 B</th>
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {abTests.map((t, i) => (
                                          <tr key={i} className="hover:bg-gray-50">
                                            <td className="border px-2 py-1">{String(t.variable ?? '')}</td>
                                            <td className="border px-2 py-1">{String(t.version_a ?? '')}</td>
                                            <td className="border px-2 py-1">{String(t.version_b ?? '')}</td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                )}

                                {actions.length === 0 && sugTitles.length === 0 && editSugs.length === 0 && algoOpt.length === 0 && abTests.length === 0 && (
                                  <div className="text-gray-400 py-2">暂无改进建议</div>
                                )}
                              </div>
                            )
                          })()}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })()}
          <DialogFooter>
            {!!detailMat?.video_analysis_id && (
              <Button variant="outline" size="sm" onClick={async () => {
                await linkVideo(String(detailMat!.id), null); setDetailMat(null); setDetailReport(null); void load()
              }}>解除视频关联</Button>
            )}
            <Button onClick={() => { setDetailMat(null); setDetailReport(null) }}>关闭</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Full-screen Iteration Tree (Feature 3) ── */}
      <Dialog open={!!treeChain} onOpenChange={(o) => { if (!o) setTreeChain(null) }}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader><DialogTitle>迭代树</DialogTitle></DialogHeader>
          {treeChain && (
            <div className="flex flex-col items-center gap-0 py-4">
              {treeChain.map((m, idx) => {
                const prev = idx > 0 ? treeChain[idx - 1] : null
                const ctags = Array.isArray(m.change_tags) ? (m.change_tags as string[]) : []
                const sc = m.video_analysis_scores as { overall?: number } | null | undefined
                const ov = sc && typeof sc === 'object' && typeof sc.overall === 'number' ? sc.overall : null
                const isRoot = idx === 0
                const isLatest = idx === treeChain.length - 1
                const borderCls = isRoot ? 'border-gray-300' : isLatest ? 'border-green-400 bg-green-50/20' : 'border-amber-300 bg-amber-50/20'
                return (
                  <div key={String(m.id)} className="flex flex-col items-center">
                    {idx > 0 && (
                      <div className="flex flex-col items-center py-1">
                        <ArrowDown className="w-4 h-4 text-gray-400" />
                        <div className="flex gap-1 flex-wrap justify-center">
                          {ctags.map((t, i) => (
                            <span key={i} className="text-[9px] bg-indigo-50 text-indigo-600 px-1 py-0.5 rounded">{t}</span>
                          ))}
                          {prev && delta(m.ctr, prev.ctr) && (
                            <span className={`text-[9px] px-1 ${delta(m.ctr, prev.ctr)!.cls}`}>CTR {delta(m.ctr, prev.ctr)!.text}</span>
                          )}
                        </div>
                      </div>
                    )}
                    <button className={`w-64 rounded-lg border-2 p-3 text-left ${borderCls} hover:shadow-md transition-shadow`}
                      onClick={() => { setDetailMat(m); setTreeChain(null) }}>
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className="text-xs font-semibold truncate">{String(m.name)}</span>
                        <span className="text-[10px] bg-gray-100 px-1 rounded">v{String(m.version || 1)}</span>
                      </div>
                      <div className="grid grid-cols-2 gap-1 text-[10px] text-gray-600">
                        <span>{fmtCost(m.cost)}</span><span>CTR {fmtCtr(m.ctr)}</span>
                        <span>完播 {fmtPct(m.completion_rate)}</span><span>A3 {m.new_a3 != null ? String(m.new_a3) : '—'}</span>
                      </div>
                      {ov != null && <div className="text-[10px] text-purple-600 mt-1">评分 {ov}/10</div>}
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ── Parent Link Dialog (enhanced with change_tags) ── */}
      <Dialog open={parentOpen} onOpenChange={setParentOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>标记为优化迭代版本</DialogTitle></DialogHeader>
          <div className="grid gap-3">
            <div>
              <span className="text-xs text-gray-500">父素材（原版或上一版）</span>
              <select className="w-full h-9 rounded-md border px-2 text-sm" value={parentPick} onChange={(e) => setParentPick(e.target.value)}>
                <option value="">选择原版素材</option>
                {materials.filter((m) => String(m.id) !== parentMat).map((m) => (
                  <option key={String(m.id)} value={String(m.id)}>
                    {String(m.name)}{Number(m.version || 1) > 1 ? ` (v${m.version})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <span className="text-xs text-gray-500">本次变更（可多选）</span>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {CHANGE_TAG_OPTIONS.map((tag) => (
                  <button key={tag} type="button"
                    className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                      parentTags.includes(tag) ? 'bg-indigo-100 border-indigo-300 text-indigo-700' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                    }`}
                    onClick={() => setParentTags((prev) => prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag])}
                  >
                    {parentTags.includes(tag) && <Check className="w-3 h-3 inline mr-0.5" />}
                    {tag}
                  </button>
                ))}
              </div>
            </div>
            {parentHint && (
              <div className="text-xs bg-amber-50 border border-amber-200 rounded p-2 text-amber-700">
                <span className="font-medium">AI 建议：</span>{parentHint}
              </div>
            )}
            {parentEvidenceFields.length > 0 && (
              <div className="text-xs bg-indigo-50 border border-indigo-200 rounded p-2 text-indigo-700">
                <span className="font-medium">证据字段：</span>
                <span className="ml-1">{parentEvidenceFields.join(', ')}</span>
              </div>
            )}
            <div>
              <span className="text-xs text-gray-500">优化说明</span>
              <Input value={parentNote} onChange={(e) => setParentNote(e.target.value)} placeholder="如：修改了开头3秒钩子，增加价格锚点" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setParentOpen(false)}>取消</Button>
            <Button onClick={() => void confirmParent()} disabled={!parentPick}>确认</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
