from __future__ import annotations

import json
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
from app.schemas.system_graph import SourceStatus
from app.services.system_graph.collectors.base import CollectorContext
from app.services.system_graph.collectors.health_delivery import HealthDeliveryCollector
from app.services.system_graph.feature_definitions import load_definitions
from app.services.system_graph.redaction import REDACTED, redact, redact_text
from app.services.system_graph.scanner import ScanRequest, scan_repository


REPO = Path(__file__).resolve().parents[3]


def test_nested_secret_values_and_inline_credentials_are_redacted() -> None:
    raw = {
        "token": "super-secret-token",
        "nested": {
            "authorization": "Bearer abcdefghijklmnop",
            "url": "postgres://user:password@db/omni?token=abcdefghi",
        },
        "safe": "cost-management",
    }
    cleaned = redact(raw)
    rendered = json.dumps(cleaned, ensure_ascii=False)
    assert cleaned["token"] == REDACTED
    assert cleaned["safe"] == "cost-management"
    for secret in ("super-secret-token", "abcdefghijklmnop", "user:password", "abcdefghi"):
        assert secret not in rendered


def test_assignment_and_bearer_redaction_is_deterministic() -> None:
    text = "TOKEN=abcdefghi Authorization: Bearer abcdefghijk cookie=session-secret"
    first = redact_text(text)
    assert first == redact_text(text)
    assert "abcdefghi" not in first
    assert "abcdefghijk" not in first
    assert "session-secret" not in first


def test_snapshot_serialization_contains_no_source_snippets_or_secret_values() -> None:
    snapshot = scan_repository(
        ScanRequest(repo=REPO, feature_ids=("cost-management",), dynamic=False)
    )
    rendered = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False)
    assert "source_snippet" not in rendered
    assert "COST_REAL_VIEW_PASSPHRASE=" not in rendered
    assert "Bearer " not in rendered


def test_external_delivery_attestation_is_explicit_and_repo_relative() -> None:
    definitions = tuple(load_definitions(REPO))
    fixture = (
        REPO
        / "services/knowledge-engine/tests/fixtures/system_graph/delivery-attestation.json"
    )
    output = HealthDeliveryCollector().collect(
        CollectorContext(
            repo=REPO,
            definitions=definitions,
            dynamic=False,
            delivery_attestation=fixture,
        )
    )
    statuses = {result.collector_id: result.status for result in output.source_results}
    assert statuses["delivery.external"] == SourceStatus.SUCCESS
    receipt = next(node for node in output.nodes if node.kind == "delivery_receipt")
    assert receipt.evidence[0].path.endswith("delivery-attestation.json")
    assert set(receipt.evidence[0].model_dump()) == {"path", "line", "symbol", "blob"}
