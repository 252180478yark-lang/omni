import {
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  ClipboardList,
  Clock3,
  Inbox,
  Loader2,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '@/lib/utils'

export type WorkbenchViewState =
  | 'loading'
  | 'empty'
  | 'error'
  | 'success'
  | 'pending-approval'
  | 'unknown'
  | 'planned'

const PRESENTATION: Record<WorkbenchViewState, { label: string; icon: LucideIcon }> = {
  loading: { label: '加载中', icon: Loader2 },
  empty: { label: '暂无数据', icon: Inbox },
  error: { label: '错误', icon: AlertTriangle },
  success: { label: '已验证', icon: CheckCircle2 },
  'pending-approval': { label: '待审批', icon: Clock3 },
  unknown: { label: '未知', icon: CircleDashed },
  planned: { label: '计划中', icon: ClipboardList },
}

export interface WorkbenchStateBadgeProps {
  state: WorkbenchViewState
  label?: string
  detail?: string
  className?: string
  testId?: string
}

export function WorkbenchStateBadge({
  state,
  label,
  detail,
  className,
  testId,
}: WorkbenchStateBadgeProps) {
  const presentation = PRESENTATION[state]
  const Icon = presentation.icon
  const visibleLabel = label || presentation.label

  return (
    <span
      className={cn('workbench-state', `workbench-state--${state}`, className)}
      data-state={state}
      data-testid={testId}
      aria-label={detail ? `${visibleLabel}：${detail}` : visibleLabel}
    >
      <Icon
        className={cn('h-3.5 w-3.5 shrink-0', state === 'loading' && 'animate-spin')}
        aria-hidden="true"
      />
      <span>{visibleLabel}</span>
      {detail ? <span className="workbench-state__detail">{detail}</span> : null}
    </span>
  )
}
