#!/usr/bin/env python3
"""Deterministic policy checks for the repository-level Codex instructions.

The normal CLI mode is a blocking gate for CI. ``--hook`` is deliberately
advisory: it emits a Codex ``SessionStart`` warning and always exits zero.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


MAX_AGENTS_BYTES = 16_384
DEVELOPMENT_SKILL = "omni-feature-development"
ROOT_INSTRUCTION_FILES = ("AGENTS.md", "AGENTS.override.md")
REPARSE_POINT_ATTRIBUTE = 0x0400
REQUIRED_TRACKED_ASSETS = (
    "AGENTS.md",
    ".codex/hooks.json",
    "scripts/check_agent_policy.py",
    "scripts/check_agents_policy.py",
    "scripts/verify_agent_archives.py",
)

SKILL_REFERENCE_RE = re.compile(
    r"(?<![\w.])\.agents[\\/]+skills[\\/]+"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)",
    re.IGNORECASE,
)

# These expressions target totals that become stale. They intentionally do not
# reject stable statements such as "1 个 tool 路由 6 类素材".
DYNAMIC_TOOL_TOTAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("doctor-total", re.compile(r"\ball\s+\d+\s+ok\b", re.IGNORECASE)),
    (
        "tool-total-zh",
        re.compile(
            r"(?:暴露|注册(?:了)?|现有|当前(?:有|为)?|共有|共计|合计|总计|"
            r"工具总数|tool\s*总数)[^。；;\n]{0,24}?"
            r"\d+\s*(?:个\s*)?(?:MCP\s*)?(?:tools?|工具)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tool-total-label",
        re.compile(
            r"(?:MCP\s*)?(?:tools?|工具)(?:\s*(?:总数|数量|count))?"
            r"\s*[:：=]\s*\d+\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tool-total-en",
        re.compile(
            r"(?:\b\d+\s+(?:MCP\s+)?tools?\s+"
            r"(?:registered|available|exposed)\b)|"
            r"(?:\b(?:exposes?|registers?|has|contains|provides?)\s+"
            r"\d+\s+(?:MCP\s+)?tools?\b)",
            re.IGNORECASE,
        ),
    ),
)

DEVELOPMENT_SKILL_TODO_RE = re.compile(r"\b(?:TODO|TBD)\b", re.IGNORECASE)
PLACEHOLDER_DESCRIPTION_RE = re.compile(
    r"\b(?:TODO|TBD|placeholder|replace\s+me)\b|"
    r"one\s+sentence|what\s+this\s+skill\s+does|when\s+to\s+invoke|"
    r"待填写|待补充|占位",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str
    line: int | None = None

    def render(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{location} [{self.code}] {self.message}"


def _instruction_paths(root: Path) -> list[Path]:
    return [root / name for name in ROOT_INSTRUCTION_FILES if (root / name).exists()]


def _read_utf8(path: Path) -> tuple[str | None, Finding | None]:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError as exc:
        return None, Finding(
            code="invalid-utf8",
            path=path.name,
            message=f"must be valid UTF-8 ({exc})",
        )


def _plain_markdown_line(line: str) -> str:
    return line.replace("`", "").replace("**", "").replace("__", "")


def _dynamic_total_findings(path: Path, text: str) -> Iterable[Finding]:
    for line_number, source_line in enumerate(text.splitlines(), start=1):
        line = _plain_markdown_line(source_line)
        for code, pattern in DYNAMIC_TOOL_TOTAL_PATTERNS:
            if pattern.search(line):
                yield Finding(
                    code=code,
                    path=path.name,
                    line=line_number,
                    message=(
                        "do not hard-code runtime tool totals; query the MCP catalog "
                        "or run doctor instead"
                    ),
                )
                break


def _referenced_skills(texts: Iterable[str]) -> set[str]:
    names: set[str] = set()
    for text in texts:
        names.update(match.group("name") for match in SKILL_REFERENCE_RE.finditer(text))
    return names


def _frontmatter_description(text: str) -> str | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    try:
        frontmatter_end = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        return None

    for index, line in enumerate(lines[1:frontmatter_end], start=1):
        match = re.match(r"^description\s*:\s*(.*)$", line, re.IGNORECASE)
        if match is None:
            continue

        value = match.group(1).strip()
        if value in {">", ">-", ">+", "|", "|-", "|+"}:
            continuation: list[str] = []
            for candidate in lines[index + 1 : frontmatter_end]:
                if candidate and not candidate[0].isspace():
                    break
                continuation.append(candidate.strip())
            value = " ".join(part for part in continuation if part)

        return value.strip().strip('"\'') or None

    return None


def _development_skill_findings(root: Path, path: Path) -> Iterable[Finding]:
    relative_path = path.relative_to(root).as_posix()
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        yield Finding(
            code="invalid-development-skill-utf8",
            path=relative_path,
            message=f"must be valid UTF-8 ({exc})",
        )
        return

    description = _frontmatter_description(text)
    if description is None:
        yield Finding(
            code="missing-development-skill-description",
            path=relative_path,
            message="frontmatter must contain a non-empty description",
        )
    elif PLACEHOLDER_DESCRIPTION_RE.search(description):
        yield Finding(
            code="placeholder-development-skill-description",
            path=relative_path,
            message="frontmatter description must state the real trigger and scope",
        )

    for line_number, line in enumerate(text.splitlines(), start=1):
        if DEVELOPMENT_SKILL_TODO_RE.search(line):
            yield Finding(
                code="development-skill-todo",
                path=relative_path,
                line=line_number,
                message="mandatory development Skill cannot contain TODO/TBD",
            )


def _is_reparse_point(path: Path) -> bool:
    """Recognize symlinks and Windows junctions without resolving them first."""

    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & REPARSE_POINT_ATTRIBUTE)


def _skill_asset_paths(
    root: Path,
    skill_path: Path,
    *,
    reject_reparse_points: bool,
) -> tuple[list[Path], list[Finding]]:
    """Return Skill files and optionally reject local links after index materialization."""

    findings: list[Finding] = []
    if _is_reparse_point(skill_path) and reject_reparse_points:
        findings.append(
            Finding(
                code="reparse-skill-reference",
                path=skill_path.relative_to(root).as_posix(),
                message="routed Skills must be ordinary directories, not symlinks or Windows junctions",
            )
        )

    files: list[Path] = []
    for directory, child_dirs, child_files in os.walk(skill_path, followlinks=False):
        parent = Path(directory)
        ordinary_dirs: list[str] = []
        for child_name in child_dirs:
            if child_name == "__pycache__":
                continue
            child = parent / child_name
            if _is_reparse_point(child):
                if reject_reparse_points:
                    findings.append(
                        Finding(
                            code="reparse-skill-asset",
                            path=child.relative_to(root).as_posix(),
                            message="Skill assets must not depend on symlinks or Windows junctions",
                        )
                    )
                # Never descend through nested links, even in index-materialization mode.
                continue
            else:
                ordinary_dirs.append(child_name)
        child_dirs[:] = ordinary_dirs
        for child_name in child_files:
            if child_name.endswith((".pyc", ".pyo")):
                continue
            child = parent / child_name
            if _is_reparse_point(child):
                if reject_reparse_points:
                    findings.append(
                        Finding(
                            code="reparse-skill-asset",
                            path=child.relative_to(root).as_posix(),
                            message="Skill assets must not depend on symlinks or Windows junctions",
                        )
                    )
            elif child.is_file():
                files.append(child)
    return files, findings


def _tracked_index_modes(root: Path) -> dict[str, str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--stage", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(f"git ls-files failed ({result.returncode}): {detail}")

    modes: dict[str, str] = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        try:
            metadata, raw_path = entry.split(b"\t", 1)
            mode = metadata.decode("ascii").split(" ", 1)[0]
            path = raw_path.decode("utf-8").replace("\\", "/")
        except (UnicodeDecodeError, ValueError) as exc:
            raise OSError(f"git index contains an invalid path entry: {exc}") from exc
        modes[path] = mode
    return modes


def _tracked_asset_findings(
    root: Path,
    skill_files: Iterable[Path],
) -> list[Finding]:
    try:
        modes = _tracked_index_modes(root)
    except OSError as exc:
        return [
            Finding(
                code="tracked-assets-unavailable",
                path=".git",
                message=f"cannot verify Git-indexed governance assets: {exc}",
            )
        ]

    findings: list[Finding] = []
    required_paths = [*REQUIRED_TRACKED_ASSETS]
    required_paths.extend(path.relative_to(root).as_posix() for path in skill_files)
    for relative_path in sorted(set(required_paths), key=str.casefold):
        mode = modes.get(relative_path)
        if mode is None:
            findings.append(
                Finding(
                    code="untracked-governance-asset",
                    path=relative_path,
                    message="must be present in the Git index for a portable checkout",
                )
            )
        elif mode not in {"100644", "100755"}:
            findings.append(
                Finding(
                    code="nonregular-governance-asset",
                    path=relative_path,
                    message=f"must be a regular tracked file, found Git mode {mode}",
                )
            )
    return findings


def check_agents_policy(
    root: Path,
    *,
    max_bytes: int = MAX_AGENTS_BYTES,
    require_tracked: bool = False,
    reject_reparse_points: bool = False,
) -> list[Finding]:
    """Return every deterministic repository instruction-policy violation."""

    root = root.resolve()
    # A tracked index blob alone does not make the live instruction tree
    # portable: Windows junctions can still redirect a routed Skill to an
    # untracked or machine-local target.  CI and explicit tracked-asset checks
    # therefore require ordinary physical directories as well.
    reject_reparse_points = reject_reparse_points or require_tracked
    agents_path = root / "AGENTS.md"
    findings: list[Finding] = []

    if not agents_path.is_file():
        findings.append(
            Finding(
                code="missing-agents",
                path="AGENTS.md",
                message="repository-level AGENTS.md is required",
            )
        )
        instruction_paths: list[Path] = []
    else:
        instruction_paths = _instruction_paths(root)

    decoded_texts: list[str] = []
    for path in instruction_paths:
        byte_count = path.stat().st_size
        if byte_count > max_bytes:
            findings.append(
                Finding(
                    code="agents-too-large",
                    path=path.name,
                    message=f"is {byte_count} UTF-8 bytes; limit is {max_bytes}",
                )
            )

        text, decode_finding = _read_utf8(path)
        if decode_finding is not None:
            findings.append(decode_finding)
            continue

        assert text is not None
        decoded_texts.append(text)
        findings.extend(_dynamic_total_findings(path, text))

    skill_root = root / ".agents" / "skills"
    development_skill_path = skill_root / DEVELOPMENT_SKILL / "SKILL.md"
    if not development_skill_path.is_file():
        findings.append(
            Finding(
                code="missing-development-skill",
                path=development_skill_path.relative_to(root).as_posix(),
                message="the mandatory feature-development skill is missing",
            )
        )
    else:
        findings.extend(
            _development_skill_findings(root, development_skill_path)
        )

    skill_files: list[Path] = []
    routed_skill_names = _referenced_skills(decoded_texts)
    routed_skill_names.add(DEVELOPMENT_SKILL)
    for skill_name in sorted(routed_skill_names, key=str.casefold):
        skill_path = skill_root / skill_name / "SKILL.md"
        if not skill_path.is_file():
            findings.append(
                Finding(
                    code="missing-skill-reference",
                    path=skill_path.relative_to(root).as_posix(),
                    message=(
                        f"AGENTS references .agents/skills/{skill_name}, "
                        "but SKILL.md does not exist"
                    ),
                )
            )
            continue
        assets, asset_findings = _skill_asset_paths(
            root,
            skill_path.parent,
            reject_reparse_points=reject_reparse_points,
        )
        findings.extend(asset_findings)
        skill_files.extend(assets)

    if require_tracked:
        findings.extend(_tracked_asset_findings(root, skill_files))

    return findings


def _format_findings(findings: Sequence[Finding]) -> str:
    return "\n".join(f"- {finding.render()}" for finding in findings)


def _hook_message(findings: Sequence[Finding]) -> str:
    shown = list(findings[:8])
    suffix = ""
    if len(findings) > len(shown):
        suffix = f"\n- ... and {len(findings) - len(shown)} more"
    return (
        "AGENTS policy warning (advisory in Codex; blocking in CI):\n"
        f"{_format_findings(shown)}{suffix}\n"
        "Run `python scripts/check_agent_policy.py` from the repository root."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate repository-level Codex instruction policy."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=MAX_AGENTS_BYTES,
        help=f"per-file AGENTS byte limit (default: {MAX_AGENTS_BYTES})",
    )
    parser.add_argument(
        "--hook",
        action="store_true",
        help="emit an advisory SessionStart response and always exit zero",
    )
    parser.add_argument(
        "--require-tracked",
        action="store_true",
        help=(
            "require routed Skill assets and S1 governance entrypoints in the Git index "
            "and ordinary local directories"
        ),
    )
    parser.add_argument(
        "--reject-reparse-points",
        action="store_true",
        help="reject symlinks and Windows junctions in the current routed Skill tree",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    findings = check_agents_policy(
        args.root,
        max_bytes=args.max_bytes,
        require_tracked=args.require_tracked,
        reject_reparse_points=args.reject_reparse_points,
    )

    if args.hook:
        if findings:
            print(
                json.dumps(
                    {"continue": True, "systemMessage": _hook_message(findings)},
                    ensure_ascii=False,
                )
            )
        return 0

    if findings:
        print(f"[agents-policy] FAIL: {len(findings)} violation(s)")
        print(_format_findings(findings))
        return 1

    agents_bytes = (args.root.resolve() / "AGENTS.md").stat().st_size
    print(
        f"[agents-policy] OK: AGENTS.md is {agents_bytes}/{args.max_bytes} bytes; "
        "dynamic totals and skill references are valid"
        + ("; routed assets are tracked" if args.require_tracked else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
