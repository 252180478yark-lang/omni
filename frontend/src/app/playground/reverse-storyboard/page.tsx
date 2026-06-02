'use client'

import { useState } from 'react'
import Link from 'next/link'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ArrowLeft, Loader2, Wand2, FileVideo, AlertCircle, Copy, Download,
  ChevronDown, ChevronRight, Sparkles, Link2,
} from 'lucide-react'

type TargetKind = '' | 'video_planting' | 'video_harvest' | 'video_soft_ad'
type InputMode = 'path' | 'url'

interface TraceShape {
  model_provider?: string
  model?: string
  final_prompt?: string
  params?: Record<string, unknown>
  cost_estimate?: string
}

interface ReverseResult {
  ok: boolean
  result?: {
    markdown?: string
    scenes?: Array<Record<string, unknown>>
    placeholders?: Record<string, unknown>
    storyboard_for_image_set?: Record<string, unknown>
    storyboard_for_video_segments?: Record<string, unknown>
    storyboard_for_video_long?: Record<string, unknown>
    methodology_guess?: Record<string, unknown>
    hook_analysis?: Record<string, unknown>
    meta?: Record<string, unknown>
    [key: string]: unknown
  }
  trace?: TraceShape
  error?: string
  hint?: string
  detail?: string
}

/**
 * Host Windows 路径 → KE 容器内路径自动转换。
 * docker-compose.yml 已 bind-mount: C:/Users/Administrator/Desktop → /host/Desktop
 *
 * 规则:
 * - 已经 /host/* 风格 → 原样返回
 * - C:/Users/Administrator/Desktop/X 或反斜杠 → /host/Desktop/X
 * - 其它 host 路径(C:/foo) → 返原值并标记 warning(显示给老板看)
 */
function hostPathToContainer(raw: string): { path: string; warning?: string } {
  const v = raw.trim().replace(/\\/g, '/')
  if (!v) return { path: '' }
  if (v.startsWith('/host/')) return { path: v }
  // C:/Users/Administrator/Desktop/* → /host/Desktop/*
  const m = v.match(/^[Cc]:\/Users\/Administrator\/Desktop\/(.+)$/)
  if (m) return { path: `/host/Desktop/${m[1]}` }
  if (/^[A-Za-z]:\//.test(v)) {
    return {
      path: v,
      warning: '这条 host 路径不在 KE 已 mount 的目录里(只有 C:/Users/Administrator/Desktop 被 mount 成 /host/Desktop)，KE 大概率读不到文件。',
    }
  }
  return { path: v }
}

export default function ReverseStoryboardTestPage() {
  const [inputMode, setInputMode] = useState<InputMode>('path')
  const [videoPath, setVideoPath] = useState('')
  const [shareUrl, setShareUrl] = useState('')
  const [targetKind, setTargetKind] = useState<TargetKind>('')
  const [extraContext, setExtraContext] = useState('')
  const [productRefCount, setProductRefCount] = useState(1)
  const [faceRefCount, setFaceRefCount] = useState(1)
  const [modelOverride, setModelOverride] = useState('')
  const [showTrace, setShowTrace] = useState(false)
  const [showRawJson, setShowRawJson] = useState(false)

  const [loading, setLoading] = useState(false)
  const [elapsedSec, setElapsedSec] = useState(0)
  const [resp, setResp] = useState<ReverseResult | null>(null)
  const [, setPathWarning] = useState<string | null>(null)

  const { path: containerPath, warning: pathWarn } = hostPathToContainer(videoPath)
  const trimmedUrl = shareUrl.trim()
  // 包含匹配(不锚 ^),容忍老板把整段抖音分享文案粘进来:
  //   "0.74 :1pm lCU:/ 07/07 标题 #tag https://v.douyin.com/xxx/ 复制此链接..."
  // 后端 resolver 也会再抠一次,前端只是给个 hint
  const isUrlPlausible = /https?:\/\/(v\.douyin\.com|(www\.)?iesdouyin\.com)\//i.test(trimmedUrl)

  async function submit() {
    if (inputMode === 'path' && !videoPath.trim()) return
    if (inputMode === 'url' && !trimmedUrl) return
    setLoading(true)
    setResp(null)
    setPathWarning(pathWarn || null)
    setElapsedSec(0)
    const t0 = Date.now()
    const timer = setInterval(() => setElapsedSec(Math.floor((Date.now() - t0) / 1000)), 1000)
    try {
      const body: Record<string, unknown> = {
        target_kind: targetKind || null,
        extra_context: extraContext.trim() || null,
        product_ref_count: productRefCount,
        face_ref_count: faceRefCount,
        model: modelOverride.trim() || null,
      }
      if (inputMode === 'path') {
        body.video_path = containerPath
      } else {
        body.share_url = trimmedUrl
      }
      const r = await fetch('/api/omni/mcp-exec/reverse-storyboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = (await r.json()) as ReverseResult
      setResp(data)
    } catch (e) {
      setResp({ ok: false, error: 'request_failed', detail: (e as Error).message })
    } finally {
      clearInterval(timer)
      setLoading(false)
    }
  }

  const markdown = resp?.result?.markdown || ''

  async function copyMd() {
    if (!markdown) return
    try {
      await navigator.clipboard.writeText(markdown)
    } catch {
      /* clipboard may be blocked */
    }
  }
  function _baseName(): string {
    if (inputMode === 'path') {
      return videoPath.split(/[\\/]/).pop()?.replace(/\.\w+$/, '') || 'reverse_storyboard'
    }
    const m = trimmedUrl.match(/\/(\d{15,20})\//) || trimmedUrl.match(/\/([A-Za-z0-9]{8,})\/?$/)
    return m ? `dyrev_${m[1]}` : 'reverse_storyboard'
  }
  function downloadMd() {
    if (!markdown) return
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${_baseName()}_storyboard.md`
    a.click()
    URL.revokeObjectURL(url)
  }
  function downloadJson() {
    if (!resp?.result) return
    const blob = new Blob([JSON.stringify(resp, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${_baseName()}_storyboard.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="min-h-[100dvh] bg-[#F5F5F7]">
      <nav className="sticky top-0 z-30 bg-white/80 backdrop-blur border-b border-gray-200/50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
          <Link
            href="/playground"
            className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900"
          >
            <ArrowLeft className="w-4 h-4" />
            返回 Playground
          </Link>
          <div className="font-semibold text-gray-900 inline-flex items-center gap-2">
            <Wand2 className="w-4 h-4 text-violet-600" />
            反推故事板 · tool 测试
          </div>
          <a
            href="https://gist.github.com" // placeholder; replaced by inline note
            className="text-[11px] text-gray-400 invisible"
          >
            spacer
          </a>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 grid lg:grid-cols-[380px_1fr] gap-6">
        {/* ── 左侧表单 ────────────────────────────── */}
        <aside className="rounded-xl bg-white border border-gray-100 shadow-sm p-4 space-y-4 h-fit lg:sticky lg:top-20">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <FileVideo className="w-4 h-4 text-violet-600" />
              <h2 className="text-sm font-semibold text-gray-900">视频来源</h2>
            </div>
            {/* mode 切换 */}
            <div className="flex gap-1 mb-2 p-0.5 bg-gray-100 rounded-md">
              <button
                type="button"
                onClick={() => setInputMode('path')}
                className={`flex-1 text-[11px] py-1.5 rounded font-medium transition ${
                  inputMode === 'path'
                    ? 'bg-white text-violet-700 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <FileVideo className="w-3 h-3 inline mr-1 -mt-0.5" />
                本地文件
              </button>
              <button
                type="button"
                onClick={() => setInputMode('url')}
                className={`flex-1 text-[11px] py-1.5 rounded font-medium transition ${
                  inputMode === 'url'
                    ? 'bg-white text-violet-700 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Link2 className="w-3 h-3 inline mr-1 -mt-0.5" />
                抖音链接
              </button>
            </div>

            {inputMode === 'path' && (
              <>
                <textarea
                  value={videoPath}
                  onChange={(e) => setVideoPath(e.target.value)}
                  rows={2}
                  placeholder="C:/Users/Administrator/Desktop/X.mp4 或 /host/Desktop/X.mp4"
                  className="w-full text-xs font-mono px-2 py-1.5 rounded border border-gray-200 focus:outline-none focus:border-violet-400 resize-none bg-white"
                />
                <div className="mt-1 text-[10px] text-gray-500 space-y-0.5">
                  {videoPath && (
                    <div>
                      容器内: <code className="font-mono text-gray-700">{containerPath || '(空)'}</code>
                    </div>
                  )}
                  <div>仅 Desktop 已 mount; 其它路径放桌面再试.</div>
                </div>
                {pathWarn && (
                  <div className="mt-1.5 px-2 py-1 rounded bg-amber-50 border border-amber-200 text-[10px] text-amber-700 flex gap-1.5">
                    <AlertCircle className="w-3 h-3 mt-0.5 shrink-0" />
                    <span>{pathWarn}</span>
                  </div>
                )}
              </>
            )}

            {inputMode === 'url' && (
              <>
                <textarea
                  value={shareUrl}
                  onChange={(e) => setShareUrl(e.target.value)}
                  rows={3}
                  placeholder={'https://v.douyin.com/I3HhgVTMMvA/\n或粘抖音 app "复制链接" 那一整段,只挑 URL 也行'}
                  className="w-full text-xs font-mono px-2 py-1.5 rounded border border-gray-200 focus:outline-none focus:border-violet-400 resize-none bg-white"
                />
                <div className="mt-1 text-[10px] text-gray-500 space-y-0.5">
                  <div>支持: <code className="font-mono">v.douyin.com</code> 短链 / <code className="font-mono">iesdouyin.com</code> 长链</div>
                  <div>视频会下载到 <code className="font-mono text-gray-700">/host/Desktop/omni_video_cache/</code>(同一视频不重复下)</div>
                </div>
                {trimmedUrl && !isUrlPlausible && (
                  <div className="mt-1.5 px-2 py-1 rounded bg-amber-50 border border-amber-200 text-[10px] text-amber-700 flex gap-1.5">
                    <AlertCircle className="w-3 h-3 mt-0.5 shrink-0" />
                    <span>不像抖音链接 — 后端会再校验一次,如果链接确实是抖音的可直接试.</span>
                  </div>
                )}
              </>
            )}
          </div>

          <div>
            <h3 className="text-xs font-semibold text-gray-700 mb-1.5">target_kind 提示方法论(可选)</h3>
            <select
              value={targetKind}
              onChange={(e) => setTargetKind(e.target.value as TargetKind)}
              className="w-full text-xs px-2 py-1.5 rounded border border-gray-200 focus:outline-none focus:border-violet-400 bg-white"
            >
              <option value="">(自动 — LLM 自由选)</option>
              <option value="video_planting">video_planting · A3 种草</option>
              <option value="video_harvest">video_harvest · A4 收割</option>
              <option value="video_soft_ad">video_soft_ad · A2 软广</option>
            </select>
            <div className="mt-1 text-[10px] text-gray-500">
              不选 → LLM 从 8 个方法论(Pixar/SoL/CER/Hero/Empathy/CT/Aspirational/Mini-Doc)里挑.
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <h3 className="text-xs font-semibold text-gray-700 mb-1.5">product_ref</h3>
              <input
                type="number"
                min={0}
                max={5}
                value={productRefCount}
                onChange={(e) => setProductRefCount(Math.max(0, Math.min(5, parseInt(e.target.value || '0', 10))))}
                className="w-full text-xs px-2 py-1.5 rounded border border-gray-200 focus:outline-none focus:border-violet-400 bg-white font-mono"
              />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-gray-700 mb-1.5">face_ref</h3>
              <input
                type="number"
                min={0}
                max={5}
                value={faceRefCount}
                onChange={(e) => setFaceRefCount(Math.max(0, Math.min(5, parseInt(e.target.value || '0', 10))))}
                className="w-full text-xs px-2 py-1.5 rounded border border-gray-200 focus:outline-none focus:border-violet-400 bg-white font-mono"
              />
            </div>
          </div>
          <div className="text-[10px] text-gray-500 -mt-2">
            期望视频里有几个产品/人脸. LLM 实际识别可能不同 → 差异写 warnings.
          </div>

          <div>
            <h3 className="text-xs font-semibold text-gray-700 mb-1.5">extra_context(可选)</h3>
            <textarea
              value={extraContext}
              onChange={(e) => setExtraContext(e.target.value)}
              rows={3}
              placeholder="给 LLM 临时方向, 如:&#10;- 这视频是抖音收割款&#10;- 重点反推钩子设计&#10;- 注意识别字幕"
              className="w-full text-xs px-2 py-1.5 rounded border border-gray-200 focus:outline-none focus:border-violet-400 resize-none bg-white"
            />
          </div>

          <div>
            <h3 className="text-xs font-semibold text-gray-700 mb-1.5">
              model 覆盖(留空 = 用 yaml 默认)
            </h3>
            <input
              type="text"
              value={modelOverride}
              onChange={(e) => setModelOverride(e.target.value)}
              placeholder="如 gemini-3-flash-preview"
              className="w-full text-xs px-2 py-1.5 rounded border border-gray-200 focus:outline-none focus:border-violet-400 bg-white font-mono"
            />
            <div className="mt-1 text-[10px] text-gray-500">
              默认 gemini-2.5-flash; pro/lite 切换填这里, 不用改 yaml.
            </div>
          </div>

          <button
            onClick={submit}
            disabled={loading || (inputMode === 'path' ? !videoPath.trim() : !trimmedUrl)}
            className="w-full inline-flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                跑反推中 · {elapsedSec}s
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                跑反推
              </>
            )}
          </button>
          <div className="text-[10px] text-gray-400 -mt-2 text-center">
            {inputMode === 'url'
              ? '抖音链接首次跑 = 解析下载几秒 + 反推 30-180s; 同链接重跑命中缓存只跑反推.'
              : '视频反推典型 30-180s · 大视频走 Files API 上传更慢.'}
          </div>
        </aside>

        {/* ── 右侧结果 ────────────────────────────── */}
        <section className="rounded-xl bg-white border border-gray-100 shadow-sm p-4 min-h-[400px]">
          {!resp && !loading && (
            <div className="text-center py-20 text-gray-400">
              <Wand2 className="w-10 h-10 mx-auto mb-3 opacity-40" />
              <div className="text-sm">填左侧表单 → 点"跑反推"看输出.</div>
              <div className="text-[11px] mt-2 max-w-md mx-auto leading-relaxed">
                输出含: 分镜表(每段 19 字段) · 3 类全局 prompt 包(image_set / video_i2v_segments / video_t2v_long) ·
                方法论判断 · 钩子完播估算.
              </div>
            </div>
          )}

          {loading && (
            <div className="text-center py-20 text-gray-500">
              <Loader2 className="w-10 h-10 mx-auto mb-3 animate-spin text-violet-500" />
              <div className="text-sm">
                {inputMode === 'url' && elapsedSec < 8 ? '解析抖音链接 + 下载视频...' : 'LLM 反推中...'}
                {' '}已耗时 {elapsedSec}s
              </div>
              <div className="text-[11px] mt-2 max-w-md mx-auto text-gray-400">
                {inputMode === 'url'
                  ? '解析 SSR HTML 抠无水印 mp4 → Gemini Files API 上传 → 多 scene 推理. 30s 短视频典型 1-2 分钟.'
                  : 'Gemini Files API 上传视频 + 多 scene 推理. 30s 短视频典型 1-2 分钟.'}
              </div>
            </div>
          )}

          {resp && !loading && (
            <div className="space-y-4">
              {/* 头部状态条 */}
              <div
                className={`px-3 py-2 rounded-md border flex items-center gap-2 text-sm ${
                  resp.ok
                    ? 'bg-green-50 border-green-200 text-green-800'
                    : 'bg-red-50 border-red-200 text-red-800'
                }`}
              >
                {resp.ok ? '✓ 反推成功' : '✗ 反推失败'}
                {!resp.ok && resp.error && (
                  <span className="font-mono text-xs">: {resp.error}</span>
                )}
              </div>

              {/* 错误细节 */}
              {!resp.ok && (resp.hint || resp.detail) && (
                <div className="px-3 py-2 rounded-md bg-red-50/50 border border-red-100 text-xs text-red-700">
                  {resp.hint && <div>{resp.hint}</div>}
                  {resp.detail && (
                    <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{resp.detail}</pre>
                  )}
                </div>
              )}

              {/* 成功 → 渲染 markdown */}
              {resp.ok && markdown && (
                <>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={copyMd}
                      className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50"
                    >
                      <Copy className="w-3 h-3" />
                      复制 md
                    </button>
                    <button
                      onClick={downloadMd}
                      className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50"
                    >
                      <Download className="w-3 h-3" />
                      下载 .md
                    </button>
                    <button
                      onClick={downloadJson}
                      className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50"
                    >
                      <Download className="w-3 h-3" />
                      下载 .json
                    </button>
                  </div>

                  <article className="prose prose-sm max-w-none prose-headings:font-semibold prose-h1:text-xl prose-h2:text-lg prose-h3:text-base prose-pre:bg-gray-50 prose-pre:text-xs prose-code:text-violet-700 prose-code:bg-violet-50 prose-code:px-1 prose-code:rounded prose-table:text-xs">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
                  </article>
                </>
              )}

              {/* 没 markdown 但有 result(老版本兜底) */}
              {resp.ok && !markdown && resp.result && (
                <div className="px-3 py-2 rounded-md bg-amber-50 border border-amber-200 text-xs text-amber-700">
                  result 没带 markdown 字段, 看下面 raw JSON.
                </div>
              )}

              {/* trace 折叠 */}
              {resp.trace && (
                <div className="border border-gray-100 rounded-md">
                  <button
                    onClick={() => setShowTrace((v) => !v)}
                    className="w-full px-3 py-2 flex items-center justify-between text-xs font-semibold text-gray-700 hover:bg-gray-50"
                  >
                    <span className="inline-flex items-center gap-1">
                      {showTrace ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      Trace ({resp.trace.model_provider}/{resp.trace.model})
                    </span>
                    <span className="text-gray-400 font-normal font-mono">{resp.trace.cost_estimate}</span>
                  </button>
                  {showTrace && (
                    <div className="px-3 pb-3 space-y-2 text-xs">
                      {resp.trace.params && (
                        <div>
                          <div className="text-[10px] font-semibold text-gray-500 mb-1">params</div>
                          <pre className="bg-gray-50 px-2 py-1.5 rounded overflow-x-auto font-mono text-[10.5px]">
                            {JSON.stringify(resp.trace.params, null, 2)}
                          </pre>
                        </div>
                      )}
                      {resp.trace.final_prompt && (
                        <div>
                          <div className="text-[10px] font-semibold text-gray-500 mb-1">final_prompt 预览</div>
                          <pre className="bg-gray-50 px-2 py-1.5 rounded overflow-x-auto font-mono text-[10.5px] max-h-64">
                            {resp.trace.final_prompt}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* raw JSON 折叠 */}
              {resp.result && (
                <div className="border border-gray-100 rounded-md">
                  <button
                    onClick={() => setShowRawJson((v) => !v)}
                    className="w-full px-3 py-2 flex items-center justify-between text-xs font-semibold text-gray-700 hover:bg-gray-50"
                  >
                    <span className="inline-flex items-center gap-1">
                      {showRawJson ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      Raw JSON (供前端/外部模型调用)
                    </span>
                    <span className="text-gray-400 font-normal">
                      scenes: {Array.isArray(resp.result.scenes) ? resp.result.scenes.length : 0}
                    </span>
                  </button>
                  {showRawJson && (
                    <pre className="px-3 pb-3 bg-gray-50 overflow-x-auto font-mono text-[10.5px] max-h-[480px]">
                      {JSON.stringify(resp.result, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
