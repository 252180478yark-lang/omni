'use client'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Loader2, Play, Square, ChevronDown, ChevronRight, FileDown, MessageSquare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { usePersonaStore } from '@/stores/personaStore'
import type { Persona } from '@/lib/personas/types'
import { useRoundtableStore, type RoundtableSpeech } from '@/stores/roundtableStore'
import { PRESET_PERSONA_IDS } from '@/lib/personas/preset-personas'
import type { SourceRef } from '@/stores/chatStore'
import { captureElementToPdf } from '@/lib/capture-element-to-pdf'

interface KBItem {
  id: string
  name: string
  description: string
}

interface RoundtableViewProps {
  kbOptions: KBItem[]
  kbIds: string[]
  onToggleKb: (id: string) => void
  selectedProvider: string
  selectedModel: string
  onContinueSolo: () => void
}

function parseAtMention(participants: Persona[], raw: string): { content: string; targetPersonaId: string | null } {
  const trimmed = raw.trim()
  const m = trimmed.match(/^@([^\s@]+)\s+([\s\S]+)$/)
  if (!m) return { content: trimmed, targetPersonaId: null }
  const name = m[1].trim()
  const p = participants.find((x) => x.name === name)
  return { content: trimmed, targetPersonaId: p?.id ?? null }
}

function speechesByRound(speeches: RoundtableSpeech[], round: number): RoundtableSpeech[] {
  return speeches.filter((s) => s.round === round)
}

function buildRoundHistoryPayload(
  speeches: RoundtableSpeech[],
  maxRound: number,
): Record<string, Record<string, string>> {
  const h: Record<string, Record<string, string>> = {}
  for (let r = 1; r <= maxRound; r++) {
    const m: Record<string, string> = {}
    for (const s of speeches) {
      if (s.round === r && s.content && !s.error) m[s.personaId] = s.content
    }
    if (Object.keys(m).length) h[String(r)] = m
  }
  return h
}

export function RoundtableView({
  kbOptions,
  kbIds,
  onToggleKb,
  selectedProvider,
  selectedModel,
  onContinueSolo,
}: RoundtableViewProps) {
  const { personas, getPersonaById } = usePersonaStore()
  const {
    session,
    createSession,
    reset,
    setAbort,
    abort,
    addSpeechPlaceholder,
    appendSpeechToken,
    finishSpeech,
    failSpeech,
    addIntervention,
    startSummary,
    appendSummaryToken,
    finishSummary,
    setStatus,
    bumpCurrentRound,
  } = useRoundtableStore()

  const orderedPersonas = useMemo(() => {
    const presetIds = new Set(PRESET_PERSONA_IDS as unknown as string[])
    const presets = PRESET_PERSONA_IDS.map((id) => personas.find((p) => p.id === id)).filter(
      Boolean,
    ) as Persona[]
    const customs = personas.filter((p) => !presetIds.has(p.id))
    return [...presets, ...customs]
  }, [personas])

  const [participantIds, setParticipantIds] = useState<string[]>([])
  const [moderatorType, setModeratorType] = useState<'default' | 'boss'>('default')
  const [totalRounds, setTotalRounds] = useState(3)
  const [topic, setTopic] = useState('')
  const [targetCharsInput, setTargetCharsInput] = useState('')
  const [running, setRunning] = useState(false)
  const [errorTip, setErrorTip] = useState('')
  const [interveneText, setInterveneText] = useState('')
  const [expandedRounds, setExpandedRounds] = useState<Record<number, boolean>>({ 1: true })
  const [pauseAfterRound, setPauseAfterRound] = useState(0)

  const participants = useMemo(
    () => participantIds.map((id) => getPersonaById(id)).filter(Boolean) as Persona[],
    [participantIds, getPersonaById],
  )

  const metaRef = useRef({
    selectedModel,
    selectedProvider,
    participants,
    totalRounds,
    targetCharsInput,
  })
  useEffect(() => {
    metaRef.current = { selectedModel, selectedProvider, participants, totalRounds, targetCharsInput }
  }, [selectedModel, selectedProvider, participants, totalRounds, targetCharsInput])

  const toggleParticipant = (id: string) => {
    setParticipantIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= 5) {
        setErrorTip('最多选择 5 个参会角色')
        return prev
      }
      setErrorTip('')
      return [...prev, id]
    })
  }

  const toggleRoundExpanded = (r: number) => {
    setExpandedRounds((e) => ({ ...e, [r]: !e[r] }))
  }

  const runStream = useCallback(
    async (body: Record<string, unknown>, ctrl: AbortController) => {
      const res = await fetch('/api/omni/roundtable', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      })
      if (!res.ok) {
        const t = await res.text()
        throw new Error(t || `HTTP ${res.status}`)
      }
      if (!res.body) throw new Error('空响应')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue
          const payload = trimmed.slice(5).trim()
          if (payload === '[DONE]') continue
          try {
            const ev = JSON.parse(payload) as Record<string, unknown>
            const type = ev.type as string
            if (type === 'speech-start') {
              addSpeechPlaceholder({
                personaId: ev.personaId as string,
                personaName: ev.personaName as string,
                personaIcon: ev.personaIcon as string,
                round: ev.round as number,
              })
            } else if (type === 'speech-token') {
              const sid = useRoundtableStore
                .getState()
                .session?.speeches.filter(
                  (s) => s.personaId === ev.personaId && s.round === ev.round && s.loading,
                )
                .at(-1)?.id
              if (sid) appendSpeechToken(sid, (ev.content as string) || '')
            } else if (type === 'speech-done') {
              const sid = useRoundtableStore
                .getState()
                .session?.speeches.find(
                  (s) => s.personaId === ev.personaId && s.round === ev.round && s.loading,
                )?.id
              if (sid) finishSpeech(sid, (ev.sources as SourceRef[]) || [])
            } else if (type === 'error' && ev.personaId) {
              const sid = useRoundtableStore
                .getState()
                .session?.speeches.find(
                  (s) =>
                    s.personaId === ev.personaId &&
                    s.loading &&
                    (ev.round == null || s.round === ev.round),
                )?.id
              if (sid) failSpeech(sid, String(ev.error || '错误'))
            } else if (type === 'summary-token') {
              appendSummaryToken((ev.content as string) || '')
            } else if (type === 'summary-continue-meta') {
              const hint = `\n\n*[续写第 ${ev.continueRound} 段，已累计约 ${ev.charsSoFar} 字符，目标 ${ev.target} 字符...]*\n\n`
              appendSummaryToken(hint)
            } else if (type === 'summary-done') {
              finishSummary()
            } else if (type === 'error' && !ev.personaId) {
              setErrorTip(String(ev.error || '未知错误'))
            }
          } catch {
            /* ignore */
          }
        }
      }
    },
    [
      addSpeechPlaceholder,
      appendSpeechToken,
      appendSummaryToken,
      failSpeech,
      finishSpeech,
      finishSummary,
    ],
  )

  const parseTargetChars = () => {
    const raw = metaRef.current.targetCharsInput.trim()
    if (!raw) return undefined
    const n = parseInt(raw, 10)
    return !Number.isNaN(n) && n > 0 ? n : undefined
  }

  const executeRound = useCallback(
    async (round: number, ctrl: AbortController) => {
      const st = useRoundtableStore.getState().session
      if (!st) throw new Error('会话不存在')
      const { selectedModel: m, selectedProvider: p, participants: parts } = metaRef.current
      setExpandedRounds((e) => ({ ...e, [round]: true }))
      setStatus('discussing')

      const speeches = useRoundtableStore.getState().session?.speeches ?? []
      const historyPayload = buildRoundHistoryPayload(speeches, round - 1)
      const ivForRound = (useRoundtableStore.getState().session?.interventions ?? []).filter(
        (i) => i.afterRound === round - 1,
      )

      const tc = parseTargetChars()
      const body: Record<string, unknown> = {
        action: 'run-round',
        topic: st.topic,
        participants: parts,
        moderatorType: st.moderatorType,
        totalRounds: st.totalRounds,
        kbIds: st.kbIds,
        model: m,
        provider: p,
        round,
        roundHistory: historyPayload,
        interventions: ivForRound.map((i) => ({
          content: i.content,
          targetPersonaId: i.targetPersonaId,
          afterRound: i.afterRound,
        })),
      }
      if (tc) body.targetChars = tc

      await runStream(body, ctrl)
      bumpCurrentRound()
    },
    [bumpCurrentRound, runStream, setStatus],
  )

  const executeSummary = useCallback(
    async (ctrl: AbortController) => {
      const st = useRoundtableStore.getState().session
      if (!st) return
      const { selectedModel: m, selectedProvider: p, participants: parts } = metaRef.current
      const speeches = useRoundtableStore.getState().session?.speeches ?? []
      const historyPayload = buildRoundHistoryPayload(speeches, st.totalRounds)
      const ivAll = useRoundtableStore.getState().session?.interventions ?? []

      const tc = parseTargetChars()
      const body: Record<string, unknown> = {
        action: 'run-summary',
        topic: st.topic,
        participants: parts,
        moderatorType: st.moderatorType,
        totalRounds: st.totalRounds,
        kbIds: st.kbIds,
        model: m,
        provider: p,
        roundHistory: historyPayload,
        interventions: ivAll.map((i) => ({
          content: i.content,
          targetPersonaId: i.targetPersonaId,
          afterRound: i.afterRound,
        })),
      }
      if (tc) body.targetChars = tc

      startSummary()
      await runStream(body, ctrl)
    },
    [runStream, startSummary],
  )

  const handleStart = async () => {
    setErrorTip('')
    if (!topic.trim()) {
      setErrorTip('请输入讨论议题')
      return
    }
    if (participantIds.length < 2) {
      setErrorTip('至少选择 2 个参会角色')
      return
    }
    if (kbIds.length === 0) {
      setErrorTip('请至少选择一个知识库')
      return
    }
    if (!selectedProvider || !selectedModel) {
      setErrorTip('请选择 AI 模型')
      return
    }

    reset()
    createSession({
      topic: topic.trim(),
      participantIds: [...participantIds],
      moderatorType,
      totalRounds,
      kbIds: [...kbIds],
      model: selectedModel,
      provider: selectedProvider,
    })

    const ctrl = new AbortController()
    setAbort(ctrl)
    setRunning(true)
    setPauseAfterRound(0)

    try {
      const st = useRoundtableStore.getState().session
      if (!st) throw new Error('会话未创建')

      await executeRound(1, ctrl)
      if (ctrl.signal.aborted) return

      if (st.totalRounds > 1) {
        setPauseAfterRound(1)
        setStatus('intervening')
        return
      }

      await executeSummary(ctrl)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setErrorTip(String(e))
    } finally {
      setRunning(false)
      setAbort(null)
    }
  }

  const handleContinueNextRound = async () => {
    const st = useRoundtableStore.getState().session
    if (!st || pauseAfterRound <= 0) return
    const nextR = pauseAfterRound + 1

    const ctrl = new AbortController()
    setAbort(ctrl)
    setRunning(true)
    setPauseAfterRound(0)
    setStatus('discussing')
    setErrorTip('')

    try {
      await executeRound(nextR, ctrl)
      if (ctrl.signal.aborted) return

      if (nextR < st.totalRounds) {
        setPauseAfterRound(nextR)
        setStatus('intervening')
      } else {
        await executeSummary(ctrl)
      }
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setErrorTip(String(e))
    } finally {
      setRunning(false)
      setAbort(null)
    }
  }

  const handleInterventionAll = () => {
    const t = interveneText.trim()
    if (!t || !pauseAfterRound) return
    addIntervention(t, null, pauseAfterRound)
    setInterveneText('')
  }

  const handleInterventionSend = () => {
    const t = interveneText.trim()
    if (!t || !pauseAfterRound) return
    const { content, targetPersonaId } = parseAtMention(participants, t)
    addIntervention(content, targetPersonaId, pauseAfterRound)
    setInterveneText('')
  }

  const handleStop = () => {
    abort()
    setRunning(false)
    setPauseAfterRound(0)
  }

  const [pdfExporting, setPdfExporting] = useState(false)

  const exportPdf = async () => {
    const s = useRoundtableStore.getState().session
    const sum = s?.summary?.content
    if (!s || !sum) return

    setPdfExporting(true)
    const overlay = document.createElement('div')
    overlay.setAttribute('aria-hidden', 'true')
    overlay.style.cssText =
      'position:fixed;inset:0;background:#fafafa;z-index:2147483646;pointer-events:all;'

    const shell = document.createElement('div')
    let exportRoot: HTMLElement | null = null
    try {
      const participantNames = s.participantIds
        .map((id) => getPersonaById(id)?.name || id)
        .join('、')
      const modLabel = s.moderatorType === 'boss' ? '老板视角' : '默认主持人'

      shell.innerHTML = `
        <div style="font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; padding: 32px; color: #111; background: #fff; width: 794px; box-sizing: border-box;">
          <h1 style="text-align: center; border-bottom: 2px solid #333; padding-bottom: 12px; font-size: 22px;">
            圆桌会议报告
          </h1>
          <table style="width: 100%; margin: 16px 0; font-size: 13px; border-collapse: collapse;">
            <tr><td style="padding: 6px; font-weight: bold; width: 120px;">议题</td><td style="padding: 6px;">${escapeHtml(s.topic)}</td></tr>
            <tr><td style="padding: 6px; font-weight: bold;">日期</td><td style="padding: 6px;">${new Date(s.createdAt).toLocaleDateString('zh-CN')}</td></tr>
            <tr><td style="padding: 6px; font-weight: bold;">参会角色</td><td style="padding: 6px;">${escapeHtml(participantNames)}</td></tr>
            <tr><td style="padding: 6px; font-weight: bold;">讨论轮数</td><td style="padding: 6px;">${s.totalRounds}轮</td></tr>
            <tr><td style="padding: 6px; font-weight: bold;">主持人</td><td style="padding: 6px;">${modLabel}</td></tr>
            <tr><td style="padding: 6px; font-weight: bold;">AI 模型</td><td style="padding: 6px;">${escapeHtml(selectedModel || '')}</td></tr>
          </table>
          <hr style="margin: 16px 0;"/>
          <div style="font-size: 13px; line-height: 1.6;">${simpleMdToHtml(sum)}</div>
        </div>
      `

      exportRoot = shell.firstElementChild as HTMLElement | null
      if (!exportRoot) throw new Error('导出内容构建失败')

      Object.assign(exportRoot.style, {
        position: 'fixed',
        left: '0',
        top: '0',
        zIndex: '2147483647',
        opacity: '1',
        visibility: 'visible',
        pointerEvents: 'none',
      })

      document.body.appendChild(overlay)
      document.body.appendChild(exportRoot)

      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
      })

      const topicShort = s.topic.slice(0, 20)
      const date = new Date().toISOString().slice(0, 10)
      const filename = `圆桌会议_${topicShort}_${date}.pdf`

      const estLen = sum.length
      const scale = estLen > 8000 ? 1.5 : 2
      await captureElementToPdf(exportRoot, filename, { scale })
    } catch (err) {
      console.error('PDF 导出失败:', err)
      setErrorTip(`PDF 导出失败: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      exportRoot?.remove()
      if (overlay.parentNode) document.body.removeChild(overlay)
      setPdfExporting(false)
    }
  }

  const showInterventionPanel =
    !running && pauseAfterRound > 0 && (session?.status === 'intervening')

  const interventionsThisRound = useMemo(
    () => (session?.interventions ?? []).filter((i) => i.afterRound === pauseAfterRound),
    [session?.interventions, pauseAfterRound],
  )

  const sessionBusy =
    running ||
    session?.status === 'intervening' ||
    session?.status === 'summarizing' ||
    (session?.status === 'discussing' && session.speeches.some((s) => s.loading))

  const canStartNew =
    !session || session.status === 'completed' || session.status === 'aborted'

  return (
    <div className="space-y-4 max-w-3xl mx-auto w-full pb-24">
      <div className="rounded-2xl border border-gray-200 bg-white/90 p-4 shadow-sm space-y-3">
        <div className="text-sm font-semibold text-gray-700">选择参会角色 (2–5 个)</div>
        <div className="text-xs text-gray-500">已选 {participantIds.length}/5</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {orderedPersonas.map((p) => {
            const checked = participantIds.includes(p.id)
            return (
              <label
                key={p.id}
                className={`flex items-start gap-2 p-2 rounded-lg border cursor-pointer text-sm ${
                  checked ? 'border-blue-300 bg-blue-50/50' : 'border-gray-100 hover:bg-gray-50'
                }`}
              >
                <Checkbox
                  checked={checked}
                  onCheckedChange={() => toggleParticipant(p.id)}
                  disabled={!checked && participantIds.length >= 5}
                />
                <span className="text-lg leading-none">{p.icon}</span>
                <span className="min-w-0">
                  <span className="font-medium block">{p.name}</span>
                  <span className="text-xs text-gray-500 line-clamp-2">{p.description}</span>
                </span>
              </label>
            )
          })}
        </div>

        <div className="border-t border-gray-100 pt-3 space-y-2">
          <div className="text-sm font-semibold text-gray-700">知识库（圆桌每角色独立 RAG）</div>
          <div className="flex flex-wrap gap-2">
            {kbOptions.map((kb) => (
              <label
                key={kb.id}
                className={`flex items-center gap-2 text-xs px-2 py-1 rounded-full border cursor-pointer ${
                  kbIds.includes(kb.id) ? 'bg-green-50 border-green-200 text-green-800' : 'bg-gray-50 border-gray-200'
                }`}
              >
                <Checkbox checked={kbIds.includes(kb.id)} onCheckedChange={() => onToggleKb(kb.id)} />
                {kb.name}
              </label>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-3 items-center">
          <div className="space-y-1">
            <div className="text-xs text-gray-500">主持人</div>
            <Select value={moderatorType} onValueChange={(v) => setModeratorType(v as 'default' | 'boss')}>
              <SelectTrigger className="w-[200px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">🤖 默认主持人</SelectItem>
                <SelectItem value="boss">👔 老板视角</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <div className="text-xs text-gray-500">讨论轮数</div>
            <Select value={String(totalRounds)} onValueChange={(v) => setTotalRounds(Number(v))}>
              <SelectTrigger className="w-[120px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="3">3 轮</SelectItem>
                <SelectItem value="4">4 轮</SelectItem>
                <SelectItem value="5">5 轮</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <div className="text-xs text-gray-500">目标字数</div>
            <input
              type="number"
              min={0}
              step={1000}
              placeholder="留空=单轮"
              value={targetCharsInput}
              onChange={(e) => setTargetCharsInput(e.target.value)}
              disabled={running}
              className="w-[140px] h-9 rounded-md border border-gray-200 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            />
          </div>
        </div>

        <Textarea
          placeholder="输入讨论议题..."
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          rows={3}
          disabled={running}
        />

        {errorTip && <div className="text-sm text-red-600">{errorTip}</div>}

        <div className="flex flex-wrap gap-2">
          {sessionBusy && (
            <Button variant="destructive" onClick={handleStop} className="gap-2">
              <Square className="w-4 h-4" />
              停止讨论
            </Button>
          )}
          {canStartNew && !running && (
            <Button onClick={() => void handleStart()} className="gap-2 bg-gradient-to-r from-blue-600 to-purple-500">
              <Play className="w-4 h-4" />
              开始讨论
            </Button>
          )}
        </div>
      </div>

      {showInterventionPanel && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-4 space-y-2">
          <div className="text-sm font-medium text-amber-900">第 {pauseAfterRound} 轮已结束 — 插话（可选）</div>
          {interventionsThisRound.length > 0 && (
            <div className="space-y-1">
              {interventionsThisRound.map((iv) => {
                const targetName = iv.targetPersonaId
                  ? participants.find((p) => p.id === iv.targetPersonaId)?.name ?? '指定角色'
                  : '全员'
                return (
                  <div key={iv.id} className="text-xs bg-amber-100 rounded px-2 py-1 text-amber-800">
                    💬 [{targetName}] {iv.content}
                  </div>
                )
              })}
            </div>
          )}
          <Textarea
            placeholder="例：@财务审计 拼多多扣点具体是多少？ 或 退货率到底按多少算？"
            value={interveneText}
            onChange={(e) => setInterveneText(e.target.value)}
            rows={2}
          />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={handleInterventionAll} disabled={!interveneText.trim()}>
              全员回应
            </Button>
            <Button size="sm" onClick={handleInterventionSend} disabled={!interveneText.trim()}>
              发送
            </Button>
            <Button size="sm" variant="outline" onClick={() => void handleContinueNextRound()}>
              {interventionsThisRound.length > 0 ? '✅ 进入下一轮' : '跳过插话，进入下一轮'}
            </Button>
          </div>
        </div>
      )}

      {session && session.speeches.length > 0 && (
        <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm space-y-3">
          <div className="font-semibold text-gray-800">讨论过程</div>
          {Array.from(new Set(session.speeches.map((s) => s.round)))
            .sort((a, b) => a - b)
            .map((r) => (
              <details
                key={r}
                open={expandedRounds[r] !== false}
                className="border border-gray-100 rounded-lg overflow-hidden"
              >
                <summary
                  className="px-3 py-2 bg-gray-50 cursor-pointer flex items-center gap-2 text-sm font-medium"
                  onClick={(e) => {
                    e.preventDefault()
                    toggleRoundExpanded(r)
                  }}
                >
                  {expandedRounds[r] !== false ? (
                    <ChevronDown className="w-4 h-4" />
                  ) : (
                    <ChevronRight className="w-4 h-4" />
                  )}
                  第 {r} 轮
                </summary>
                {expandedRounds[r] !== false && (
                  <div className="p-3 space-y-3">
                    {speechesByRound(session.speeches, r).map((sp) => (
                      <div key={sp.id} className="rounded-xl border border-gray-100 p-3 bg-white">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-lg">{sp.personaIcon}</span>
                          <span className="font-medium text-sm">{sp.personaName}</span>
                          {sp.loading && (
                            <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-400" />
                          )}
                        </div>
                        <div className="markdown-body text-sm prose prose-sm max-w-none">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{sp.content || '…'}</ReactMarkdown>
                        </div>
                        {sp.error && <p className="text-xs text-red-500 mt-1">{sp.error}</p>}
                      </div>
                    ))}
                  </div>
                )}
              </details>
            ))}
        </div>
      )}

      {session?.summary && (
        <div className="rounded-2xl border border-purple-200 bg-purple-50/40 p-4 shadow-sm space-y-3">
          <div className="font-semibold text-purple-900 flex items-center gap-2">
            🎯 主持人总结
            {session.summary.loading && <Loader2 className="w-4 h-4 animate-spin" />}
          </div>
          <div className="markdown-body text-sm prose prose-sm max-w-none bg-white rounded-lg p-3 border border-purple-100">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{session.summary.content}</ReactMarkdown>
          </div>
          {!session.summary.loading && session.status === 'completed' && (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" className="gap-2" onClick={() => void exportPdf()} disabled={pdfExporting}>
                {pdfExporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileDown className="w-4 h-4" />}
                {pdfExporting ? '正在导出…' : '📄 导出 PDF'}
              </Button>
              <Button className="gap-2" onClick={onContinueSolo}>
                <MessageSquare className="w-4 h-4" />
                切回单人问答继续深聊
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function escapeHtml(s: string) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 极简 Markdown → HTML，供 PDF 内联（标题、列表、粗体） */
function simpleMdToHtml(md: string) {
  let h = escapeHtml(md.replace(/\r\n/g, '\n').replace(/\r/g, '\n'))
  h = h.replace(/^### (.+)$/gm, '<h3 style="margin:12px 0 6px;font-size:15px;">$1</h3>')
  h = h.replace(/^## (.+)$/gm, '<h2 style="margin:14px 0 8px;font-size:16px;">$1</h2>')
  h = h.replace(/^# (.+)$/gm, '<h1 style="margin:16px 0 10px;font-size:18px;">$1</h1>')
  h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  h = h.replace(/^- (.+)$/gm, '<li style="margin:4px 0;">$1</li>')
  h = h.replace(/\n/g, '<br/>')
  return h
}
