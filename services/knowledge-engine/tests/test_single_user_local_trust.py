from pathlib import Path
import sys

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.routers.runtime_traces import require_trace_access
from app.schemas.approval_operations import ApprovalOperationCreate
from app.services.approval_operations import trusted_local_principal


def test_trusted_local_is_default_owner_without_internal_secret(monkeypatch):
    monkeypatch.delenv("OMNI_APPROVAL_AUTH_MODE", raising=False)
    monkeypatch.delenv("OMNI_APPROVAL_SERVICE_SECRET_FILE", raising=False)
    principal = trusted_local_principal()

    assert principal is not None
    assert principal.principal_id == "local-owner"
    assert principal.roles == frozenset({"owner"})
    require_trace_access(None)


def test_legacy_service_auth_environment_does_not_restore_an_internal_token_boundary(monkeypatch, tmp_path):
    token_path = tmp_path / "trace.token"
    token_path.write_text("x" * 32, encoding="utf-8")
    monkeypatch.setenv("OMNI_APPROVAL_AUTH_MODE", "service-hmac")
    monkeypatch.setenv("OMNI_RUNTIME_TRACE_TOKEN_FILE", str(token_path))

    assert require_trace_access(None) is None


def test_write_operation_contract_remains_r3_and_explicit():
    field = ApprovalOperationCreate.model_fields["risk"]
    assert field.default == "R3"
