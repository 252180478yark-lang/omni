"""Deterministic S9 findings.  This module never changes graph facts or code."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from app.schemas.runtime_trace import (
    EventType,
    FindingClassification,
    FindingState,
    RuntimeEvent,
    RuntimeFinding,
)

DETECTOR_VERSION = "runtime-radar-v1"


def _fingerprint(code: str, trace_id: str, evidence: list[str]) -> str:
    raw = json.dumps([DETECTOR_VERSION, code, trace_id, sorted(evidence)], separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _finding(
    *, code: str, trace_id: str, severity: str, layers: list[str], message: str,
    evidence: list[str], repair: str, verification: str, state: FindingState = FindingState.OPEN,
) -> RuntimeFinding:
    return RuntimeFinding(
        fingerprint=_fingerprint(code, trace_id, evidence), detector_version=DETECTOR_VERSION, code=code,
        severity=severity, classification=FindingClassification.OBSERVED_FACT, state=state,
        layers=layers, trace_id=trace_id, message_zh=message, evidence=evidence,
        repair_hint=repair, verification=verification,
        impact_path=layers, possible_fix_locations=[item for item in evidence if item.startswith(("node:", "edge:"))],
        history=[f"{DETECTOR_VERSION}:observed"],
    )


def detect_runtime_findings(
    trace_id: str,
    events: Iterable[RuntimeEvent],
    *,
    known_node_ids: set[str] | None = None,
    source_status: str = "success",
    delivery_state: str = "verified_not_delivered",
    graph_unknown_nodes: list[str] | None = None,
    graph_diagnostics: list[str] | None = None,
) -> list[RuntimeFinding]:
    """Return stable facts; unavailable collection results keep findings stale rather than resolved."""
    findings: list[RuntimeFinding] = []
    event_list = list(events)
    for event in event_list:
        evidence = [f"event:{event.source}:{event.event_id}"]
        if event.node_id is None or event.event_type is EventType.GAP:
            findings.append(_finding(
                code="runtime_event_unmapped", trace_id=trace_id, severity="warning", layers=["fact", "runtime"],
                message="运行事件无法映射到事实图节点，已显示为缺口，未补画执行路径。", evidence=evidence,
                repair="为该 producer 写入稳定 node_id、trace_id 和 span_id。", verification="重放同一 trace，确认事件不再进入 gap。",
            ))
        elif known_node_ids is not None and event.node_id not in known_node_ids:
            findings.append(_finding(
                code="runtime_node_not_in_fact_snapshot", trace_id=trace_id, severity="warning", layers=["fact", "runtime"],
                message="运行事件引用的节点不在当前事实快照中，已保留为运行偏差。", evidence=evidence,
                repair="刷新静态事实采集或修正 producer 的 node_id。", verification="成功扫描后该 node_id 应存在于快照。",
            ))
        if event.ordering == "ordering_unknown":
            findings.append(_finding(
                code="runtime_event_ordering_unknown", trace_id=trace_id, severity="warning", layers=["runtime"],
                message="事件缺少可确定顺序，界面只按已知顺序显示并标记 ordering_unknown。", evidence=evidence,
                repair="为同一 producer 发送单调递增 sequence。", verification="断线重连 fixture 不再产生 ordering_unknown。",
            ))
        if event.status.value == "failed":
            findings.append(_finding(
                code="runtime_step_failed", trace_id=trace_id, severity="blocking", layers=["runtime"],
                message="已观测到运行步骤失败；执行路径停留在真实失败节点。", evidence=evidence,
                repair="从失败节点建立候选修复计划，并沿用原 operation 的权限和 Gate。", verification="使用新的 trace 重跑并确认 terminal event 为 completed。",
            ))
    by_span: dict[str, list[RuntimeEvent]] = {}
    for event in event_list:
        if event.span_id:
            by_span.setdefault(event.span_id, []).append(event)
    for span_id, span_events in by_span.items():
        if any(event.event_type is EventType.STARTED for event in span_events) and not any(event.event_type in {EventType.COMPLETED, EventType.FAILED, EventType.CANCELLED} for event in span_events):
            findings.append(_finding(
                code="runtime_terminal_missing", trace_id=trace_id, severity="warning", layers=["runtime"],
                message="该 span 已开始但尚未观察到完成、失败或取消事件，不能显示为成功。", evidence=[f"span:{span_id}"],
                repair="补齐 producer 的 terminal event，或确认任务仍在运行。", verification="同一 span 出现唯一 terminal event。",
            ))
    for node_id in sorted(graph_unknown_nodes or []):
        findings.append(_finding(
            code="planned_fact_unknown", trace_id=trace_id, severity="warning", layers=["planned", "fact"],
            message="计划节点在当前事实快照中仍为 unknown，不能视为已接通。", evidence=[f"node:{node_id}"],
            repair="恢复对应静态 collector 并刷新事实快照。", verification="同一节点在成功快照中变为 observed 且证据可定位。",
        ))
    for diagnostic in sorted(graph_diagnostics or []):
        findings.append(_finding(
            code="fact_collector_diagnostic", trace_id=trace_id, severity="warning", layers=["fact"],
            message="事实采集器报告诊断项；该范围的事实不能作为完整安全证明。", evidence=[f"diagnostic:{diagnostic}"],
            repair="处理 collector 诊断并成功重扫。", verification="新快照不再包含同 fingerprint 诊断。",
        ))
    if source_status != "success":
        findings.append(_finding(
            code="runtime_collector_partial", trace_id=trace_id, severity="info", layers=["runtime"],
            message="运行采集来源不完整，旧发现保持 open/stale，系统没有给出全部正常结论。", evidence=[f"source_status:{source_status}"],
            repair="恢复受影响 producer 后使用同一 detector 成功重扫。", verification="成功重扫且证据消失后才允许 resolved。",
            state=FindingState.STALE,
        ))
    if delivery_state != "delivered":
        findings.append(_finding(
            code="delivery_not_attested", trace_id=trace_id, severity="warning", layers=["delivery"],
            message="该候选尚无外部 DeliveryReceipt；运行证据不能把它显示为已交付。", evidence=[f"delivery_state:{delivery_state}"],
            repair="在目标集成分支由 CI 生成外部 attestation。", verification="验证 subject commit 的 DeliveryReceipt。",
        ))
    return sorted({item.fingerprint: item for item in findings}.values(), key=lambda item: item.fingerprint)
