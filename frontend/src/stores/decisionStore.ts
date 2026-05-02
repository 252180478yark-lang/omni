/**
 * decisionStore.ts
 * ────────────────
 * AI 输出的"持久身份"——所有圆桌讨论、复盘建议、知识库问答的关键结果，
 * 一律落到这个 store + 持久化到 localStorage + 双写后端 mvp_decision_log。
 *
 * 路径 A 双写策略：
 *   - 写入 (addAsync)：先 POST /api/omni/scout/decisions 拿 backendId，失败回退仅本地
 *   - 状态变更 (adopt/reject/postpone)：有 backendId 则同步 PATCH 到后端
 *   - 拉取 (hydrateFromBackend)：挂载时合并后端数据，按 backendId 去重
 *   - localStorage 是离线兜底，后端是跨设备的真源
 *
 * 路径 B 升级阶段：
 *   - 字段对齐 omni_decision.decision_log
 *   - 状态机完整流转 (pending / adopted / rejected / postponed / executing / verified)
 *   - 与 change_event / verification 联动
 *   - 列表升级为筛选/批量/搜索/状态机视图
 *
 * 关键设计：
 *   - 决策一旦写入不可删除（只能改状态）——这是命中率追踪的基础
 *   - 本地 id 用 timestamp+random 防冲突，backendId 在双写成功后回填
 *   - source 字段记清楚来源，路径 B 时迁移容易
 */

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export type DecisionSource =
  | 'roundtable'        // 圆桌讨论结论
  | 'chat'              // 智能问答里手动收藏的回答
  | 'scout_anomaly'     // 巡店异动检测自动诊断
  | 'manual_diagnosis'  // SKU 详情页"启动深度诊断"
  | 'ad_review'         // 投放复盘建议
  | 'strategy_archive'  // 已验证动作归档为可复用策略
  | 'other'

export type DecisionStatus =
  | 'pending'      // 默认：等待你处理
  | 'adopted'      // 已采纳：会自动建一条 change_event
  | 'rejected'     // 已拒绝：留备忘
  | 'postponed'    // 暂缓：设提醒日期
  | 'executing'    // 执行中：动作已发起，等数据回流
  | 'verified'     // 已验证：7 天后系统跑完前后对比

export type DecisionType =
  | 'diagnosis'    // 诊断结论
  | 'suggestion'   // 行动建议
  | 'anomaly'      // 异动告警
  | 'experiment'   // 实验设计

export interface DecisionRecord {
  /** 本地 id，永不变 */
  id: string
  /** 后端 mvp_decision_log.id（双写成功后回填，作为 PATCH 凭据） */
  backendId?: number
  /** 来源模块 */
  source: DecisionSource
  /** 来源 run id（圆桌 session id / scout run id），可选 */
  sourceRunId?: string
  /** 决策类型 */
  type: DecisionType
  /** 关联 SKU */
  skuId?: string
  /** 标题 */
  title: string
  /** 摘要 */
  summary: string
  /** 完整内容（markdown） */
  fullContent: string
  /** 状态 */
  status: DecisionStatus
  /** 创建时间（ISO） */
  createdAt: string
  /** 最后更新时间（ISO） */
  updatedAt: string
  /** 采纳时间 */
  adoptedAt?: string
  /** 拒绝原因 */
  rejectedReason?: string
  /** 暂缓到期日（YYYY-MM-DD） */
  postponedUntil?: string
  /** 关联到的 change_event */
  linkedChangeEventId?: string
  /** 验证时间 */
  verifiedAt?: string
  /** 验证结果 */
  verificationResult?: {
    verdict: 'positive' | 'negative' | 'neutral'
    summary: string
    deltas?: Record<string, { pre: number; post: number; deltaPct: number }>
  }
  /** 元数据：参与角色、相关链接、附件等 */
  meta?: Record<string, unknown>
}

type DecisionInput = Omit<DecisionRecord, 'id' | 'createdAt' | 'updatedAt' | 'status' | 'backendId'> & {
  status?: DecisionStatus
}

interface DecisionState {
  decisions: DecisionRecord[]
  /** 本地立即写入（仅 localStorage），用于离线场景 */
  add: (input: DecisionInput) => DecisionRecord
  /** 异步双写：先 POST 后端拿 backendId，再更新本地。后端失败时仍写本地。 */
  addAsync: (input: DecisionInput) => Promise<DecisionRecord>
  /** 更新决策（部分字段，本地） */
  update: (id: string, patch: Partial<DecisionRecord>) => void
  /** 标记采纳（双写：有 backendId 则 PATCH） */
  adopt: (id: string, linkedChangeEventId?: string) => Promise<void>
  /** 标记拒绝（双写） */
  reject: (id: string, reason: string) => Promise<void>
  /** 暂缓到指定日期（双写） */
  postpone: (id: string, until: string) => Promise<void>
  /** 写入验证结果（仅本地，verification 由后端 cron 主导） */
  setVerification: (id: string, result: NonNullable<DecisionRecord['verificationResult']>) => void
  /** 从后端 mvp_decision_log 拉取并合并（backendId 去重） */
  hydrateFromBackend: () => Promise<{ fetched: number; merged: number; ok: boolean }>
  /** 按 SKU 筛选 */
  bySku: (skuId: string) => DecisionRecord[]
  /** 按状态筛选 */
  byStatus: (status: DecisionStatus) => DecisionRecord[]
}

function nano(): string {
  return `dec-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function nowIso(): string {
  return new Date().toISOString()
}

function recordToBackendPayload(r: DecisionRecord) {
  return {
    source_module: r.source,
    source_run_id: r.sourceRunId,
    sku_id: r.skuId || null,
    type: r.type,
    title: r.title,
    summary: r.summary,
    full_content: r.fullContent,
    status: r.status,
    meta: r.meta || {},
  }
}

function backendRowToRecord(row: {
  id: number
  source_module: string
  source_run_id: string | null
  sku_id: string | null
  type: string | null
  title: string
  summary: string | null
  full_content: string | null
  status: string
  created_at: string
  updated_at?: string | null
  adopted_at?: string | null
  rejected_reason?: string | null
  postponed_until?: string | null
  linked_change_event_id?: number | null
  verified_at?: string | null
  verification_result?: Record<string, unknown> | null
  meta?: Record<string, unknown> | null
}): DecisionRecord {
  return {
    id: `srv-${row.id}`,
    backendId: row.id,
    source: (row.source_module as DecisionSource) ?? 'other',
    sourceRunId: row.source_run_id ?? undefined,
    type: (row.type as DecisionType) ?? 'suggestion',
    skuId: row.sku_id ?? undefined,
    title: row.title,
    summary: row.summary ?? '',
    fullContent: row.full_content ?? row.summary ?? '',
    status: (row.status as DecisionStatus) ?? 'pending',
    createdAt: row.created_at,
    updatedAt: row.updated_at ?? row.created_at,
    adoptedAt: row.adopted_at ?? undefined,
    rejectedReason: row.rejected_reason ?? undefined,
    postponedUntil: row.postponed_until ?? undefined,
    linkedChangeEventId: row.linked_change_event_id != null ? String(row.linked_change_event_id) : undefined,
    verifiedAt: row.verified_at ?? undefined,
    verificationResult: row.verification_result as DecisionRecord['verificationResult'] | undefined ?? undefined,
    meta: row.meta ?? undefined,
  }
}

async function safePost<T>(url: string, body: unknown): Promise<T | null> {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

async function safePatch<T>(url: string, body: unknown): Promise<T | null> {
  try {
    const res = await fetch(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

export const useDecisionStore = create<DecisionState>()(
  persist(
    (set, get) => ({
      decisions: [],

      add: (input) => {
        const record: DecisionRecord = {
          id: nano(),
          createdAt: nowIso(),
          updatedAt: nowIso(),
          status: input.status ?? 'pending',
          ...input,
        }
        set((s) => ({ decisions: [record, ...s.decisions] }))
        return record
      },

      addAsync: async (input) => {
        const record = get().add(input)
        const resp = await safePost<{ id: number }>('/api/omni/scout/decisions', recordToBackendPayload(record))
        if (resp?.id) {
          set((s) => ({
            decisions: s.decisions.map((d) =>
              d.id === record.id ? { ...d, backendId: resp.id, updatedAt: nowIso() } : d,
            ),
          }))
          return { ...record, backendId: resp.id }
        }
        return record
      },

      update: (id, patch) =>
        set((s) => ({
          decisions: s.decisions.map((d) =>
            d.id === id ? { ...d, ...patch, updatedAt: nowIso() } : d,
          ),
        })),

      adopt: async (id, linkedChangeEventId) => {
        const target = get().decisions.find((d) => d.id === id)
        set((s) => ({
          decisions: s.decisions.map((d) =>
            d.id === id
              ? {
                  ...d,
                  status: 'adopted' as DecisionStatus,
                  adoptedAt: nowIso(),
                  linkedChangeEventId: linkedChangeEventId ?? d.linkedChangeEventId,
                  updatedAt: nowIso(),
                }
              : d,
          ),
        }))
        if (target?.backendId) {
          await safePatch(`/api/omni/scout/decisions/${target.backendId}`, {
            status: 'adopted',
            linked_change_event_id: linkedChangeEventId ? Number(linkedChangeEventId) || undefined : undefined,
          })
        }
      },

      reject: async (id, reason) => {
        const target = get().decisions.find((d) => d.id === id)
        set((s) => ({
          decisions: s.decisions.map((d) =>
            d.id === id
              ? { ...d, status: 'rejected' as DecisionStatus, rejectedReason: reason, updatedAt: nowIso() }
              : d,
          ),
        }))
        if (target?.backendId) {
          await safePatch(`/api/omni/scout/decisions/${target.backendId}`, {
            status: 'rejected',
            rejected_reason: reason,
          })
        }
      },

      postpone: async (id, until) => {
        const target = get().decisions.find((d) => d.id === id)
        set((s) => ({
          decisions: s.decisions.map((d) =>
            d.id === id
              ? { ...d, status: 'postponed' as DecisionStatus, postponedUntil: until, updatedAt: nowIso() }
              : d,
          ),
        }))
        if (target?.backendId) {
          await safePatch(`/api/omni/scout/decisions/${target.backendId}`, {
            status: 'postponed',
            postponed_until: until,
          })
        }
      },

      setVerification: (id, result) =>
        set((s) => ({
          decisions: s.decisions.map((d) =>
            d.id === id
              ? {
                  ...d,
                  status: 'verified' as DecisionStatus,
                  verifiedAt: nowIso(),
                  verificationResult: result,
                  updatedAt: nowIso(),
                }
              : d,
          ),
        })),

      hydrateFromBackend: async () => {
        try {
          const res = await fetch('/api/omni/scout/decisions?limit=200')
          if (!res.ok) return { fetched: 0, merged: 0, ok: false }
          const rows = (await res.json()) as Parameters<typeof backendRowToRecord>[0][]
          const remoteRecords = rows.map(backendRowToRecord)
          let merged = 0
          set((s) => {
            const byBackendId = new Map<number, DecisionRecord>()
            const localOnly: DecisionRecord[] = []
            for (const d of s.decisions) {
              if (d.backendId) byBackendId.set(d.backendId, d)
              else localOnly.push(d)
            }
            for (const r of remoteRecords) {
              if (!r.backendId) continue
              const existing = byBackendId.get(r.backendId)
              if (!existing) {
                byBackendId.set(r.backendId, r)
                merged += 1
              } else {
                // Backend wins on status/adoptedAt/postponedUntil; keep local fullContent if richer
                byBackendId.set(r.backendId, {
                  ...existing,
                  ...r,
                  fullContent: existing.fullContent && existing.fullContent.length > (r.fullContent?.length ?? 0)
                    ? existing.fullContent
                    : r.fullContent,
                })
              }
            }
            const sorted = Array.from(byBackendId.values()).concat(localOnly).sort(
              (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
            )
            return { decisions: sorted }
          })
          return { fetched: remoteRecords.length, merged, ok: true }
        } catch {
          return { fetched: 0, merged: 0, ok: false }
        }
      },

      bySku: (skuId) => get().decisions.filter((d) => d.skuId === skuId),
      byStatus: (status) => get().decisions.filter((d) => d.status === status),
    }),
    {
      name: 'omni-decision-log-v1',
      storage: createJSONStorage(() =>
        typeof window !== 'undefined'
          ? window.localStorage
          : (undefined as unknown as Storage),
      ),
      version: 1,
    },
  ),
)
