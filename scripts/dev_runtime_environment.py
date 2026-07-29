#!/usr/bin/env python3
"""Launch host-mode dev processes with one isolated RuntimeAllocation environment.

The launcher never prints connection strings or credentials.  It emits only a
child PID; callers can therefore use it from PowerShell without serializing
secrets through stdout or command-line arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import quote


class DevEnvironmentError(RuntimeError):
    """The allocated host-service environment is incomplete or unsafe."""


PORT_ENV = {
    "identity": "IDENTITY_SERVICE_PORT",
    "hub": "AI_PROVIDER_HUB_PORT",
    "knowledge": "KNOWLEDGE_ENGINE_PORT",
    "news": "NEWS_AGGREGATOR_PORT",
    "video": "VIDEO_ANALYSIS_PORT",
    "livestream": "LIVESTREAM_ANALYSIS_PORT",
    "ad_review": "AD_REVIEW_PORT",
    "scout": "SCOUT_AGENT_PORT",
    "frontend": "FRONTEND_PORT",
    "postgres": "POSTGRES_PORT",
    "redis": "REDIS_PORT",
}

DATABASE_SCHEMES = {
    "identity-service": "postgresql+asyncpg",
    "news-aggregator": "postgresql+asyncpg",
    "video-analysis": "postgresql",
    "livestream-analysis": "postgresql",
    "ad-review-service": "postgresql",
    "scout-agent": "postgresql",
}

REDIS_DATABASES = {
    "identity-service": 3,
    "news-aggregator": 2,
}

ALLOWED_SERVICES = frozenset((*DATABASE_SCHEMES, "frontend"))


def _required(source: Mapping[str, str], name: str) -> str:
    value = str(source.get(name, "")).strip()
    if not value:
        raise DevEnvironmentError(f"required allocated environment is missing: {name}")
    return value


def _port(source: Mapping[str, str], name: str) -> int:
    raw = _required(source, PORT_ENV[name])
    try:
        value = int(raw)
    except ValueError as exc:
        raise DevEnvironmentError(f"allocated port is invalid: {PORT_ENV[name]}") from exc
    if not 1 <= value <= 65535:
        raise DevEnvironmentError(f"allocated port is invalid: {PORT_ENV[name]}")
    return value


def _absolute_file_path(source: Mapping[str, str], name: str) -> str:
    value = _required(source, name)
    if not Path(value).is_absolute():
        raise DevEnvironmentError(f"allocated secret file path is not absolute: {name}")
    return value


def build_service_environment(
    service: str, source: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Build a child environment bound only to allocated host endpoints."""

    if service not in ALLOWED_SERVICES:
        raise DevEnvironmentError(f"unsupported host dev service: {service}")
    inherited = dict(os.environ if source is None else source)
    if _required(inherited, "OMNI_DATABASE_DISPOSABLE").casefold() != "true":
        raise DevEnvironmentError("host dev processes require a disposable RuntimeAllocation")
    for identity_key in (
        "OMNI_ALLOCATION_ID",
        "OMNI_RUNTIME_ID",
        "OMNI_WORKTREE_ID",
        "OMNI_SOURCE_FINGERPRINT",
    ):
        _required(inherited, identity_key)

    ports = {name: _port(inherited, name) for name in PORT_ENV}
    loopback = "127.0.0.1"
    urls = {
        "IDENTITY_SERVICE_URL": f"http://{loopback}:{ports['identity']}",
        "AI_PROVIDER_HUB_URL": f"http://{loopback}:{ports['hub']}",
        "KNOWLEDGE_ENGINE_URL": f"http://{loopback}:{ports['knowledge']}",
        "NEWS_AGGREGATOR_URL": f"http://{loopback}:{ports['news']}",
        "VIDEO_ANALYSIS_SERVICE_URL": f"http://{loopback}:{ports['video']}",
        "LIVESTREAM_ANALYSIS_SERVICE_URL": f"http://{loopback}:{ports['livestream']}",
        "AD_REVIEW_SERVICE_URL": f"http://{loopback}:{ports['ad_review']}",
        "SCOUT_AGENT_URL": f"http://{loopback}:{ports['scout']}",
    }
    environment = {**inherited, **urls}
    environment.update(
        {
            "AI_HUB_URL": urls["AI_PROVIDER_HUB_URL"],
            "VIDEO_ANALYSIS_URL": urls["VIDEO_ANALYSIS_SERVICE_URL"],
            "SP3_BASE_URL": urls["AI_PROVIDER_HUB_URL"],
            "SP4_BASE_URL": urls["KNOWLEDGE_ENGINE_URL"],
            "OMNI_KE_URL": urls["KNOWLEDGE_ENGINE_URL"],
            "NEXT_PUBLIC_OPENAI_BASE_URL": urls["AI_PROVIDER_HUB_URL"] + "/v1",
            "NEXT_PUBLIC_OMNI_API_BASE_URL": f"http://{loopback}:{ports['frontend']}",
        }
    )

    if service in DATABASE_SCHEMES:
        user = quote(str(inherited.get("POSTGRES_USER", "omni_user")), safe="")
        password = quote(str(inherited.get("POSTGRES_PASSWORD", "changeme_in_production")), safe="")
        database = quote(_required(inherited, "POSTGRES_DB"), safe="")
        environment["DATABASE_URL"] = (
            f"{DATABASE_SCHEMES[service]}://{user}:{password}@{loopback}:"
            f"{ports['postgres']}/{database}"
        )
    elif service == "frontend":
        environment.pop("DATABASE_URL", None)
        environment.update(
            {
                "PGHOST": loopback,
                "PGPORT": str(ports["postgres"]),
                "PGUSER": str(inherited.get("POSTGRES_USER", "omni_user")),
                "PGPASSWORD": str(
                    inherited.get("POSTGRES_PASSWORD", "changeme_in_production")
                ),
                "PGDATABASE": _required(inherited, "POSTGRES_DB"),
            }
        )

    if service in REDIS_DATABASES:
        password = quote(str(inherited.get("REDIS_PASSWORD", "changeme_redis")), safe="")
        environment["REDIS_URL"] = (
            f"redis://:{password}@{loopback}:{ports['redis']}/{REDIS_DATABASES[service]}"
        )
    elif service == "frontend":
        password = quote(str(inherited.get("REDIS_PASSWORD", "changeme_redis")), safe="")
        environment["REDIS_URL"] = f"redis://:{password}@{loopback}:{ports['redis']}/1"
    else:
        environment.pop("REDIS_URL", None)

    environment.pop("JWT_SECRET_KEY", None)
    if service == "identity-service":
        environment["JWT_SECRET_KEY_FILE"] = _absolute_file_path(
            inherited, "OMNI_IDENTITY_JWT_SECRET_FILE"
        )
    else:
        environment.pop("JWT_SECRET_KEY_FILE", None)

    environment.pop("OMNI_APPROVAL_SERVICE_TOKEN", None)
    if service == "frontend":
        environment["OMNI_APPROVAL_SERVICE_SECRET_FILE"] = _absolute_file_path(
            inherited, "OMNI_APPROVAL_HMAC_SECRET_FILE"
        )
    else:
        environment.pop("OMNI_APPROVAL_SERVICE_SECRET_FILE", None)
    return environment


def launch_process(
    service: str,
    command: Sequence[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    source: Mapping[str, str] | None = None,
) -> int:
    if not command:
        raise DevEnvironmentError("child command is required")
    environment = build_service_environment(service, source)
    cwd = cwd.resolve()
    if not cwd.is_dir():
        raise DevEnvironmentError("child working directory does not exist")
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    creationflags = 0
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:  # pragma: no cover - Windows is the primary dev launcher
        kwargs["start_new_session"] = True
    with stdout_path.open("ab") as stdout_handle, stderr_path.open("ab") as stderr_handle:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
            **kwargs,
        )
    return int(process.pid)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command_name", required=True)
    launch = subparsers.add_parser("launch")
    launch.add_argument("--service", choices=sorted(ALLOWED_SERVICES), required=True)
    launch.add_argument("--cwd", type=Path, required=True)
    launch.add_argument("--stdout", type=Path, required=True)
    launch.add_argument("--stderr", type=Path, required=True)
    launch.add_argument("child_command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        command = list(args.child_command)
        if command and command[0] == "--":
            command.pop(0)
        pid = launch_process(
            args.service,
            command,
            cwd=args.cwd,
            stdout_path=args.stdout,
            stderr_path=args.stderr,
        )
        print(json.dumps({"pid": pid}, sort_keys=True))
        return 0
    except (DevEnvironmentError, OSError, ValueError) as exc:
        print(f"[dev-runtime] BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
