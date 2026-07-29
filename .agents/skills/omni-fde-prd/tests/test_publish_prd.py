from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_module() -> ModuleType:
    script = Path(__file__).parents[1] / "scripts" / "publish_prd.py"
    spec = importlib.util.spec_from_file_location("omni_publish_prd", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publisher = _load_module()


def _sources(tmp_path: Path) -> tuple[Path, Path]:
    markdown = tmp_path / "source.md"
    markdown.write_text(
        "# PRD：示例实施方案\n\n"
        "- 状态：READY\n"
        "- 版本：v1.0\n"
        "- 日期：2026-07-29\n\n"
        "## 正文\n\n内容。\n",
        encoding="utf-8",
    )
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    return markdown, pdf


def _publish(tmp_path: Path) -> tuple[Path, dict]:
    markdown, pdf = _sources(tmp_path)
    root = tmp_path / "prds"
    entry = publisher.publish_prd(
        markdown=markdown,
        pdf=pdf,
        prd_id="2026-07-29-example-prd",
        title="示例实施方案",
        version="v1.0",
        status="READY",
        root=root,
    )
    return root, entry


def test_publish_creates_pair_catalog_and_index(tmp_path: Path) -> None:
    root, entry = _publish(tmp_path)

    assert (root / entry["markdown"]).is_file()
    assert (root / entry["pdf"]).is_file()
    assert (root / entry["markdown"]).stem == (root / entry["pdf"]).stem
    assert "打开 Markdown" in (root / "README.md").read_text(encoding="utf-8")
    assert publisher.check_archive(root) == {"items": 1, "markdown": 1, "pdf": 1}


def test_publish_is_idempotent_and_rejects_same_version_overwrite(tmp_path: Path) -> None:
    root, entry = _publish(tmp_path)
    original = (root / entry["markdown"]).read_bytes()
    markdown, pdf = _sources(tmp_path)

    publisher.publish_prd(
        markdown=markdown,
        pdf=pdf,
        prd_id="2026-07-29-example-prd",
        title="示例实施方案",
        version="v1.0",
        status="READY",
        root=root,
    )
    markdown.write_text(markdown.read_text(encoding="utf-8") + "变更内容\n", encoding="utf-8")
    with pytest.raises(publisher.PublicationError, match="禁止覆盖"):
        publisher.publish_prd(
            markdown=markdown,
            pdf=pdf,
            prd_id="2026-07-29-example-prd",
            title="示例实施方案",
            version="v1.0",
            status="READY",
            root=root,
        )
    assert (root / entry["markdown"]).read_bytes() == original


def test_publish_rejects_metadata_mismatch_and_invalid_pdf(tmp_path: Path) -> None:
    markdown, pdf = _sources(tmp_path)
    root = tmp_path / "prds"
    with pytest.raises(publisher.PublicationError, match="与 Markdown"):
        publisher.publish_prd(
            markdown=markdown,
            pdf=pdf,
            prd_id="2026-07-29-example-prd",
            title="示例实施方案",
            version="v2.0",
            status="READY",
            root=root,
        )

    pdf.write_bytes(b"not a pdf")
    with pytest.raises(publisher.PublicationError, match="PDF 文件头"):
        publisher.publish_prd(
            markdown=markdown,
            pdf=pdf,
            prd_id="2026-07-29-example-prd",
            title="示例实施方案",
            version="v1.0",
            status="READY",
            root=root,
        )


def test_check_detects_hash_drift(tmp_path: Path) -> None:
    root, entry = _publish(tmp_path)
    (root / entry["markdown"]).write_text("drift", encoding="utf-8")

    with pytest.raises(publisher.PublicationError):
        publisher.check_archive(root)


def test_check_detects_unindexed_or_partial_pair(tmp_path: Path) -> None:
    root, _ = _publish(tmp_path)
    extra_dir = root / "2026-07-29-unindexed-prd"
    extra_dir.mkdir()
    (extra_dir / "2026-07-29-unindexed-prd-v1.0.pdf").write_bytes(
        b"%PDF-1.4\n%%EOF\n"
    )

    with pytest.raises(publisher.PublicationError, match="未配对或未登记"):
        publisher.check_archive(root)
