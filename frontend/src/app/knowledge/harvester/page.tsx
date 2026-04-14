'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import Link from 'next/link'
import {
  Globe,
  Search,
  FileText,
  CheckCircle,
  Loader2,
  Database,
  ArrowLeft,
  Eye,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  Save,
  RefreshCw,
  KeyRound,
  ShieldCheck,
  ShieldAlert,
  Trash2,
  X,
  Image as ImageIcon,
  Sparkles,
  CheckSquare,
  Square,
  Clapperboard,
  FolderOpen,
} from 'lucide-react'

interface TreeArticle {
  title: string
  mapping_id: string | number
  graph_path: string
  target_id?: string | number
}

interface TreeNode {
  title: string
  mapping_type: number
  mapping_id?: string | number
  graph_path: string
  target_id?: string | number
  children: TreeNode[]
}

interface NavTree {
  graph_name: string
  graph_id: string
  articles: TreeArticle[]
  total_articles: number
  tree_nodes?: TreeNode[]
}

interface ChapterImages {
  downloaded: number
  total: number
  analyzed?: number
}

interface ChapterVideos {
  analyzed: number
}

interface Chapter {
  index: number
  title: string
  graph_path: string
  markdown: string
  text?: string
  word_count: number
  block_count: number
  source_url?: string
  error?: string
  images?: ChapterImages
  videos?: ChapterVideos
  image_descriptions?: Record<string, string>
}

interface ImageInfo {
  filename: string
  token: string
  alt: string
  url: string
  exists: boolean
  size: number
}

interface CurrentArticle {
  index: number
  title: string
  graph_path: string
  /** 后端在长时间步骤（如图解读、短视频）里刷新的子状态文案 */
  detail?: string
}

interface ActivityLogEntry {
  t: number
  msg: string
  snippet?: string
}

interface CrawlJob {
  status: string
  progress: number
  /** 当前篇内部的完成比例 0–0.99，用于进度条在 chapters 尚未写入时不长时间停在 0% */
  progress_hint?: number
  total?: number
  chapters: Chapter[]
  current_article?: CurrentArticle | null
  graph_name?: string
  total_articles?: number
  error?: string | null
  /** 后端追加的实时步骤日志（轮询 GET job） */
  activity_log?: ActivityLogEntry[]
  /** 最近一次提取到的纯文本预览 */
  text_preview?: string
}

function crawlProgressPct(job: CrawlJob): number {
  const total = job.total || 1
  const hint = typeof job.progress_hint === 'number' ? job.progress_hint : 0
  const completedBoost =
    job.chapters.length > 0 && job.chapters[job.chapters.length - 1].index === job.progress ? 1 : 0
  return Math.min(100, Math.round(((job.progress + hint + completedBoost) / total) * 100))
}

/** 统一 snake_case / camelCase，避免代理或旧后端漏字段导致日志区空白 */
function normalizeHarvesterJob(data: CrawlJob): CrawlJob {
  const d = data as CrawlJob & { activityLog?: ActivityLogEntry[]; textPreview?: string }
  const log = d.activity_log ?? d.activityLog
  const activity_log = Array.isArray(log) ? log : []
  const text_preview = d.text_preview ?? d.textPreview ?? ''
  return { ...d, activity_log, text_preview }
}

interface KBItem {
  id: string
  name: string
  description: string
}

type Step = 'input' | 'browse' | 'crawling' | 'review' | 'saving' | 'done'

/** 刷新 / 新开标签后恢复采集任务：job 仍在知识引擎进程内存中时可拉回（引擎重启后仍会丢失）。 */
const HARVESTER_JOB_STORAGE_KEY = 'omni-knowledge-harvester-job-id'
/** 旧版仅用 sessionStorage，迁移一次到 localStorage */
const HARVESTER_JOB_SESSION_LEGACY_KEY = 'omni-knowledge-harvester-job-id'

function readStoredHarvestJobId(): string {
  try {
    if (typeof window === 'undefined') return ''
    const qs = new URLSearchParams(window.location.search)
    const fromUrl = qs.get('job_id')?.trim()
    if (fromUrl) return fromUrl
    let v = window.localStorage.getItem(HARVESTER_JOB_STORAGE_KEY) || ''
    if (!v) {
      v = window.sessionStorage.getItem(HARVESTER_JOB_SESSION_LEGACY_KEY) || ''
      if (v) {
        window.localStorage.setItem(HARVESTER_JOB_STORAGE_KEY, v)
        window.sessionStorage.removeItem(HARVESTER_JOB_SESSION_LEGACY_KEY)
      }
    }
    return v
  } catch {
    return ''
  }
}

function persistHarvestJobId(id: string) {
  try {
    if (typeof window !== 'undefined' && id) {
      window.localStorage.setItem(HARVESTER_JOB_STORAGE_KEY, id)
      try {
        const url = new URL(window.location.href)
        if (url.searchParams.get('job_id') !== id) {
          url.searchParams.set('job_id', id)
          window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
        }
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }
}

function clearPersistedHarvestJobId() {
  try {
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(HARVESTER_JOB_STORAGE_KEY)
      window.sessionStorage.removeItem(HARVESTER_JOB_SESSION_LEGACY_KEY)
      try {
        const url = new URL(window.location.href)
        if (!url.searchParams.has('job_id')) return
        url.searchParams.delete('job_id')
        const q = url.searchParams.toString()
        window.history.replaceState({}, '', `${url.pathname}${q ? `?${q}` : ''}${url.hash}`)
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }
}

/** 目录 API 可能返回 number 或 string，统一成字符串避免 Set.has 匹配失败导致「选了 A 却爬成别篇或退回全量」。 */
function midKey(id: string | number | undefined | null): string {
  if (id == null || id === '') return ''
  return String(id)
}

function allLeafMappingIds(nodes: TreeNode[] | undefined): string[] {
  if (!nodes?.length) return []
  const out: string[] = []
  const walk = (list: TreeNode[]) => {
    for (const n of list) {
      if (n.mapping_type === 2 && n.mapping_id != null && n.mapping_id !== '') {
        const k = midKey(n.mapping_id)
        if (k) out.push(k)
      }
      if (n.children?.length) walk(n.children)
    }
  }
  walk(nodes)
  return out
}

function filterNavTree(nodes: TreeNode[], q: string): TreeNode[] {
  const t = q.trim().toLowerCase()
  if (!t) return nodes
  const filt = (list: TreeNode[]): TreeNode[] => {
    const res: TreeNode[] = []
    for (const n of list) {
      const hit = n.title.toLowerCase().includes(t) || n.graph_path.toLowerCase().includes(t)
      const kids = n.children?.length ? filt(n.children) : []
      if (n.mapping_type === 2) {
        if (hit) res.push({ ...n, children: [] })
      } else if (kids.length || hit) {
        res.push({ ...n, children: kids })
      }
    }
    return res
  }
  return filt(nodes)
}

function HarvesterTreeRow({
  node,
  depth,
  treeSelected,
  setTreeSelected,
  expandedPaths,
  setExpandedPaths,
}: {
  node: TreeNode
  depth: number
  treeSelected: Set<string>
  setTreeSelected: React.Dispatch<React.SetStateAction<Set<string>>>
  expandedPaths: Set<string>
  setExpandedPaths: React.Dispatch<React.SetStateAction<Set<string>>>
}) {
  const isLeaf = node.mapping_type === 2
  const expanded = expandedPaths.has(node.graph_path)

  if (isLeaf && node.mapping_id != null) {
    const k = midKey(node.mapping_id)
    const isSelected = k ? treeSelected.has(k) : false
    return (
      <div
        style={{ paddingLeft: `${12 + depth * 16}px` }}
        className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-gray-50 transition ${isSelected ? 'bg-blue-50/50' : ''}`}
        onClick={() => {
          if (!k) return
          setTreeSelected(prev => {
            const next = new Set(prev)
            if (next.has(k)) next.delete(k)
            else next.add(k)
            return next
          })
        }}
      >
        <input
          type="checkbox"
          checked={isSelected}
          readOnly
          className="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500 flex-shrink-0"
        />
        <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-gray-900 truncate">{node.title}</div>
          <div className="text-xs text-gray-400 truncate">{node.graph_path}</div>
        </div>
        <Badge variant="outline" className="text-xs text-gray-400 flex-shrink-0">
          #{node.mapping_id}
        </Badge>
      </div>
    )
  }

  return (
    <div className="border-b border-gray-50 last:border-0">
      <div
        style={{ paddingLeft: `${8 + depth * 16}px` }}
        className="flex items-center gap-2 px-4 py-2 cursor-pointer hover:bg-amber-50/40 text-sm font-medium text-gray-800"
        onClick={() => {
          setExpandedPaths(prev => {
            const next = new Set(prev)
            if (next.has(node.graph_path)) next.delete(node.graph_path)
            else next.add(node.graph_path)
            return next
          })
        }}
      >
        {expanded
          ? <ChevronDown className="w-4 h-4 text-gray-500 flex-shrink-0" />
          : <ChevronRight className="w-4 h-4 text-gray-500 flex-shrink-0" />}
        <FolderOpen className="w-4 h-4 text-amber-500 flex-shrink-0" />
        <span className="truncate">{node.title}</span>
      </div>
      {expanded && (node.children || []).map((ch, j) => (
        <HarvesterTreeRow
          key={`${ch.graph_path}-${j}`}
          node={ch}
          depth={depth + 1}
          treeSelected={treeSelected}
          setTreeSelected={setTreeSelected}
          expandedPaths={expandedPaths}
          setExpandedPaths={setExpandedPaths}
        />
      ))}
    </div>
  )
}

export default function HarvesterPage() {
  const [step, setStep] = useState<Step>('input')
  const [url, setUrl] = useState('')
  const [maxPages, setMaxPages] = useState<string>('')
  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<CrawlJob | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [bases, setBases] = useState<KBItem[]>([])
  const [selectedKb, setSelectedKb] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedTasks, setSavedTasks] = useState<string[]>([])
  const [hasAuth, setHasAuth] = useState<boolean | null>(null)
  const [showCookieModal, setShowCookieModal] = useState(false)
  const [cookieText, setCookieText] = useState('')
  const [cookieSaving, setCookieSaving] = useState(false)
  const [chapterImages, setChapterImages] = useState<Record<number, ImageInfo[]>>({})
  const [selectedImages, setSelectedImages] = useState<Record<number, Set<string>>>({}
  )
  const [analyzingChapter, setAnalyzingChapter] = useState<number | null>(null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [hasFeishuAuth, setHasFeishuAuth] = useState<boolean | null>(null)
  const [loginCommandModal, setLoginCommandModal] = useState<'oceanengine' | 'feishu' | null>(null)
  const [extractCommandModal, setExtractCommandModal] = useState<string | null>(null)
  const [extractPolling, setExtractPolling] = useState(false)
  const [navTree, setNavTree] = useState<NavTree | null>(null)
  const [treeLoading, setTreeLoading] = useState(false)
  const [treeSelected, setTreeSelected] = useState<Set<string>>(new Set())
  const [treeFilter, setTreeFilter] = useState('')
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set())
  const [endingHarvest, setEndingHarvest] = useState(false)
  const activityLogRef = useRef<HTMLDivElement>(null)
  const restoreAttemptedRef = useRef(false)

  const isFeishuUrl = (u: string) => /larkoffice\.com\/docx\/|feishu\.cn\/docx\/|larksuite\.com\/docx\/|larkoffice\.com\/wiki\/|feishu\.cn\/wiki\//i.test(u)

  const checkAuth = useCallback(async () => {
    try {
      const res = await fetch('/api/omni/knowledge/harvester')
      const json = await res.json()
      setHasAuth(json.success ? json.data?.has_auth ?? false : false)
    } catch { setHasAuth(false) }
    try {
      const res = await fetch('/api/omni/knowledge/harvester?auth_type=feishu')
      const json = await res.json()
      setHasFeishuAuth(json.success ? json.data?.has_auth ?? false : false)
    } catch { setHasFeishuAuth(false) }
  }, [])

  useEffect(() => { checkAuth() }, [checkAuth])

  useEffect(() => {
    if (jobId) persistHarvestJobId(jobId)
  }, [jobId])

  useEffect(() => {
    if (restoreAttemptedRef.current) return
    restoreAttemptedRef.current = true
    const stored = readStoredHarvestJobId()
    if (!stored.trim()) return

    void (async () => {
      try {
        const res = await fetch(`/api/omni/knowledge/harvester?job_id=${encodeURIComponent(stored)}`, {
          cache: 'no-store',
        })
        const json = await res.json()
        if (!json.success || !json.data) {
          clearPersistedHarvestJobId()
          return
        }
        const j = normalizeHarvesterJob(json.data as CrawlJob)
        setJobId(stored)
        setJob(j)
        if (j.status === 'done') {
          setStep('review')
          setSelected(new Set(j.chapters.filter(c => c.word_count > 0).map(c => c.index)))
          setError('')
        } else if (j.status === 'failed') {
          setError(j.error || '上次采集任务已失败')
          setStep('input')
          clearPersistedHarvestJobId()
        } else {
          setStep('crawling')
        }
      } catch {
        clearPersistedHarvestJobId()
      }
    })()
  }, [])

  useEffect(() => {
    fetch('/api/omni/knowledge/bases', { cache: 'no-store' })
      .then(r => r.json())
      .then(json => {
        if (json.success && json.data?.length) {
          const list = json.data as KBItem[]
          setBases(list)
          const prefer = list.find(k => k.name.includes('巨量千川'))
          setSelectedKb(prefer?.id ?? list[0].id)
        }
      })
      .catch(() => {})
  }, [])

  const saveCookies = useCallback(async () => {
    if (!cookieText.trim()) return
    setCookieSaving(true)
    setError('')
    try {
      const cookies = cookieText.trim().split(';').map(pair => {
        const eqIdx = pair.indexOf('=')
        if (eqIdx < 0) return null
        return {
          name: pair.slice(0, eqIdx).trim(),
          value: pair.slice(eqIdx + 1).trim(),
          domain: '.oceanengine.com',
          path: '/',
        }
      }).filter(Boolean)

      if (cookies.length === 0) throw new Error('无法解析 Cookie，请检查格式')

      const res = await fetch('/api/omni/knowledge/harvester?action=save-auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookies }),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '保存失败')
      setShowCookieModal(false)
      setCookieText('')
      setHasAuth(true)
    } catch (e) {
      setError(String(e))
    } finally {
      setCookieSaving(false)
    }
  }, [cookieText])

  const clearAuth = useCallback(async () => {
    try {
      await fetch('/api/omni/knowledge/harvester', { method: 'DELETE' })
      setHasAuth(false)
    } catch { /* ignore */ }
  }, [])

  const clearFeishuAuth = useCallback(async () => {
    try {
      await fetch('/api/omni/knowledge/harvester?auth_type=feishu', { method: 'DELETE' })
      setHasFeishuAuth(false)
    } catch { /* ignore */ }
  }, [])

  const startFeishuBrowserLogin = useCallback(() => {
    setLoginCommandModal('feishu')
  }, [])

  const startBrowserLogin = useCallback(() => {
    setLoginCommandModal('oceanengine')
  }, [])

  // Poll auth status while the login command modal is open
  useEffect(() => {
    if (!loginCommandModal) return
    const interval = setInterval(checkAuth, 2500)
    return () => clearInterval(interval)
  }, [loginCommandModal, checkAuth])

  // Auto-close modal when auth is detected
  useEffect(() => {
    if (loginCommandModal === 'oceanengine' && hasAuth) {
      const t = setTimeout(() => setLoginCommandModal(null), 2500)
      return () => clearTimeout(t)
    }
    if (loginCommandModal === 'feishu' && hasFeishuAuth) {
      const t = setTimeout(() => setLoginCommandModal(null), 2500)
      return () => clearTimeout(t)
    }
  }, [loginCommandModal, hasAuth, hasFeishuAuth])

  // Poll for extract upload completion
  useEffect(() => {
    if (!extractCommandModal) { setExtractPolling(false); return }
    setExtractPolling(true)
    const interval = setInterval(async () => {
      try {
        const res = await fetch('/api/omni/knowledge/harvester?latest_upload=1')
        const json = await res.json()
        if (json.success && json.data?.job_id && json.data.job_id !== jobId) {
          const newJobId = json.data.job_id
          setJobId(newJobId)
          setExtractCommandModal(null)
          setExtractPolling(false)
          // Fetch the job data
          const jRes = await fetch(`/api/omni/knowledge/harvester?job_id=${newJobId}`)
          const jJson = await jRes.json()
          if (jJson.success && jJson.data) {
            const j = normalizeHarvesterJob(jJson.data as CrawlJob)
            setJob(j)
            if (j.status === 'done') {
              setStep('review')
              setSelected(new Set(j.chapters.filter(c => c.word_count > 0).map(c => c.index)))
              setError('')
            }
          }
        }
      } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(interval)
  }, [extractCommandModal, jobId])

  const browseTree = useCallback(async () => {
    if (!url.trim()) return
    setError('')
    setTreeLoading(true)
    try {
      const res = await fetch('/api/omni/knowledge/harvester?action=tree', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim() }),
      })
      const json = await res.json()
      if (!res.ok || !json.success) throw new Error(json.error || `${res.status}: 获取目录失败`)
      const tree = json.data as NavTree
      setNavTree(tree)
      const leaves = allLeafMappingIds(tree.tree_nodes)
      setTreeSelected(new Set(leaves.length ? leaves : tree.articles.map(a => midKey(a.mapping_id)).filter(Boolean)))
      setExpandedPaths(new Set((tree.tree_nodes || []).map(n => n.graph_path)))
      setStep('browse')
    } catch (e) {
      setError(String(e))
    } finally {
      setTreeLoading(false)
    }
  }, [url])

  const startCrawl = useCallback(async () => {
    if (!url.trim()) return
    setError('')
    setStep('crawling')
    setJob(null)
    try {
      const body: Record<string, unknown> = { url: url.trim() }
      if (maxPages) body.max_pages = parseInt(maxPages, 10)
      const res = await fetch('/api/omni/knowledge/harvester?action=crawl', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const json = await res.json()
      if (!res.ok || !json.success) throw new Error(json.error || `${res.status}: 启动爬取失败`)
      setJobId(json.data.job_id)
    } catch (e) {
      setError(String(e))
      setStep('input')
    }
  }, [url, maxPages])

  /** 结束爬取：后端在当前篇完成后停止，保留已采集章节并进入审核入库 */
  const cancelHarvestToReview = useCallback(async () => {
    if (!jobId) return
    setEndingHarvest(true)
    setError('')
    try {
      const res = await fetch('/api/omni/knowledge/harvester?action=cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: jobId }),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '结束任务失败')
      for (let i = 0; i < 600; i++) {
        await new Promise(r => setTimeout(r, 1000))
        const jRes = await fetch(`/api/omni/knowledge/harvester?job_id=${jobId}`)
        const jJson = await jRes.json()
        if (!jJson.success || !jJson.data) continue
        const j = normalizeHarvesterJob(jJson.data as CrawlJob)
        setJob(j)
        if (j.status === 'done') {
          setStep('review')
          setSelected(new Set(j.chapters.filter(c => c.word_count > 0 && c.markdown).map(c => c.index)))
          return
        }
        if (j.status === 'failed') {
          setError(j.error || '任务失败')
          setStep('input')
          return
        }
      }
      setError('等待结束超时，请刷新页面或到任务进度查看状态')
    } catch (e) {
      setError(String(e))
    } finally {
      setEndingHarvest(false)
    }
  }, [jobId])

  const crawlSelected = useCallback(async () => {
    if (!url.trim() || !navTree || treeSelected.size === 0) return
    setError('')
    setStep('crawling')
    setJob(null)
    try {
      const selectedArticles = navTree.articles
        .filter(a => treeSelected.has(midKey(a.mapping_id)))
        .map(a => ({
          title: a.title,
          mapping_id: a.mapping_id,
          graph_path: a.graph_path,
          target_id: a.target_id || a.mapping_id,
        }))
      if (selectedArticles.length === 0) {
        setError('没有匹配到已选文章（可能是目录 ID 类型异常），请取消全选后重新勾选再试。')
        setStep('browse')
        return
      }
      const res = await fetch('/api/omni/knowledge/harvester?action=crawl', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url.trim(), selected_articles: selectedArticles }),
      })
      const json = await res.json()
      if (!res.ok || !json.success) throw new Error(json.error || `${res.status}: 启动爬取失败`)
      setJobId(json.data.job_id)
    } catch (e) {
      setError(String(e))
      setStep('input')
    }
  }, [url, navTree, treeSelected])

  useEffect(() => {
    if (step !== 'crawling' || !jobId) return
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/omni/knowledge/harvester?job_id=${jobId}`)
        const json = await res.json()
        if (json.success && json.data) {
          const j = normalizeHarvesterJob(json.data as CrawlJob)
          setJob(j)
          if (j.status === 'done') {
            setStep('review')
            const allIdx = new Set(j.chapters.filter(c => c.word_count > 0).map(c => c.index))
            setSelected(allIdx)
            clearInterval(interval)
          } else if (j.status === 'failed') {
            setError(j.error || '爬取失败')
            setStep('input')
            clearInterval(interval)
          }
        }
      } catch { /* ignore */ }
    }, 1000)
    return () => clearInterval(interval)
  }, [step, jobId])

  const activityTail = job?.activity_log?.length
    ? job.activity_log[job.activity_log.length - 1]?.t
    : 0
  useEffect(() => {
    const el = activityLogRef.current
    if (!el || !job?.activity_log?.length) return
    el.scrollTop = el.scrollHeight
  }, [job?.activity_log?.length, activityTail])

  const toggleSelect = (idx: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const toggleExpand = (idx: number) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(idx)) {
        next.delete(idx)
      } else {
        next.add(idx)
        loadChapterImages(idx)
      }
      return next
    })
  }

  const selectAll = () => {
    if (job) setSelected(new Set(job.chapters.filter(c => c.word_count > 0).map(c => c.index)))
  }

  const selectNone = () => setSelected(new Set())

  const saveSelected = useCallback(async () => {
    if (!selectedKb || selected.size === 0 || !job) return
    setSaving(true)
    setError('')
    try {
      const chapters = job.chapters
        .filter(c => selected.has(c.index) && c.markdown)
        .map(c => ({
          title: c.title,
          markdown: c.markdown,
          source_url: c.source_url || null,
        }))

      const res = await fetch('/api/omni/knowledge/harvester?action=save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kb_id: selectedKb, chapters }),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || '保存失败')
      setSavedTasks(json.data.task_ids)
      clearPersistedHarvestJobId()
      setStep('done')
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }, [selectedKb, selected, job])

  const loadChapterImages = useCallback(async (chapterIndex: number) => {
    if (!jobId || chapterImages[chapterIndex]) return
    try {
      const res = await fetch(
        `/api/omni/knowledge/harvester?job_id=${jobId}&images=1&chapter_index=${chapterIndex}`
      )
      const json = await res.json()
      if (json.success && json.data) {
        const imgs: ImageInfo[] = json.data
        setChapterImages(prev => ({ ...prev, [chapterIndex]: imgs }))
        setSelectedImages(prev => ({
          ...prev,
          [chapterIndex]: new Set(imgs.filter(i => i.exists).map(i => i.filename)),
        }))
      }
    } catch { /* ignore */ }
  }, [jobId, chapterImages])

  const toggleImageSelect = (chapterIndex: number, filename: string) => {
    setSelectedImages(prev => {
      const current = new Set(prev[chapterIndex] || [])
      if (current.has(filename)) current.delete(filename)
      else current.add(filename)
      return { ...prev, [chapterIndex]: current }
    })
  }

  const selectAllImages = (chapterIndex: number) => {
    const imgs = chapterImages[chapterIndex] || []
    setSelectedImages(prev => ({
      ...prev,
      [chapterIndex]: new Set(imgs.filter(i => i.exists).map(i => i.filename)),
    }))
  }

  const selectNoImages = (chapterIndex: number) => {
    setSelectedImages(prev => ({ ...prev, [chapterIndex]: new Set() }))
  }

  const analyzeChapterImages = useCallback(async (chapterIndex: number) => {
    if (!jobId) return
    const filenames = Array.from(selectedImages[chapterIndex] || [])
    if (filenames.length === 0) return

    setAnalyzingChapter(chapterIndex)
    setError('')
    try {
      const res = await fetch('/api/omni/knowledge/harvester?action=analyze-images', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: jobId,
          chapter_index: chapterIndex,
          filenames,
          merge: true,
        }),
      })
      const json = await res.json()
      if (!json.success) throw new Error(json.error || 'AI 解读失败')

      if (json.data?.chapter && job) {
        const updated = json.data.chapter
        setJob(prev => {
          if (!prev) return prev
          return {
            ...prev,
            chapters: prev.chapters.map(c =>
              c.index === chapterIndex ? { ...c, ...updated } : c
            ),
          }
        })
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setAnalyzingChapter(null)
    }
  }, [jobId, selectedImages, job])

  const reset = () => {
    clearPersistedHarvestJobId()
    setStep('input')
    setUrl('')
    setMaxPages('')
    setJobId('')
    setJob(null)
    setError('')
    setSelected(new Set())
    setExpanded(new Set())
    setSavedTasks([])
    setChapterImages({})
    setSelectedImages({})
    setAnalyzingChapter(null)
    setImagePreview(null)
    setNavTree(null)
    setTreeSelected(new Set())
    setTreeFilter('')
    setExpandedPaths(new Set())
  }

  return (
    <div className="min-h-screen bg-[#F5F5F7] pb-20">
      <nav className="sticky top-0 z-50 glass border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-3">
              <Link href="/" className="text-xl font-bold bg-gradient-to-r from-gray-900 to-gray-600 bg-clip-text text-transparent">
                Omni-Vibe OS
              </Link>
              <span className="text-gray-300">/</span>
              <Link href="/knowledge" className="text-sm text-gray-500 hover:text-gray-900 flex items-center gap-1">
                <Database className="w-4 h-4" /> 知识库
              </Link>
              <span className="text-gray-300">/</span>
              <span className="text-sm font-medium text-gray-900 flex items-center gap-1">
                <Globe className="w-4 h-4" /> 知识采集
              </span>
            </div>
            <div className="flex items-center gap-4">
              <Link href="/knowledge">
                <Button variant="ghost" size="sm"><ArrowLeft className="w-4 h-4 mr-1" /> 返回知识库</Button>
              </Link>
              <Link href="/tasks">
                <Button variant="outline" size="sm">任务进度</Button>
              </Link>
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm flex items-center justify-between">
            <span>{error}</span>
            <div className="flex items-center gap-2">
              {url && (
                <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setExtractCommandModal(url)}>
                  <Globe className="w-3 h-3 mr-1" /> 本机提取
                </Button>
              )}
              <Button variant="ghost" size="sm" className="h-6 text-red-400" onClick={() => setError('')}>
                <X className="w-3 h-3" />
              </Button>
            </div>
          </div>
        )}

        {/* Cookie Modal */}
        {showCookieModal && (
          <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-lg apple-card">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2"><KeyRound className="w-5 h-5 text-amber-500" /> 设置认证 Cookie</CardTitle>
                  <Button variant="ghost" size="sm" onClick={() => setShowCookieModal(false)}><X className="w-4 h-4" /></Button>
                </div>
                <CardDescription>
                  部分帮助中心需要登录才能访问。请在浏览器中登录后，复制 Cookie 粘贴到下方。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="text-xs text-gray-500 bg-gray-50 rounded-lg p-3 space-y-1">
                  <p className="font-medium text-gray-700">获取方法：</p>
                  <p>1. 在浏览器中打开并登录 support.oceanengine.com 或 yuntu.oceanengine.com</p>
                  <p>2. 按 F12 打开开发者工具 → Application → Cookies</p>
                  <p>3. 复制所有 Cookie（格式: name=value; name2=value2）</p>
                </div>
                <textarea
                  value={cookieText}
                  onChange={e => setCookieText(e.target.value)}
                  placeholder="sessionid=abc123; passport_csrf_token=xyz456; ..."
                  rows={4}
                  className="w-full px-4 py-3 rounded-xl border border-gray-200 bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition text-sm font-mono"
                />
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setShowCookieModal(false)}>取消</Button>
                  <Button onClick={saveCookies} disabled={cookieSaving || !cookieText.trim()}>
                    {cookieSaving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Save className="w-4 h-4 mr-1" />}
                    保存认证
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Login Command Modal */}
        {loginCommandModal && (
          <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-lg apple-card">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2">
                    <Globe className="w-5 h-5 text-blue-500" />
                    {loginCommandModal === 'feishu' ? '飞书浏览器登录' : '帮助中心浏览器登录'}
                  </CardTitle>
                  <Button variant="ghost" size="sm" onClick={() => setLoginCommandModal(null)}>
                    <X className="w-4 h-4" />
                  </Button>
                </div>
                <CardDescription>
                  在本机终端运行以下命令，将自动打开浏览器。完成登录后 Cookie 会自动保存。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="relative">
                  <pre className="bg-gray-900 text-green-400 rounded-lg p-4 pr-20 text-sm font-mono overflow-x-auto whitespace-pre-wrap break-all">
                    {`python scripts/browser_login.py ${loginCommandModal === 'feishu' ? 'feishu' : 'oceanengine'}`}
                  </pre>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="absolute top-2 right-2 text-gray-400 hover:text-white h-7 text-xs"
                    onClick={() => {
                      navigator.clipboard.writeText(
                        `python scripts/browser_login.py ${loginCommandModal === 'feishu' ? 'feishu' : 'oceanengine'}`
                      )
                    }}
                  >
                    复制
                  </Button>
                </div>

                <div className="text-xs text-gray-500 bg-gray-50 rounded-lg p-3 space-y-1">
                  <p className="font-medium text-gray-700">首次使用？</p>
                  <p>需要安装 Playwright: <code className="bg-gray-200 px-1 rounded">pip install playwright</code></p>
                  <p>然后安装浏览器: <code className="bg-gray-200 px-1 rounded">playwright install chromium</code></p>
                </div>

                <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg border">
                  {(loginCommandModal === 'oceanengine' && hasAuth) || (loginCommandModal === 'feishu' && hasFeishuAuth) ? (
                    <div className="flex items-center gap-2 text-green-600">
                      <CheckCircle className="w-4 h-4" />
                      <span className="text-sm font-medium">登录成功！Cookie 已保存</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-gray-500">
                      <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                      <span className="text-sm">等待登录完成...</span>
                    </div>
                  )}
                </div>

                <div className="flex justify-end">
                  <Button variant="outline" onClick={() => setLoginCommandModal(null)}>关闭</Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Extract Command Modal */}
        {extractCommandModal && (
          <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
            <Card className="w-full max-w-lg apple-card">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2">
                    <Globe className="w-5 h-5 text-green-500" />
                    本机内容提取
                  </CardTitle>
                  <Button variant="ghost" size="sm" onClick={() => setExtractCommandModal(null)}>
                    <X className="w-4 h-4" />
                  </Button>
                </div>
                <CardDescription>
                  若自动采集未拿到完整正文（常见于复杂嵌入页），可在本机终端运行以下命令，用浏览器完成提取并回传结果。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="relative">
                  <pre className="bg-gray-900 text-green-400 rounded-lg p-4 pr-20 text-sm font-mono overflow-x-auto whitespace-pre-wrap break-all">
                    {`python scripts/browser_extract.py "${extractCommandModal}"`}
                  </pre>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="absolute top-2 right-2 text-gray-400 hover:text-white h-7 text-xs"
                    onClick={() => {
                      navigator.clipboard.writeText(
                        `python scripts/browser_extract.py "${extractCommandModal}"`
                      )
                    }}
                  >
                    复制
                  </Button>
                </div>

                <div className="text-xs text-gray-500 bg-gray-50 rounded-lg p-3 space-y-1">
                  <p className="font-medium text-gray-700">脚本功能：</p>
                  <p>1. 在本机浏览器中打开页面，等待内容完全渲染</p>
                  <p>2. 自动提取全部文本内容 + 下载所有图片</p>
                  <p>3. 图片自动发送给 AI 解读并嵌入文档</p>
                  <p>4. 完成后此页面自动刷新显示结果</p>
                </div>

                <div className="text-xs text-gray-500 bg-gray-50 rounded-lg p-3 space-y-1">
                  <p className="font-medium text-gray-700">首次使用？</p>
                  <p>需要安装: <code className="bg-gray-200 px-1 rounded">pip install playwright && playwright install chromium</code></p>
                </div>

                <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg border">
                  {extractPolling ? (
                    <div className="flex items-center gap-2 text-gray-500">
                      <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
                      <span className="text-sm">等待提取完成... 完成后自动显示结果</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-green-600">
                      <CheckCircle className="w-4 h-4" />
                      <span className="text-sm font-medium">提取完成！</span>
                    </div>
                  )}
                </div>

                <div className="flex justify-end">
                  <Button variant="outline" onClick={() => setExtractCommandModal(null)}>关闭</Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Step 1: Input */}
        {step === 'input' && (
          <>
            {/* Auth Status Banner */}
            {hasAuth !== null && (
              <div className={`mb-4 px-4 py-3 rounded-xl border flex items-center justify-between ${
                hasAuth
                  ? 'bg-green-50 border-green-200 text-green-700'
                  : 'bg-amber-50 border-amber-200 text-amber-700'
              }`}>
                <div className="flex items-center gap-2 text-sm">
                  {hasAuth
                    ? <><ShieldCheck className="w-4 h-4" /> 已配置认证 Cookie — 可访问需要登录的帮助中心</>
                    : <><ShieldAlert className="w-4 h-4" /> 未配置认证 — 仅能采集公开内容，飞书文档类需要认证</>
                  }
                </div>
                <div className="flex items-center gap-1.5">
                  <Button
                    variant="default"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={startBrowserLogin}
                  >
                    <Globe className="w-3 h-3 mr-1" /> 浏览器登录
                  </Button>
                  <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setShowCookieModal(true)}>
                    <KeyRound className="w-3 h-3 mr-1" /> 手动粘贴
                  </Button>
                  {hasAuth && (
                    <Button variant="ghost" size="sm" className="h-7 text-xs text-red-500 hover:text-red-600" onClick={clearAuth}>
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  )}
                </div>
              </div>
            )}

            {/* Feishu Auth Banner */}
            {hasFeishuAuth !== null && (
              <div className={`mb-4 px-4 py-3 rounded-xl border flex items-center justify-between ${
                hasFeishuAuth
                  ? 'bg-green-50 border-green-200 text-green-700'
                  : 'bg-amber-50 border-amber-200 text-amber-700'
              }`}>
                <div className="flex items-center gap-2 text-sm">
                  {hasFeishuAuth
                    ? <><ShieldCheck className="w-4 h-4" /> 已配置飞书认证 — 可爬取需要登录的飞书文档</>
                    : <><ShieldAlert className="w-4 h-4" /> 未配置飞书认证 — 仅能爬取公开分享的飞书文档</>
                  }
                </div>
                <div className="flex items-center gap-1.5">
                  <Button variant="default" size="sm" className="h-7 text-xs" onClick={startFeishuBrowserLogin}>
                    <Globe className="w-3 h-3 mr-1" /> 飞书浏览器登录
                  </Button>
                  {hasFeishuAuth && (
                    <Button variant="ghost" size="sm" className="h-7 text-xs text-red-500 hover:text-red-600" onClick={clearFeishuAuth}>
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  )}
                </div>
              </div>
            )}

            <Card className="apple-card">
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><Globe className="w-5 h-5 text-blue-500" /> 知识采集器</CardTitle>
                <CardDescription>
                  输入帮助中心或飞书文档 URL，系统自动爬取正文+表格+图片+视频 → AI解读图片 → 短视频分析解读视频 → 审核确认 → 入库向量化+RAG
                  <span className="block mt-2 text-xs text-gray-500 leading-relaxed">
                    提示：采集任务 ID 会写入本机存储与地址栏（?job_id=…），刷新或新开本站标签页可继续上次的任务；若知识引擎服务曾重启，内存中的未入库任务会清空，重要内容请尽快入库。
                  </span>
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="text-sm font-medium text-gray-700 mb-1 block">文档 URL</label>
                  <input
                    type="url"
                    value={url}
                    onChange={e => setUrl(e.target.value)}
                    placeholder="飞书文档 / 帮助中心 URL"
                    className="w-full px-4 py-3 rounded-xl border border-gray-200 bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition"
                  />
                  {url && isFeishuUrl(url) && (
                    <div className="mt-1.5 flex items-center gap-1.5 text-xs text-blue-600">
                      <FileText className="w-3 h-3" /> 检测到飞书文档 — 将直接提取文档正文和图片
                    </div>
                  )}
                </div>
                {!isFeishuUrl(url) && (
                  <div>
                    <label className="text-sm font-medium text-gray-700 mb-1 block">最大页数（可选）</label>
                    <input
                      type="number"
                      value={maxPages}
                      onChange={e => setMaxPages(e.target.value)}
                      placeholder="留空则爬取全部"
                      min={1}
                      max={2000}
                      className="w-48 px-4 py-3 rounded-xl border border-gray-200 bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition"
                    />
                  </div>
                )}
                <div className="flex items-center gap-3 mt-2">
                  {!isFeishuUrl(url) && (
                    <Button variant="outline" onClick={browseTree} disabled={!url.trim() || treeLoading} size="lg">
                      {treeLoading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Eye className="w-4 h-4 mr-2" />}
                      浏览目录（选择性爬取）
                    </Button>
                  )}
                  <Button onClick={startCrawl} disabled={!url.trim()} size="lg">
                    <Search className="w-4 h-4 mr-2" /> {isFeishuUrl(url) ? '开始爬取' : '爬取全部'}
                  </Button>
                </div>
                {!isFeishuUrl(url) && (
                  <p className="text-xs text-gray-400 mt-1.5">
                    支持输入根目录 URL 或单篇文章 URL（含 mappingType=2 的链接）
                  </p>
                )}
              </CardContent>
            </Card>
          </>
        )}

        {/* Step 1.5: Browse Tree */}
        {step === 'browse' && navTree && (
          <>
            <Card className="apple-card mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="w-5 h-5 text-blue-500" /> 选择要爬取的文章
                  {navTree.graph_name && <Badge variant="outline" className="ml-2 font-normal">{navTree.graph_name}</Badge>}
                </CardTitle>
                <CardDescription>
                  共 {navTree.total_articles} 篇文章，已选 {treeSelected.size} 篇。勾选需要的文章后点击&ldquo;爬取选中&rdquo;。
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex items-center gap-3">
                  <input
                    type="text"
                    value={treeFilter}
                    onChange={e => setTreeFilter(e.target.value)}
                    placeholder="搜索文章标题..."
                    className="flex-1 px-3 py-2 rounded-lg border border-gray-200 bg-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      const leaves = allLeafMappingIds(navTree.tree_nodes)
                      setTreeSelected(new Set(leaves.length ? leaves : navTree.articles.map(a => midKey(a.mapping_id)).filter(Boolean)))
                    }}
                  >
                    全选
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setTreeSelected(new Set())}>
                    取消全选
                  </Button>
                </div>

                <div className="max-h-[500px] overflow-y-auto rounded-lg border border-gray-100">
                  {navTree.tree_nodes && navTree.tree_nodes.length > 0 ? (
                    <>
                      {treeFilter.trim() && (
                        <p className="text-xs text-gray-500 px-4 py-2 bg-gray-50 border-b border-gray-100">
                          搜索模式下按标题/路径筛选目录树；留空显示完整层级。
                        </p>
                      )}
                      {filterNavTree(navTree.tree_nodes, treeFilter).map((node, i) => (
                        <HarvesterTreeRow
                          key={`${node.graph_path}-root-${i}`}
                          node={node}
                          depth={0}
                          treeSelected={treeSelected}
                          setTreeSelected={setTreeSelected}
                          expandedPaths={expandedPaths}
                          setExpandedPaths={setExpandedPaths}
                        />
                      ))}
                    </>
                  ) : (
                    <div className="divide-y divide-gray-50">
                      {navTree.articles
                        .filter(a => !treeFilter || a.title.toLowerCase().includes(treeFilter.toLowerCase()) || a.graph_path.toLowerCase().includes(treeFilter.toLowerCase()))
                        .map((article, i) => {
                          const ak = midKey(article.mapping_id)
                          const isSelected = treeSelected.has(ak)
                          return (
                            <div
                              key={`${article.mapping_id}-${i}`}
                              className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-gray-50 transition ${isSelected ? 'bg-blue-50/50' : ''}`}
                              onClick={() => {
                                setTreeSelected(prev => {
                                  const next = new Set(prev)
                                  if (next.has(ak)) next.delete(ak)
                                  else next.add(ak)
                                  return next
                                })
                              }}
                            >
                              <input
                                type="checkbox"
                                checked={isSelected}
                                readOnly
                                className="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-500 flex-shrink-0"
                              />
                              <div className="flex-1 min-w-0">
                                <div className="text-sm font-medium text-gray-900 truncate">{article.title}</div>
                                <div className="text-xs text-gray-400 truncate">{article.graph_path}</div>
                              </div>
                              <Badge variant="outline" className="text-xs text-gray-400 flex-shrink-0">
                                #{article.mapping_id}
                              </Badge>
                            </div>
                          )
                        })}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-3 pt-2">
                  <Button onClick={crawlSelected} disabled={treeSelected.size === 0} size="lg">
                    <Search className="w-4 h-4 mr-2" /> 爬取选中 ({treeSelected.size})
                  </Button>
                  <Button variant="outline" onClick={() => setStep('input')} size="lg">
                    <ArrowLeft className="w-4 h-4 mr-2" /> 返回
                  </Button>
                  <span className="text-sm text-gray-500 ml-auto">
                    {treeFilter && `筛选结果: ${navTree.articles.filter(a => a.title.toLowerCase().includes(treeFilter.toLowerCase()) || a.graph_path.toLowerCase().includes(treeFilter.toLowerCase())).length} 篇`}
                  </span>
                </div>
              </CardContent>
            </Card>
          </>
        )}

        {/* Step 2: Crawling */}
        {step === 'crawling' && (
          <>
            <Card className="apple-card mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 flex-wrap">
                  <Loader2 className="w-5 h-5 animate-spin text-blue-500" /> 正在爬取
                  {job?.graph_name && <Badge variant="outline" className="ml-2 font-normal">{job.graph_name}</Badge>}
                  {jobId && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="ml-auto h-8 text-amber-700 border-amber-300 hover:bg-amber-50"
                      disabled={endingHarvest}
                      onClick={() => void cancelHarvestToReview()}
                    >
                      {endingHarvest ? (
                        <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 结束中…</>
                      ) : (
                        <>结束并去审核</>
                      )}
                    </Button>
                  )}
                </CardTitle>
                <CardDescription>
                  {!job && '正在解析导航树...'}
                  {job?.status === 'fetching_tree' && '正在获取文章目录...'}
                  {job?.status === 'browser_starting' && `共 ${job.total} 篇文章，正在启动浏览器...`}
                  {job?.status === 'extracting' && `已完成 ${job.chapters.length}/${job.total} 篇，提取中...`}
                  {job?.status === 'extracting_api' && `已完成 ${job.chapters.length}/${job.total} 篇，API 提取中...`}
                  {job?.status === 'extracting_browser' && (() => {
                    const imgStats = job.chapters.reduce(
                      (acc, c) => ({
                        downloaded: acc.downloaded + (c.images?.downloaded || 0),
                        analyzed: acc.analyzed + (c.images?.analyzed || 0),
                      }),
                      { downloaded: 0, analyzed: 0 }
                    )
                    const sub = job.current_article?.detail
                    return (
                      `已完成 ${job.chapters.length}/${job.total} 篇，浏览器提取 + 图片/视频处理中` +
                      (imgStats.downloaded > 0 ? `（已累计 ${imgStats.downloaded} 张图 / ${imgStats.analyzed} 张已解读）` : '') +
                      (sub ? ` — ${sub}` : '')
                    )
                  })()}
                  <span className="block mt-1.5 text-xs text-amber-700/90">
                    可先点右上角「结束并去审核」：当前篇处理完后会停止爬取，已采文章保留；在审核页选「巨量千川」知识库后保存入库。
                  </span>
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-gray-800">实时日志</span>
                    <span className="text-[10px] text-gray-400">约每秒刷新 · job {jobId.slice(0, 8)}…</span>
                  </div>
                  <div
                    ref={activityLogRef}
                    className="min-h-[140px] max-h-64 overflow-y-auto rounded-xl border-2 border-gray-700 bg-gray-950 px-3 py-2.5 font-mono text-[11px] leading-relaxed text-green-400/95 shadow-inner"
                  >
                    {!job?.activity_log?.length && (
                      <div className="space-y-1 text-gray-400">
                        <p>已连接任务，等待后端写入步骤…</p>
                        <p className="text-[10px] text-amber-600/90">
                          若一直无新行：请执行 <code className="text-amber-700">docker compose up -d --build frontend knowledge-engine</code>
                        </p>
                      </div>
                    )}
                    {job?.activity_log?.map((e, i) => (
                      <div key={`${e.t}-${i}`} className="border-b border-gray-800/80 py-1.5 last:border-0">
                        <div className="flex gap-2 text-gray-500">
                          <span className="flex-shrink-0 w-[64px]">
                            {new Date((e.t || 0) * 1000).toLocaleTimeString('zh-CN', { hour12: false })}
                          </span>
                          <span className="min-w-0 flex-1 text-gray-200 break-words">{e.msg}</span>
                        </div>
                        {e.snippet ? (
                          <pre className="mt-1 ml-[64px] whitespace-pre-wrap break-words text-amber-200/80 text-[10px] max-h-24 overflow-y-auto">
                            {e.snippet}
                          </pre>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>

                <div className="space-y-1.5">
                  <span className="text-xs font-medium text-gray-600">正文预览</span>
                  <div className="min-h-[100px] max-h-72 overflow-y-auto rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs text-gray-700 leading-relaxed whitespace-pre-wrap font-mono">
                    {job?.text_preview ? (
                      job.text_preview
                    ) : (
                      <span className="text-gray-400">结构提取完成后会在此显示正文；若后端已返回文本，约 1 秒内刷新可见。</span>
                    )}
                  </div>
                </div>

                {job && !!job.total && (
                  <div>
                    <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                      <span>{job.chapters.length} 篇已提取</span>
                      <span>{crawlProgressPct(job)}%</span>
                    </div>
                    <div className="w-full bg-gray-100 rounded-full h-2.5 overflow-hidden">
                      <div
                        className="bg-gradient-to-r from-blue-500 to-blue-400 h-full rounded-full transition-all duration-700 ease-out"
                        style={{ width: `${Math.max(2, crawlProgressPct(job))}%` }}
                      />
                    </div>
                  </div>
                )}

                {job?.current_article && (
                  <div className="flex items-start gap-2 px-3 py-2 bg-blue-50 border border-blue-100 rounded-lg">
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500 flex-shrink-0 mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm text-blue-700 truncate">正在提取: {job.current_article.title}</span>
                        <span className="text-xs text-blue-400 flex-shrink-0">{job.current_article.index + 1}/{job.total}</span>
                      </div>
                      {job.current_article.detail && (
                        <p className="text-xs text-blue-600/90 mt-1 break-words">{job.current_article.detail}</p>
                      )}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            {job?.chapters && job.chapters.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-sm font-medium text-gray-500 px-1">已提取的文章</h3>
                {job.chapters.slice().reverse().map(ch => (
                  <Card key={ch.index} className="apple-card">
                    <div className="flex items-center gap-3 px-5 py-3">
                      {ch.error === 'needs_auth' || ch.error === 'auth_expired' ? (
                        <ShieldAlert className="w-5 h-5 text-amber-400 flex-shrink-0" />
                      ) : ch.error ? (
                        <span className="w-5 h-5 rounded-full bg-red-100 text-red-500 flex items-center justify-center text-xs flex-shrink-0">✕</span>
                      ) : (
                        <CheckCircle className="w-5 h-5 text-green-500 flex-shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium text-gray-900 truncate">{ch.title}</div>
                        <div className="text-xs text-gray-400 mt-0.5 truncate">{ch.graph_path}</div>
                      </div>
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        {ch.error === 'needs_auth' || ch.error === 'auth_expired' ? (
                          <Badge variant="outline" className="text-xs text-amber-600 border-amber-300">{ch.error === 'auth_expired' ? '认证过期' : '需认证'}</Badge>
                        ) : ch.error ? (
                          <Badge variant="destructive" className="text-xs">失败</Badge>
                        ) : (
                          <>
                            <Badge variant="secondary" className="text-xs">{ch.word_count.toLocaleString()}字</Badge>
                            <Badge variant="outline" className="text-xs">{ch.block_count}块</Badge>
                            {ch.images && ch.images.downloaded > 0 && (
                              <Badge variant="outline" className="text-xs text-blue-600 border-blue-300">
                                {ch.images.downloaded}图{(ch.images.analyzed ?? 0) > 0 ? `/${ch.images.analyzed}解读` : ''}
                              </Badge>
                            )}
                            {(ch.videos?.analyzed ?? 0) > 0 && (
                              <Badge variant="outline" className="text-xs text-violet-600 border-violet-300">
                                <Clapperboard className="w-3 h-3 inline mr-0.5" />
                                {ch.videos!.analyzed}视频解读
                              </Badge>
                            )}
                          </>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 w-8 p-0 shrink-0"
                          title={expanded.has(ch.index) ? '收起正文' : '查看提取正文'}
                          aria-label={expanded.has(ch.index) ? '收起正文' : '查看提取正文'}
                          onClick={() => toggleExpand(ch.index)}
                        >
                          {expanded.has(ch.index) ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                        </Button>
                      </div>
                    </div>
                    {expanded.has(ch.index) && (
                      <CardContent className="pt-0 pb-4 px-5 border-t border-gray-100">
                        <p className="text-xs text-gray-500 mb-2">提取正文（Markdown / 纯文本）</p>
                        <div className="bg-gray-50 rounded-lg p-4 max-h-[min(28rem,70vh)] overflow-y-auto">
                          <pre className="whitespace-pre-wrap text-sm text-gray-700 font-mono leading-relaxed">
                            {ch.markdown || ch.text || '（暂无正文，若仍在采集中可稍后再展开）'}
                          </pre>
                        </div>
                      </CardContent>
                    )}
                  </Card>
                ))}
              </div>
            )}
          </>
        )}

        {/* Step 3: Review */}
        {step === 'review' && job && (
          <>
            {/* Show extract command when chapters failed */}
            {job.chapters.some(c => c.error === 'extraction_failed' || (c.word_count === 0 && !c.error?.includes('auth'))) && (
              <div className="mb-4 p-4 bg-amber-50 border border-amber-200 rounded-xl">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm text-amber-700">
                    <ShieldAlert className="w-4 h-4" />
                    <span>部分文章自动采集未拿到正文。可选：使用本机浏览器脚本补充提取（见「本机提取」）。</span>
                  </div>
                  <Button
                    size="sm"
                    className="h-8"
                    onClick={() => {
                      const failedCh = job.chapters.find(c => c.error === 'extraction_failed' || (c.word_count === 0 && !c.error?.includes('auth')))
                      const extractUrl = failedCh?.source_url || url
                      setExtractCommandModal(extractUrl)
                    }}
                  >
                    <Globe className="w-3 h-3 mr-1" /> 本机提取
                  </Button>
                </div>
              </div>
            )}

            <Card className="apple-card mb-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><Eye className="w-5 h-5 text-green-500" /> 审核采集结果</CardTitle>
                <CardDescription>
                  {job.graph_name && <Badge variant="outline" className="mr-2">{job.graph_name}</Badge>}
                  共 {job.chapters.length} 篇文章，
                  {job.chapters.reduce((s, c) => s + c.word_count, 0).toLocaleString()} 字
                  {(() => {
                    const totalImgs = job.chapters.reduce((s, c) => s + (c.images?.downloaded || 0), 0)
                    const analyzedImgs = job.chapters.reduce((s, c) => s + (c.images?.analyzed || 0), 0)
                    return totalImgs > 0 ? `，${totalImgs} 张图片（${analyzedImgs} 张已AI解读）` : ''
                  })()}
                  <span className="block mt-1 text-xs text-gray-400">勾选需要的章节，确认后保存入库 → 自动分块 → 向量化 → RAG</span>
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-3 mb-4">
                  <Button variant="outline" size="sm" onClick={selectAll}>全选</Button>
                  <Button variant="outline" size="sm" onClick={selectNone}>取消全选</Button>
                  <span className="text-sm text-gray-500">已选 {selected.size}/{job.chapters.length}</span>
                  <div className="ml-auto flex items-center gap-2">
                    <select
                      value={selectedKb}
                      onChange={e => setSelectedKb(e.target.value)}
                      className="px-3 py-2 rounded-lg border border-gray-200 bg-white text-sm"
                    >
                      {bases.map(kb => (
                        <option key={kb.id} value={kb.id}>{kb.name}</option>
                      ))}
                    </select>
                    <Button onClick={saveSelected} disabled={saving || selected.size === 0 || !selectedKb}>
                      {saving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Save className="w-4 h-4 mr-1" />}
                      保存到知识库 ({selected.size})
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="space-y-3">
              {job.chapters.map(ch => (
                <Card key={ch.index} className={`apple-card transition-all ${selected.has(ch.index) ? 'ring-2 ring-blue-400' : ''}`}>
                  <div
                    className="flex items-center gap-3 px-6 py-4 cursor-pointer"
                    onClick={() => toggleSelect(ch.index)}
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(ch.index)}
                      onChange={() => toggleSelect(ch.index)}
                      className="w-5 h-5 rounded border-gray-300 text-blue-500 focus:ring-blue-500"
                      onClick={e => e.stopPropagation()}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-gray-900 truncate">{ch.title}</div>
                      <div className="text-xs text-gray-500 mt-0.5">{ch.graph_path}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {ch.error === 'needs_auth' || ch.error === 'auth_expired' ? (
                        <Badge variant="outline" className="text-amber-600 border-amber-300">{ch.error === 'auth_expired' ? '认证已过期，请重新登录' : '需要认证'}</Badge>
                      ) : ch.error ? (
                        <>
                          <Badge variant="destructive">提取失败</Badge>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={e => { e.stopPropagation(); setExtractCommandModal(ch.source_url || url) }}
                          >
                            <Globe className="w-3 h-3 mr-1" /> 本机提取
                          </Button>
                        </>
                      ) : (
                        <>
                          <Badge variant="secondary">{ch.word_count.toLocaleString()}字</Badge>
                          <Badge variant="outline">{ch.block_count}块</Badge>
                          {ch.images && ch.images.downloaded > 0 && (
                            <Badge variant="outline" className="text-blue-600 border-blue-300 flex items-center gap-0.5">
                              <ImageIcon className="w-3 h-3" />{ch.images.downloaded}张
                            </Badge>
                          )}
                          {(ch.images?.analyzed ?? 0) > 0 && (
                            <Badge variant="outline" className="text-green-600 border-green-300 flex items-center gap-0.5">
                              <Sparkles className="w-3 h-3" />已解读{ch.images!.analyzed}张
                            </Badge>
                          )}
                          {(ch.videos?.analyzed ?? 0) > 0 && (
                            <Badge variant="outline" className="text-violet-600 border-violet-300 flex items-center gap-0.5">
                              <Clapperboard className="w-3 h-3" />{ch.videos!.analyzed}段视频已解读
                            </Badge>
                          )}
                          {ch.image_descriptions && Object.keys(ch.image_descriptions).length > 0 && (
                            <Badge variant="outline" className="text-amber-600 border-amber-300 flex items-center gap-0.5">
                              <Sparkles className="w-3 h-3" />{Object.keys(ch.image_descriptions).length}
                            </Badge>
                          )}
                        </>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={e => { e.stopPropagation(); toggleExpand(ch.index) }}
                      >
                        {expanded.has(ch.index) ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </Button>
                    </div>
                  </div>
                  {expanded.has(ch.index) && (
                    <CardContent className="pt-0 border-t border-gray-100 space-y-4">
                      {/* Image Gallery */}
                      {(() => {
                        const imgs = chapterImages[ch.index]
                        const selImgs = selectedImages[ch.index] || new Set()
                        const isAnalyzing = analyzingChapter === ch.index
                        if (!imgs || imgs.length === 0) return null
                        return (
                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <h4 className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
                                <ImageIcon className="w-4 h-4 text-blue-500" />
                                图片 ({imgs.filter(i => i.exists).length})
                              </h4>
                              <div className="flex items-center gap-2">
                                <Button variant="ghost" size="sm" className="h-7 text-xs"
                                  onClick={() => selectAllImages(ch.index)}>全选</Button>
                                <Button variant="ghost" size="sm" className="h-7 text-xs"
                                  onClick={() => selectNoImages(ch.index)}>取消</Button>
                                <span className="text-xs text-gray-400">{selImgs.size} 张已选</span>
                                <Button
                                  size="sm"
                                  className="h-7 text-xs"
                                  disabled={isAnalyzing || selImgs.size === 0}
                                  onClick={() => analyzeChapterImages(ch.index)}
                                >
                                  {isAnalyzing
                                    ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" /> 解读中...</>
                                    : <><Sparkles className="w-3 h-3 mr-1" /> AI 解读 ({selImgs.size})</>
                                  }
                                </Button>
                              </div>
                            </div>
                            <div className="grid grid-cols-4 sm:grid-cols-6 gap-2">
                              {imgs.filter(i => i.exists).map(img => {
                                const isSel = selImgs.has(img.filename)
                                const desc = ch.image_descriptions?.[img.filename]
                                return (
                                  <div
                                    key={img.filename}
                                    className={`relative group rounded-lg overflow-hidden border-2 transition-all cursor-pointer ${
                                      isSel ? 'border-blue-400 shadow-sm' : 'border-transparent hover:border-gray-200'
                                    }`}
                                  >
                                    <div
                                      className="absolute top-1 left-1 z-10"
                                      onClick={(e) => { e.stopPropagation(); toggleImageSelect(ch.index, img.filename) }}
                                    >
                                      {isSel
                                        ? <CheckSquare className="w-4 h-4 text-blue-500 bg-white rounded" />
                                        : <Square className="w-4 h-4 text-gray-400 bg-white/80 rounded opacity-0 group-hover:opacity-100 transition" />
                                      }
                                    </div>
                                    {desc && (
                                      <div className="absolute top-1 right-1 z-10">
                                        <Sparkles className="w-3 h-3 text-amber-500" />
                                      </div>
                                    )}
                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                    <img
                                      src={img.url}
                                      alt={img.alt || img.token}
                                      className="w-full h-20 object-cover bg-gray-100"
                                      loading="lazy"
                                      onClick={() => setImagePreview(img.url)}
                                    />
                                    {desc && (
                                      <div className="absolute inset-x-0 bottom-0 bg-black/60 text-white text-[10px] p-1 line-clamp-2 leading-tight">
                                        {desc.slice(0, 60)}…
                                      </div>
                                    )}
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                        )
                      })()}

                      {/* Text Content */}
                      <div className="bg-gray-50 rounded-lg p-4 max-h-96 overflow-y-auto">
                        <pre className="whitespace-pre-wrap text-sm text-gray-700 font-mono leading-relaxed">
                          {ch.markdown || ch.text || '(无内容)'}
                        </pre>
                      </div>
                    </CardContent>
                  )}
                </Card>
              ))}
            </div>
          </>
        )}

        {/* Step 4: Done */}
        {step === 'done' && (
          <Card className="apple-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><CheckCircle className="w-5 h-5 text-green-500" /> 保存完成</CardTitle>
              <CardDescription>
                已提交 {savedTasks.length} 篇文章到知识库，正在后台执行完整入库管线
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="bg-gray-50 rounded-lg p-4 space-y-2">
                <div className="text-sm font-medium text-gray-700">入库管线</div>
                <div className="flex flex-wrap gap-2">
                  {['分块(Chunking)', '向量化(Embedding)', '假设提示嵌入(HyPE)', '知识图谱(GraphRAG)'].map(stage => (
                    <Badge key={stage} variant="outline" className="text-xs text-green-600 border-green-300">
                      <CheckCircle className="w-3 h-3 mr-1" />{stage}
                    </Badge>
                  ))}
                </div>
              </div>
              {savedTasks.length > 0 && (
                <div className="text-sm text-gray-500">
                  任务ID: {savedTasks.map(t => t.slice(0, 8)).join(', ')}
                </div>
              )}
              <div className="flex gap-3 mt-4">
                <Link href="/tasks">
                  <Button variant="default"><FileText className="w-4 h-4 mr-1" /> 查看入库进度</Button>
                </Link>
                <Button variant="outline" onClick={reset}><RefreshCw className="w-4 h-4 mr-1" /> 继续采集</Button>
                <Link href="/knowledge">
                  <Button variant="ghost"><Database className="w-4 h-4 mr-1" /> 返回知识库</Button>
                </Link>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Image Preview Modal */}
        {imagePreview && (
          <div
            className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-8 cursor-pointer"
            onClick={() => setImagePreview(null)}
          >
            <div className="relative max-w-4xl max-h-[85vh]" onClick={e => e.stopPropagation()}>
              <Button
                variant="ghost"
                size="sm"
                className="absolute -top-10 right-0 text-white hover:bg-white/20"
                onClick={() => setImagePreview(null)}
              >
                <X className="w-5 h-5" />
              </Button>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imagePreview}
                alt="Preview"
                className="max-w-full max-h-[85vh] object-contain rounded-lg shadow-2xl"
              />
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
