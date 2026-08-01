"""Generate a deterministic graph/trace/finding health baseline for S14."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def build_baseline(snapshot: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    content = snapshot.get("content") or {}
    sources = content.get("source_results") or []
    unavailable = [
        f"{item.get('collector_id')}:{item.get('status')}"
        for item in sources if item.get("status") != "success"
    ]
    diagnostics = content.get("diagnostics") or []
    return {
        "schema_version": 1,
        "kind": "omni_fde_health_baseline",
        "graph": {
            "snapshot_id": snapshot.get("snapshot_id"),
            "node_count": len(content.get("nodes") or []),
            "edge_count": len(content.get("edges") or []),
            "status": "partial" if unavailable else "healthy",
            "unavailable_sources": unavailable,
        },
        "trace": {
            "status": "unknown",
            "event_count": None,
            "reason_code": "runtime_evidence_not_supplied",
        },
        "findings": {
            "static_diagnostic_count": len(diagnostics),
            "runtime_blocking_count": None,
            "status": "unknown",
            "reason_code": "runtime_evidence_not_supplied",
        },
        "delivery": {"status": "verified_not_delivered", "external_attestation_required": True},
        "policy": {
            "policy_id": policy.get("policy_id"),
            "deterministic_p0_codes": sorted(policy.get("deterministic_p0_codes") or []),
            "unknown_behavior": policy.get("unknown_behavior"),
            "historical_debt_behavior": policy.get("historical_debt_behavior"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--policy", type=Path, default=Path("services/knowledge-engine/config/system_graph/block-policy.yaml"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    policy = yaml.safe_load(args.policy.read_text(encoding="utf-8")) or {}
    expected = json.dumps(build_baseline(snapshot, policy), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.check:
        actual = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if actual != expected:
            raise SystemExit(f"stale FDE health baseline: {args.output}")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + ".tmp")
        temporary.write_text(expected, encoding="utf-8")
        temporary.replace(args.output)
    print(json.dumps({"ok": True, "mode": "check" if args.check else "write", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
