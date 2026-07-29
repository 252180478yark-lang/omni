"""FeatureDefinition build and deterministic system-graph CLI."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.services.system_graph.diff import diff_snapshots  # noqa: E402
from app.services.system_graph.feature_definitions import (  # noqa: E402
    DefinitionError,
    generate_bundle,
    load_definitions,
    select_definitions,
)
from app.services.system_graph.scanner import ScanRequest, scan_repository  # noqa: E402
from app.services.system_graph.snapshots import (  # noqa: E402
    read_snapshot,
    verify_evidence,
    write_snapshot,
)


def _repo(value: str | None) -> Path:
    return Path(value).resolve() if value else REPO_ROOT


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def command_generate(args: argparse.Namespace) -> int:
    bundle = generate_bundle(_repo(args.repo), check=args.check)
    _print(
        {
            "ok": True,
            "definition_revision": bundle["definition_revision"],
            "mode": "check" if args.check else "write",
        }
    )
    return 0


def command_scan(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    base = read_snapshot(Path(args.base_snapshot)) if args.base_snapshot else None
    snapshot = scan_repository(
        ScanRequest(
            repo=repo,
            feature_ids=tuple(args.feature or ()),
            ref=args.ref,
            dynamic=args.dynamic,
            timeout_seconds=args.timeout,
            delivery_attestation=(
                Path(args.delivery_attestation) if args.delivery_attestation else None
            ),
            base_snapshot=base,
        )
    )
    directory = (
        Path(args.output).resolve()
        if args.output
        else repo / "output" / "system-graph" / "snapshots"
    )
    path = write_snapshot(snapshot, directory)
    _print(
        {
            "ok": True,
            "snapshot_id": snapshot.snapshot_id,
            "path": str(path),
            "nodes": len(snapshot.content.nodes),
            "edges": len(snapshot.content.edges),
            "source_results": [
                result.model_dump(mode="json") for result in snapshot.content.source_results
            ],
        }
    )
    return 0


def command_diff(args: argparse.Namespace) -> int:
    before = read_snapshot(Path(args.before))
    after = read_snapshot(Path(args.after))
    diff = diff_snapshots(before, after)
    payload = diff.model_dump(mode="json")
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    _print(payload)
    return 0


def command_verify(args: argparse.Namespace) -> int:
    repo = _repo(args.repo)
    generate_bundle(repo, check=True)
    definitions = select_definitions(load_definitions(repo), [args.feature])
    request = ScanRequest(
        repo=repo,
        feature_ids=(args.feature,),
        ref=args.ref,
        # Dynamic adapters have their own tests. Verification remains hermetic and
        # demonstrates their explicit unknown fallback without DB/network access.
        dynamic=False,
    )
    first = scan_repository(request)
    second = scan_repository(request)
    if first.content_hash != second.content_hash:
        raise RuntimeError("two scans of the same inputs produced different hashes")
    diff = diff_snapshots(first, second)
    if not diff.is_empty:
        raise RuntimeError(f"same-input graph diff is not empty: {diff.model_dump()}")
    actual_edges = {
        (edge.source, edge.target, edge.relation) for edge in first.content.edges
    }
    missing = [
        (edge.source, edge.target, edge.relation)
        for edge in definitions[0].expected_edges
        if edge.required and (edge.source, edge.target, edge.relation) not in actual_edges
    ]
    if missing:
        raise RuntimeError(f"required sample edges are missing: {missing}")
    evidence_errors = verify_evidence(first, repo)
    if evidence_errors:
        raise RuntimeError("; ".join(evidence_errors))
    with tempfile.TemporaryDirectory(prefix="omni-system-graph-") as directory:
        first_path = write_snapshot(first, Path(directory))
        second_path = write_snapshot(second, Path(directory))
        if first_path != second_path:
            raise RuntimeError("content-addressed snapshot was not reused")
    _print(
        {
            "ok": True,
            "feature_id": args.feature,
            "snapshot_id": first.snapshot_id,
            "nodes": len(first.content.nodes),
            "edges": len(first.content.edges),
            "diff_empty": True,
            "evidence_verified": sum(
                len(node.evidence) for node in first.content.nodes
            )
            + sum(len(edge.evidence) for edge in first.content.edges),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="build/check FeatureDefinition projections")
    generate.add_argument("--repo")
    generate.add_argument("--check", action="store_true")
    generate.set_defaults(handler=command_generate)

    scan = subparsers.add_parser("scan", help="create an immutable fact snapshot")
    scan.add_argument("--repo")
    scan.add_argument("--feature", action="append")
    scan.add_argument("--ref", default="HEAD")
    scan.add_argument("--output")
    scan.add_argument("--base-snapshot")
    scan.add_argument("--delivery-attestation")
    scan.add_argument("--timeout", type=float, default=8.0)
    scan.add_argument("--dynamic", action=argparse.BooleanOptionalAction, default=True)
    scan.set_defaults(handler=command_scan)

    diff = subparsers.add_parser("diff", help="compare two fact snapshots")
    diff.add_argument("--from", dest="before", required=True)
    diff.add_argument("--to", dest="after", required=True)
    diff.add_argument("--output")
    diff.set_defaults(handler=command_diff)

    verify = subparsers.add_parser("verify", help="verify stable sample graph and evidence")
    verify.add_argument("--repo")
    verify.add_argument("--feature", required=True)
    verify.add_argument("--ref", default="HEAD")
    verify.set_defaults(handler=command_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (DefinitionError, OSError, ValueError, RuntimeError) as exc:
        print(f"system_graph_error:{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
