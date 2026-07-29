#!/usr/bin/env python3
"""Deterministic quality gate for omni implementation PRDs."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


REQUIRED_HEADINGS = [
    "落地结论",
    "背景、现场问题与目标",
    "当前系统事实",
    "范围与非目标",
    "目标流程与状态机",
    "功能需求",
    "系统落点、复用与差距",
    "数据、接口、工具与 AI 契约",
    "交互、权限、安全与审计",
    "异常、兼容、发布与回滚",
    "可观测性与成功指标",
    "验收标准",
    "实施切片",
    "风险、假设、待决策与 Definition of Ready",
]

FAILURE_CASES = ["空数据", "无权限", "超时", "重复提交", "部分失败"]


@dataclass
class Issue:
    severity: str
    code: str
    message: str


def _extract_block(text: str, start_pattern: str, end_pattern: str) -> str:
    match = re.search(start_pattern, text, flags=re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    end_match = re.search(end_pattern, text[start:], flags=re.MULTILINE)
    end = start + end_match.start() if end_match else len(text)
    return text[start:end].strip()


def validate(text: str, strict: bool) -> tuple[str | None, list[Issue]]:
    issues: list[Issue] = []

    def add(severity: str, code: str, message: str) -> None:
        issues.append(Issue(severity, code, message))

    status_match = re.search(
        r"(?mi)^\s*-\s*状态\s*[：:]\s*(DISCOVERY|DRAFT|READY)\s*$", text
    )
    status = status_match.group(1).upper() if status_match else None
    if status is None:
        add("error", "metadata.status", "缺少合法状态：DISCOVERY、DRAFT 或 READY。")
    elif strict and status != "READY":
        add("error", "metadata.not_ready", "--strict 要求文档状态为 READY。")

    for index, title in enumerate(REQUIRED_HEADINGS, start=1):
        pattern = rf"(?m)^##\s+{index}\.\s+{re.escape(title)}\s*$"
        if not re.search(pattern, text):
            add("error", "structure.heading", f"缺少固定章节：## {index}. {title}")

    placeholder_patterns = {
        "双花括号模板占位符": r"\{\{[^\n{}]+\}\}",
        "TODO/TBD/待填写": r"(?i)\b(?:TODO|TBD)\b|待填写",
        "未决元数据": r"(?m)(?:[：:]\s*待确认\s*$|\|\s*待确认\s*\|)",
    }
    for label, pattern in placeholder_patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            sample = matches[0] if isinstance(matches[0], str) else str(matches[0])
            add("error", "content.placeholder", f"存在{label}：{sample!r}")

    fr_pattern = re.compile(
        r"(?ms)^###\s+(FR-(\d{3,}))\s+\[(P[01])\][^\n]*\n(.*?)(?=^###\s+|^##\s+|\Z)"
    )
    fr_blocks = fr_pattern.findall(text)
    fr_matches = [(full, number, priority) for full, number, priority, _body in fr_blocks]
    fr_ids = [full for full, _number, _priority in fr_matches]
    if not fr_ids:
        add("error", "requirements.missing", "至少需要一个带优先级的 FR，例如 FR-001 [P0]。")
    duplicate_frs = sorted({item for item in fr_ids if fr_ids.count(item) > 1})
    if duplicate_frs:
        add("error", "requirements.duplicate", f"FR ID 重复：{', '.join(duplicate_frs)}")

    for fr_id, _number, _priority, body in fr_blocks:
        for field in ("角色", "触发", "前置", "规则", "输出", "异常", "来源"):
            if not re.search(rf"(?m)^\s*-?\s*{field}\s*[：:]", body):
                add("error", "requirements.field", f"{fr_id} 缺少{field}。")

    ac_pattern = re.compile(
        r"(?ms)^###\s+(AC-FR(\d{3,})-\d{2,})\s*\n(.*?)(?=^###\s+|^##\s+|\Z)"
    )
    ac_matches = ac_pattern.findall(text)
    ac_ids = [full for full, _number, _body in ac_matches]
    if not ac_ids:
        add("error", "acceptance.missing", "至少需要一个 AC-FRxxx-xx 验收用例。")
    duplicate_acs = sorted({item for item in ac_ids if ac_ids.count(item) > 1})
    if duplicate_acs:
        add("error", "acceptance.duplicate", f"AC ID 重复：{', '.join(duplicate_acs)}")

    defined_numbers = {number for _full, number, _priority in fr_matches}
    ac_numbers = {number for _full, number, _body in ac_matches}
    for ac_id, number, body in ac_matches:
        if number not in defined_numbers:
            add("error", "acceptance.dangling", f"{ac_id} 指向未定义的 FR-{number}。")
        for field in ("Given", "When", "Then", "And", "Evidence"):
            if not re.search(rf"(?mi)^\s*-?\s*{field}\s*[：:]", body):
                add("error", "acceptance.field", f"{ac_id} 缺少 {field}。")

    for _full, number, priority in fr_matches:
        if priority == "P0" and number not in ac_numbers:
            add("error", "acceptance.coverage", f"P0 FR-{number} 没有对应 AC。")

    evidence_checks = {
        "[现状事实] 标签": "[现状事实]" in text,
        "SYS 证据 ID": bool(re.search(r"\bSYS-\d{3,}\b", text)),
        "源码或运行时证据": bool(
            re.search(r"`[^`\n]*(?:/|\\|\.py|\.ts|\.tsx|\.sql|\.md|tool|query)[^`\n]*`", text)
        ),
    }
    for label, present in evidence_checks.items():
        if not present:
            add("error" if strict else "warning", "evidence.missing", f"缺少{label}。")

    for category in ("复用", "修改", "拟新增", "不做"):
        if category not in text:
            add("error" if strict else "warning", "fit_gap.missing", f"能力差距缺少“{category}”分类。")

    for failure_case in FAILURE_CASES:
        if failure_case not in text:
            add(
                "error" if strict else "warning",
                "failure_case.missing",
                f"未覆盖失败场景：{failure_case}（不适用也需说明原因）。",
            )

    dor_block = _extract_block(
        text,
        r"^###\s+Definition of Ready\s*$",
        r"^##\s+",
    )
    if not dor_block:
        add("error", "dor.missing", "缺少 Definition of Ready 检查清单。")

    unchecked = re.findall(r"(?m)^\s*-\s*\[ \]\s+.+$", dor_block)
    if unchecked:
        add(
            "error" if strict or status == "READY" else "warning",
            "dor.unchecked",
            f"Definition of Ready 仍有 {len(unchecked)} 项未勾选。",
        )
    checked = re.findall(r"(?mi)^\s*-\s*\[[xX]\]\s+.+$", dor_block)
    if strict and len(checked) < 8:
        add("error", "dor.incomplete", "READY 文档至少应明确勾选 8 项 DoR。")

    blocker_block = _extract_block(
        text,
        r"^####\s+阻塞开工\s*$",
        r"^####\s+|^###\s+|^##\s+",
    )
    blocker_bullets = [
        line.strip()
        for line in blocker_block.splitlines()
        if re.match(r"^\s*-\s+", line)
    ]
    blocker_is_none = (
        len(blocker_bullets) == 1
        and bool(re.match(r"^-\s*(?:无|none)(?:[；;。.]|\s|$)", blocker_bullets[0], re.I))
    )
    if status == "READY" and not blocker_is_none:
        add("error", "blocker.present", "READY 文档的“阻塞开工”必须明确且仅写“无”。")

    if strict and re.search(r"(?m)^\s*-\s*状态\s*[：:]\s*READY\s*$", text):
        if re.search(r"\bOPN-\d{3,}\b", blocker_block):
            add("error", "blocker.open_id", "READY 文档仍在阻塞区包含 OPN 待决策 ID。")

    return status, issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prd_path", help="Markdown PRD path, or '-' to read text from stdin")
    parser.add_argument("--strict", action="store_true", help="Require READY-level completeness")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--stdin-base64",
        action="store_true",
        help="Decode base64-encoded UTF-8 from stdin (safe for Windows PowerShell 5.1)",
    )
    args = parser.parse_args()

    if args.stdin_base64 and args.prd_path != "-":
        parser.error("--stdin-base64 requires prd_path '-'")

    if args.prd_path == "-":
        path_label = "<stdin>"
        stdin_text = sys.stdin.read()
        if args.stdin_base64:
            try:
                encoded = "".join(stdin_text.split()).encode("ascii")
                text = base64.b64decode(encoded, validate=True).decode("utf-8-sig")
            except (UnicodeEncodeError, UnicodeDecodeError, binascii.Error) as exc:
                payload = {"path": path_label, "status": None, "errors": 1, "warnings": 0,
                           "issues": [{"severity": "error", "code": "stdin.base64", "message": f"stdin Base64/UTF-8 无效：{exc}"}]}
                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    print(f"[FAIL] {path_label}\n- ERROR stdin.base64: stdin Base64/UTF-8 无效：{exc}")
                return 1
        else:
            text = stdin_text
        if not text.strip():
            payload = {"path": path_label, "status": None, "errors": 1, "warnings": 0,
                       "issues": [{"severity": "error", "code": "stdin.empty", "message": "stdin 没有 PRD 内容。"}]}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"[FAIL] {path_label}\n- ERROR stdin.empty: stdin 没有 PRD 内容。")
            return 1
    else:
        path = Path(args.prd_path).resolve()
        path_label = str(path)
        if not path.is_file():
            payload = {"path": path_label, "status": None, "errors": 1, "warnings": 0,
                       "issues": [{"severity": "error", "code": "file.missing", "message": "PRD 文件不存在。"}]}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"[FAIL] {path_label}\n- ERROR file.missing: PRD 文件不存在。")
            return 1

        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            print(f"[FAIL] {path_label}\n- ERROR file.encoding: 不是有效 UTF-8：{exc}")
            return 1

    status, issues = validate(text, args.strict)
    errors = sum(issue.severity == "error" for issue in issues)
    warnings = sum(issue.severity == "warning" for issue in issues)
    payload = {
        "path": path_label,
        "status": status,
        "strict": args.strict,
        "errors": errors,
        "warnings": warnings,
        "issues": [asdict(issue) for issue in issues],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        verdict = "PASS" if errors == 0 else "FAIL"
        print(f"[{verdict}] {path_label}")
        print(f"status={status or 'missing'} strict={args.strict} errors={errors} warnings={warnings}")
        for issue in issues:
            print(f"- {issue.severity.upper()} {issue.code}: {issue.message}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
