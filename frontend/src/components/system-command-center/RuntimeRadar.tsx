'use client'

import type { RuntimeFinding } from '@/lib/system-command-center/runtime-model'

export function RuntimeRadar({ findings, onCreateDraft, creatingFingerprint }: {
  findings: RuntimeFinding[]
  onCreateDraft?: (finding: RuntimeFinding) => void
  creatingFingerprint?: string
}) {
  if (!findings.length) return <p className="text-sm text-slate-500">没有可用的雷达事实；这不表示全链路正常。</p>
  const counts = {
    blocking: findings.filter((finding) => finding.severity === 'blocking').length,
    degraded: findings.filter((finding) => finding.severity === 'warning').length,
    unknown: findings.filter((finding) => finding.state === 'stale' || finding.classification === 'hypothesis').length,
  }
  return <div><p className="mb-2 text-xs text-slate-600">blocking {counts.blocking} · degraded {counts.degraded} · unknown {counts.unknown}</p><ul className="space-y-2" aria-label="四层雷达发现">
    {findings.map((finding) => (
      <li key={finding.fingerprint} className="rounded border border-slate-200 p-3 text-sm">
        <div className="flex flex-wrap gap-2">
          <span className={finding.classification === 'observed_fact' ? 'text-rose-700' : 'text-amber-700'}>
            {finding.classification === 'observed_fact' ? '确定性事实' : 'AI 建议'}
          </span>
          <span className="text-slate-500">{finding.layers.join(' / ')}</span>
          <span className="text-slate-500">{finding.state}</span>
        </div>
        <p className="mt-1 text-slate-800">{finding.message_zh}</p>
        <p className="mt-1 text-xs text-slate-500">修复：{finding.repair_hint}；验证：{finding.verification}</p>
        {onCreateDraft ? <button type="button" onClick={() => onCreateDraft(finding)} disabled={creatingFingerprint === finding.fingerprint} className="mt-2 rounded border border-violet-200 px-2 py-1 text-xs text-violet-700 disabled:opacity-50">
          {creatingFingerprint === finding.fingerprint ? '正在建草稿…' : '加入候选计划（仅草稿）'}
        </button> : null}
      </li>
    ))}
  </ul></div>
}
