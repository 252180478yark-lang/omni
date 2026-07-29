"""Verify compact AGENTS files and their dated rollback snapshots."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


PROJECT_ARCHIVE_SHA256 = "4F4DBC0340AD2250AFFACF73DA7F79DF176A50242B367C8F9B527D3DC1756047"
GLOBAL_ARCHIVE_SHA256 = "521C026C75826D9B8407A98AFA2EA74BCEA572962B536EAD3D3F2B740885E6EF"
PROJECT_MAX_BYTES = 16 * 1024
GLOBAL_MAX_BYTES = 8 * 1024
ARCHIVE_MIN_BYTES = 32 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def check_pair(
    *,
    label: str,
    compact: Path,
    archive: Path,
    compact_max_bytes: int,
    archive_sha256: str,
) -> list[str]:
    errors: list[str] = []
    if not compact.is_file():
        errors.append(f"{label} compact AGENTS file is missing: {compact}")
    elif compact.stat().st_size > compact_max_bytes:
        errors.append(
            f"{label} compact AGENTS is {compact.stat().st_size} bytes; "
            f"maximum is {compact_max_bytes}"
        )

    if not archive.is_file():
        errors.append(f"{label} rollback archive is missing: {archive}")
    else:
        archive_size = archive.stat().st_size
        if archive_size < ARCHIVE_MIN_BYTES:
            errors.append(
                f"{label} rollback archive is unexpectedly small: {archive_size} bytes"
            )
        actual_sha256 = sha256(archive)
        if actual_sha256 != archive_sha256:
            errors.append(
                f"{label} rollback archive SHA256 mismatch: "
                f"expected {archive_sha256}, got {actual_sha256}"
            )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify compact project/global AGENTS files and rollback snapshots."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Omni repository root (defaults to the parent of scripts/).",
    )
    parser.add_argument(
        "--global-root",
        type=Path,
        help="Codex home containing global AGENTS.md and archive/.",
    )
    parser.add_argument(
        "--require-global",
        action="store_true",
        help="Fail unless --global-root is supplied and its pair validates.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project_root = args.project_root.resolve()
    errors = check_pair(
        label="project",
        compact=project_root / "AGENTS.md",
        archive=project_root / "docs" / "archive" / "agents" / "AGENTS.pre-slim-2026-07-28.md",
        compact_max_bytes=PROJECT_MAX_BYTES,
        archive_sha256=PROJECT_ARCHIVE_SHA256,
    )

    if args.global_root is not None:
        global_root = args.global_root.resolve()
        errors.extend(
            check_pair(
                label="global",
                compact=global_root / "AGENTS.md",
                archive=global_root / "archive" / "AGENTS.pre-slim-2026-07-28.md",
                compact_max_bytes=GLOBAL_MAX_BYTES,
                archive_sha256=GLOBAL_ARCHIVE_SHA256,
            )
        )
    elif args.require_global:
        errors.append("--require-global needs --global-root")

    if errors:
        for error in errors:
            print(f"[agents-archive] ERROR: {error}")
        return 1

    checked = "project and global" if args.global_root is not None else "project"
    print(f"[agents-archive] OK: verified {checked} compact files and rollback snapshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
