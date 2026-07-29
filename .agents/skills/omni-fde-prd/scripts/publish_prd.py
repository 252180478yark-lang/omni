#!/usr/bin/env python3
"""Publish and verify immutable Markdown/PDF PRD pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
CATALOG_NAME = "catalog.json"
INDEX_NAME = "README.md"
PRD_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{2,127}")
VERSION_PATTERN = re.compile(r"v\d+(?:\.\d+)*")
ALLOWED_STATUSES = {"DISCOVERY", "DRAFT", "READY"}


class PublicationError(ValueError):
    """Raised when a PRD pair or archive violates the publication contract."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _match_metadata(text: str, pattern: str, label: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise PublicationError(f"Markdown 缺少可解析的{label}")
    return match.group(1).strip()


def read_markdown_metadata(data: bytes) -> dict[str, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationError("Markdown 必须使用 UTF-8 编码") from exc
    if not text.strip():
        raise PublicationError("Markdown 不能为空")

    title = _match_metadata(text, r"^#\s*PRD[：:]\s*(.+?)\s*$", "PRD 标题")
    status = _match_metadata(text, r"^-\s*状态[：:]\s*(\S+)\s*$", "状态")
    version = _match_metadata(text, r"^-\s*版本[：:]\s*(\S+)\s*$", "版本")
    published_on = _match_metadata(
        text, r"^-\s*日期[：:]\s*(\d{4}-\d{2}-\d{2})\s*$", "日期"
    )
    if status not in ALLOWED_STATUSES:
        raise PublicationError(
            f"Markdown 状态必须是 {', '.join(sorted(ALLOWED_STATUSES))}，实际为 {status}"
        )
    if not VERSION_PATTERN.fullmatch(version):
        raise PublicationError(f"Markdown 版本格式无效：{version}")
    try:
        date.fromisoformat(published_on)
    except ValueError as exc:
        raise PublicationError(f"Markdown 日期无效：{published_on}") from exc
    return {
        "title": title,
        "status": status,
        "version": version,
        "date": published_on,
    }


def validate_pdf(data: bytes) -> None:
    if not data.startswith(b"%PDF-"):
        raise PublicationError("PDF 文件头无效")
    if b"%%EOF" not in data[-2048:]:
        raise PublicationError("PDF 文件尾无效或文件不完整")


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "items": []}


def _load_catalog(root: Path, *, required: bool) -> dict[str, Any]:
    path = root / CATALOG_NAME
    if not path.exists():
        if required:
            raise PublicationError(f"缺少目录文件：{path}")
        return _empty_catalog()
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationError(f"目录文件不可解析：{path}") from exc
    if not isinstance(catalog, dict) or catalog.get("schema_version") != SCHEMA_VERSION:
        raise PublicationError(f"目录 schema_version 必须为 {SCHEMA_VERSION}")
    if not isinstance(catalog.get("items"), list):
        raise PublicationError("目录 items 必须是数组")
    return catalog


def _catalog_bytes(catalog: dict[str, Any]) -> bytes:
    return (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_index(catalog: dict[str, Any]) -> str:
    lines = [
        "# Omni PRD 总目录",
        "",
        "以后生成的文件型 PRD 统一保存在本目录。每个版本必须同时提供同名 Markdown 和 PDF；旧版本不可覆盖。",
        "",
        "> 本文件与 `catalog.json` 由 `publish_prd.py` 自动生成，请勿手工修改。历史 PRD 仍保留在 `../plans/`，历史 PDF 仍保留在 `../../output/pdf/`。",
        "",
        "| PRD | 状态 | 版本 | 日期 | Markdown | PDF |",
        "|---|---|---|---|---|---|",
    ]
    for item in catalog["items"]:
        lines.append(
            "| {title} | {status} | {version} | {date} | [打开 Markdown]({markdown}) | [打开 PDF]({pdf}) |".format(
                title=_escape_cell(item["title"]),
                status=item["status"],
                version=item["version"],
                date=item["date"],
                markdown=item["markdown"],
                pdf=item["pdf"],
            )
        )
    return "\n".join(lines) + "\n"


def _validate_identity(prd_id: str, version: str, status: str) -> None:
    if not PRD_ID_PATTERN.fullmatch(prd_id):
        raise PublicationError("prd-id 只能使用小写字母、数字和连字符，长度为 3-128")
    if not VERSION_PATTERN.fullmatch(version):
        raise PublicationError("version 必须使用 v1、v1.1 这类格式")
    if status not in ALLOWED_STATUSES:
        raise PublicationError(
            f"status 必须是 {', '.join(sorted(ALLOWED_STATUSES))}"
        )


def _entry_for(
    *,
    prd_id: str,
    title: str,
    version: str,
    status: str,
    published_on: str,
    markdown_path: str,
    pdf_path: str,
    markdown_data: bytes,
    pdf_data: bytes,
) -> dict[str, Any]:
    return {
        "prd_id": prd_id,
        "title": title,
        "status": status,
        "version": version,
        "date": published_on,
        "markdown": markdown_path,
        "pdf": pdf_path,
        "sha256": {
            "markdown": _sha256(markdown_data),
            "pdf": _sha256(pdf_data),
        },
    }


def _assert_no_conflict(path: Path, expected: bytes) -> None:
    if path.exists() and path.read_bytes() != expected:
        raise PublicationError(
            f"同版本目标已存在且内容不同，禁止覆盖：{path}；请提升版本号"
        )


def publish_prd(
    *,
    markdown: Path,
    pdf: Path,
    prd_id: str,
    title: str,
    version: str,
    status: str,
    root: Path,
) -> dict[str, Any]:
    _validate_identity(prd_id, version, status)
    if not markdown.is_file():
        raise PublicationError(f"Markdown 源文件不存在：{markdown}")
    if not pdf.is_file():
        raise PublicationError(f"PDF 源文件不存在：{pdf}")

    markdown_data = markdown.read_bytes()
    pdf_data = pdf.read_bytes()
    metadata = read_markdown_metadata(markdown_data)
    validate_pdf(pdf_data)
    expected = {"title": title, "version": version, "status": status}
    for field, value in expected.items():
        if metadata[field] != value:
            raise PublicationError(
                f"参数 {field}={value} 与 Markdown 中的 {metadata[field]} 不一致"
            )

    basename = f"{prd_id}-{version}"
    relative_markdown = f"{prd_id}/{basename}.md"
    relative_pdf = f"{prd_id}/{basename}.pdf"
    destination_markdown = root / relative_markdown
    destination_pdf = root / relative_pdf
    _assert_no_conflict(destination_markdown, markdown_data)
    _assert_no_conflict(destination_pdf, pdf_data)

    catalog = _load_catalog(root, required=False)
    entry = _entry_for(
        prd_id=prd_id,
        title=title,
        version=version,
        status=status,
        published_on=metadata["date"],
        markdown_path=relative_markdown,
        pdf_path=relative_pdf,
        markdown_data=markdown_data,
        pdf_data=pdf_data,
    )
    key = (prd_id, version)
    items: list[dict[str, Any]] = []
    replaced = False
    for item in catalog["items"]:
        if not isinstance(item, dict):
            raise PublicationError("目录 items 中存在非对象条目")
        if (item.get("prd_id"), item.get("version")) == key:
            if replaced:
                raise PublicationError(f"目录中存在重复版本：{prd_id} {version}")
            items.append(entry)
            replaced = True
        else:
            items.append(item)
    if not replaced:
        items.append(entry)
    catalog = {
        "schema_version": SCHEMA_VERSION,
        "items": sorted(items, key=lambda item: (item["prd_id"], item["version"])),
    }

    if not destination_markdown.exists():
        _atomic_write(destination_markdown, markdown_data)
    if not destination_pdf.exists():
        _atomic_write(destination_pdf, pdf_data)
    _atomic_write(root / CATALOG_NAME, _catalog_bytes(catalog))
    _atomic_write(root / INDEX_NAME, render_index(catalog).encode("utf-8"))
    check_archive(root)
    return entry


def _required_text(item: dict[str, Any], field: str, index: int) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PublicationError(f"目录 items[{index}].{field} 必须是非空字符串")
    return value


def check_archive(root: Path) -> dict[str, int]:
    if not root.is_dir():
        raise PublicationError(f"PRD 根目录不存在：{root}")
    catalog = _load_catalog(root, required=True)
    seen: set[tuple[str, str]] = set()
    expected_markdown: set[Path] = set()
    expected_pdf: set[Path] = set()

    for index, raw_item in enumerate(catalog["items"]):
        if not isinstance(raw_item, dict):
            raise PublicationError(f"目录 items[{index}] 必须是对象")
        prd_id = _required_text(raw_item, "prd_id", index)
        title = _required_text(raw_item, "title", index)
        status = _required_text(raw_item, "status", index)
        version = _required_text(raw_item, "version", index)
        published_on = _required_text(raw_item, "date", index)
        markdown_rel = _required_text(raw_item, "markdown", index)
        pdf_rel = _required_text(raw_item, "pdf", index)
        _validate_identity(prd_id, version, status)
        try:
            date.fromisoformat(published_on)
        except ValueError as exc:
            raise PublicationError(f"目录 items[{index}].date 无效") from exc
        key = (prd_id, version)
        if key in seen:
            raise PublicationError(f"目录中存在重复版本：{prd_id} {version}")
        seen.add(key)

        expected_basename = f"{prd_id}-{version}"
        expected_markdown_rel = f"{prd_id}/{expected_basename}.md"
        expected_pdf_rel = f"{prd_id}/{expected_basename}.pdf"
        if markdown_rel != expected_markdown_rel or pdf_rel != expected_pdf_rel:
            raise PublicationError(f"目录 items[{index}] 的路径不符合固定命名规则")
        markdown_path = root / markdown_rel
        pdf_path = root / pdf_rel
        if markdown_path.stem != pdf_path.stem:
            raise PublicationError(f"Markdown/PDF basename 不一致：{prd_id} {version}")
        if not markdown_path.is_file() or not pdf_path.is_file():
            raise PublicationError(f"PRD 配对文件缺失：{prd_id} {version}")

        markdown_data = markdown_path.read_bytes()
        pdf_data = pdf_path.read_bytes()
        metadata = read_markdown_metadata(markdown_data)
        validate_pdf(pdf_data)
        for field, value in {
            "title": title,
            "status": status,
            "version": version,
            "date": published_on,
        }.items():
            if metadata[field] != value:
                raise PublicationError(
                    f"{markdown_rel} 的 {field} 与目录不一致"
                )
        hashes = raw_item.get("sha256")
        if not isinstance(hashes, dict):
            raise PublicationError(f"目录 items[{index}].sha256 必须是对象")
        if hashes.get("markdown") != _sha256(markdown_data):
            raise PublicationError(f"Markdown 哈希漂移：{markdown_rel}")
        if hashes.get("pdf") != _sha256(pdf_data):
            raise PublicationError(f"PDF 哈希漂移：{pdf_rel}")
        expected_markdown.add(markdown_path.resolve())
        expected_pdf.add(pdf_path.resolve())

    actual_markdown = {
        path.resolve() for path in root.rglob("*.md") if path.name != INDEX_NAME
    }
    actual_pdf = {path.resolve() for path in root.rglob("*.pdf")}
    unindexed_markdown = sorted(actual_markdown - expected_markdown)
    unindexed_pdf = sorted(actual_pdf - expected_pdf)
    if unindexed_markdown or unindexed_pdf:
        extra = [str(path) for path in unindexed_markdown + unindexed_pdf]
        raise PublicationError("存在未配对或未登记文件：" + ", ".join(extra))
    missing_markdown = sorted(expected_markdown - actual_markdown)
    missing_pdf = sorted(expected_pdf - actual_pdf)
    if missing_markdown or missing_pdf:
        missing = [str(path) for path in missing_markdown + missing_pdf]
        raise PublicationError("目录登记文件缺失：" + ", ".join(missing))

    index_path = root / INDEX_NAME
    if not index_path.is_file():
        raise PublicationError(f"缺少统一索引：{index_path}")
    expected_index = render_index(catalog)
    if index_path.read_text(encoding="utf-8") != expected_index:
        raise PublicationError("README.md 与 catalog.json 不一致，请重新发布生成索引")
    return {"items": len(seen), "markdown": len(actual_markdown), "pdf": len(actual_pdf)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish or verify immutable Markdown/PDF PRD pairs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish = subparsers.add_parser("publish", help="Publish one PRD pair.")
    publish.add_argument("--markdown", type=Path, required=True)
    publish.add_argument("--pdf", type=Path, required=True)
    publish.add_argument("--prd-id", required=True)
    publish.add_argument("--title", required=True)
    publish.add_argument("--version", required=True)
    publish.add_argument("--status", choices=sorted(ALLOWED_STATUSES), required=True)
    publish.add_argument("--root", type=Path, default=Path("docs/prds"))

    check = subparsers.add_parser("check", help="Verify the entire PRD archive.")
    check.add_argument("--root", type=Path, default=Path("docs/prds"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "publish":
            result = publish_prd(
                markdown=args.markdown,
                pdf=args.pdf,
                prd_id=args.prd_id,
                title=args.title,
                version=args.version,
                status=args.status,
                root=args.root,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            result = check_archive(args.root)
            print(
                "OK: {items} PRD versions, {markdown} Markdown files, {pdf} PDF files".format(
                    **result
                )
            )
    except (OSError, PublicationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
