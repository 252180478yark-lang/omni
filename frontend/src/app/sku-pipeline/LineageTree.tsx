'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Loader2, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'

// ───────────────────────────────────────────────────────────────
// 节点类型（对应后端 get_sku_lineage 返回结构）
// ───────────────────────────────────────────────────────────────
interface AssetNode {
  id: string
  asset_type: string
  scene_no: number | null
  status: string
  file_url: string | null
  thumbnail_url: string | null
  external_video_id: string | null
  created_at: string
}
interface ScriptNode {
  id: string
  kind: string
  version: number
  status: string
  target_purpose: string | null
  model: string | null
  created_at: string
  assets: AssetNode[]
}
interface PackNode {
  id: string
  version: number
  status: string
  model: string | null
  created_at: string
  scripts: ScriptNode[]
}
interface RecordNode {
  id: string
  ordinal: number
  name: string
  kb_doc: string | null
  layer_tags: string[]
  status: string
  selected_for_pack: boolean
  created_at: string
  audience_packs: PackNode[]
  scripts_direct: ScriptNode[]
}
interface AudienceRunNode {
  id: string
  version: number
  status: string
  record_count: number
  model: string | null
  created_at: string
  audience_records: RecordNode[]
}
interface MatrixRunNode {
  id: string
  version: number
  status: string
  model: string | null
  created_at: string
  audience_runs: AudienceRunNode[]
}
interface LineageData {
  ok: boolean
  sku_id: string
  matrix_runs: MatrixRunNode[]
  orphan_packs: PackNode[]
  orphan_scripts: ScriptNode[]
  orphan_assets: AssetNode[]
  counts: Record<string, number>
}

// 4 类节点可被 pick 模式选中（assets phase D 起开放）
export type PickableNode = {
  kind: 'matrix_run' | 'audience_run' | 'audience_record' | 'audience_pack' | 'script' | 'asset'
  id: string
  label: string
  status: string
}

// 6 层 accent color（左边框粗条 4px，一眼分清层）+ 中文 label
const LAYER_ACCENT: Record<PickableNode['kind'], { border: string; dot: string; icon: string; label: string }> = {
  matrix_run:      { border: 'border-l-purple-500',  dot: 'bg-purple-500',  icon: '◆', label: '卖点矩阵' },
  audience_run:    { border: 'border-l-orange-500',  dot: 'bg-orange-500',  icon: '◇', label: '人群匹配' },
  audience_record: { border: 'border-l-amber-500',   dot: 'bg-amber-500',   icon: '●', label: '候选人群' },
  audience_pack:   { border: 'border-l-pink-500',    dot: 'bg-pink-500',    icon: '▲', label: '圈包' },
  script:          { border: 'border-l-cyan-500',    dot: 'bg-cyan-500',    icon: '▼', label: '创意脚本' },
  asset:           { border: 'border-l-slate-500',   dot: 'bg-slate-500',   icon: '★', label: '素材资产' },
}

// status 中文（数据库 enum 直显）
const STATUS_LABEL: Record<string, string> = {
  draft:     '草稿',
  adopted:   '已采纳',
  published: '已发布',
  discarded: '已废弃',
}
const statusText = (s: string): string => STATUS_LABEL[s] || s

// script kind 中文（跟 page.tsx CREATIVE_KIND_LIST 一致）
const SCRIPT_KIND_LABEL: Record<string, string> = {
  video_soft_ad:        '视频·软广',
  video_planting:       '视频·种草',
  video_harvest:        '视频·收割',
  graphic_harvest:      '图文·收割',
  product_main_image:   '商品·主图',
  product_detail_page:  '商品·详情页',
}
const scriptKindText = (k: string): string => SCRIPT_KIND_LABEL[k] || k

// asset_type 中文
const ASSET_TYPE_LABEL: Record<string, string> = {
  image: '图片',
  video: '视频',
}
const assetTypeText = (t: string): string => ASSET_TYPE_LABEL[t] || t

interface Props {
  skuId: string
  onPick?: (node: PickableNode) => void  // 传 = pick 模式（节点显示"← 选用作输入"按钮）
  pickKinds?: PickableNode['kind'][]      // pick 模式下哪些 kind 可点（默认 record + pack）
  onClose?: () => void                    // pick 完关闭模态
  height?: string                         // CSS height（默认 70vh）
}

// ───────────────────────────────────────────────────────────────
// 状态着色（draft 灰 / adopted 绿 / published 蓝 / discarded 红 / 其他默认）
// ───────────────────────────────────────────────────────────────
function statusColor(status: string): { border: string; bg: string; badge: 'default' | 'outline' | 'secondary' | 'destructive' } {
  switch (status) {
    case 'adopted':
      return { border: 'border-emerald-300 dark:border-emerald-800', bg: 'bg-emerald-50/40 dark:bg-emerald-950/20', badge: 'default' }
    case 'published':
      return { border: 'border-blue-300 dark:border-blue-800', bg: 'bg-blue-50/40 dark:bg-blue-950/20', badge: 'default' }
    case 'discarded':
      return { border: 'border-red-300 dark:border-red-800', bg: 'bg-red-50/40 dark:bg-red-950/20', badge: 'destructive' }
    case 'draft':
    default:
      return { border: 'border-gray-300 dark:border-gray-700', bg: 'bg-gray-50/40 dark:bg-gray-950/20', badge: 'outline' }
  }
}

function fmtDate(iso: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  } catch {
    return iso.slice(0, 16)
  }
}

// ───────────────────────────────────────────────────────────────
// 通用节点壳（折叠头 + 内容 + 操作按钮）
//   - 整行可点折叠（chevron + header 区都触发；actions stopPropagation）
//   - 左侧 4px layer accent 色条 + status 填色
//   - 子容器有左竖虚线，看出父子关系
// ───────────────────────────────────────────────────────────────
interface NodeShellProps {
  nodeKey: string
  status: string
  layer: PickableNode['kind']
  expanded: boolean
  onToggle: () => void
  header: React.ReactNode
  pickButton?: React.ReactNode
  adoptButton?: React.ReactNode
  archiveButton?: React.ReactNode
  children?: React.ReactNode  // 折叠内容
  childCount?: number
  hasChildren?: boolean       // 即使无 children 渲染，也可显示展开图标（懒加载场景）
}

function NodeShell({ status, layer, expanded, onToggle, header, pickButton, adoptButton, archiveButton, children, childCount, hasChildren }: NodeShellProps) {
  const c = statusColor(status)
  const accent = LAYER_ACCENT[layer]
  // 显示折叠图标条件：显式传 hasChildren 优先；否则按 childCount > 0；否则按 children 是否存在
  const showToggle = (hasChildren !== undefined)
    ? hasChildren
    : (childCount !== undefined ? childCount > 0 : !!children)
  return (
    <div className={`border-y border-r border-l-4 rounded-r ${accent.border} ${c.border} ${c.bg} transition-colors`}>
      <div
        className={`flex items-center gap-2 px-2 py-1.5 text-xs ${showToggle ? 'cursor-pointer hover:bg-muted/40' : ''} select-none`}
        onClick={showToggle ? onToggle : undefined}
      >
        <span className="shrink-0 w-4 flex items-center justify-center">
          {showToggle ? (
            expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />
          ) : (
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${accent.dot}`} />
          )}
        </span>
        <span className={`shrink-0 inline-flex items-center justify-center w-4 h-4 rounded text-[11px] text-white ${accent.dot}`} title={accent.label}>
          {accent.icon}
        </span>
        <div className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
          {header}
          {childCount !== undefined && childCount > 0 && (
            <span className="text-[10px] text-muted-foreground">({childCount})</span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
          {adoptButton}
          {pickButton}
          {archiveButton}
        </div>
      </div>
      {expanded && showToggle && children && (
        <div className="ml-3 pl-3 border-l-2 border-dashed border-muted-foreground/20 py-1.5 pr-1 space-y-1.5">
          {children}
        </div>
      )}
    </div>
  )
}

// ───────────────────────────────────────────────────────────────
// 主组件
// ───────────────────────────────────────────────────────────────
export default function LineageTree({ skuId, onPick, pickKinds, onClose, height = '70vh' }: Props) {
  const [data, setData] = useState<LineageData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [adopting, setAdopting] = useState<string | null>(null)
  const [archiving, setArchiving] = useState<string | null>(null)
  const [includeArchived, setIncludeArchived] = useState(false)

  const allowedPicks = pickKinds || ['audience_record', 'audience_pack']

  // 记录"已经做过首次自动展开"的 skuId，避免后续 fetchLineage 重置 expanded
  const autoExpandedSkuRef = useRef<string | null>(null)

  const fetchLineage = useCallback(async () => {
    if (!skuId) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/omni/sku-pipeline/lineage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku_id: skuId, limit_per_table: 100, include_archived: includeArchived }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        setData(json.data)
        // 只在该 SKU 首次加载时自动展开 adopted 节点；后续 adopt/archive 刷新保留老板手动展开状态
        if (autoExpandedSkuRef.current !== skuId) {
          autoExpandedSkuRef.current = skuId
          const auto = new Set<string>()
          for (const m of json.data.matrix_runs || []) {
            if (m.status === 'adopted') auto.add(`m:${m.id}`)
            for (const ar of m.audience_runs || []) {
              if (ar.status === 'adopted') auto.add(`ar:${ar.id}`)
              for (const r of ar.audience_records || []) {
                if (r.status === 'adopted') auto.add(`r:${r.id}`)
                for (const p of r.audience_packs || []) {
                  if (p.status === 'adopted') auto.add(`p:${p.id}`)
                }
              }
            }
          }
          setExpanded(auto)
        }
      } else {
        setError(json.data?.error || json.error || '拉血缘失败')
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [skuId, includeArchived])

  useEffect(() => {
    fetchLineage()
  }, [fetchLineage])

  const toggle = (key: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // 收集所有可折叠节点 id（matrix/arun/record/pack/script，asset 是叶子不折）
  const allExpandableKeys = useCallback((): string[] => {
    if (!data) return []
    const keys: string[] = []
    for (const m of data.matrix_runs) {
      keys.push(`m:${m.id}`)
      for (const ar of m.audience_runs) {
        keys.push(`ar:${ar.id}`)
        for (const r of ar.audience_records) {
          keys.push(`r:${r.id}`)
          for (const p of r.audience_packs) {
            keys.push(`p:${p.id}`)
            for (const s of p.scripts) keys.push(`s:${s.id}`)
          }
          for (const s of r.scripts_direct) keys.push(`s:${s.id}`)
        }
      }
    }
    for (const p of data.orphan_packs) {
      keys.push(`p:${p.id}`)
      for (const s of p.scripts) keys.push(`s:${s.id}`)
    }
    for (const s of data.orphan_scripts) keys.push(`s:${s.id}`)
    return keys
  }, [data])

  const expandAll = () => setExpanded(new Set(allExpandableKeys()))
  const collapseAll = () => setExpanded(new Set())

  const adoptNode = async (table: string, id: string) => {
    if (adopting) return
    setAdopting(id)
    try {
      const res = await fetch('/api/omni/sku-pipeline/adopt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table, run_id: id }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        await fetchLineage()  // 刷新血缘
      } else {
        setError(`采纳失败：${json.data?.error || json.error || '未知'}`)
      }
    } catch (e) {
      setError(`采纳异常：${String(e)}`)
    } finally {
      setAdopting(null)
    }
  }

  const renderArchiveBtn = (table: string, id: string, label: string) => (
    <Button
      size="sm"
      variant="ghost"
      className="h-7 px-2 text-muted-foreground hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30"
      disabled={archiving === id}
      onClick={() => archiveNode(table, id, label)}
      title="归档（从血缘图隐藏，data 不删可恢复）"
    >
      {archiving === id ? <Loader2 className="w-3 h-3 animate-spin" /> : '🗑'}
    </Button>
  )

  const archiveNode = async (table: string, id: string, label: string) => {
    if (archiving) return
    if (!confirm(`归档此节点？\n\n${label}\n\n归档后从血缘图默认视图隐藏（可恢复，data 不删）。\n要彻底删除需手动到数据库 DELETE。`)) return
    setArchiving(id)
    try {
      const res = await fetch('/api/omni/sku-pipeline/archive', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table, run_id: id }),
      })
      const json = await res.json()
      if (json.success && json.data?.ok) {
        await fetchLineage()
      } else {
        setError(`归档失败：${json.data?.error || json.error || '未知'}`)
      }
    } catch (e) {
      setError(`归档异常：${String(e)}`)
    } finally {
      setArchiving(null)
    }
  }

  const pickNode = (node: PickableNode) => {
    if (!onPick) return
    onPick(node)
    if (onClose) onClose()
  }

  // ── 节点渲染：6 类 ────────────────────────────────────────
  const renderAsset = (a: AssetNode) => {
    const key = `a:${a.id}`
    const canPick = onPick && allowedPicks.includes('asset')
    return (
      <NodeShell
        key={key}
        nodeKey={key}
        status={a.status}
        layer="asset"
        expanded={false}
        onToggle={() => {}}
        header={
          <>
            <Badge variant="secondary" className="text-[10px]">素材</Badge>
            <Badge variant={statusColor(a.status).badge} className="text-[10px]">{statusText(a.status)}</Badge>
            <span className="font-medium">{assetTypeText(a.asset_type)}{a.scene_no ? ` · 第 ${a.scene_no} 段` : ''}</span>
            {a.external_video_id && <Badge variant="outline" className="text-[10px]">已上传</Badge>}
            <span className="text-[10px] text-muted-foreground ml-1">{fmtDate(a.created_at)}</span>
          </>
        }
        pickButton={canPick ? (
          <Button size="sm" variant="outline" onClick={() => pickNode({ kind: 'asset', id: a.id, label: `${assetTypeText(a.asset_type)}#${a.scene_no || '?'}`, status: a.status })}>
            ← 选这个
          </Button>
        ) : undefined}
        adoptButton={a.status === 'draft' ? (
          <Button size="sm" variant="outline" disabled={adopting === a.id} onClick={() => adoptNode('assets', a.id)}>
            {adopting === a.id ? <Loader2 className="w-3 h-3 animate-spin" /> : '✓ 采纳'}
          </Button>
        ) : undefined}
        archiveButton={renderArchiveBtn('assets', a.id, `${assetTypeText(a.asset_type)} #${a.scene_no || '?'}`)}
      />
    )
  }

  const renderScript = (s: ScriptNode) => {
    const key = `s:${s.id}`
    const isExpanded = expanded.has(key)
    const canPick = onPick && allowedPicks.includes('script')
    const hasAssets = s.assets.length > 0
    return (
      <NodeShell
        key={key}
        nodeKey={key}
        status={s.status}
        layer="script"
        expanded={isExpanded}
        onToggle={() => toggle(key)}
        header={
          <>
            <Badge variant="secondary" className="text-[10px]">脚本</Badge>
            <Badge variant={statusColor(s.status).badge} className="text-[10px]">{statusText(s.status)}</Badge>
            <span className="font-medium">{scriptKindText(s.kind)}</span>
            <Badge variant="outline" className="text-[10px]">第 {s.version} 版</Badge>
            <span className="text-[10px] text-muted-foreground">{s.model || ''}</span>
            <span className="text-[10px] text-muted-foreground ml-1">{fmtDate(s.created_at)}</span>
          </>
        }
        pickButton={canPick ? (
          <Button size="sm" variant="outline" onClick={() => pickNode({ kind: 'script', id: s.id, label: `${scriptKindText(s.kind)} 第${s.version}版`, status: s.status })}>
            ← 选这个
          </Button>
        ) : undefined}
        adoptButton={s.status === 'draft' ? (
          <Button size="sm" variant="outline" disabled={adopting === s.id} onClick={() => adoptNode('scripts', s.id)}>
            {adopting === s.id ? <Loader2 className="w-3 h-3 animate-spin" /> : '✓ 采纳'}
          </Button>
        ) : undefined}
        archiveButton={renderArchiveBtn('scripts', s.id, `${scriptKindText(s.kind)} 第${s.version}版`)}
        childCount={s.assets.length}
      >
        {hasAssets && s.assets.map(renderAsset)}
      </NodeShell>
    )
  }

  const renderPack = (p: PackNode) => {
    const key = `p:${p.id}`
    const isExpanded = expanded.has(key)
    const canPick = onPick && allowedPicks.includes('audience_pack')
    return (
      <NodeShell
        key={key}
        nodeKey={key}
        status={p.status}
        layer="audience_pack"
        expanded={isExpanded}
        onToggle={() => toggle(key)}
        header={
          <>
            <Badge variant="secondary" className="text-[10px]">圈包</Badge>
            <Badge variant={statusColor(p.status).badge} className="text-[10px]">{statusText(p.status)}</Badge>
            <span className="font-medium">圈包第 {p.version} 版</span>
            <span className="text-[10px] text-muted-foreground">{p.model || ''}</span>
            <span className="text-[10px] text-muted-foreground ml-1">{fmtDate(p.created_at)}</span>
          </>
        }
        pickButton={canPick ? (
          <Button size="sm" variant="outline" onClick={() => pickNode({ kind: 'audience_pack', id: p.id, label: `圈包第${p.version}版`, status: p.status })}>
            ← 选这个
          </Button>
        ) : undefined}
        adoptButton={p.status === 'draft' ? (
          <Button size="sm" variant="outline" disabled={adopting === p.id} onClick={() => adoptNode('audience_packs', p.id)}>
            {adopting === p.id ? <Loader2 className="w-3 h-3 animate-spin" /> : '✓ 采纳'}
          </Button>
        ) : undefined}
        archiveButton={renderArchiveBtn('audience_packs', p.id, `圈包第${p.version}版`)}
        childCount={p.scripts.length}
      >
        {p.scripts.map(renderScript)}
      </NodeShell>
    )
  }

  const renderRecord = (r: RecordNode) => {
    const key = `r:${r.id}`
    const isExpanded = expanded.has(key)
    const canPick = onPick && allowedPicks.includes('audience_record')
    const childN = r.audience_packs.length + r.scripts_direct.length
    return (
      <NodeShell
        key={key}
        nodeKey={key}
        status={r.status}
        layer="audience_record"
        expanded={isExpanded}
        onToggle={() => toggle(key)}
        header={
          <>
            <Badge variant="secondary" className="text-[10px]">候选人群</Badge>
            <Badge variant={statusColor(r.status).badge} className="text-[10px]">{statusText(r.status)}</Badge>
            <span className="text-[10px] text-muted-foreground">#{r.ordinal}</span>
            <span className="font-medium">{r.name}</span>
            {r.layer_tags.slice(0, 2).map((t, i) => (
              <Badge key={i} variant="outline" className="text-[10px]">{t}</Badge>
            ))}
            {r.selected_for_pack && <Badge variant="default" className="text-[10px]" title="已加入 SKU 人群池">⭐</Badge>}
          </>
        }
        pickButton={canPick ? (
          <Button size="sm" variant="outline" onClick={() => pickNode({ kind: 'audience_record', id: r.id, label: r.name, status: r.status })}>
            ← 选这个
          </Button>
        ) : undefined}
        adoptButton={r.status === 'draft' ? (
          <Button size="sm" variant="outline" disabled={adopting === r.id} onClick={() => adoptNode('audience_records', r.id)}>
            {adopting === r.id ? <Loader2 className="w-3 h-3 animate-spin" /> : '⭐ 加入人群池'}
          </Button>
        ) : undefined}
        archiveButton={renderArchiveBtn('audience_records', r.id, `候选人群 #${r.ordinal} ${r.name}`)}
        childCount={childN}
      >
        {r.audience_packs.map(renderPack)}
        {r.scripts_direct.length > 0 && (
          <div className="pl-2 border-l-2 border-dashed border-muted-foreground/30 space-y-1.5">
            <div className="text-[10px] text-muted-foreground">绕过圈包直挂的脚本：</div>
            {r.scripts_direct.map(renderScript)}
          </div>
        )}
      </NodeShell>
    )
  }

  const renderAudienceRun = (ar: AudienceRunNode) => {
    const key = `ar:${ar.id}`
    const isExpanded = expanded.has(key)
    return (
      <NodeShell
        key={key}
        nodeKey={key}
        status={ar.status}
        layer="audience_run"
        expanded={isExpanded}
        onToggle={() => toggle(key)}
        header={
          <>
            <Badge variant="secondary" className="text-[10px]">人群匹配</Badge>
            <Badge variant={statusColor(ar.status).badge} className="text-[10px]">{statusText(ar.status)}</Badge>
            <span className="font-medium">人群匹配第 {ar.version} 版</span>
            <span className="text-[10px] text-muted-foreground">拆 {ar.record_count} 候选</span>
            <span className="text-[10px] text-muted-foreground">{ar.model || ''}</span>
            <span className="text-[10px] text-muted-foreground ml-1">{fmtDate(ar.created_at)}</span>
          </>
        }
        adoptButton={ar.status === 'draft' ? (
          <Button size="sm" variant="outline" disabled={adopting === ar.id} onClick={() => adoptNode('audience_runs', ar.id)}>
            {adopting === ar.id ? <Loader2 className="w-3 h-3 animate-spin" /> : '✓ 采纳'}
          </Button>
        ) : undefined}
        archiveButton={renderArchiveBtn('audience_runs', ar.id, `人群匹配第${ar.version}版`)}
        childCount={ar.audience_records.length}
      >
        {ar.audience_records.map(renderRecord)}
      </NodeShell>
    )
  }

  const renderMatrix = (m: MatrixRunNode) => {
    const key = `m:${m.id}`
    const isExpanded = expanded.has(key)
    return (
      <NodeShell
        key={key}
        nodeKey={key}
        status={m.status}
        layer="matrix_run"
        expanded={isExpanded}
        onToggle={() => toggle(key)}
        header={
          <>
            <Badge variant="secondary" className="text-[10px]">卖点矩阵</Badge>
            <Badge variant={statusColor(m.status).badge} className="text-[10px]">{statusText(m.status)}</Badge>
            <span className="font-medium">卖点矩阵第 {m.version} 版</span>
            <span className="text-[10px] text-muted-foreground">{m.model || ''}</span>
            <span className="text-[10px] text-muted-foreground ml-1">{fmtDate(m.created_at)}</span>
          </>
        }
        adoptButton={m.status === 'draft' ? (
          <Button size="sm" variant="outline" disabled={adopting === m.id} onClick={() => adoptNode('matrix_runs', m.id)}>
            {adopting === m.id ? <Loader2 className="w-3 h-3 animate-spin" /> : '✓ 采纳'}
          </Button>
        ) : undefined}
        archiveButton={renderArchiveBtn('matrix_runs', m.id, `卖点矩阵第${m.version}版`)}
        childCount={m.audience_runs.length}
      >
        {m.audience_runs.map(renderAudienceRun)}
      </NodeShell>
    )
  }

  // ── 主渲染 ──────────────────────────────────────────────
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="text-xs text-muted-foreground">
          {data && (
            <>
              <code className="text-[10px]">{data.sku_id}</code>
              {' · '}
              卖点矩阵 {data.counts.matrix_runs} · 人群匹配 {data.counts.audience_runs} · 候选人群 {data.counts.audience_records} · 圈包 {data.counts.audience_packs} · 脚本 {data.counts.scripts} · 素材 {data.counts.assets}
            </>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] text-muted-foreground flex items-center gap-2">
            <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-400" /> 已采纳</span>
            <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-400" /> 已发布</span>
            <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-400" /> 草稿</span>
          </span>
          <Button size="sm" variant="outline" onClick={expandAll} disabled={loading || !data} title="展开所有节点">
            <ChevronDown className="w-3 h-3 mr-1" />全展
          </Button>
          <Button size="sm" variant="outline" onClick={collapseAll} disabled={loading || !data} title="折叠所有节点">
            <ChevronRight className="w-3 h-3 mr-1" />全折
          </Button>
          <label className="text-[11px] flex items-center gap-1 cursor-pointer select-none" title="勾上后已归档节点也出现在血缘图（默认隐藏）">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={e => setIncludeArchived(e.target.checked)}
            />
            <span>显示已归档</span>
          </label>
          <Button size="sm" variant="outline" onClick={fetchLineage} disabled={loading} title="刷新">
            {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          </Button>
        </div>
      </div>

      {/* 6 层 accent 色图例 */}
      <div className="flex items-center gap-3 text-[10px] text-muted-foreground flex-wrap px-1">
        <span className="font-medium">层级：</span>
        {(Object.entries(LAYER_ACCENT) as [PickableNode['kind'], typeof LAYER_ACCENT[PickableNode['kind']]][]).map(([kind, accent]) => (
          <span key={kind} className="inline-flex items-center gap-1">
            <span className={`inline-block w-3 h-3 rounded text-white text-[8px] flex items-center justify-center ${accent.dot}`}>{accent.icon}</span>
            <span>{accent.label}</span>
          </span>
        ))}
      </div>

      {error && (
        <div className="text-xs text-red-500 p-2 border border-red-200 rounded bg-red-50">
          {error}
        </div>
      )}

      {onPick && (
        <div className="text-xs text-muted-foreground p-2 border border-dashed border-amber-300 rounded bg-amber-50/30 dark:bg-amber-950/20">
          🎯 选取模式：在 {allowedPicks.map(k => LAYER_ACCENT[k].label).join(' / ')} 节点上点 "← 选这个" 把它绑给本次输入。
          {pickKinds === undefined && '默认可选 候选人群 / 圈包。'}
        </div>
      )}

      <div className="overflow-y-auto space-y-2" style={{ maxHeight: height }}>
        {loading && !data && (
          <div className="text-sm text-muted-foreground py-12 text-center">
            <Loader2 className="w-5 h-5 mx-auto animate-spin mb-2" />
            拉取血缘数据...
          </div>
        )}
        {data && data.matrix_runs.length === 0 && data.orphan_packs.length === 0 && data.orphan_scripts.length === 0 && data.orphan_assets.length === 0 && (
          <div className="text-sm text-muted-foreground py-12 text-center border border-dashed rounded">
            这个 SKU 还没跑过任何步骤。先去 Step 2 跑卖点矩阵。
          </div>
        )}
        {data && data.matrix_runs.map(renderMatrix)}

        {data && data.orphan_packs.length > 0 && (
          <div className="border-t pt-3 mt-3 space-y-2">
            <div className="text-xs font-medium text-muted-foreground">⚠ 没挂候选人群的圈包（不该有）</div>
            {data.orphan_packs.map(renderPack)}
          </div>
        )}
        {data && data.orphan_scripts.length > 0 && (
          <div className="border-t pt-3 mt-3 space-y-2">
            <div className="text-xs font-medium text-muted-foreground">没挂圈包/候选人群的脚本（SKU 直跑模式）</div>
            {data.orphan_scripts.map(renderScript)}
          </div>
        )}
        {data && data.orphan_assets.length > 0 && (
          <div className="border-t pt-3 mt-3 space-y-2">
            <div className="text-xs font-medium text-muted-foreground">没挂脚本的素材资产</div>
            {data.orphan_assets.map(renderAsset)}
          </div>
        )}
      </div>
    </div>
  )
}
