#!/usr/bin/env python3
"""Risk-aware, read-only local development hook.

The hook deliberately never edits a contract or a runtime allocation.  A
``REMEDIATE`` result releases control back to Codex with an exact repair, so
the contract update remains visible and reviewable before the original write
is retried.  Hook infrastructure failures are never converted to green.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REMEDIATE = "REMEDIATE"
    BLOCK = "BLOCK"


RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
WRITE_TOOLS = {
    "apply_patch",
    "edit",
    "multiedit",
    "notebookedit",
    "write",
    "write_file",
}
READ_TOOLS = {"glob", "grep", "ls", "read", "read_file", "search", "view"}
SHELL_TOOLS = {"bash", "shell", "shell_command", "powershell", "exec", "exec_command"}
TERMINAL_STATES = {"COMPLETE", "COMPLETED", "CANCELLED", "REJECTED", "ROLLED_BACK"}
WRITABLE_ACTIVE_STATES = {"IMPACT_LOCKED", "IMPLEMENTING", "VERIFYING"}
SENSITIVE_PATH_MARKERS = (
    "migrations/",
    "docker-compose",
    ".github/workflows/",
    "scripts/apply_migrations.py",
    "services/infra-core/",
)
WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul", "clock$",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class ContractView:
    change_id: str
    risk: str
    state: str
    paths: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class LeaseView:
    known: bool
    conflict: bool = False
    owner: str | None = None
    change_id: str | None = None
    expires_at: str | None = None
    source: str | None = None
    stale: bool = False


@dataclass(frozen=True)
class GateResult:
    event: str
    decision: Decision
    risk: str
    issue_code: str
    reason: str
    change_id: str | None = None
    path: str | None = None
    lease_owner: str | None = None
    repair: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


@dataclass(frozen=True)
class ShellAnalysis:
    intent: str  # read | write | unknown
    targets: tuple[str, ...] = ()
    reason: str = ""
    complete: bool = True


@dataclass(frozen=True)
class TargetExtraction:
    targets: tuple[str, ...] = ()
    unresolved: bool = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_HOOK_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_HOOK_DSN = re.compile(r"(?P<prefix>://[^:/\s]+:)[^@/\s]+(?=@)")
_HOOK_API_KEY = re.compile(r"(?i)\b(?:sk|pk|api|key|token)[-_][A-Za-z0-9_-]{12,}\b")


def _fingerprint(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _sanitize_hook_text(value: str) -> str:
    value = _HOOK_BEARER.sub("Bearer [REDACTED]", value)
    value = _HOOK_DSN.sub(r"\g<prefix>[REDACTED]", value)
    return _HOOK_API_KEY.sub("[REDACTED]", value)


def _sanitize_hook_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _sanitize_hook_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_hook_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_hook_text(value)
    return value


def _repo_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        if value:
            return Path(value).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    return Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> Mapping[str, Any] | None:
    try:
        import yaml  # type: ignore

        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        return value if isinstance(value, Mapping) else None
    except Exception:
        return None


def _normalize_path(value: str, root: Path) -> str | None:
    del root  # repository-relative paths only; absolute paths are ambiguous at hook time.
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    if not value or "\x00" in value:
        return None
    normalized = value.replace("\\", "/")
    if (
        normalized.startswith("/")
        or normalized.startswith("//")
        or re.match(r"^[A-Za-z]:", normalized)
    ):
        return None
    raw_parts = normalized.split("/")
    if any(part == ".." for part in raw_parts):
        return None
    parts = [part for part in raw_parts if part not in {"", "."}]
    if not parts:
        return None
    for part in parts:
        if ":" in part or part.endswith((".", " ")):
            return None
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
            return None
    return "/".join(parts)


def _shell_command(payload: Mapping[str, Any]) -> str | None:
    tool = str(payload.get("tool_name") or payload.get("tool") or "").lower()
    if tool not in SHELL_TOOLS:
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, Mapping) or not isinstance(tool_input.get("command"), str):
        return ""
    return str(tool_input["command"])


def _command_tokens(value: str) -> list[str]:
    return [
        next(group for group in match.groups() if group is not None)
        for match in re.finditer(r'"([^"\r\n]+)"|\'([^\'\r\n]+)\'|([^\s,;|]+)', value)
    ]


def _shell_write_targets(command: str, root: Path) -> tuple[tuple[str, ...], bool]:
    raw_targets: list[str] = []
    normalized_command = command.replace("\\", "/")
    # Shell redirection (excluding fd plumbing such as 2>&1).
    for match in re.finditer(
        r"(?<!\d)(?:>>|>)\s*(?!&)(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))",
        normalized_command,
    ):
        raw_targets.append(next(value for value in match.groups() if value is not None))

    powershell = re.compile(
        r"(?i)\b(Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Move-Item|"
        r"Copy-Item|Rename-Item)\b([^;|\r\n]*)"
    )
    for match in powershell.finditer(normalized_command):
        name, arguments = match.group(1).lower(), match.group(2)
        option_targets = re.findall(
            r"(?i)-(LiteralPath|Path|Destination|FilePath)\s+(?:\"([^\"]+)\"|'([^']+)'|([^\s;|]+))",
            arguments,
        )
        selected_options: list[str] = []
        for option, *groups in option_targets:
            value = next((item for item in groups if item), "")
            if name in {"copy-item", "move-item", "rename-item"}:
                if option.casefold() == "destination":
                    selected_options.append(value)
            elif option.casefold() in {"literalpath", "path", "filepath"}:
                selected_options.append(value)
        raw_targets.extend(selected_options)
        positional = [token for token in _command_tokens(arguments) if not token.startswith("-")]
        if name in {"copy-item", "move-item", "rename-item"} and not selected_options and positional:
            raw_targets.append(positional[-1])
        elif name in {"set-content", "add-content", "out-file", "new-item", "remove-item"} and not selected_options and positional:
            raw_targets.append(positional[-1])

    for match in re.finditer(r"(?i)(?:^|[;&]\s*)(touch|mkdir|rm)\s+([^;&|]+)", normalized_command):
        raw_targets.extend(token for token in _command_tokens(match.group(2)) if not token.startswith("-"))
    for match in re.finditer(r"(?i)(?:^|[;&]\s*)(cp|mv)\s+([^;&|]+)", normalized_command):
        positional = [token for token in _command_tokens(match.group(2)) if not token.startswith("-")]
        if positional:
            raw_targets.append(positional[-1])

    if re.search(
        r"(?i)python(?:3)?(?:\.exe)?\s+[^\r\n]*(?:-c|-Command)[^\r\n]*"
        r"(?:write_text|write_bytes|open\s*\([^)]*[, ]\s*['\"](?:w|a|x)|unlink|rmtree|shutil\.(?:copy|move))",
        normalized_command,
    ):
        for match in re.finditer(r"['\"]([^'\"]+[\\/][^'\"]+|[^'\"]+\.[A-Za-z0-9]{1,8})['\"]", normalized_command):
            raw_targets.append(match.group(1))

    raw_targets.extend(
        match.group(1)
        for match in re.finditer(
            r"(?<![\w.-])((?:scripts|services|frontend|migrations)/[\w./-]+)",
            normalized_command,
        )
    )

    targets: list[str] = []
    unresolved = False
    for raw in raw_targets:
        for value in str(raw).split(","):
            normalized = _normalize_path(value, root)
            if normalized and normalized not in targets:
                targets.append(normalized)
            elif value.strip():
                unresolved = True
    return tuple(targets), unresolved


def _analyze_shell(payload: Mapping[str, Any], root: Path) -> ShellAnalysis | None:
    command = _shell_command(payload)
    if command is None:
        return None
    if not command.strip():
        return ShellAnalysis("unknown", reason="shell command is missing")
    targets, unresolved = _shell_write_targets(command, root)
    write_marker = re.search(
        r"(?i)(?:>>|(?<!\d)>\s*(?!&)|\b(?:Set-Content|Add-Content|Out-File|New-Item|"
        r"Remove-Item|Move-Item|Copy-Item|Rename-Item|touch|mkdir|rm|mv|cp|sed\s+-i|"
        r"git\s+(?:add|commit|push|merge|rebase)|docker\s+compose\s+up|"
        r"apply_migrations|write_text|write_bytes|unlink|rmtree)\b|"
        r"open\s*\([^)]*[, ]\s*['\"](?:w|a|x)|"
        r"Invoke-RestMethod\b[^\r\n]*(?:-Method\s+)?(?:POST|PUT|PATCH|DELETE)|"
        r"curl\b[^\r\n]*(?:-X|--request)\s*(?:POST|PUT|PATCH|DELETE)|"
        r"psql\b[^\r\n]*\b(?:INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|TRUNCATE)\b)",
        command,
    )
    if write_marker:
        return ShellAnalysis(
            "write",
            targets,
            f"write marker: {write_marker.group(0)}",
            complete=bool(targets) and not unresolved,
        )
    read_patterns = (
        r"^\s*(?:rg|grep|find|ls|dir|Get-Content|Get-ChildItem|Select-String|Test-Path)\b",
        r"^\s*git\s+(?:status|diff|log|show|rev-parse|ls-files|worktree\s+list|for-each-ref)\b",
        r"^\s*python(?:3)?(?:\.exe)?\s+-B\s+-m\s+pytest\b",
        r"^\s*python(?:3)?(?:\.exe)?\s+-B\s+scripts/(?:check|verify|generate_)[\w./-]*\.py\b",
        r"^\s*(?:npm|pnpm|yarn)\b[^\r\n]*(?:test|lint|check)\b",
        r"^\s*docker\s+compose\b[^\r\n]*\bconfig\b",
    )
    segments = [segment.strip() for segment in re.split(r"\s*(?:;|&&|\|)\s*", command) if segment.strip()]
    if segments and all(any(re.search(pattern, segment, re.I) for pattern in read_patterns) for segment in segments):
        return ShellAnalysis("read", reason="all shell segments match the read-only allowlist")
    return ShellAnalysis("unknown", reason="shell command is outside the deterministic allowlist")


def _target_extraction(payload: Mapping[str, Any], root: Path) -> TargetExtraction:
    tool_input = payload.get("tool_input")
    values: list[Any] = []
    unresolved = False
    if isinstance(tool_input, Mapping):
        for key in ("file_path", "path", "target", "notebook_path"):
            if key in tool_input:
                values.append(tool_input.get(key))
        for collection_key in ("edits", "files", "targets"):
            collection = tool_input.get(collection_key)
            if collection is None:
                continue
            if not isinstance(collection, Sequence) or isinstance(collection, (str, bytes)):
                unresolved = True
                continue
            for item in collection:
                if isinstance(item, str):
                    values.append(item)
                    continue
                if not isinstance(item, Mapping):
                    unresolved = True
                    continue
                found = False
                for key in ("file_path", "path", "target", "notebook_path"):
                    if key in item:
                        values.append(item.get(key))
                        found = True
                if not found:
                    unresolved = True
        patches = tool_input.get("patch") or tool_input.get("input")
        if isinstance(patches, str):
            patch_paths = [
                match.group(1)
                for match in re.finditer(
                    r"(?:(?:Update|Add|Delete|Move) File|Move to):\s*([^\r\n]+)", patches
                )
            ]
            values.extend(patch_paths)
            tool = str(payload.get("tool_name") or payload.get("tool") or "").lower()
            if ("patch" in tool or tool == "apply_patch") and not patch_paths:
                unresolved = True
        command = tool_input.get("command")
        if isinstance(command, str):
            tool = str(payload.get("tool_name") or payload.get("tool") or "").lower()
            if "patch" in tool:
                command_paths = [
                    match.group(1)
                    for match in re.finditer(
                        r"(?:(?:Add|Update|Delete|Move) File|Move to):\s*([^\r\n]+)", command
                    )
                ]
                values.extend(command_paths)
                if not command_paths:
                    unresolved = True
            analysis = _analyze_shell(payload, root)
            if analysis:
                values.extend(analysis.targets)
                unresolved = unresolved or (analysis.intent == "write" and not analysis.complete)
    for key in ("file_path", "path", "target_path"):
        if key in payload:
            values.append(payload.get(key))
    targets: list[str] = []
    for value in values:
        if not isinstance(value, str):
            unresolved = True
            continue
        normalized = _normalize_path(value, root)
        if normalized and normalized not in targets:
            targets.append(normalized)
        elif value.strip():
            unresolved = True
    return TargetExtraction(tuple(targets), unresolved)


def _extract_targets(payload: Mapping[str, Any], root: Path) -> tuple[str, ...]:
    return _target_extraction(payload, root).targets


def _extract_target(payload: Mapping[str, Any], root: Path) -> str | None:
    targets = _extract_targets(payload, root)
    return targets[0] if targets else None


def _is_write(payload: Mapping[str, Any]) -> bool:
    tool = str(payload.get("tool_name") or payload.get("tool") or "").lower()
    if tool in READ_TOOLS:
        return False
    if tool in WRITE_TOOLS or any(token in tool for token in ("write", "edit", "patch")):
        return True
    effects = payload.get("effect_kinds") or payload.get("effects") or []
    if isinstance(effects, str):
        effects = [effects]
    if isinstance(effects, Sequence) and any(
        re.search(r"(?i)(?:write|create|update|delete|send|publish|deploy|migrate|execute)", str(effect))
        for effect in effects
    ):
        return True
    if re.search(r"(?i)(?:^|[_:.])(send|publish|delete|deploy|migrate|execute)(?:$|[_:.])", tool):
        return True
    if tool in SHELL_TOOLS:
        # The root-independent marker is used only for risk classification;
        # evaluate_pre_tool performs the full root-aware shell analysis.
        command = _shell_command(payload) or ""
        return bool(
            re.search(
                r"(?i)(?:>>|(?<!\d)>\s*(?!&)|\b(?:set-content|add-content|out-file|new-item|"
                r"remove-item|move-item|copy-item|rename-item|touch|mkdir|rm|mv|cp|sed\s+-i|"
                r"git\s+(?:add|commit|push|merge|rebase)|docker\s+compose\s+up|"
                r"apply_migrations|write_text|write_bytes|unlink|rmtree)\b)",
                command,
            )
        )
    return False


def _is_known_read_or_orchestration(payload: Mapping[str, Any]) -> bool:
    tool = str(payload.get("tool_name") or payload.get("tool") or "").lower()
    leaf = re.split(r"[.:/]", tool)[-1]
    if tool in READ_TOOLS or leaf in READ_TOOLS:
        return True
    if tool in {"functions.exec", "exec", "request_user_input", "wait", "wait_agent"}:
        return True
    if tool.startswith("collaboration.") or tool.startswith("collaboration__"):
        return True
    if tool.startswith(("web", "read_mcp_resource", "list_mcp_", "view_image")):
        return True
    return bool(re.match(r"^(?:get|list|read|search|find|view|open|status|diff|screenshot)(?:_|$)", leaf))


def _requested_risk(payload: Mapping[str, Any], path: str | None) -> str:
    for container in (payload, payload.get("omni") if isinstance(payload.get("omni"), Mapping) else {}):
        value = container.get("risk") if isinstance(container, Mapping) else None
        if isinstance(value, str) and value.upper() in RISK_ORDER:
            return value.upper()
    tool_input = payload.get("tool_input")
    command = str(tool_input.get("command", "")) if isinstance(tool_input, Mapping) else ""
    tool = str(payload.get("tool_name") or payload.get("tool") or "")
    effects = payload.get("effect_kinds") or payload.get("effects") or []
    effect_text = effects if isinstance(effects, str) else " ".join(str(item) for item in effects)
    if re.search(
        r"(?i)(?:send|publish|delete|deploy|migrate|external[_-]?write)",
        f"{tool} {effect_text}",
    ):
        return "R3"
    if re.search(
        r"(?i)(?:Invoke-RestMethod\b[^\r\n]*(?:POST|PUT|PATCH|DELETE)|"
        r"curl\b[^\r\n]*(?:-X|--request)\s*(?:POST|PUT|PATCH|DELETE)|"
        r"psql\b[^\r\n]*\b(?:INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|TRUNCATE)\b)",
        command,
    ):
        return "R3"
    migration_verify = bool(
        re.search(r"(?i)apply_migrations", command)
        and re.search(r"(?i)(?:--dry-run|--verify)", command)
        and not re.search(r"(?i)(?:production|prod(?:uction)?[_-]?database|--execute|--apply)", command)
    )
    if re.search(r"(?i)\b(?:push|deploy|publish|drop\s+(?:database|table))\b", command) or (
        re.search(r"(?i)apply_migrations", command) and not migration_verify
    ):
        return "R3"
    if migration_verify:
        return "R2"
    if path and any(marker in path.lower() for marker in SENSITIVE_PATH_MARKERS):
        return "R2"
    return "R1" if _is_write(payload) else "R0"


def _shared_policy_risk(
    root: Path,
    payload: Mapping[str, Any],
    path: str | None,
) -> str | None:
    module = _load_module(root / "scripts" / "development_policy.py", "omni_development_policy")
    if module is None:
        return None
    classifier = getattr(module, "classify_change", None)
    if not callable(classifier):
        return None
    raw_effects = payload.get("effect_kinds") or payload.get("effects") or []
    if isinstance(raw_effects, str):
        raw_effects = [raw_effects]
    effects = [str(item) for item in raw_effects] if isinstance(raw_effects, Sequence) else []
    try:
        decision = classifier(
            [path] if path else [],
            effect_kinds=effects,
            read_only=not _is_write(payload),
            uncertain=_is_write(payload) and path is None,
        )
    except Exception:
        return None
    level = str(getattr(decision, "level", "")).upper()
    return level if level in RISK_ORDER else None


def _scope_delta_action(
    root: Path,
    contract: ContractView,
    path: str,
) -> tuple[str, str] | None:
    module = _load_module(root / "scripts" / "development_policy.py", "omni_development_policy")
    classifier = getattr(module, "classify_scope_delta", None) if module else None
    if not callable(classifier):
        return None
    try:
        decision = classifier(contract.risk, contract.paths, [path])
    except Exception:
        return None
    return str(getattr(decision, "action", "")), str(getattr(decision, "reason", ""))


def _path_matches(path: str, pattern: str) -> bool:
    pattern = pattern.replace("\\", "/")
    path = path.replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    while path.startswith("./"):
        path = path[2:]
    if not path or not pattern or ".." in path.split("/") or ".." in pattern.split("/"):
        return False
    pieces: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    pieces.append("(?:.*/)?")
                    index += 1
                else:
                    pieces.append(".*")
                continue
            pieces.append("[^/]*")
        elif char == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(char))
        index += 1
    return re.fullmatch("".join(pieces), path) is not None


def _contracts(root: Path) -> list[ContractView]:
    result: list[ContractView] = []
    for source in sorted((root / "docs" / "dev-changes").glob("*/impact.yaml")):
        data = _load_yaml(source)
        if not data:
            continue
        state = str(data.get("state", "UNKNOWN")).upper()
        if state in TERMINAL_STATES:
            continue
        risk_data = data.get("risk")
        risk = str(risk_data.get("level", "R1") if isinstance(risk_data, Mapping) else risk_data or "R1").upper()
        planned = data.get("planned_changes")
        paths: list[str] = []
        if isinstance(planned, Sequence) and not isinstance(planned, (str, bytes)):
            for change in planned:
                if not isinstance(change, Mapping):
                    continue
                values = change.get("paths")
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                    paths.extend(str(value).replace("\\", "/") for value in values)
        result.append(
            ContractView(
                change_id=str(data.get("change_id") or source.parent.name),
                risk=risk if risk in RISK_ORDER else "R1",
                state=state,
                # A contract always owns its own auditable state directory.
                # Without this implicit path, writing completion evidence would
                # make Stop deterministically block the contract that requested it.
                paths=tuple(paths + [f"docs/dev-changes/{str(data.get('change_id') or source.parent.name)}/**"]),
                source=source.relative_to(root).as_posix(),
            )
        )
    return result


def _select_contract(
    contracts: Sequence[ContractView], payload: Mapping[str, Any], path: str | None
) -> ContractView | None:
    requested = payload.get("change_id")
    omni = payload.get("omni")
    if not requested and isinstance(omni, Mapping):
        requested = omni.get("change_id")
    if requested:
        for contract in contracts:
            if contract.change_id == str(requested):
                return contract
    if path:
        matches = [c for c in contracts if any(_path_matches(path, p) for p in c.paths)]
        writable = [c for c in matches if c.state in WRITABLE_ACTIVE_STATES]
        if len(writable) == 1:
            return writable[0]
        if len(matches) == 1:
            return matches[0]
    writable = [c for c in contracts if c.state in WRITABLE_ACTIVE_STATES]
    if len(writable) == 1:
        return writable[0]
    return contracts[0] if len(contracts) == 1 else None


def _load_module(path: Path, name: str) -> Any | None:
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        # dataclasses and other runtime introspection resolve annotations via
        # sys.modules while the module is executing.
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(name, None)
        return None


def _call_public_conflict_api(
    root: Path, path: str, change_id: str | None
) -> LeaseView | None:
    """Use S1.5's public read-only conflict API when it is available.

    Several signatures are accepted during the staged rollout.  We never call
    alloc/release/cleanup methods from a hook.
    """

    module = _load_module(root / "scripts" / "runtime_allocation.py", "omni_runtime_allocation")
    if module is None:
        return None
    for name in ("resolve_path_conflict", "find_path_conflict", "check_path_conflict"):
        function = getattr(module, name, None)
        if not callable(function):
            continue
        attempts = (
            # The resolver itself is read-only; read_only=False describes the
            # pending tool action so an active foreign write lease conflicts.
            lambda: function(root=root, path=path, change_id=change_id, read_only=False),
            lambda: function(root, path, change_id),
            lambda: function(path=path, change_id=change_id),
        )
        for call in attempts:
            try:
                value = call()
            except TypeError:
                continue
            except Exception:
                return LeaseView(known=False, source=f"runtime_allocation.{name}")
            if asyncio.iscoroutine(value):
                return LeaseView(known=False, source=f"runtime_allocation.{name}:async")
            if value is None or value is False:
                return LeaseView(known=True, source=f"runtime_allocation.{name}")
            if isinstance(value, Mapping):
                return LeaseView(
                    known=bool(value.get("known", True)),
                    conflict=bool(value.get("conflict", True)),
                    owner=str(value.get("owner") or value.get("lease_owner") or "unknown"),
                    change_id=str(value.get("change_id") or "") or None,
                    expires_at=str(value.get("expires_at") or "") or None,
                    source=f"runtime_allocation.{name}",
                    stale=bool(value.get("stale", False)),
                )
            return LeaseView(
                known=True,
                conflict=True,
                owner=str(getattr(value, "owner", "unknown")),
                change_id=str(getattr(value, "change_id", "")) or None,
                expires_at=str(getattr(value, "expires_at", "")) or None,
                source=f"runtime_allocation.{name}",
                stale=bool(getattr(value, "stale", False)),
            )
    return None


def _git_common_dir(root: Path) -> Path | None:
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    candidate = Path(raw)
    return (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _iter_lease_records(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if any(key in value for key in ("paths", "path_globs", "path", "lease_owner")):
            yield value
        for key in ("leases", "workspace_leases", "allocations", "items"):
            child = value.get(key)
            if child is not None:
                yield from _iter_lease_records(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _iter_lease_records(child)


def _read_lease_store(root: Path, path: str, change_id: str | None) -> LeaseView:
    via_api = _call_public_conflict_api(root, path, change_id)
    if via_api is not None:
        return via_api
    common = _git_common_dir(root)
    candidates: list[Path] = []
    if common:
        candidates.extend(
            common / "omni-runtime" / name
            for name in ("workspace-leases.json", "leases.json", "allocations.json", "state.json")
        )
    candidates.extend(
        root / ".runtime" / name
        for name in ("workspace-leases.json", "leases.json", "allocations.json")
    )
    existing = [candidate for candidate in candidates if candidate.is_file()]
    if not existing:
        return LeaseView(known=False, source="allocation-store-missing")
    for source in existing:
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except Exception:
            return LeaseView(known=False, source=str(source))
        for record in _iter_lease_records(data):
            patterns = record.get("path_globs") or record.get("paths") or record.get("path") or []
            if isinstance(patterns, str):
                patterns = [patterns]
            if not isinstance(patterns, Sequence) or not any(
                _path_matches(path, str(pattern)) for pattern in patterns
            ):
                continue
            record_change = str(record.get("change_id") or "") or None
            if change_id and record_change == change_id:
                continue
            expires_at = record.get("expires_at")
            expires = _parse_time(expires_at)
            stale = expires is not None and expires <= _utc_now()
            return LeaseView(
                known=True,
                conflict=not stale,
                stale=stale,
                owner=str(record.get("owner") or record.get("lease_owner") or "unknown"),
                change_id=record_change,
                expires_at=str(expires_at or "") or None,
                source=str(source),
            )
    return LeaseView(known=True, source=str(existing[0]))


def _evaluate_write_target(
    payload: Mapping[str, Any],
    root: Path,
    path: str,
    risk: str,
    contracts: Sequence[ContractView],
    lease_resolver: Callable[[Path, str, str | None], LeaseView],
) -> GateResult:
    contract = _select_contract(contracts, payload, path)
    if contract is None:
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            risk,
            "contract_unknown",
            "No unique writable active development contract could be resolved.",
            path=path,
            repair="Create or select one locked impact contract before retrying.",
        )
    if contract.state not in WRITABLE_ACTIVE_STATES:
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            risk,
            "contract_not_writable",
            f"Contract {contract.change_id} is in non-writable state {contract.state}.",
            change_id=contract.change_id,
            path=path,
            repair="Use a uniquely selected contract in IMPACT_LOCKED, IMPLEMENTING, or VERIFYING state.",
        )
    if RISK_ORDER[risk] > RISK_ORDER.get(contract.risk, 1):
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            risk,
            "risk_escalation",
            f"Requested {risk} exceeds contract {contract.risk}.",
            change_id=contract.change_id,
            path=path,
            repair="Escalate and re-lock the contract with the required approval before retrying.",
        )
    lease = lease_resolver(root, path, contract.change_id)
    if lease.conflict:
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            risk,
            "active_lease_conflict",
            f"Path is leased by {lease.owner or 'another owner'}.",
            change_id=contract.change_id,
            path=path,
            lease_owner=lease.owner,
            repair="Coordinate with the active lease owner or wait for a verified release; do not clean it up from this hook.",
        )
    covered = any(_path_matches(path, pattern) for pattern in contract.paths)
    if not covered:
        delta = _scope_delta_action(root, contract, path)
        if delta and delta[0] == "block_risk_escalation":
            return GateResult(
                "PreToolUse",
                Decision.BLOCK,
                risk,
                "risk_escalation",
                delta[1] or "The shared policy classified the scope delta as a risk escalation.",
                change_id=contract.change_id,
                path=path,
                repair="Escalate and re-lock the contract before retrying the original write.",
            )
        return GateResult(
            "PreToolUse",
            Decision.REMEDIATE,
            risk,
            "contract_delta_required",
            (delta[1] if delta else "The target is outside the locked path set but does not raise risk."),
            change_id=contract.change_id,
            path=path,
            lease_owner=lease.owner,
            repair="Add the exact path and graph/test impact to the contract, reclassify it, then retry the original write.",
        )
    if not lease.known:
        if RISK_ORDER[risk] >= RISK_ORDER["R2"]:
            return GateResult(
                "PreToolUse",
                Decision.BLOCK,
                risk,
                "lease_unknown",
                "Workspace lease state is unavailable; it cannot be treated as conflict-free.",
                change_id=contract.change_id,
                path=path,
                repair="Restore the S1.5 read-only allocation resolver/store and retry.",
            )
        return GateResult(
            "PreToolUse",
            Decision.ALLOW,
            risk,
            "lease_unknown_warning",
            "Low-risk write is allowed with an unknown lease state.",
            change_id=contract.change_id,
            path=path,
            warnings=("Lease state is unknown; CI and Stop must verify ownership.",),
        )
    warnings = (
        (f"Ignored stale lease for {lease.owner or 'unknown owner'}; cleanup still requires owner verification.",)
        if lease.stale
        else ()
    )
    return GateResult(
        "PreToolUse",
        Decision.ALLOW,
        risk,
        "contract_and_lease_match",
        "Risk, path ownership, and lease checks passed.",
        change_id=contract.change_id,
        path=path,
        warnings=warnings,
    )


def evaluate_pre_tool(
    payload: Mapping[str, Any],
    root: Path,
    *,
    lease_resolver: Callable[[Path, str, str | None], LeaseView] = _read_lease_store,
) -> GateResult:
    if payload.get("_malformed_input"):
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            "R2",
            "malformed_hook_input",
            "PreToolUse input was not valid JSON and cannot be classified safely.",
            repair="Retry with a valid hook payload; do not infer read-only from malformed input.",
        )

    tool_value = payload.get("tool_name") or payload.get("tool")
    if not isinstance(tool_value, str) or not tool_value.strip():
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            "R2",
            "malformed_hook_input",
            "PreToolUse input is missing a valid tool name.",
            repair="Retry with the complete host hook payload.",
        )
    if tool_value.lower() in SHELL_TOOLS:
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, Mapping) or not isinstance(tool_input.get("command"), str) or not tool_input["command"].strip():
            return GateResult(
                "PreToolUse",
                Decision.BLOCK,
                "R2",
                "malformed_hook_input",
                "Shell hook input is missing a non-empty command.",
                repair="Retry with the complete host shell payload.",
            )

    shell = _analyze_shell(payload, root)
    extraction = _target_extraction(payload, root)
    targets = extraction.targets
    candidate_paths: tuple[str | None, ...] = tuple(targets) or (None,)
    heuristic_risks = [_requested_risk(payload, path) for path in candidate_paths]
    shared_risks = [_shared_policy_risk(root, payload, path) for path in candidate_paths]
    risk = max(
        (*heuristic_risks, *(level or "R0" for level in shared_risks)),
        key=lambda value: RISK_ORDER[value],
    )
    if shell and shell.intent == "unknown":
        risk = max(risk, "R1", key=lambda value: RISK_ORDER[value])
    if (root / "scripts" / "development_policy.py").is_file() and any(
        level is None for level in shared_risks
    ):
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            max(risk, "R2", key=lambda value: RISK_ORDER[value]),
            "development_policy_unknown",
            "The shared S1 risk classifier could not classify this tool action.",
            path=targets[0] if targets else None,
            repair="Run scripts/development_policy.py directly, resolve its deterministic input error, and retry.",
        )

    if shell and shell.intent == "unknown":
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            max(risk, "R2", key=lambda value: RISK_ORDER[value]),
            "shell_intent_unknown",
            shell.reason or "The shell command intent could not be classified safely.",
            path=targets[0] if targets else None,
            repair="Split the command into deterministic read-only or explicit-target write operations and retry.",
        )

    if shell and shell.intent == "read":
        return GateResult(
            "PreToolUse",
            Decision.ALLOW,
            risk,
            "read_only",
            "Read-only shell use is allowed.",
            path=targets[0] if targets else None,
        )

    is_write = shell.intent == "write" if shell else _is_write(payload)
    if not is_write:
        if not _is_known_read_or_orchestration(payload):
            return GateResult(
                "PreToolUse",
                Decision.BLOCK,
                max(risk, "R2", key=lambda value: RISK_ORDER[value]),
                "tool_intent_unknown",
                "Unknown tool intent cannot be assumed read-only.",
                repair="Provide deterministic effect metadata or add the tool to the reviewed read-only allowlist.",
            )
        return GateResult(
            "PreToolUse",
            Decision.ALLOW,
            risk,
            "read_only",
            "Read-only tool use is allowed.",
            path=targets[0] if targets else None,
        )
    if extraction.unresolved or (shell and not shell.complete):
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            risk,
            "target_invalid_or_incomplete",
            "At least one write target is invalid, ambiguous, or could not be normalized.",
            path=targets[0] if targets else None,
            repair="Use explicit repository-relative targets without traversal, drive, UNC, ADS, or reserved path segments.",
        )
    if not targets:
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            risk,
            "target_unknown",
            "The write target could not be determined.",
            repair="Use an explicit repository-relative target and retry.",
        )

    contracts = _contracts(root)
    results = [
        _evaluate_write_target(payload, root, path, risk, contracts, lease_resolver)
        for path in targets
    ]
    if len(results) == 1:
        return results[0]
    change_ids = {result.change_id for result in results if result.change_id}
    if len(change_ids) > 1:
        return GateResult(
            "PreToolUse",
            Decision.BLOCK,
            risk,
            "multi_contract_write",
            "One tool action cannot atomically write targets owned by different contracts.",
            path=targets[0],
            repair="Split the action by owning contract and retry each write independently.",
        )
    for decision in (Decision.BLOCK, Decision.REMEDIATE):
        for result in results:
            if result.decision is decision:
                return result
    warnings = tuple(warning for result in results for warning in result.warnings)
    first = results[0]
    return GateResult(
        "PreToolUse",
        Decision.ALLOW,
        risk,
        "contract_and_lease_match",
        f"Risk, path ownership, and lease checks passed for {len(targets)} target(s).",
        change_id=first.change_id,
        path=first.path,
        lease_owner=first.lease_owner,
        warnings=warnings,
    )


def _session_start(root: Path, timeout_seconds: float) -> GateResult:
    messages: list[str] = []
    deadline = time.monotonic() + timeout_seconds
    checks = (
        ("agent-policy", [sys.executable, "-B", str(root / "scripts" / "check_agent_policy.py"), "--hook"]),
        (
            "development-readiness",
            [sys.executable, "-B", str(root / "scripts" / "check_development_readiness.py"), "--hook", "--runtime"],
        ),
    )
    for name, command in checks:
        remaining = max(0.01, deadline - time.monotonic())
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                input="{}",
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=remaining,
                check=False,
            )
        except subprocess.TimeoutExpired:
            messages.append(f"{name}=unknown(timeout)")
            continue
        except OSError as exc:
            messages.append(f"{name}=unknown({type(exc).__name__})")
            continue
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        if completed.returncode != 0:
            messages.append(
                f"{name}=unknown(exit={completed.returncode},output={_fingerprint(output)})"
            )
            continue
        try:
            json.loads(completed.stdout or "{}")
            messages.append(f"{name}=ok")
        except (json.JSONDecodeError, AttributeError):
            messages.append(f"{name}=ok(unstructured,output={_fingerprint(output)})")
    issue = "session_context_ready" if not any("unknown(" in m for m in messages) else "session_context_partial"
    return GateResult(
        "SessionStart",
        Decision.ALLOW,
        "R0",
        issue,
        "\n".join(messages) or "No session checks were available.",
        warnings=tuple(m for m in messages if "unknown(" in m),
    )


def _changed_paths(root: Path) -> list[str]:
    commands = (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    )
    result: set[str] = set()
    for command in commands:
        try:
            output = subprocess.check_output(command, cwd=root, text=True, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            continue
        result.update(line.strip().replace("\\", "/") for line in output.splitlines() if line.strip())
    return sorted(result)


def evaluate_stop(
    payload: Mapping[str, Any],
    root: Path,
    *,
    timeout_seconds: float = 20.0,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> GateResult:
    if payload.get("stop_hook_active") or os.environ.get("OMNI_STOP_HOOK_ACTIVE") == "1":
        return GateResult(
            "Stop",
            Decision.ALLOW,
            "R0",
            "recursion_guard",
            "Stop validation is already active; recursion was suppressed.",
        )
    paths = payload.get("changed_paths")
    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
        paths = _changed_paths(root)
    paths = [str(path).replace("\\", "/") for path in paths]
    contracts = [
        contract for contract in _contracts(root) if contract.state in WRITABLE_ACTIVE_STATES
    ]
    uncovered = [
        path for path in paths if not any(any(_path_matches(path, p) for p in contract.paths) for contract in contracts)
    ]
    if uncovered:
        return GateResult(
            "Stop",
            Decision.BLOCK,
            "R2",
            "deterministic_scope_gap",
            f"Changed paths are outside every active contract: {', '.join(uncovered[:5])}",
            path=uncovered[0],
            repair="Update and re-lock the owning contract, then run the required verification.",
        )
    command = [sys.executable, "-B", str(root / "scripts" / "check_feature_contracts.py"), "--mode", "worktree"]
    env = dict(os.environ)
    env["OMNI_STOP_HOOK_ACTIVE"] = "1"
    try:
        completed = command_runner(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return GateResult(
            "Stop",
            Decision.BLOCK,
            "R2",
            "verification_timeout",
            "Minimal contract verification timed out and is unknown.",
            repair="Run the contract verifier directly, resolve the timeout, and retry Stop.",
        )
    except OSError as exc:
        return GateResult(
            "Stop",
            Decision.BLOCK,
            "R2",
            "verification_unavailable",
            f"Minimal contract verification is unavailable: {type(exc).__name__}.",
            repair="Restore the verifier and run it directly before completion.",
        )
    if completed.returncode != 0:
        detail = (completed.stdout + "\n" + completed.stderr).strip()
        return GateResult(
            "Stop",
            Decision.BLOCK,
            "R2",
            "verification_failed",
            (
                f"Contract verifier exited {completed.returncode}; "
                f"output={_fingerprint(detail)}."
            ),
            repair="Resolve the deterministic verifier findings and retry Stop.",
        )
    return GateResult(
        "Stop",
        Decision.ALLOW,
        "R2",
        "minimal_verification_passed",
        "Active contract coverage and deterministic evidence checks passed.",
    )


def _output(result: GateResult) -> dict[str, Any]:
    message = _sanitize_hook_text(
        f"[{result.decision.value}] {result.issue_code}: {result.reason}"
    )
    if result.repair:
        message += _sanitize_hook_text(f" Repair: {result.repair}")
    if result.event == "SessionStart":
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
            },
        }
    if result.event == "PreToolUse":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if result.allowed else "deny",
                "permissionDecisionReason": message,
            },
        }
    payload: dict[str, Any] = {}
    if not result.allowed:
        payload = {"decision": "block", "reason": message}
    return payload


def _read_input() -> Mapping[str, Any]:
    try:
        raw = sys.stdin.read()
        value = json.loads(raw or "{}")
        if not isinstance(value, Mapping):
            return {"_malformed_input": True, "_input_error": "json_root_not_object"}
        return value
    except OSError:
        return {"_malformed_input": True, "_input_error": "stdin_unavailable"}
    except json.JSONDecodeError:
        return {"_malformed_input": True, "_input_error": "invalid_json"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", choices=("SessionStart", "PreToolUse", "Stop"))
    parser.add_argument("--root")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    payload = _read_input()
    event = args.event or str(payload.get("hook_event_name") or payload.get("hookEventName") or "SessionStart")
    root = _repo_root(args.root)
    if event == "PreToolUse":
        result = evaluate_pre_tool(payload, root)
    elif event == "Stop":
        result = evaluate_stop(payload, root, timeout_seconds=args.timeout)
    else:
        result = _session_start(root, args.timeout)
    print(json.dumps(_output(result), ensure_ascii=False))
    # Hook protocol decisions live in JSON.  Keeping process exit zero prevents
    # host-specific fail-open/fail-closed differences.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
