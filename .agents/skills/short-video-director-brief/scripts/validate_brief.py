#!/usr/bin/env python3
"""Deterministic structural validator for human short-video director briefs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_HEADING_RE = re.compile(
    r"^###\s+脚本\s+(\d{1,3})\s*｜\s*`([^`]+)`\s*([^｜\n]*)｜",
    re.MULTILINE,
)
BODY_SECTION_RE = re.compile(r"^#\s+(第一部分：人群理解|第二部分：[^\n]+)$", re.MULTILINE)
FORBIDDEN_SECTION_RE = re.compile(r"^##\s+2\.[78](?:\s|$)", re.MULTILINE)
MIXED_TAG_RE = re.compile(
    r"\[(?:人群包数据|商品事实|项目确认|创意假设|实测)[^\]]*[＋+]"
    r"[^\]]*(?:人群包数据|商品事实|项目确认|创意假设|实测)[^\]]*\]"
)

TECHNICAL_TERMS = (
    "25fps",
    "50fps",
    "白平衡",
    "焦段",
    "机位图",
    "双机位",
    "灯位图",
    "布光图",
    "镜头编号",
    "Best Take",
)

SCENE_ONLY_TYPE_NAMES = {
    "家庭",
    "家庭生活",
    "单人",
    "单人生活",
    "独居",
    "厨房",
    "餐桌",
    "晚归",
    "周末",
    "办公室",
    "露营",
    "有机",
    "配料表",
    "套组",
}

REQUIRED_MANIFEST_SCRIPT_FIELDS = (
    "item_no",
    "type_code",
    "title",
    "duration_s",
    "audience_state",
    "pain_point",
    "scene",
    "hook_3s",
    "product_entry",
    "fact_boundary",
    "beats",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _count_beat_rows(segment: str) -> int:
    count = 0
    for line in segment.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or set("".join(cells)) <= {"-", ":"}:
            continue
        # Supports both: time is the first column, or paragraph name is first and time is second.
        candidates = cells[:2]
        if any(re.search(r"\d+\s*[–-]\s*\d+\s*秒", value) for value in candidates):
            count += 1
    return count


def validate_markdown(
    text: str,
    min_types: int,
    min_scripts: int,
    no_purify: bool,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []

    all_h1s = re.findall(r"^#\s+([^\n]+)$", text, re.MULTILINE)
    body_sections = BODY_SECTION_RE.findall(text)
    if "第一部分：人群理解" not in body_sections:
        errors.append("缺少一级标题：第一部分：人群理解")
    if not any(item.startswith("第二部分：") for item in body_sections):
        errors.append("缺少第二部分一级标题")
    if len(body_sections) != 2 or len(all_h1s) != 3:
        errors.append(
            "正文必须只有两个主体一级标题（另允许一个文档标题）：人群理解、内容类型与拍摄脚本"
        )
    if FORBIDDEN_SECTION_RE.search(text):
        errors.append("正文包含禁止的 2.7 或 2.8 章节")

    found_technical = [term for term in TECHNICAL_TERMS if term.lower() in text.lower()]
    if found_technical:
        errors.append("正文包含摄影施工参数：" + "、".join(found_technical))

    mixed_tags = MIXED_TAG_RE.findall(text)
    if mixed_tags:
        errors.append("存在混合事实标签，请拆句：" + "、".join(sorted(set(mixed_tags))))

    headings = list(SCRIPT_HEADING_RE.finditer(text))
    if len(headings) < min_scripts:
        errors.append(f"脚本数量不足：{len(headings)} < {min_scripts}")

    numbers = [int(match.group(1)) for match in headings]
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        errors.append(f"脚本编号不连续或顺序错误：{numbers}")

    type_codes = [match.group(2).strip() for match in headings]
    unique_types = sorted(set(type_codes))
    if len(unique_types) < min_types:
        errors.append(f"唯一内容类型不足：{len(unique_types)} < {min_types}")

    titles: list[str] = []
    for index, match in enumerate(headings):
        number = int(match.group(1))
        type_name = match.group(3).strip()
        segment_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        segment = text[match.start() : segment_end]
        beat_rows = _count_beat_rows(segment)
        if beat_rows != 5:
            errors.append(f"脚本 {number:02d} 的五段表实际为 {beat_rows} 段")
        if "产品怎么进入" not in segment:
            errors.append(f"脚本 {number:02d} 缺少“产品怎么进入”字段")
        if not re.search(r"台词|画外音|字幕", segment):
            errors.append(f"脚本 {number:02d} 缺少台词/画外音/字幕字段")
        if type_name in SCENE_ONLY_TYPE_NAMES:
            errors.append(f"脚本 {number:02d} 把场景/主题“{type_name}”当成内容类型")

        heading_end = text.find("\n", match.start())
        heading_line = text[match.start() : heading_end if heading_end != -1 else len(text)]
        title_match = re.search(r"\u300a([^\u300b]+)\u300b", heading_line)
        if title_match:
            titles.append(title_match.group(1).strip())
        else:
            errors.append(f"脚本 {number:02d} 标题行缺少《标题》")

    if len(titles) != len(set(titles)):
        errors.append("存在重复脚本标题，疑似只换开头或场景凑数")

    required_tags = ("[人群包数据]", "[商品事实]", "[创意假设]")
    missing_tags = [tag for tag in required_tags if tag not in text]
    if missing_tags:
        errors.append("正式 Brief 缺少必要来源标签：" + "、".join(missing_tags))

    if no_purify:
        purify_actions = re.findall(
            r"(?<!不)(?<!无须)(?<!无需)建议提纯|(?<!不)继续提纯|(?<!不)收窄人群|"
            r"(?<!不)缩(?:小|掉)一个量级|(?<!不)重新切包",
            text,
        )
        if purify_actions:
            errors.append("项目已确认不提纯，但正文仍出现提纯动作建议")

    metrics = {
        "script_count": len(headings),
        "unique_type_count": len(unique_types),
        "type_codes": unique_types,
        "body_sections": body_sections,
    }
    return errors, warnings, metrics


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def validate_manifest(
    data: dict[str, Any],
    min_types: int,
    min_scripts: int,
    markdown_metrics: dict[str, Any],
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []

    lineage_status = data.get("lineage_status")
    if lineage_status not in {"full", "partial", "local_only"}:
        errors.append("manifest.lineage_status 必须是 full / partial / local_only")

    content_types = data.get("content_types") or []
    scripts = data.get("scripts") or []
    raw_type_codes = [str(item.get("code", "")).strip() for item in content_types if item.get("code")]
    type_codes = set(raw_type_codes)
    script_type_codes = {str(item.get("type_code", "")).strip() for item in scripts if item.get("type_code")}

    if len(raw_type_codes) != len(type_codes):
        errors.append("manifest.content_types 存在重复 type_code")
    for index, item in enumerate(content_types, start=1):
        missing_fields = [
            field for field in ("code", "name", "watch_value", "purchase_question")
            if not _nonempty(item.get(field))
        ]
        if missing_fields:
            errors.append(f"manifest 内容类型 {index} 缺字段：" + "、".join(missing_fields))

    if len(type_codes) < min_types:
        errors.append(f"manifest 内容类型不足：{len(type_codes)} < {min_types}")
    if len(scripts) < min_scripts:
        errors.append(f"manifest 脚本不足：{len(scripts)} < {min_scripts}")
    missing_type_defs = sorted(script_type_codes - type_codes)
    if missing_type_defs:
        errors.append("脚本引用了未定义 type_code：" + "、".join(missing_type_defs))

    item_numbers: list[int] = []
    source_ids = {
        str(item.get("source_id", "")).strip()
        for item in (data.get("sources") or [])
        if item.get("source_id")
    }
    for index, script in enumerate(scripts, start=1):
        missing_fields = [
            field for field in REQUIRED_MANIFEST_SCRIPT_FIELDS if not _nonempty(script.get(field))
        ]
        if missing_fields:
            errors.append(f"manifest 脚本 {index} 缺字段：" + "、".join(missing_fields))
        try:
            item_numbers.append(int(script.get("item_no")))
        except (TypeError, ValueError):
            errors.append(f"manifest 脚本 {index} 的 item_no 非整数")
        try:
            if float(script.get("duration_s", 0)) <= 0:
                errors.append(f"manifest 脚本 {index} 的 duration_s 必须大于 0")
        except (TypeError, ValueError):
            errors.append(f"manifest 脚本 {index} 的 duration_s 非数字")
        beats = script.get("beats") or []
        if len(beats) != 5:
            errors.append(f"manifest 脚本 {index} 的 beats 数量为 {len(beats)}，应为 5")
        else:
            beat_orders = [beat.get("order") for beat in beats]
            if beat_orders != [1, 2, 3, 4, 5]:
                errors.append(f"manifest 脚本 {index} 的 beat.order 必须依次为 1-5")
            for beat_index, beat in enumerate(beats, start=1):
                missing_beat_fields = [
                    field for field in ("time", "action", "copy", "product_action")
                    if not _nonempty(beat.get(field))
                ]
                if missing_beat_fields:
                    errors.append(
                        f"manifest 脚本 {index} 第 {beat_index} 段缺字段："
                        + "、".join(missing_beat_fields)
                    )
        for claim in script.get("claims") or []:
            if claim.get("status") not in {"approved", "pending", "blocked"}:
                errors.append(f"manifest 脚本 {index} 有无效 claim.status")
            if claim.get("status") == "approved":
                source_id = str(claim.get("source_id", "")).strip()
                if not source_id or source_id not in source_ids:
                    errors.append(
                        f"manifest 脚本 {index} 有 approved claim，但 source_id 不存在于 sources"
                    )

    if item_numbers and item_numbers != list(range(1, len(item_numbers) + 1)):
        errors.append(f"manifest item_no 不连续：{item_numbers}")

    if markdown_metrics.get("script_count") != len(scripts):
        errors.append("Markdown 与 manifest 的脚本数量不一致")
    if set(markdown_metrics.get("type_codes") or []) != script_type_codes:
        errors.append("Markdown 与 manifest 的 type_code 集合不一致")

    metrics = {
        "manifest_script_count": len(scripts),
        "manifest_type_count": len(type_codes),
        "lineage_status": lineage_status,
        "blocked_claim_count": len(data.get("blocked_claims") or []),
    }
    return errors, warnings, metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path, help="Markdown brief path")
    parser.add_argument("--manifest", type=Path, help="Optional manifest JSON path")
    parser.add_argument("--min-types", type=int, default=10)
    parser.add_argument("--min-scripts", type=int, default=10)
    parser.add_argument("--no-purify", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    if not args.brief.exists():
        errors.append(f"Brief 不存在：{args.brief}")
    else:
        md_errors, md_warnings, md_metrics = validate_markdown(
            _read_text(args.brief), args.min_types, args.min_scripts, args.no_purify
        )
        errors.extend(md_errors)
        warnings.extend(md_warnings)
        metrics.update(md_metrics)

        if args.manifest:
            if not args.manifest.exists():
                errors.append(f"Manifest 不存在：{args.manifest}")
            else:
                try:
                    manifest_data = json.loads(_read_text(args.manifest))
                except json.JSONDecodeError as exc:
                    errors.append(f"Manifest JSON 无效：{exc}")
                else:
                    mf_errors, mf_warnings, mf_metrics = validate_manifest(
                        manifest_data, args.min_types, args.min_scripts, md_metrics
                    )
                    errors.extend(mf_errors)
                    warnings.extend(mf_warnings)
                    metrics.update(mf_metrics)

    result = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
