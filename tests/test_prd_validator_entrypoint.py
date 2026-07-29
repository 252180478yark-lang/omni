from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_prd.py"


def ready_prd_text() -> str:
    headings = [
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
    sections = ["# PRD：验证入口夹具", "", "- 状态：READY", "- 版本：v1.0", "- 日期：2026-07-29", ""]
    for index, heading in enumerate(headings, start=1):
        sections.extend([f"## {index}. {heading}", "", "本节记录可验证的实施事实。", ""])
    sections.extend(
        [
            "[现状事实] `services/example.py` 已提供验证路径（SYS-001）。",
            "",
            "### FR-001 [P0] 验证入口",
            "- 角色：开发者",
            "- 触发：运行验证命令",
            "- 前置：仓库文件存在",
            "- 规则：执行稳定入口",
            "- 输出：结构化校验结果",
            "- 异常：空数据、无权限、超时、重复提交和部分失败均有明确错误。",
            "- 来源：SYS-001",
            "",
            "### AC-FR001-01",
            "- Given：存在 READY 文档",
            "- When：运行严格校验",
            "- Then：返回通过结果",
            "- And：输出可读取",
            "- Evidence：`tests/test_prd_validator_entrypoint.py`",
            "",
            "复用现有 validator；修改稳定入口；拟新增夹具；不做业务写入。",
            "",
            "### Definition of Ready",
            "- [x] 使用者明确",
            "- [x] 问题明确",
            "- [x] 当前事实有证据",
            "- [x] FR 有验收",
            "- [x] 数据合同明确",
            "- [x] 权限边界明确",
            "- [x] 回滚明确",
            "- [x] 验证命令明确",
            "",
            "#### 阻塞开工",
            "- 无",
            "",
        ]
    )
    return "\n".join(sections)


class PrdValidatorEntrypointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="omni-prd-validator-")
        self.addCleanup(self.temp_dir.cleanup)
        self.prd = Path(self.temp_dir.name) / "ready.md"
        self.prd.write_text(ready_prd_text(), encoding="utf-8")

    def run_validator(self, *args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(VALIDATOR), *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_root_entrypoint_validates_ready_prd_from_a_subdirectory(self) -> None:
        result = self.run_validator(
            str(self.prd),
            "--strict",
            "--json",
            cwd=ROOT / "frontend",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["errors"], 0)

    def test_root_entrypoint_preserves_missing_input_error(self) -> None:
        result = self.run_validator("docs/prds/missing.md", "--strict")

        self.assertEqual(result.returncode, 1)
        self.assertIn("file.missing", result.stdout)


if __name__ == "__main__":
    unittest.main()
