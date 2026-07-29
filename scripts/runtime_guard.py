#!/usr/bin/env python3
"""Read-only runtime ownership and source-truth guard for Omni.

The guard never starts/stops containers and never writes a database.  It uses
Docker/Git inspection plus TCP/HTTP probes to fail closed when a runtime cannot
be tied to one worktree, source fingerprint, and set of writable resources.

The YAML manifest is deliberately JSON-compatible so this safety check has no
third-party parser dependency (JSON is a valid YAML 1.2 subset).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config" / "runtime-manifest.yaml"
TRUE_VALUES = {"1", "true", "yes", "on", "enabled", "owner"}
FALSE_VALUES = {"0", "false", "no", "off", "disabled", "none"}
HOST_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?!/))")
SECRET_RE = re.compile(r"(?i)(?:password|passwd|pwd|token|secret)=([^\s&]+)")


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    message: str
    containers: tuple[str, ...] = ()
    resource: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["containers"] = list(self.containers)
        return {key: value for key, value in data.items() if value not in (None, [], ())}


@dataclass
class ContainerFact:
    container_id: str
    name: str
    service: str
    project: str
    state: str
    image: str
    runtime_id: str
    source_commit: str
    source_fingerprint: str
    scheduler_role: str
    worktree: str
    declared_worktree: str
    ports: set[int] = field(default_factory=set)
    database_resources: set[str] = field(default_factory=set)
    writable_resources: set[str] = field(default_factory=set)
    scheduler_enabled: bool = False
    read_only_database: bool = False
    health_status: str = ""

    @property
    def ref(self) -> str:
        return f"{self.name}#{self.container_id[:12]}"

    @property
    def worktree_ref(self) -> str:
        if not self.worktree:
            return "unknown"
        leaf = self.worktree.rstrip("/").split("/")[-1] or "root"
        digest = hashlib.sha256(self.worktree.encode("utf-8")).hexdigest()[:8]
        return f"{leaf}#{digest}"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "id": self.container_id[:12],
            "name": self.name,
            "service": self.service,
            "project": self.project,
            "state": self.state,
            "image": self.image,
            "runtime_id": self.runtime_id or None,
            "source_commit": self.source_commit or None,
            "source_fingerprint": self.source_fingerprint or None,
            "scheduler_role": self.scheduler_role or None,
            "worktree_ref": self.worktree_ref,
            "ports": sorted(self.ports),
            "database_resources": sorted(self.database_resources),
            "writable_resources": sorted(self.writable_resources),
            "scheduler_enabled": self.scheduler_enabled,
            "read_only_database": self.read_only_database,
            "health_status": self.health_status or None,
        }


class GuardFailure(RuntimeError):
    pass


def _run(args: Sequence[str], *, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        safe_detail = detail[-1][:300] if detail else f"exit {proc.returncode}"
        safe_detail = SECRET_RE.sub(lambda m: m.group(0).split("=", 1)[0] + "=<redacted>", safe_detail)
        raise GuardFailure(f"command failed ({args[0]}): {safe_detail}")
    return proc.stdout


def _is_host_absolute(value: str) -> bool:
    if "://" in value:
        return False
    return bool(HOST_ABSOLUTE_RE.match(value.strip())) or value.strip().startswith("~")


def find_host_absolute_values(value: Any, prefix: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            found.extend(find_host_absolute_values(child, f"{prefix}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_host_absolute_values(child, f"{prefix}[{index}]"))
    elif isinstance(value, str) and _is_host_absolute(value):
        found.append(prefix)
    return found


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GuardFailure(f"runtime manifest missing: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise GuardFailure(f"runtime manifest must be JSON-compatible YAML: line {exc.lineno}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise GuardFailure("runtime manifest schema_version must be 1")
    for key in ("canonical_runtime", "identity_labels", "services"):
        if not isinstance(manifest.get(key), dict) or not manifest[key]:
            raise GuardFailure(f"runtime manifest requires non-empty {key}")
    absolute = find_host_absolute_values(manifest)
    if absolute:
        raise GuardFailure("runtime manifest contains host-absolute paths at " + ", ".join(absolute))
    return manifest


def normalize_worktree(value: str) -> str:
    text = (value or "").strip().replace("\\", "/")
    match = re.match(r"^/run/desktop/mnt/host/([A-Za-z])/(.*)$", text, re.IGNORECASE)
    if match:
        text = f"{match.group(1)}:/{match.group(2)}"
    text = re.sub(r"/+", "/", text).rstrip("/")
    return text.casefold()


def connection_identity(value: str, *, kind: str = "db") -> str:
    """Return a stable credential-free identity; never return connection text."""
    raw = (value or "").strip()
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.split("+", 1)[0].lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port or 0
        path = parsed.path.strip("/").lower()
        canonical = f"{scheme}|{host}|{port}|{path}"
    except (TypeError, ValueError):
        without_credentials = re.sub(r"(?<=://).*@", "", raw)
        canonical = SECRET_RE.sub(lambda m: m.group(0).split("=", 1)[0], without_credentials)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


def _bool_value(value: str) -> bool | None:
    normalized = (value or "").strip().casefold()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _env_map(raw_env: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in raw_env:
        if "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    return result


def _infer_worktree(raw: Mapping[str, Any], labels: Mapping[str, str], declared: str) -> str:
    if declared:
        return normalize_worktree(declared)
    compose_root = labels.get("com.docker.compose.project.working_dir", "")
    if compose_root:
        return normalize_worktree(compose_root)
    for mount in raw.get("Mounts") or []:
        if mount.get("Destination") == "/workspace" and mount.get("Source"):
            return normalize_worktree(str(mount["Source"]))
    return ""


def container_from_inspect(raw: Mapping[str, Any], manifest: Mapping[str, Any]) -> ContainerFact:
    config = raw.get("Config") or {}
    state = raw.get("State") or {}
    labels = {str(k): str(v) for k, v in (config.get("Labels") or {}).items()}
    env = _env_map(config.get("Env") or [])
    identity = manifest["identity_labels"]
    name = str(raw.get("Name") or "unknown").lstrip("/")
    service = labels.get("com.docker.compose.service", "") or name
    declared_worktree = labels.get(identity["worktree"], "")
    worktree = _infer_worktree(raw, labels, declared_worktree)

    ports: set[int] = set()
    for bindings in ((raw.get("NetworkSettings") or {}).get("Ports") or {}).values():
        for binding in bindings or []:
            try:
                ports.add(int(binding.get("HostPort")))
            except (TypeError, ValueError):
                continue

    db_resources: set[str] = set()
    for key in manifest.get("database", {}).get("connection_env", []):
        if env.get(key):
            db_resources.add(connection_identity(env[key], kind="db"))
    read_only = _bool_value(env.get(manifest.get("database", {}).get("read_only_env", ""), "")) is True

    target_tokens = {
        str(item).strip("/").casefold() for item in manifest.get("writable_mount_targets", [])
    }
    writable: set[str] = set()
    for mount in raw.get("Mounts") or []:
        if not bool(mount.get("RW")):
            continue
        mount_type = str(mount.get("Type") or "")
        destination = str(mount.get("Destination") or "").strip("/").casefold()
        if mount_type == "volume" and mount.get("Name"):
            writable.add(f"volume:{mount['Name']}")
        elif mount_type == "bind" and any(
            destination == token or destination.startswith(token + "/") for token in target_tokens
        ):
            source = normalize_worktree(str(mount.get("Source") or ""))
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
            writable.add(f"bind:{digest}")

    role = labels.get(identity["scheduler_role"], "")
    role_value = _bool_value(role)
    scheduler_enabled = role_value is True
    implicit = set(manifest.get("scheduler", {}).get("implicit_services", []))
    service_cfg = manifest.get("services", {}).get(service, {})
    if role_value is None and (service in implicit or service_cfg.get("scheduler_default") is True):
        scheduler_enabled = True
    elif role_value is None:
        scheduler_values = [
            _bool_value(env.get(key, "")) for key in manifest.get("scheduler", {}).get("enable_env", [])
        ]
        scheduler_enabled = any(value is True for value in scheduler_values)

    health = state.get("Health") or {}
    return ContainerFact(
        container_id=str(raw.get("Id") or ""),
        name=name,
        service=service,
        project=labels.get("com.docker.compose.project", ""),
        state=str(state.get("Status") or "unknown"),
        image=str(config.get("Image") or raw.get("Image") or ""),
        runtime_id=labels.get(identity["runtime_id"], ""),
        source_commit=labels.get(identity["source_commit"], "") or labels.get("io.omni.source_commit", ""),
        source_fingerprint=labels.get(identity["source_fingerprint"], ""),
        scheduler_role=role,
        worktree=worktree,
        declared_worktree=normalize_worktree(declared_worktree),
        ports=ports,
        database_resources=db_resources,
        writable_resources=writable,
        scheduler_enabled=scheduler_enabled,
        read_only_database=read_only,
        health_status=str(health.get("Status") or ""),
    )


def inspect_running_containers(manifest: Mapping[str, Any]) -> list[ContainerFact]:
    ids = [item for item in _run(["docker", "ps", "-q"]).splitlines() if item.strip()]
    if not ids:
        return []
    raw = json.loads(_run(["docker", "inspect", *ids]))
    return [container_from_inspect(item, manifest) for item in raw]


def primary_worktree(repo_root: Path) -> str:
    output = _run(["git", "worktree", "list", "--porcelain"], cwd=repo_root)
    for line in output.splitlines():
        if line.startswith("worktree "):
            return normalize_worktree(line.removeprefix("worktree "))
    return normalize_worktree(str(repo_root))


def source_commit(repo_root: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], cwd=repo_root).strip()


def source_fingerprint(repo_root: Path, paths: Sequence[str]) -> str:
    selected = [str(path) for path in paths]
    if not selected:
        return ""
    output = _run(
        ["git", "ls-files", "-co", "--exclude-standard", "--", *selected],
        cwd=repo_root,
    )
    digest = hashlib.sha256()
    digest.update(source_commit(repo_root).encode("ascii", errors="ignore"))
    for relative in sorted(set(line.strip() for line in output.splitlines() if line.strip())):
        path = (repo_root / relative).resolve()
        try:
            path.relative_to(repo_root.resolve())
        except ValueError:
            continue
        if not path.is_file():
            continue
        digest.update(relative.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def expected_identity(repo_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    fingerprints: dict[str, str] = {}
    for service, cfg in manifest.get("services", {}).items():
        fingerprints[service] = source_fingerprint(repo_root, cfg.get("source_paths", []))
    return {
        "commit": source_commit(repo_root),
        "worktree": normalize_worktree(str(repo_root.resolve())),
        "primary_worktree": primary_worktree(repo_root),
        "fingerprints": fingerprints,
    }


def _issue(
    code: str,
    message: str,
    containers: Iterable[ContainerFact] = (),
    *,
    resource: str | None = None,
    severity: str = "error",
) -> Issue:
    refs = tuple(sorted(container.ref for container in containers))
    return Issue(code=code, severity=severity, message=message, containers=refs, resource=resource)


def _relevant_containers(
    containers: Sequence[ContainerFact], manifest: Mapping[str, Any]
) -> list[ContainerFact]:
    service_names = set(manifest.get("services", {}))
    project = str(manifest.get("canonical_runtime", {}).get("compose_project", ""))
    expected_ports = {
        int(port)
        for cfg in manifest.get("services", {}).values()
        for port in cfg.get("published_ports", [])
    }
    return [
        item
        for item in containers
        if item.state == "running"
        and (item.service in service_names or item.project == project or bool(item.ports & expected_ports))
    ]


def _shared_resource_issues(containers: Sequence[ContainerFact]) -> list[Issue]:
    issues: list[Issue] = []

    database_groups: dict[str, list[ContainerFact]] = {}
    for container in containers:
        if container.read_only_database:
            continue
        for resource in container.database_resources:
            database_groups.setdefault(resource, []).append(container)
    for resource, group in database_groups.items():
        worktrees = {item.worktree or f"unknown:{item.ref}" for item in group}
        if len(group) > 1 and len(worktrees) > 1:
            issues.append(
                _issue(
                    "cross_worktree_writable_database",
                    "different worktrees share one writable database identity",
                    group,
                    resource=resource,
                )
            )
            schedulers = [item for item in group if item.scheduler_enabled]
            scheduler_worktrees = {item.worktree or f"unknown:{item.ref}" for item in schedulers}
            if len(schedulers) > 1 and len(scheduler_worktrees) > 1:
                issues.append(
                    _issue(
                        "cross_worktree_scheduler",
                        "scheduler-capable containers from different worktrees share one database",
                        schedulers,
                        resource=resource,
                    )
                )

    volume_groups: dict[str, list[ContainerFact]] = {}
    for container in containers:
        for resource in container.writable_resources:
            volume_groups.setdefault(resource, []).append(container)
    for resource, group in volume_groups.items():
        worktrees = {item.worktree or f"unknown:{item.ref}" for item in group}
        if len(group) > 1 and len(worktrees) > 1:
            issues.append(
                _issue(
                    "cross_worktree_writable_volume",
                    "different worktrees share one writable volume or protected bind mount",
                    group,
                    resource=resource,
                )
            )
    return issues


def _port_is_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def analyze_runtime(
    containers: Sequence[ContainerFact],
    manifest: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    runtime_id: str,
    check_unknown_listeners: bool = True,
    require_services: bool = False,
) -> list[Issue]:
    relevant = _relevant_containers(containers, manifest)
    issues = _shared_resource_issues(relevant)
    labels = manifest["identity_labels"]

    for container in relevant:
        if not container.runtime_id:
            issues.append(
                _issue("missing_runtime_identity", f"{container.ref} has no {labels['runtime_id']} label", [container])
            )
        if not container.source_commit:
            issues.append(
                _issue("missing_source_commit", f"{container.ref} has no immutable source revision", [container])
            )
        if not container.source_fingerprint:
            issues.append(
                _issue("missing_source_fingerprint", f"{container.ref} has no source/build fingerprint", [container])
            )
        if not container.declared_worktree:
            issues.append(
                _issue("missing_worktree_identity", f"{container.ref} has no declared worktree identity", [container])
            )
        if container.scheduler_enabled and not container.scheduler_role:
            issues.append(
                _issue("missing_scheduler_identity", f"{container.ref} can schedule writes but has no scheduler role", [container])
            )

        if container.runtime_id == runtime_id:
            if container.source_commit and container.source_commit != expected.get("commit"):
                issues.append(
                    _issue("source_commit_mismatch", f"{container.ref} source revision does not match this checkout", [container])
                )
            expected_fp = expected.get("fingerprints", {}).get(container.service, "")
            if expected_fp and container.source_fingerprint and container.source_fingerprint != expected_fp:
                issues.append(
                    _issue("source_fingerprint_mismatch", f"{container.ref} source/build fingerprint is stale", [container])
                )
            if container.declared_worktree and container.declared_worktree != expected.get("worktree"):
                issues.append(
                    _issue("worktree_identity_mismatch", f"{container.ref} declares another worktree", [container])
                )

    expected_port_owner: dict[int, str] = {}
    for service, cfg in manifest.get("services", {}).items():
        for port in cfg.get("published_ports", []):
            expected_port_owner[int(port)] = service
    for port, service in expected_port_owner.items():
        owners = [item for item in relevant if port in item.ports]
        for owner in owners:
            if owner.service != service or (owner.runtime_id and owner.runtime_id != runtime_id):
                issues.append(
                    _issue(
                        "wrong_port_owner",
                        f"host port {port} is owned by service/runtime {owner.service}/{owner.runtime_id or 'unidentified'}",
                        [owner],
                        resource=f"port:{port}",
                    )
                )
            elif not owner.runtime_id:
                issues.append(
                    _issue(
                        "port_owner_identity_missing",
                        f"host port {port} owner cannot prove runtime identity",
                        [owner],
                        resource=f"port:{port}",
                    )
                )
        if not owners and check_unknown_listeners and _port_is_listening(port):
            issues.append(
                Issue(
                    code="unknown_port_owner",
                    severity="error",
                    message=f"host port {port} is listening but no inspected Docker owner matches",
                    resource=f"port:{port}",
                )
            )

    if require_services:
        for service, cfg in manifest.get("services", {}).items():
            if not cfg.get("required"):
                continue
            matches = [item for item in relevant if item.service == service]
            if not matches:
                issues.append(
                    Issue(
                        code="required_service_missing",
                        severity="error",
                        message=f"required service {service} is not running",
                    )
                )
    return sorted(issues, key=lambda item: (item.severity, item.code, item.containers))


def scan_static(repo_root: Path, manifest: Mapping[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    compose_files = [repo_root / item for item in manifest.get("compose_files", [])]
    identity_tokens = list(manifest.get("identity_labels", {}).values())
    for path in compose_files:
        if not path.is_file():
            issues.append(
                Issue("compose_file_missing", "error", f"declared Compose file is missing: {path.name}")
            )
            continue
        text = path.read_text(encoding="utf-8")
        fixed_count = len(re.findall(r"(?m)^\s*container_name\s*:", text))
        if fixed_count:
            issues.append(
                Issue(
                    "fixed_container_names",
                    "error",
                    f"{path.relative_to(repo_root).as_posix()} has {fixed_count} fixed container names",
                )
            )
        if path.name == "docker-compose.yml":
            missing = [token for token in identity_tokens if token not in text]
            if missing:
                issues.append(
                    Issue(
                        "compose_identity_labels_missing",
                        "error",
                        f"canonical Compose omits {len(missing)} required runtime identity labels",
                    )
                )
    return sorted(issues, key=lambda item: (item.severity, item.code, item.message))


def preflight_policy_issues(
    repo_root: Path, manifest: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[Issue]:
    """Return static and worktree-policy failures that must block a start."""
    issues = scan_static(repo_root, manifest)
    policy = manifest.get("worktree_defaults", {})
    if (
        policy.get("long_lived_runtime") == "deny"
        and expected.get("worktree") != expected.get("primary_worktree")
    ):
        issues.append(
            Issue(
                code="non_primary_long_lived_runtime",
                severity="error",
                message="a non-primary worktree may only use an explicitly isolated disposable runtime",
            )
        )
    return sorted(issues, key=lambda item: (item.severity, item.code, item.message))


def _health_issues(
    containers: Sequence[ContainerFact], manifest: Mapping[str, Any], timeout: float
) -> list[Issue]:
    issues: list[Issue] = []
    opener = build_opener(ProxyHandler({}))
    for service, cfg in manifest.get("services", {}).items():
        if not cfg.get("required"):
            continue
        matches = [item for item in containers if item.state == "running" and item.service == service]
        if not matches:
            continue
        health = cfg.get("health") or {}
        kind = health.get("kind")
        if kind == "docker":
            if not any(item.health_status == "healthy" for item in matches):
                issues.append(
                    _issue("service_unhealthy", f"required service {service} lacks healthy Docker state", matches)
                )
        elif kind == "http":
            ports = [int(item) for item in cfg.get("published_ports", [])]
            path = str(health.get("path") or "").strip("/")
            ok = False
            for port in ports:
                url = f"http://127.0.0.1:{port}/" + path
                try:
                    with opener.open(url, timeout=timeout) as response:
                        if 200 <= int(response.status) < 300:
                            ok = True
                            break
                except Exception:
                    continue
            if not ok:
                issues.append(
                    _issue("service_unhealthy", f"required service {service} failed its HTTP readiness probe", matches)
                )
    return issues


def _report(
    command: str,
    runtime_id: str,
    containers: Sequence[ContainerFact],
    issues: Sequence[Issue],
    expected: Mapping[str, Any] | None,
) -> dict[str, Any]:
    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    repository = None
    if expected:
        repository = {
            "source_commit": expected.get("commit"),
            "worktree_ref": _worktree_ref(str(expected.get("worktree") or "")),
            "is_primary_worktree": expected.get("worktree") == expected.get("primary_worktree"),
            "service_fingerprints": expected.get("fingerprints", {}),
        }
    return {
        "schema_version": 1,
        "command": command,
        "ok": errors == 0,
        "read_only": True,
        "runtime_id": runtime_id,
        "summary": {
            "containers": len(containers),
            "errors": errors,
            "warnings": warnings,
        },
        "repository": repository,
        "containers": [item.safe_dict() for item in sorted(containers, key=lambda item: item.name)],
        "issues": [issue.to_dict() for issue in issues],
    }


def _worktree_ref(value: str) -> str:
    normalized = normalize_worktree(value)
    if not normalized:
        return "unknown"
    leaf = normalized.rstrip("/").split("/")[-1] or "root"
    return f"{leaf}#{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:8]}"


def emit(report: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return
    summary = report["summary"]
    status = "PASS" if report["ok"] else "BLOCKED"
    print(
        f"[runtime-guard] {status} command={report['command']} runtime={report['runtime_id']} "
        f"containers={summary['containers']} errors={summary['errors']} warnings={summary['warnings']}"
    )
    for container in report.get("containers", []):
        print(
            "  container "
            f"{container['name']} service={container['service']} state={container['state']} "
            f"runtime={container.get('runtime_id') or 'unidentified'} "
            f"worktree={container['worktree_ref']} ports={container['ports']}"
        )
    for issue in report.get("issues", []):
        suffix = f" containers={','.join(issue.get('containers', []))}" if issue.get("containers") else ""
        resource = f" resource={issue['resource']}" if issue.get("resource") else ""
        print(f"  {issue['severity'].upper()} {issue['code']}: {issue['message']}{resource}{suffix}")


def _common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--runtime-id", default="")
    parser.add_argument("--json", action="store_true", dest="as_json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Omni runtime ownership guard")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("static", "audit", "preflight"):
        child = sub.add_parser(name)
        _common_args(child)
    verify = sub.add_parser("verify")
    _common_args(verify)
    verify.add_argument("--skip-health", action="store_true")
    verify.add_argument("--health-timeout", type=float, default=2.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest.resolve())
        repo_root = args.repo_root.resolve()
        runtime_id = args.runtime_id or manifest["canonical_runtime"]["runtime_id"]
        if args.command == "static":
            issues = scan_static(repo_root, manifest)
            report = _report("static", runtime_id, [], issues, None)
            emit(report, as_json=args.as_json)
            return 0 if report["ok"] else 2

        expected = expected_identity(repo_root, manifest)
        containers = inspect_running_containers(manifest)
        require_services = args.command == "verify"
        issues = analyze_runtime(
            containers,
            manifest,
            expected,
            runtime_id=runtime_id,
            require_services=require_services,
        )
        if args.command == "preflight":
            issues.extend(preflight_policy_issues(repo_root, manifest, expected))
            issues = sorted(issues, key=lambda item: (item.severity, item.code, item.containers))
        if args.command == "verify" and not args.skip_health:
            issues.extend(_health_issues(containers, manifest, args.health_timeout))
            issues = sorted(issues, key=lambda item: (item.severity, item.code, item.containers))
        report = _report(args.command, runtime_id, containers, issues, expected)
        emit(report, as_json=args.as_json)
        if args.command == "audit":
            return 0
        return 0 if report["ok"] else 2
    except GuardFailure as exc:
        report = {
            "schema_version": 1,
            "command": getattr(args, "command", "unknown"),
            "ok": False,
            "read_only": True,
            "runtime_id": getattr(args, "runtime_id", "") or "unknown",
            "summary": {"containers": 0, "errors": 1, "warnings": 0},
            "repository": None,
            "containers": [],
            "issues": [Issue("guard_unavailable", "error", str(exc)).to_dict()],
        }
        emit(report, as_json=getattr(args, "as_json", False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
