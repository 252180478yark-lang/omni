"""Offline, fail-closed S13 retirement audit. Never opens a keychain or prints paths."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REQUIRED = ("sqlite", "attachments", "settings", "secret_reauthorization", "host_smoke", "restore_smoke")


def audit(value: dict[str, Any], *, as_of: datetime) -> dict[str, Any]:
    blockers: list[str] = []
    start = datetime.fromisoformat(str(value.get("observation_started_at", "")).replace("Z", "+00:00")) if value.get("observation_started_at") else None
    if start is None or start > as_of - timedelta(days=14):
        blockers.append("observation_window_incomplete")
    exclusive = [event for event in value.get("exclusive_events", []) if event.get("exclusive")]
    if exclusive:
        blockers.append("exclusive_usage_observed")
    inventory = value.get("inventory") if isinstance(value.get("inventory"), dict) else {}
    for kind in REQUIRED:
        item = inventory.get(kind) if isinstance(inventory.get(kind), dict) else {}
        matched = item.get("state") == "matched"
        if kind in {"sqlite", "attachments", "settings"}:
            matched = matched and bool(item.get("source_checksum")) and item.get("source_checksum") == item.get("target_checksum")
        if not matched:
            blockers.append(f"{kind}_not_reconciled")
    return {
        "client_id": value.get("client_id", "unknown"),
        "as_of": as_of.isoformat(),
        "ready_for_r3_review": not blockers,
        "physical_retirement_allowed": False,
        "required_gate": "R3 explicit owner approval",
        "blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(timezone.utc)
    report = audit(value, as_of=as_of)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ready_for_r3_review"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
